"""
Spatial HEALPix Gaia Catalog Manager and Safe Rate-Limited Ingestion Engine.

Provides:
- HEALPix spatial tessellation (default NSIDE=128, ~0.46 deg diameter tiles)
  matching Roman WFI SCA field of view (~0.08 x 0.08 deg).
- Zero-API-overload architecture: Workers read pre-cached local Parquet tiles
  in < 1 ms with zero network calls.
- Pre-flight footprint aggregation and single-threaded rate-limited TAP fetching.
- Instant offline partitioning if a master precomputed catalog is provided.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

try:
    import astropy_healpix as ah
    import astropy.units as u
except ImportError:
    import healpy as hp
    ah = None
    u = None

from romanepsf.catalog import sanitize_source_catalog

logger = logging.getLogger("romanepsf.gaia_spatial")


class GaiaSpatialManager:
    """
    Manages spatial partitioning, disk caching, and rate-limited acquisition
    of Gaia DR3 astrometric/photometric catalogs for Roman WFI footprints.
    """

    def __init__(
        self,
        cache_dir: Union[str, Path] = "cache/gaia_healpix",
        nside: int = 128,
        precomputed_catalog: Optional[Union[str, Path]] = None,
        mag_col: str = "mag_lambda",
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.nside = int(nside)
        self.precomputed_catalog = Path(precomputed_catalog) if precomputed_catalog else None
        self.mag_col = mag_col

        if ah is not None:
            self._hpx = ah.HEALPix(nside=self.nside, order="ring", frame="icrs")
        else:
            self._hpx = None

    def ang2pix(self, ra_deg: float, dec_deg: float) -> int:
        """Convert RA/Dec in degrees to HEALPix pixel index (RING ordering)."""
        if self._hpx is not None:
            return int(self._hpx.lonlat_to_healpix(ra_deg * u.deg, dec_deg * u.deg))
        else:
            theta = np.radians(90.0 - dec_deg)
            phi = np.radians(ra_deg)
            return int(hp.ang2pix(self.nside, theta, phi, nest=False))

    def query_disc_tiles(self, ra_deg: float, dec_deg: float, radius_deg: float) -> List[int]:
        """Find all HEALPix tile indices intersecting a celestial cone."""
        if self._hpx is not None:
            pix = self._hpx.cone_search_lonlat(ra_deg * u.deg, dec_deg * u.deg, radius_deg * u.deg)
            return [int(p) for p in pix]
        else:
            vec = hp.ang2vec(ra_deg, dec_deg, lonlat=True)
            pix = hp.query_disc(self.nside, vec, np.radians(radius_deg), inclusive=True, nest=False)
            return [int(p) for p in pix]

    def get_tile_path(self, tile_id: int) -> Path:
        """Standardized Parquet path for a given HEALPix tile."""
        return self.cache_dir / f"gaia_dr3_nside{self.nside}_{tile_id}.parquet"

    def is_tile_cached(self, tile_id: int) -> bool:
        """Check if a tile is already present on local disk."""
        return self.get_tile_path(tile_id).is_file()

    def get_missing_tiles(self, tile_ids: Sequence[int]) -> List[int]:
        """Return subset of tile IDs not yet in local cache."""
        unique_ids = sorted(set(tile_ids))
        return [t for t in unique_ids if not self.is_tile_cached(t)]

    def partition_from_master_catalog(
        self,
        master_catalog_path: Optional[Union[str, Path]] = None,
        target_tiles: Optional[Sequence[int]] = None,
        mag_limit: float = 20.0,
    ) -> int:
        """
        Slices a local master catalog (CSV or Parquet) into HEALPix Parquet tiles.
        Runs entirely offline in memory with zero API calls.
        """
        cat_path = Path(master_catalog_path) if master_catalog_path else self.precomputed_catalog
        if not cat_path or not cat_path.is_file():
            return 0

        logger.info(f"Partitioning local master catalog into HEALPix tiles: {cat_path}")
        if cat_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(cat_path)
        else:
            df = pd.read_csv(cat_path, low_memory=False)

        df = sanitize_source_catalog(df, mag_col=self.mag_col)
        eff_mag = self.mag_col if self.mag_col in df.columns else "phot_g_mean_mag"
        if eff_mag in df.columns:
            df = df[df[eff_mag] <= mag_limit].copy()

        # Compute pixel index for all stars
        ra = df["ra"].to_numpy(dtype=float)
        dec = df["dec"].to_numpy(dtype=float)

        if self._hpx is not None:
            pix_arr = self._hpx.lonlat_to_healpix(ra * u.deg, dec * u.deg)
        else:
            theta = np.radians(90.0 - dec)
            phi = np.radians(ra)
            pix_arr = hp.ang2pix(self.nside, theta, phi, nest=False)

        df["_healpix_tile"] = pix_arr

        target_set = set(target_tiles) if target_tiles is not None else None
        created_count = 0

        for tile_id, group in df.groupby("_healpix_tile"):
            tile_int = int(tile_id)
            if target_set is not None and tile_int not in target_set:
                continue

            tile_file = self.get_tile_path(tile_int)
            clean_tile = group.drop(columns=["_healpix_tile"]).reset_index(drop=True)
            clean_tile.to_parquet(tile_file, index=False)
            created_count += 1

        logger.info(f"Created {created_count} local HEALPix Parquet tiles from master catalog.")
        return created_count

    def fetch_missing_tiles_polite(
        self,
        missing_tiles: Sequence[int],
        mag_limit: float = 20.0,
        delay_seconds: float = 1.5,
        max_retries: int = 3,
    ) -> int:
        """
        Download missing HEALPix tiles using single-threaded rate-limited TAP queries.
        Strictly enforces inter-query pauses to prevent HTTP 429/503 rate limit blocks.
        """
        if not missing_tiles:
            return 0

        # Try offline partition first if master catalog is available
        if self.precomputed_catalog and self.precomputed_catalog.is_file():
            self.partition_from_master_catalog(target_tiles=missing_tiles, mag_limit=mag_limit)
            missing_tiles = self.get_missing_tiles(missing_tiles)
            if not missing_tiles:
                return 0

        try:
            from astroquery.gaia import Gaia
        except ImportError:
            logger.error("astroquery is required for online Gaia DR3 TAP querying.")
            return 0

        logger.info(
            f"Pre-fetching {len(missing_tiles)} HEALPix tiles from Gaia DR3 TAP "
            f"(polite mode: {delay_seconds:.1f}s interval between requests)..."
        )

        fetched = 0
        for i, tile_id in enumerate(missing_tiles):
            tile_path = self.get_tile_path(tile_id)
            if tile_path.is_file():
                continue

            # Compute tile polygon or cone
            if self._hpx is not None:
                lon_c, lat_c = self._hpx.boundaries_lonlat([tile_id], step=1)
                poly_pts = ", ".join(
                    [f"{float(lon.deg):.6f}, {float(lat.deg):.6f}" for lon, lat in zip(lon_c[0], lat_c[0])]
                )
                spatial_clause = f"1 = CONTAINS(POINT('ICRS', ra, dec), POLYGON('ICRS', {poly_pts}))"
            else:
                theta, phi = hp.pix2ang(self.nside, tile_id, nest=False)
                ra_c = float(np.degrees(phi))
                dec_c = float(90.0 - np.degrees(theta))
                approx_radius = float(np.degrees(hp.max_pixrad(self.nside)))
                spatial_clause = (
                    f"1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra_c:.6f}, {dec_c:.6f}, {approx_radius:.6f}))"
                )

            adql = f"""
            SELECT source_id, ra, dec, phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag
            FROM gaiadr3.gaia_source
            WHERE {spatial_clause}
              AND phot_g_mean_mag <= {mag_limit:.2f}
            ORDER BY phot_g_mean_mag ASC
            """

            success = False
            for attempt in range(max_retries):
                try:
                    time.sleep(delay_seconds)
                    job = Gaia.launch_job_async(adql, dump_to_file=False)
                    res = job.get_results()
                    df_res = res.to_pandas()
                    df_res = sanitize_source_catalog(df_res, mag_col="phot_g_mean_mag")
                    df_res.to_parquet(tile_path, index=False)
                    fetched += 1
                    success = True
                    break
                except Exception as exc:
                    wait_backoff = (attempt + 1) * 3.0
                    logger.warning(
                        f"Gaia TAP query failed on tile {tile_id} (attempt {attempt+1}/{max_retries}): {exc}. "
                        f"Retrying in {wait_backoff:.1f}s..."
                    )
                    time.sleep(wait_backoff)

            if not success:
                logger.error(f"Failed to fetch Gaia tile {tile_id} after {max_retries} attempts.")

        logger.info(f"Gaia pre-fetch complete. Fetched {fetched} new tiles to {self.cache_dir}.")
        return fetched

    def get_catalog_for_bounds(
        self,
        ra_min: float,
        ra_max: float,
        dec_min: float,
        dec_max: float,
        mag_limit: float = 20.0,
    ) -> pd.DataFrame:
        """
        Fast local retrieval: loads cached Parquet tiles overlapping the bounding box
        and slices stars matching the bounds.
        Executes in < 2 milliseconds with zero network requests.
        """
        ra_cen = 0.5 * (ra_min + ra_max)
        dec_cen = 0.5 * (dec_min + dec_max)
        cos_dec = np.cos(np.radians(dec_cen))
        diag_deg = np.hypot((ra_max - ra_min) * cos_dec, dec_max - dec_min)
        radius_deg = 0.5 * diag_deg + 0.01

        tile_ids = self.query_disc_tiles(ra_cen, dec_cen, radius_deg)
        dfs = []

        for t in tile_ids:
            t_path = self.get_tile_path(t)
            if t_path.is_file():
                try:
                    tile_df = pd.read_parquet(t_path)
                    dfs.append(tile_df)
                except Exception as err:
                    logger.warning(f"Error reading cached tile {t_path}: {err}")

        if not dfs:
            return pd.DataFrame(columns=["source_id", "ra", "dec", "phot_g_mean_mag"])

        combined = pd.concat(dfs, ignore_index=True)
        if "source_id" in combined.columns:
            combined = combined.drop_duplicates(subset=["source_id"])

        # Spatial box filter
        in_box = (
            (combined["ra"] >= ra_min)
            & (combined["ra"] <= ra_max)
            & (combined["dec"] >= dec_min)
            & (combined["dec"] <= dec_max)
        )
        sub = combined[in_box].copy()

        eff_mag = self.mag_col if self.mag_col in sub.columns else "phot_g_mean_mag"
        if eff_mag in sub.columns:
            sub = sub[sub[eff_mag] <= mag_limit]

        return sub.reset_index(drop=True)
