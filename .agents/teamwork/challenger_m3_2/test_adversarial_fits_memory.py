"""
Adversarial Stress Test Suite: Memory Footprint, Scalability & FITS Forensics.

Validates Milestone 3 deliverables against:
1. Memory Ceiling & Leak Audit (Peak RSS < 4,000 MB, consecutive execution leak detection).
2. FITS Output Forensics (HDUs, <= 8-char keywords, zero HIERARCH cards, unit sum, coverage, profiles, summary).
3. 2D Non-Circular Structure & 6-Fold Diffraction Spike Preservation.
4. Cross-Tier Overlap Scale Factor Physics (0 < k_MB < k_FM < 1).
"""

from __future__ import annotations

import gc
import os
import sys
import time
import threading
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import psutil
import pytest
from astropy.io import fits

from romanepsf.masking import get_theoretical_spike_angles, ROMAN_BASE_SPIKE_ANGLES_DEG
from romanepsf.pipeline import run_pipeline, run_single_detector

COMPOSITE_FITS = Path("/Users/pmsanch1/code/romanepsf/output/run_all/roman_epsf_composite.fits")
SINGLE_WFI01_FITS = Path("/Users/pmsanch1/code/romanepsf/output/single_wfi01/roman_epsf_wfi01.fits")


class MemorySampler:
    """Monitors RSS memory usage of the current process in a background thread."""

    def __init__(self, sample_interval_s: float = 0.02):
        self.interval = sample_interval_s
        self.process = psutil.Process(os.getpid())
        self.stop_event = threading.Event()
        self.peak_rss_mb = self._get_rss_mb()
        self.samples: List[float] = [self.peak_rss_mb]
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _get_rss_mb(self) -> float:
        return self.process.memory_info().rss / (1024.0 * 1024.0)

    def _run(self):
        while not self.stop_event.is_set():
            rss = self._get_rss_mb()
            self.samples.append(rss)
            if rss > self.peak_rss_mb:
                self.peak_rss_mb = rss
            time.sleep(self.interval)

    def start(self):
        self.thread.start()

    def stop(self) -> float:
        self.stop_event.set()
        self.thread.join(timeout=2.0)
        final_rss = self._get_rss_mb()
        self.samples.append(final_rss)
        if final_rss > self.peak_rss_mb:
            self.peak_rss_mb = final_rss
        return self.peak_rss_mb


class TestMemoryFootprintAndLeaks:
    """Stress tests on memory ceiling and leak resistance."""

    def test_single_detector_memory_and_leak(self, tmp_path):
        """Verify single detector runs maintain peak RSS < 4000 MB and stabilize."""
        proc = psutil.Process(os.getpid())
        gc.collect()

        peaks = []
        post_gcs = []

        for i in range(3):
            out_dir = tmp_path / f"test_single_{i}"
            sampler = MemorySampler(0.02)
            sampler.start()
            res = run_single_detector("wfi01", output_dir=out_dir)
            peak = sampler.stop()
            peaks.append(peak)

            del res
            gc.collect()
            post_gc = proc.memory_info().rss / (1024.0 * 1024.0)
            post_gcs.append(post_gc)

            assert peak < 4000.0, f"Run {i+1} peak RSS {peak:.2f} MB exceeded 4000 MB ceiling!"

        # Ensure memory plateaus well below 4000 MB ceiling (headroom > 1500 MB)
        assert post_gcs[-1] < 2500.0, f"Post-GC RSS {post_gcs[-1]:.2f} MB exceeded 2500 MB safety threshold!"
        # Verify delta between consecutive runs stabilizes (run 3 vs run 2 delta < 150 MB)
        stab_delta = abs(post_gcs[-1] - post_gcs[-2])
        assert stab_delta < 150.0, f"Memory did not stabilize: delta between run 2 and 3 = {stab_delta:.2f} MB"

    def test_multi_detector_18_sca_peak_memory_and_leak(self, tmp_path):
        """Verify full 18-detector run strictly stays < 4000 MB peak RSS and stabilizes."""
        proc = psutil.Process(os.getpid())
        gc.collect()

        peaks = []
        post_gcs = []

        for i in range(2):
            out_dir = tmp_path / f"test_all_{i}"
            sampler = MemorySampler(0.05)
            sampler.start()
            outputs = run_pipeline(output_dir=out_dir)
            peak = sampler.stop()
            peaks.append(peak)

            del outputs
            gc.collect()
            post_gc = proc.memory_info().rss / (1024.0 * 1024.0)
            post_gcs.append(post_gc)

            assert peak < 4000.0, f"18-detector execution peak RSS {peak:.2f} MB exceeded 4000 MB ceiling!"

        # Ensure multi-detector RSS stays well below 4000 MB and stabilizes
        assert post_gcs[-1] < 2500.0, f"Multi-detector post-GC RSS {post_gcs[-1]:.2f} MB exceeded 2500 MB threshold!"
        leak_delta = post_gcs[1] - post_gcs[0]
        assert leak_delta < 200.0, f"Multi-detector memory leak detected: delta = {leak_delta:.2f} MB"


class TestFITSOutputForensics:
    """Forensic integrity testing of serialized FITS models."""

    def test_composite_fits_hdus_and_bitpix(self):
        """Verify all 4 HDUs exist with correct names, types, shapes, and bitpix."""
        assert COMPOSITE_FITS.is_file(), f"Missing composite FITS: {COMPOSITE_FITS}"

        with fits.open(COMPOSITE_FITS) as hdul:
            assert len(hdul) == 4, f"Expected exactly 4 HDUs, found {len(hdul)}"

            # HDU 0: Primary EPSF
            assert isinstance(hdul[0], fits.PrimaryHDU)
            assert hdul[0].name == "EPSF"
            assert hdul[0].header["BITPIX"] == -32  # IEEE single precision float
            assert hdul[0].data.shape == (1025, 1025)
            assert hdul[0].data.dtype in (np.float32, np.dtype(">f4"))

            # HDU 1: COVERAGE
            assert isinstance(hdul[1], fits.ImageHDU)
            assert hdul[1].name == "COVERAGE"
            assert hdul[1].header["BITPIX"] == 32  # 32-bit signed integer
            assert hdul[1].data.shape == (1025, 1025)
            assert np.issubdtype(hdul[1].data.dtype, np.integer)

            # HDU 2: RADIAL_PROFILES
            assert isinstance(hdul[2], fits.BinTableHDU)
            assert hdul[2].name == "RADIAL_PROFILES"
            assert hdul[2].header["BITPIX"] == 8

            # HDU 3: DETECTOR_SUMMARY
            assert isinstance(hdul[3], fits.BinTableHDU)
            assert hdul[3].name == "DETECTOR_SUMMARY"
            assert hdul[3].header["BITPIX"] == 8

    def test_fits_header_keywords_length_and_no_hierarch(self):
        """Verify every single header keyword in all HDUs <= 8 chars and zero HIERARCH cards exist."""
        for path in [COMPOSITE_FITS, SINGLE_WFI01_FITS]:
            assert path.is_file(), f"Missing FITS file: {path}"
            with fits.open(path) as hdul:
                for idx, hdu in enumerate(hdul):
                    for card in hdu.header.cards:
                        key = card.keyword
                        # Standard FITS keywords can include CONTINUE, COMMENT, HISTORY
                        assert len(key) <= 8 or key.startswith("CONTINUE"), (
                            f"Header keyword '{key}' in {path.name} HDU {idx} ({hdu.name}) exceeds 8 characters!"
                        )
                        card_str = str(card)
                        assert "HIERARCH" not in card_str, (
                            f"HIERARCH card found in {path.name} HDU {idx} ({hdu.name}): {card_str}"
                        )

    def test_composite_primary_hdu_flux_and_centering(self):
        """Verify Primary HDU flux sum = 1.000000 ± 1e-4, peak positive, centered, no NaN/Inf."""
        with fits.open(COMPOSITE_FITS) as hdul:
            data = hdul[0].data
            hdr = hdul[0].header

            # No NaNs or Infs
            assert not np.isnan(data).any(), "Primary HDU data contains NaN values!"
            assert not np.isinf(data).any(), "Primary HDU data contains Inf values!"
            assert np.min(data) >= 0.0, f"Primary HDU has negative values: min = {np.min(data)}"

            # Flux normalization
            total_flux = float(np.sum(data))
            assert np.isclose(total_flux, 1.0, atol=1e-4), (
                f"Primary HDU total flux {total_flux:.8f} deviates from 1.000000 by > 1e-4!"
            )
            assert np.isclose(hdr["SUM_FLUX"], 1.0, atol=1e-4)

            # Peak pixel positive
            peak_val = float(np.max(data))
            assert peak_val > 0.0, f"Peak pixel flux is non-positive: {peak_val}"

            # Centering
            cy, cx = (data.shape[0] - 1) // 2, (data.shape[1] - 1) // 2  # (512, 512)
            peak_y, peak_x = np.unravel_index(np.argmax(data), data.shape)
            dist_to_center = np.hypot(peak_x - cx, peak_y - cy)
            assert dist_to_center <= 1.5, (
                f"Peak pixel at ({peak_y}, {peak_x}) is not centered at ({cy}, {cx}), dist = {dist_to_center:.2f} px"
            )

            # Continuous centroid check in central 7x7 box
            box = data[cy - 3 : cy + 4, cx - 3 : cx + 4]
            y_idx, x_idx = np.indices(box.shape) - 3
            cen_dy = np.sum(box * y_idx) / np.sum(box)
            cen_dx = np.sum(box * x_idx) / np.sum(box)
            centroid_offset = np.hypot(cen_dx, cen_dy)
            assert centroid_offset < 0.20, (
                f"Continuous centroid offset {centroid_offset:.4f} px is too large!"
            )

    def test_single_wfi01_primary_hdu_flux_and_centering(self):
        """Verify single WFI01 Primary HDU flux sum = 1.000000 ± 1e-4, peak positive, centered."""
        assert SINGLE_WFI01_FITS.is_file()
        with fits.open(SINGLE_WFI01_FITS) as hdul:
            data = hdul[0].data
            hdr = hdul[0].header

            assert not np.isnan(data).any()
            assert not np.isinf(data).any()
            assert np.min(data) >= 0.0

            total_flux = float(np.sum(data))
            assert np.isclose(total_flux, 1.0, atol=1e-4), (
                f"WFI01 total flux {total_flux:.8f} deviates from 1.000000 by > 1e-4!"
            )

            peak_y, peak_x = np.unravel_index(np.argmax(data), data.shape)
            cy, cx = (data.shape[0] - 1) // 2, (data.shape[1] - 1) // 2
            dist = np.hypot(peak_x - cx, peak_y - cy)
            assert dist <= 1.5, f"WFI01 peak at ({peak_y}, {peak_x}) is not centered at ({cy}, {cx})"

    def test_coverage_hdu_integrity(self):
        """Verify HDU 1 (COVERAGE): min >= 0, integer type, core region has positive coverage."""
        with fits.open(COMPOSITE_FITS) as hdul:
            cov = hdul[1].data
            assert np.issubdtype(cov.dtype, np.integer), f"Coverage dtype is not integer: {cov.dtype}"
            assert np.min(cov) >= 0, f"Coverage map contains negative values: min = {np.min(cov)}"

            cy, cx = (cov.shape[0] - 1) // 2, (cov.shape[1] - 1) // 2
            core_cov = cov[cy, cx]
            assert core_cov > 0, f"Core pixel ({cy}, {cx}) has zero coverage: {core_cov}"
            assert np.max(cov) >= 100, f"Max coverage {np.max(cov)} unexpectedly low"

    def test_radial_profiles_hdu_columns_and_monotonicity(self):
        """Verify HDU 2 (RADIAL_PROFILES): columns and monotonicity in outer wings."""
        with fits.open(COMPOSITE_FITS) as hdul:
            tab = hdul[2].data
            expected_cols = [
                "RADIUS_PX",
                "RADIUS_ARCSEC",
                "FLUX_COMPOSITE",
                "FLUX_FAINT",
                "FLUX_MED_SCALED",
                "FLUX_BRIGHT_SCALED",
            ]
            for col in expected_cols:
                assert col in tab.names, f"Missing required column '{col}' in RADIAL_PROFILES"

            r = tab["RADIUS_PX"]
            fc = tab["FLUX_COMPOSITE"]

            # Radii must be strictly increasing
            assert np.all(np.diff(r) > 0), "RADIUS_PX is not strictly increasing!"

            # Monotonicity in outer wings (e.g. r between 50 and 300 px)
            wing_mask = (r[:-1] >= 50.0) & (r[:-1] <= 300.0)
            diffs = np.diff(fc)[wing_mask]
            # No substantial positive spikes in outer wings (tolerance 1e-8)
            bad_spikes = diffs[diffs > 1e-8]
            assert len(bad_spikes) == 0, (
                f"Found {len(bad_spikes)} non-monotonic positive flux spikes in outer wings (r in [50, 300]): {bad_spikes}"
            )

    def test_detector_summary_hdu_structure(self):
        """Verify HDU 3 (DETECTOR_SUMMARY): exactly 18 rows, correct columns, star sum matches Primary NSTARS."""
        with fits.open(COMPOSITE_FITS) as hdul:
            tab = hdul[3].data
            prim_nstars = hdul[0].header["NSTARS"]

            assert len(tab) == 18, f"Expected exactly 18 detector summary rows, found {len(tab)}"

            expected_cols = [
                "DETECTOR",
                "N_FAINT",
                "N_MEDIUM",
                "N_BRIGHT",
                "N_TOTAL",
                "PA_APER_DEG",
                "PIXSCALE",
                "TIME_SEC",
                "STATUS",
            ]
            for col in expected_cols:
                assert col in tab.names, f"Missing column '{col}' in DETECTOR_SUMMARY"

            # Check detector naming
            det_names = [str(d).upper() for d in tab["DETECTOR"]]
            for i in range(1, 19):
                assert f"WFI{i:02d}" in det_names, f"Detector WFI{i:02d} missing from DETECTOR_SUMMARY"

            # Check star counts match Primary HDU
            tot_stars = int(np.sum(tab["N_TOTAL"]))
            assert tot_stars == prim_nstars, (
                f"DETECTOR_SUMMARY total stars ({tot_stars}) does not match Primary HDU NSTARS ({prim_nstars})!"
            )


class TestNonCircularStructureAndSpikes:
    """Stress tests verifying 2D non-circular structure and 6-fold diffraction spike preservation."""

    def test_azimuthal_variance_at_fixed_radii(self):
        """Empirically verify composite ePSF is NOT circularized via azimuthal variance."""
        with fits.open(COMPOSITE_FITS) as hdul:
            epsf = hdul[0].data

        S = epsf.shape[0]
        cy, cx = (S - 1) / 2.0, (S - 1) / 2.0
        y, x = np.ogrid[:S, :S]
        r = np.hypot(x - cx, y - cy)

        for test_r, dr in [(50.0, 3.0), (150.0, 5.0)]:
            ring = (r >= test_r - dr) & (r <= test_r + dr)
            ring_flux = epsf[ring]
            mean_f = np.mean(ring_flux)
            std_f = np.std(ring_flux)
            cv = std_f / mean_f

            # If circularized, CV would be near 0.0 (< 0.05).
            # True 2D ePSF with 6-fold spikes has CV > 0.25 (> 25%).
            assert cv > 0.20, (
                f"Azimuthal CV at r={test_r} px is {cv:.4f} <= 0.20, indicating artificial circularization!"
            )

    def test_diffraction_spike_flux_elevation(self):
        """Verify flux along theoretical 6-fold spike angles is higher than off-spike background."""
        with fits.open(COMPOSITE_FITS) as hdul:
            epsf = hdul[0].data
            hdr = hdul[0].header
            pa_aper = hdr["PA_APER"]
            det_off = hdr["DET_OFF"]

        spike_angles = get_theoretical_spike_angles(pa_aper, det_off)

        S = epsf.shape[0]
        cy, cx = (S - 1) / 2.0, (S - 1) / 2.0
        y, x = np.ogrid[:S, :S]
        r = np.hypot(x - cx, y - cy)
        theta = np.degrees(np.arctan2(y - cy, x - cx)) % 360.0

        # Test at r=50 px, r=100 px, r=150 px
        for test_r in [50.0, 100.0, 150.0]:
            ring = (r >= test_r - 2.5) & (r <= test_r + 2.5)
            ring_theta = theta[ring]
            ring_flux = epsf[ring]

            min_ang_dist = np.min(
                [np.abs((ring_theta - sa + 180.0) % 360.0 - 180.0) for sa in spike_angles],
                axis=0,
            )

            on_spike_flux = ring_flux[min_ang_dist <= 3.5]
            off_spike_flux = ring_flux[min_ang_dist >= 8.0]

            assert len(on_spike_flux) > 0 and len(off_spike_flux) > 0
            mean_on = float(np.mean(on_spike_flux))
            mean_off = float(np.mean(off_spike_flux))

            ratio = mean_on / mean_off
            assert ratio > 1.02, (
                f"Spike-to-background flux ratio at r={test_r} px is {ratio:.4f} <= 1.02; "
                f"diffraction spikes are not preserved!"
            )


class TestScaleFactorValidation:
    """Stress tests on cross-tier flux scale factors."""

    def test_composite_scale_factors_physics(self):
        """Verify cross-tier scale factors are strictly positive and satisfy 0 < k_MB < k_FM < 1."""
        with fits.open(COMPOSITE_FITS) as hdul:
            hdr = hdul[0].header
            k_fm = hdr.get("SCALE_FM", hdr.get("K_FM"))
            k_mb = hdr.get("SCALE_MB", hdr.get("K_MB"))

            assert k_fm is not None and k_mb is not None
            assert 0.0 < k_mb < k_fm < 1.0, (
                f"Scale factors violate physical ordering 0 < k_MB < k_FM < 1: k_FM={k_fm}, k_MB={k_mb}"
            )

    def test_single_wfi01_scale_factors_physics(self):
        """Verify single WFI01 cross-tier scale factors satisfy 0 < k_MB < k_FM < 1."""
        with fits.open(SINGLE_WFI01_FITS) as hdul:
            hdr = hdul[0].header
            k_fm = hdr.get("K_FM")
            k_mb = hdr.get("K_MB")

            assert k_fm is not None and k_mb is not None
            assert 0.0 < k_mb < k_fm < 1.0, (
                f"WFI01 scale factors violate physical ordering: k_FM={k_fm}, k_MB={k_mb}"
            )


if __name__ == "__main__":
    ret = pytest.main([__file__, "-v", "-s"])
    sys.exit(ret)
