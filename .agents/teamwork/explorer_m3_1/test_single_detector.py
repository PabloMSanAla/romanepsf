"""
Comprehensive Unit Tests for Single-Detector Extended PSF Execution (Milestone 3).

Tests:
1. SingleDetectorResult dataclass serialization and formatting.
2. Standard astropy.io.fits header compliance for single-detector model export.
3. Signature polymorphism for run_single_detector (standard, config-first, keyword-only).
4. Full execution flow on simulated commissioning data (mocked and live).
5. Multi-tier fallback handling for detectors with 0 bright stars (e.g. WFI02).
6. Missing ASDF file and empty catalog error handling.
7. Click CLI `romanepsf single` flag parsing (--detector, --asdf, --catalog, --config, --output-dir, --canvas-size).
8. Even canvas size conversion to odd integer.
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

# Import blueprint implementations
import sys
sys.path.insert(0, str(Path(__file__).parent))
from blueprint_pipeline import (
    SingleDetectorResult,
    PipelineOutputs,
    RomanPSFConfig,
    export_single_detector_fits,
    run_single_detector,
    run_pipeline,
)
from romanepsf.config import load_config, PipelineConfig
from romanepsf.stamps import StellarStamp


class TestSingleDetectorResultDataclass:
    """Tests for SingleDetectorResult container."""

    def test_result_attributes_and_serialization(self):
        """Verify attributes and to_dict serialization."""
        canvas = np.zeros((1025, 1025), dtype=np.float32)
        canvas[512, 512] = 1.0

        res = SingleDetectorResult(
            detector_id="wfi01",
            asdf_path=Path("dummy_wfi01.asdf"),
            fits_path=Path("dummy_wfi01.fits"),
            epsf_model=canvas,
            canvas_size=1025,
            star_counts={"bright": 1, "medium": 2, "faint": 2, "total": 5},
            scale_factors={"k_fm": 0.197, "k_mb": 0.027},
            pixel_scale=0.11,
            pa_aperture=-110.02,
            diagnostics={"k_fm": 0.197, "k_mb": 0.027},
            stamps_by_tier={"bright": [], "medium": [], "faint": []},
            catalog_df=pd.DataFrame({"source_id": [1, 2, 3]}),
            execution_time_s=3.45,
            success=True,
        )

        d = res.to_dict()
        assert d["detector_id"] == "wfi01"
        assert d["canvas_size"] == 1025
        assert d["star_counts"]["total"] == 5
        assert d["scale_factors"]["k_fm"] == 0.197
        assert d["success"] is True

        summary = res.summary()
        assert "WFI01" in summary
        assert "stars=5" in summary
        assert "1025x1025" in summary


class TestExportSingleDetectorFITS:
    """Tests for FITS export and standard header compliance."""

    def test_export_fits_headers_compliance(self, tmp_path):
        """Verify all required standard header cards are properly populated."""
        canvas = np.zeros((1025, 1025), dtype=np.float32)
        canvas[512, 512] = 1.0
        fits_out = tmp_path / "test_wfi01.fits"

        export_single_detector_fits(
            epsf_model=canvas,
            fits_path=fits_out,
            detector_id="wfi01",
            filter_name="F146",
            pixel_scale=0.11,
            pixel_area=2.800978e-13,
            zp_ab=26.836,
            pa_aperture=-110.02,
            star_counts={"bright": 1, "medium": 2, "faint": 2, "total": 5},
            scale_factors={"k_fm": 0.197245, "k_mb": 0.027220},
        )

        assert fits_out.is_file()
        with fits.open(fits_out) as hdul:
            assert len(hdul) == 1
            h = hdul[0].header
            assert h["EXTNAME"] == "EPSF"
            assert h["TELESCOP"] == "ROMAN"
            assert h["INSTRUME"] == "WFI"
            assert h["DETECTOR"] == "WFI01"
            assert h["FILTER"] == "F146"
            assert np.isclose(h["PIXSCALE"], 0.11)
            assert h["CANVAS_S"] == 1025
            assert np.isclose(h["CRPIX1"], 513.0)
            assert np.isclose(h["CRPIX2"], 513.0)
            assert np.isclose(h["CRVAL1"], 0.0)
            assert np.isclose(h["CRVAL2"], 0.0)
            assert h["NORM"] == "UNIT_FLUX"
            assert np.isclose(h["SUM_FLUX"], 1.0)
            assert h["N_BRIGHT"] == 1
            assert h["N_MEDIUM"] == 2
            assert h["N_FAINT"] == 2
            assert h["N_TOTAL"] == 5
            assert np.isclose(h["K_FM"], 0.197245)
            assert np.isclose(h["K_MB"], 0.027220)
            assert "DATE" in h
            assert h["ORIGIN"] == "Roman Extended PSF Pipeline"

    def test_export_fits_missing_bright_tier_header(self, tmp_path):
        """Verify fallback detector (0 bright stars) encodes K_MB as -1.0 and N_BRIGHT as 0."""
        canvas = np.zeros((1025, 1025), dtype=np.float32)
        canvas[512, 512] = 1.0
        fits_out = tmp_path / "test_wfi02.fits"

        export_single_detector_fits(
            epsf_model=canvas,
            fits_path=fits_out,
            detector_id="wfi02",
            filter_name="F146",
            pixel_scale=0.11,
            star_counts={"bright": 0, "medium": 2, "faint": 4, "total": 6},
            scale_factors={"k_fm": 0.106889, "k_mb": None},
        )

        with fits.open(fits_out) as hdul:
            h = hdul[0].header
            assert h["DETECTOR"] == "WFI02"
            assert h["N_BRIGHT"] == 0
            assert h["N_TOTAL"] == 6
            assert np.isclose(h["K_FM"], 0.106889)
            assert np.isclose(h["K_MB"], -1.0)  # Unused flag value


class TestRunSingleDetectorExecution:
    """Tests for run_single_detector pipeline orchestration."""

    @pytest.fixture
    def mock_l2_data(self):
        """Mock RomanL2Data object."""
        l2 = MagicMock()
        l2.detector = "WFI01"
        l2.filter_name = "F146"
        l2.data = np.full((4088, 4088), 10.0, dtype=np.float32)
        l2.raw_data = np.full((4088, 4088), 10.0, dtype=np.float32)
        l2.err = np.ones((4088, 4088), dtype=np.float32)
        l2.dq = np.zeros((4088, 4088), dtype=np.uint32)
        l2.pixel_scale = 0.11
        l2.pixel_area = 2.800978e-13
        l2.zp_ab = 26.836
        l2.pa_aperture = -110.0
        l2.wcs = MagicMock()
        l2.wcs.side_effect = lambda x, y: (10.0 + np.asarray(x) * 0.0001, -20.0 + np.asarray(y) * 0.0001)
        l2.wcs.backward_transform.side_effect = lambda ra, dec: (
            (np.asarray(ra) - 10.0) / 0.0001,
            (np.asarray(dec) + 20.0) / 0.0001,
        )
        return l2

    @patch("blueprint_pipeline.load_l2_image")
    @patch("blueprint_pipeline.assemble_composite_extended_psf")
    def test_run_single_detector_signature_polymorphism(
        self, mock_assemble, mock_load, mock_l2_data, tmp_path
    ):
        """Verify run_single_detector supports both standard and config-first signatures."""
        mock_load.return_value = mock_l2_data
        canvas = np.zeros((1025, 1025), dtype=np.float32)
        canvas[512, 512] = 1.0
        mock_assemble.return_value = (canvas, {"k_fm": 0.2, "k_mb": 0.03})

        asdf_dummy = tmp_path / "dummy_wfi01.asdf"
        asdf_dummy.touch()
        cat_dummy = tmp_path / "dummy_cat.csv"
        df = pd.DataFrame({
            "source_id": [1, 2, 3],
            "ra": [10.05, 10.10, 10.15],
            "dec": [-19.95, -19.90, -19.85],
            "mag_lambda": [10.5, 12.0, 14.0],
            "tier": ["bright", "medium", "faint"],
        })
        df.to_csv(cat_dummy, index=False)

        cfg = load_config()

        # Signature 1: run_single_detector(detector_id, asdf_path, catalog_path, config, output_dir)
        res1 = run_single_detector(
            "wfi01",
            asdf_path=asdf_dummy,
            catalog_path=cat_dummy,
            config=cfg,
            output_dir=tmp_path / "out1",
        )
        assert isinstance(res1, SingleDetectorResult)
        assert res1.detector_id == "wfi01"
        assert res1.fits_path.is_file()

        # Signature 2: run_single_detector(cfg, detector="wfi01", asdf_path=...)
        res2 = run_single_detector(
            cfg,
            detector="wfi01",
            asdf_path=asdf_dummy,
            catalog_path=cat_dummy,
            output_dir=tmp_path / "out2",
        )
        assert isinstance(res2, SingleDetectorResult)
        assert res2.detector_id == "wfi01"
        assert res2.fits_path.is_file()

    def test_missing_asdf_raises_file_not_found(self, tmp_path):
        """Verify non-existent ASDF path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="ASDF file not found"):
            run_single_detector(
                detector_id="wfi01",
                asdf_path=tmp_path / "non_existent.asdf",
                catalog_path=tmp_path / "dummy.csv",
                output_dir=tmp_path,
            )

    @patch("blueprint_pipeline.load_l2_image")
    def test_empty_catalog_raises_runtime_error(self, mock_load, mock_l2_data, tmp_path):
        """Verify empty catalog bounds raise descriptive RuntimeError."""
        mock_load.return_value = mock_l2_data
        asdf_dummy = tmp_path / "dummy_wfi01.asdf"
        asdf_dummy.touch()
        cat_dummy = tmp_path / "empty_cat.csv"
        pd.DataFrame(columns=["ra", "dec", "mag_lambda"]).to_csv(cat_dummy, index=False)

        with pytest.raises(RuntimeError, match="No catalog stars found"):
            run_single_detector(
                detector_id="wfi01",
                asdf_path=asdf_dummy,
                catalog_path=cat_dummy,
                output_dir=tmp_path,
            )

    @patch("blueprint_pipeline.load_l2_image")
    @patch("blueprint_pipeline.assemble_composite_extended_psf")
    def test_even_canvas_size_conversion(self, mock_assemble, mock_load, mock_l2_data, tmp_path):
        """Verify even canvas_size=1024 is automatically promoted to odd 1025."""
        mock_load.return_value = mock_l2_data
        canvas = np.zeros((1025, 1025), dtype=np.float32)
        canvas[512, 512] = 1.0
        mock_assemble.return_value = (canvas, {"k_fm": 0.2, "k_mb": 0.03})

        asdf_dummy = tmp_path / "dummy_wfi01.asdf"
        asdf_dummy.touch()
        cat_dummy = tmp_path / "dummy_cat.csv"
        pd.DataFrame({
            "source_id": [1],
            "ra": [10.05],
            "dec": [-19.95],
            "mag_lambda": [12.0],
            "tier": ["medium"],
        }).to_csv(cat_dummy, index=False)

        res = run_single_detector(
            "wfi01",
            asdf_path=asdf_dummy,
            catalog_path=cat_dummy,
            output_dir=tmp_path,
            canvas_size=1024,
        )
        assert res.canvas_size == 1025
        assert mock_assemble.call_args.kwargs["output_size"] == 1025


class TestCliSingleCommandIntegration:
    """Tests for Click CLI single subcommand."""

    def test_cli_single_help_displays_flags(self):
        """Verify `romanepsf single --help` exposes all required flags."""
        from romanepsf.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["single", "--help"])
        assert result.exit_code == 0
        assert "--detector" in result.output
        assert "--canvas-size" in result.output
        assert "--output-dir" in result.output

    def test_cli_single_execution_mocked(self):
        """Verify CLI single parses arguments and invokes run_single_detector."""
        from romanepsf.cli import cli
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_output = MagicMock()
        mock_output.fits_path = Path("output/roman_epsf_wfi01.fits")
        mock_pipeline.run_single_detector.return_value = mock_output

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, [
                "single",
                "--detector", "wfi01",
                "--canvas-size", "1025",
                "--output-dir", "output/test_cli",
            ])

            assert result.exit_code == 0
            assert mock_pipeline.run_single_detector.called
            cfg_arg = mock_pipeline.run_single_detector.call_args[0][0]
            assert cfg_arg.data.detectors == ["wfi01"]
            assert cfg_arg.assembly.canvas_size == 1025


class TestLiveSimulatedDataExecution:
    """Integration tests running directly on real simulated commissioning ASDF datasets."""

    @pytest.mark.skipif(
        not Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf").is_file(),
        reason="Simulated commissioning data not found",
    )
    def test_live_single_detector_wfi01_end_to_end(self, tmp_path):
        """Verify full end-to-end execution on live WFI01 data."""
        cfg = load_config()
        cfg.data.output_dir = tmp_path / "wfi01_out"

        res = run_single_detector("wfi01", config=cfg, output_dir=tmp_path / "wfi01_out")
        assert res.success is True
        assert res.detector_id == "wfi01"
        assert res.epsf_model.shape == (1025, 1025)
        assert np.isclose(np.sum(res.epsf_model), 1.0, atol=1e-5)
        assert res.star_counts["bright"] >= 1
        assert res.star_counts["medium"] >= 1
        assert res.star_counts["faint"] >= 1
        assert res.scale_factors["k_fm"] is not None and res.scale_factors["k_fm"] > 0
        assert res.scale_factors["k_mb"] is not None and res.scale_factors["k_mb"] > 0
        assert res.fits_path.is_file()

        # Check FITS header
        with fits.open(res.fits_path) as hdul:
            h = hdul[0].header
            assert h["DETECTOR"] == "WFI01"
            assert h["EXTNAME"] == "EPSF"
            assert h["N_TOTAL"] == res.star_counts["total"]
            assert np.isclose(h["SUM_FLUX"], 1.0, atol=1e-5)

    @pytest.mark.skipif(
        not Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi02_f146_cal.asdf").is_file(),
        reason="Simulated commissioning data not found",
    )
    def test_live_single_detector_wfi02_fallback_zero_bright_stars(self, tmp_path):
        """Verify 2-tier fallback execution on live WFI02 data (0 bright stars)."""
        cfg = load_config()
        out_dir = tmp_path / "wfi02_out"

        res = run_single_detector("wfi02", config=cfg, output_dir=out_dir)
        assert res.success is True
        assert res.detector_id == "wfi02"
        assert res.epsf_model.shape == (1025, 1025)
        assert np.isclose(np.sum(res.epsf_model), 1.0, atol=1e-5)
        assert res.star_counts["bright"] == 0
        assert res.star_counts["medium"] >= 1
        assert res.star_counts["faint"] >= 1
        assert res.scale_factors["k_fm"] is not None and res.scale_factors["k_fm"] > 0
        assert res.scale_factors["k_mb"] is None
        assert res.fits_path.is_file()

        with fits.open(res.fits_path) as hdul:
            h = hdul[0].header
            assert h["DETECTOR"] == "WFI02"
            assert h["N_BRIGHT"] == 0
            assert h["K_MB"] == -1.0

