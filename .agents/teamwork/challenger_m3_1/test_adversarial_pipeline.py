"""
Adversarial Stress Test Suite for Roman ePSF Pipeline & CLI (Milestone 3).

Target Modules:
- src/romanepsf/pipeline.py
- src/pipeline.py
- src/romanepsf/cli.py

Stress Test Areas:
1. Missing-Tier Detectors:
   - Tests all 6 SCAs that lack bright stars (wfi02, wfi03, wfi08, wfi13, wfi17, wfi18).
   - Verifies 2-tier graceful fallback, k_mb = None, FITS K_MB = -1.0, N_BRIGHT = 0.
2. Signature Polymorphism Stress:
   - Tests positional (cfg, detector="wfi01"), positional 5-argument, keyword-only subsets.
   - Tests str paths vs Path objects.
   - Tests invalid types/values to ensure informative exceptions.
   - Tests export_single_detector_fits polymorphic calling styles and error modes.
   - Tests discover_detectors discovery and filtering.
3. Canvas Dimensions & Coordinate Centering:
   - Tests even canvas dimensions (1024, 2048) promoted to odd (1025, 2049).
   - Tests odd dimensions exact centering and FITS CRPIX compliance.
   - Tests exact peak centering on synthetic stars.
   - Tests real detector centering within 1 pixel discrete tolerance.
4. CLI Subcommand Invocations:
   - Tests Click CliRunner for single and run with valid and invalid flags, verifying exit codes.
5. Zero-Star Detector Graceful Error:
   - Tests out-of-footprint and empty catalogs, verifying descriptive RuntimeErrors.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits
from click.testing import CliRunner

from romanepsf.assembly import assemble_composite_extended_psf
from romanepsf.cli import cli
from romanepsf.config import Config, PipelineConfig, load_config
from romanepsf.pipeline import (
    PipelineOutputs,
    SingleDetectorResult,
    discover_detectors,
    export_single_detector_fits,
    process_single_detector_stamps,
    run_pipeline,
    run_single_detector,
)
from romanepsf.stamps import StellarStamp


# ==============================================================================
# Global Fixtures & Constants
# ==============================================================================
DATA_DIR = Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors")
CATALOG_PATH = DATA_DIR / "code" / "r0108301001001001001_0001_wfi_source_catalog.csv"
MISSING_TIER_DETECTORS = ["wfi02", "wfi03", "wfi08", "wfi13", "wfi17", "wfi18"]


def create_synthetic_stamp(
    size: int,
    tier: str,
    peak_offset: tuple[float, float] = (0.0, 0.0),
    fwhm: float = 3.0,
) -> StellarStamp:
    """Create a synthetic StellarStamp with an analytical 2D Gaussian profile."""
    half = (size - 1) // 2
    gy, gx = np.ogrid[:size, :size]
    dy, dx = peak_offset
    r2 = (gx - (half + dx)) ** 2 + (gy - (half + dy)) ** 2
    sigma = fwhm / 2.355
    data = (100.0 * np.exp(-r2 / (2.0 * sigma**2))).astype(np.float32)
    mask = np.zeros((size, size), dtype=bool)

    return StellarStamp(
        source_id=101,
        tier=tier,
        mag=14.0 if tier == "faint" else (12.0 if tier == "medium" else 9.0),
        data=data,
        mask=mask,
        center_original=(float(half), float(half)),
        size=size,
        norm_factor=1.0,
        bkg_value=0.0,
        bkg_rms=0.0,
    )


# ==============================================================================
# Area 1: Missing-Tier Detectors Adversarial Stress Tests
# ==============================================================================
class TestMissingTierDetectors:
    """Stress tests for all 6 SCAs lacking bright stars."""

    @pytest.mark.parametrize("det_id", MISSING_TIER_DETECTORS)
    def test_missing_bright_tier_execution(self, det_id: str, tmp_path: Path):
        """
        Verify that each of the 6 detectors lacking bright stars:
        1. Executes without crashing or empty tier ValueError.
        2. Successfully returns SingleDetectorResult with success=True.
        3. Records N_BRIGHT = 0, but N_TOTAL > 0.
        4. Sets scale_factors['k_mb'] = None.
        5. Produces a finite, unit-flux normalized float32 model.
        6. Exports valid FITS with K_MB = -1.0, N_BRIGHT = 0, and SUM_FLUX > 0.99.
        """
        result = run_single_detector(det_id, output_dir=tmp_path)

        assert isinstance(result, SingleDetectorResult)
        assert result.success is True
        assert result.detector_id == det_id

        # Star counts verification
        assert result.star_counts["bright"] == 0, f"{det_id} unexpectedly had bright stars"
        assert result.star_counts["total"] > 0, f"{det_id} had zero total stars"
        assert result.star_counts["medium"] + result.star_counts["faint"] == result.star_counts["total"]

        # Scale factor verification
        assert result.scale_factors["k_mb"] is None
        assert result.diagnostics.get("k_mb") is None
        assert result.scale_factors.get("k_fm") is not None
        assert result.scale_factors["k_fm"] > 0.0

        # Model array verification
        model = result.epsf_model
        assert isinstance(model, np.ndarray)
        assert model.shape == (1025, 1025)
        assert model.dtype == np.float32
        assert np.isfinite(model).all()
        assert np.isclose(float(np.sum(model)), 1.0, atol=1e-3)
        assert float(np.max(model)) > 0.0

        # FITS file verification
        assert result.fits_path.is_file()
        with fits.open(result.fits_path) as hdul:
            hdr = hdul[0].header
            assert hdr["EXTNAME"] == "EPSF"
            assert hdr["DETECTOR"] == det_id.upper()
            assert hdr["K_MB"] == -1.0
            assert hdr["N_BRIGHT"] == 0
            assert hdr["N_TOTAL"] == result.star_counts["total"]
            assert hdr["SUM_FLUX"] > 0.99
            assert hdr["NORM"] == "UNIT_FLUX"


# ==============================================================================
# Area 2: Signature Polymorphism Stress Tests
# ==============================================================================
class TestSignaturePolymorphismStress:
    """Stress tests for caller signatures, types, and parameter variations."""

    @pytest.fixture
    def default_cfg(self) -> Config:
        return load_config()

    @pytest.fixture
    def wfi01_asdf(self) -> Path:
        return DATA_DIR / "r0108301001001001001_0001_wfi01_f146_cal.asdf"

    def test_positional_config_first(self, default_cfg: Config, tmp_path: Path):
        """Verify positional (cfg, detector='wfi01') calling convention."""
        res = run_single_detector(default_cfg, detector="wfi01", output_dir=tmp_path)
        assert res.success is True
        assert res.detector_id == "wfi01"
        assert res.fits_path.is_file()

    def test_positional_five_arguments(
        self, default_cfg: Config, wfi01_asdf: Path, tmp_path: Path
    ):
        """Verify positional (detector_id, asdf_path, catalog_path, config, output_dir)."""
        res = run_single_detector(
            "wfi01",
            wfi01_asdf,
            CATALOG_PATH,
            default_cfg,
            tmp_path,
        )
        assert res.success is True
        assert res.detector_id == "wfi01"

    def test_keyword_only_calls(self, wfi01_asdf: Path, tmp_path: Path):
        """Verify keyword-only invocations with subsets of overrides."""
        res1 = run_single_detector(
            detector_id="wfi01",
            asdf_path=wfi01_asdf,
            output_dir=tmp_path / "k1",
        )
        assert res1.success is True

        res2 = run_single_detector(
            detector="wfi01",
            canvas_size=1025,
            device="cpu",
            output_dir=tmp_path / "k2",
        )
        assert res2.success is True
        assert res2.canvas_size == 1025

    def test_path_strings_vs_path_objects(self, default_cfg: Config, wfi01_asdf: Path, tmp_path: Path):
        """Verify passing str paths operates identically to Path objects."""
        res = run_single_detector(
            "wfi01",
            asdf_path=str(wfi01_asdf),
            catalog_path=str(CATALOG_PATH),
            config=default_cfg,
            output_dir=str(tmp_path),
        )
        assert res.success is True
        assert isinstance(res.fits_path, Path)

    def test_invalid_asdf_path_raises_filenotfound(self, tmp_path: Path):
        """Verify non-existent ASDF path raises informative FileNotFoundError."""
        bogus_path = tmp_path / "nonexistent_cal.asdf"
        with pytest.raises(FileNotFoundError, match="Detector ASDF file not found"):
            run_single_detector("wfi01", asdf_path=bogus_path, output_dir=tmp_path)

    def test_invalid_detector_raises_filenotfound(self, tmp_path: Path):
        """Verify invalid detector identifier (e.g. wfi99) raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Detector ASDF file not found"):
            run_single_detector("wfi99", output_dir=tmp_path)

    def test_invalid_config_type_raises_informative_error(self, tmp_path: Path):
        """Verify passing an invalid config type raises AttributeError / TypeError rather than silent failure."""
        with pytest.raises((AttributeError, TypeError)):
            run_single_detector("wfi01", config=99999, output_dir=tmp_path)

    def test_export_single_detector_fits_polymorphism(self, tmp_path: Path):
        """Verify export_single_detector_fits handles results, raw arrays, and keyword variants."""
        canvas = np.zeros((501, 501), dtype=np.float32)
        canvas[250, 250] = 1.0

        p1 = tmp_path / "model1.fits"
        p2 = tmp_path / "model2.fits"
        p3 = tmp_path / "model3.fits"

        # 1. Positional (canvas, fits_path)
        out1 = export_single_detector_fits(canvas, p1, detector_id="wfi01")
        assert out1.is_file()

        # 2. Keyword-only (epsf_model=canvas, fits_path=p2)
        out2 = export_single_detector_fits(epsf_model=canvas, fits_path=p2, detector_id="wfi02")
        assert out2.is_file()

        # 3. Invalid model argument raises ValueError
        with pytest.raises(ValueError, match="Must provide either SingleDetectorResult or 2D numpy array"):
            export_single_detector_fits("not_an_array", p3)

        # 4. Missing output path raises ValueError
        with pytest.raises(ValueError, match="Must specify output path"):
            export_single_detector_fits(canvas)

    def test_discover_detectors_robustness(self, tmp_path: Path):
        """Verify discover_detectors case-insensitivity, sorting, and filtering."""
        for i in [1, 2, 10]:
            (tmp_path / f"r0108301001001001001_0001_wfi{i:02d}_f146_cal.asdf").touch()
        (tmp_path / "random_file.txt").touch()

        # All discovery
        all_dets = discover_detectors(tmp_path)
        assert sorted(all_dets.keys()) == ["wfi01", "wfi02", "wfi10"]

        # Case-insensitive requested filtering
        filtered = discover_detectors(tmp_path, requested=["WFI01", "wfi10"])
        assert sorted(filtered.keys()) == ["wfi01", "wfi10"]

        # 'all' keyword
        all_keyword = discover_detectors(tmp_path, requested=["all"])
        assert len(all_keyword) == 3


# ==============================================================================
# Area 3: Canvas Dimensions & Coordinate Centering Stress Tests
# ==============================================================================
class TestCanvasDimensionsAndCentering:
    """Stress tests for canvas dimensions, odd-sizing promotion, and peak centering."""

    def test_even_dimension_promoted_to_odd(self, tmp_path: Path):
        """Verify even canvas sizes (1024, 2048) are automatically promoted to (1025, 2049)."""
        # Test via run_single_detector
        res = run_single_detector("wfi01", canvas_size=1024, output_dir=tmp_path)
        assert res.canvas_size == 1025
        assert res.epsf_model.shape == (1025, 1025)

        with fits.open(res.fits_path) as hdul:
            hdr = hdul[0].header
            assert hdr["CANVAS_S"] == 1025
            assert hdr["CRPIX1"] == 513.0  # (1025 + 1) / 2
            assert hdr["CRPIX2"] == 513.0

    def test_odd_dimension_exact_center_metadata(self, tmp_path: Path):
        """Verify odd dimensions maintain exact center coordinates in FITS headers."""
        for s in [501, 1025]:
            canvas = np.zeros((s, s), dtype=np.float32)
            p = tmp_path / f"test_{s}.fits"
            export_single_detector_fits(canvas, p, detector_id="wfi01")

            with fits.open(p) as hdul:
                hdr = hdul[0].header
                expected_crpix = (s + 1.0) / 2.0
                assert hdr["CANVAS_S"] == s
                assert hdr["CRPIX1"] == expected_crpix
                assert hdr["CRPIX2"] == expected_crpix

    def test_synthetic_star_peak_flux_exact_centering(self):
        """
        Verify that for synthetic clean stars across tiers,
        the synthesized ePSF peak flux is located EXACTLY at the canvas center pixel ((S-1)//2, (S-1)//2).
        """
        tier_stamps = {
            "faint": [create_synthetic_stamp(81, "faint")],
            "medium": [create_synthetic_stamp(201, "medium")],
            "bright": [create_synthetic_stamp(501, "bright")],
        }

        for canvas_sz in [501, 1025, 2049]:
            epsf, diag = assemble_composite_extended_psf(tier_stamps, output_size=canvas_sz)
            py, px = np.unravel_index(np.argmax(epsf), epsf.shape)
            cy, cx = (canvas_sz - 1) // 2, (canvas_sz - 1) // 2
            assert (py, px) == (cy, cx), f"Size {canvas_sz}: Peak at ({py}, {px}) != Center ({cy}, {cx})"

    def test_real_detector_peak_discrete_proximity(self, tmp_path: Path):
        """
        Verify that on real detector data (WFI01), the discrete pixel argmax is within
        1.5 pixels of the geometric center ((S-1)//2, (S-1)//2).

        Empirical Note: In Roman Level 2 commissioning data, faint stars possess DQ bit 1
        (DO_NOT_USE / DROPOUT) at the central pixel, causing the discrete pixel peak
        to lie at an adjacent pixel (e.g. (511, 512)), while the continuous subpixel
        centroid is maintained at (512.0, 512.0).
        """
        res = run_single_detector("wfi01", canvas_size=1025, output_dir=tmp_path)
        m = res.epsf_model
        py, px = np.unravel_index(np.argmax(m), m.shape)
        cy, cx = 512, 512

        distance = np.hypot(py - cy, px - cx)
        assert distance <= 1.5, f"WFI01 peak ({py}, {px}) is too far from center ({cy}, {cx}): dist={distance}"


# ==============================================================================
# Area 4: CLI Subcommand Invocations Adversarial Tests
# ==============================================================================
class TestCliSubcommandInvocations:
    """Stress tests for Click CLI error paths and parameter validation."""

    def test_cli_invalid_device_flag(self):
        """Verify passing an unsupported device choice produces exit code 2."""
        runner = CliRunner()
        # Top-level global device
        res1 = runner.invoke(cli, ["--device", "quantum_tpu", "single"])
        assert res1.exit_code == 2
        assert "Invalid value for '--device'" in res1.output

        # Subcommand device
        res2 = runner.invoke(cli, ["run", "--device", "invalid_dev"])
        assert res2.exit_code == 2
        assert "Invalid value for '--device'" in res2.output

    def test_cli_single_nonexistent_asdf(self, tmp_path: Path):
        """Verify passing a non-existent ASDF path produces exit code 2."""
        runner = CliRunner()
        res = runner.invoke(cli, ["single", "--asdf", str(tmp_path / "bogus.asdf")])
        assert res.exit_code == 2
        assert "does not exist" in res.output

    def test_cli_run_nonexistent_catalog(self, tmp_path: Path):
        """Verify passing a non-existent catalog path produces exit code 2."""
        runner = CliRunner()
        res = runner.invoke(cli, ["run", "--catalog", str(tmp_path / "bogus.csv")])
        assert res.exit_code == 2
        assert "does not exist" in res.output

    def test_cli_single_invalid_detector(self):
        """Verify passing an invalid detector name (wfi99) exits cleanly with code 1."""
        runner = CliRunner()
        res = runner.invoke(cli, ["single", "--detector", "wfi99"])
        assert res.exit_code == 1
        assert "Single detector execution failed" in res.output or "not found" in res.output

    def test_cli_unknown_subcommand_and_option(self):
        """Verify unknown subcommands and unrecognized options produce exit code 2."""
        runner = CliRunner()
        res1 = runner.invoke(cli, ["single", "--unrecognized-option-xyz"])
        assert res1.exit_code == 2

        res2 = runner.invoke(cli, ["nonexistent_subcommand"])
        assert res2.exit_code == 2

    def test_cli_invalid_integer_options(self):
        """Verify non-integer canvas-size or num-workers produce exit code 2."""
        runner = CliRunner()
        res1 = runner.invoke(cli, ["single", "--canvas-size", "not_an_int"])
        assert res1.exit_code == 2

        res2 = runner.invoke(cli, ["run", "--num-workers", "not_an_int"])
        assert res2.exit_code == 2


# ==============================================================================
# Area 5: Zero-Star Detector Graceful Error Handling
# ==============================================================================
class TestZeroStarGracefulErrorHandling:
    """Stress tests for empty and out-of-footprint catalogs."""

    def test_catalog_zero_stars_in_detector_footprint(self, tmp_path: Path):
        """
        Verify that a catalog with stars entirely outside the detector sky bounds
        raises a descriptive RuntimeError rather than an unhandled crash or IndexError.
        """
        bogus_cat = tmp_path / "out_of_bounds.csv"
        pd.DataFrame({
            "source_id": [99901, 99902],
            "ra": [0.0, 1.0],  # Remote sky coordinates
            "dec": [0.0, 1.0],
            "mag_lambda": [14.0, 15.0],
        }).to_csv(bogus_cat, index=False)

        with pytest.raises(RuntimeError, match="No catalog stars found within celestial footprint"):
            run_single_detector("wfi01", catalog_path=bogus_cat, output_dir=tmp_path)

    def test_empty_catalog_file_raises_runtime_error(self, tmp_path: Path):
        """Verify an empty CSV file raises a clean descriptive RuntimeError."""
        empty_cat = tmp_path / "empty_catalog.csv"
        pd.DataFrame(columns=["source_id", "ra", "dec", "mag_lambda"]).to_csv(empty_cat, index=False)

        with pytest.raises(RuntimeError, match="No catalog stars found within celestial footprint"):
            run_single_detector("wfi01", catalog_path=empty_cat, output_dir=tmp_path)

    def test_run_pipeline_zero_stars_raises_runtime_error(self, tmp_path: Path):
        """Verify run_pipeline raises RuntimeError if no stars are extracted across detectors."""
        empty_cat = tmp_path / "empty_cat.csv"
        pd.DataFrame({
            "source_id": [99999],
            "ra": [0.0],
            "dec": [0.0],
            "mag_lambda": [14.0],
        }).to_csv(empty_cat, index=False)

        with pytest.raises(RuntimeError, match="No valid stars extracted across any of the"):
            run_pipeline(catalog_path=empty_cat, detectors=["wfi01"], output_dir=tmp_path)
