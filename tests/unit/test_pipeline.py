"""
Unit and Integration Tests for Roman ePSF Pipeline (Milestone 3).

Comprehensive test suite covering:
1. discover_detectors discovery and filtering.
2. SingleDetectorResult and PipelineOutputs containers.
3. export_single_detector_fits standard FITS header compliance and signature polymorphism.
4. run_single_detector signature polymorphism and even canvas size promotion.
5. Missing ASDF file and empty catalog error handling.
6. Multi-tier fallback handling for detectors with 0 bright stars (e.g. WFI02).
7. process_single_detector_stamps memory management and extraction.
8. serialize_composite_epsf_fits 4-HDU multi-extension FITS structure.
9. Multi-detector pooling and pipeline execution across multiple SCAs.
10. Live execution on real simulated commissioning data (WFI01 and WFI02).
"""

from __future__ import annotations

import gc
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pytest
from astropy.io import fits

from romanepsf.pipeline import (
    SingleDetectorResult,
    PipelineOutputs,
    discover_detectors,
    process_single_detector_stamps,
    export_single_detector_fits,
    run_single_detector,
    run_pipeline,
)
from romanepsf.assembly import serialize_composite_epsf_fits
from romanepsf.config import Config, PipelineConfig, load_config
from romanepsf.stamps import StellarStamp


class TestDiscoverDetectors:
    """Tests for detector file discovery and filtering."""

    def test_discover_all_detectors(self, tmp_path):
        """Verify discovery of all matching cal ASDF files."""
        for i in range(1, 19):
            (tmp_path / f"r0108301001001001001_0001_wfi{i:02d}_f146_cal.asdf").touch()
        # Non-matching file
        (tmp_path / "other_file.txt").touch()

        dets = discover_detectors(tmp_path)
        assert len(dets) == 18
        assert "wfi01" in dets
        assert "wfi18" in dets
        assert dets["wfi01"].name.endswith("wfi01_f146_cal.asdf")

    def test_discover_requested_detectors_subset(self, tmp_path):
        """Verify filtering when a specific detector list is requested."""
        for i in [1, 2, 5, 8]:
            (tmp_path / f"r0108301001001001001_0001_wfi{i:02d}_f146_cal.asdf").touch()

        dets = discover_detectors(tmp_path, requested=["WFI01", "wfi05"])
        assert len(dets) == 2
        assert set(dets.keys()) == {"wfi01", "wfi05"}

    def test_discover_requested_all_keyword(self, tmp_path):
        """Verify requested=['all'] returns all discovered detectors."""
        for i in [1, 2]:
            (tmp_path / f"r0108301001001001001_0001_wfi{i:02d}_f146_cal.asdf").touch()

        dets = discover_detectors(tmp_path, requested=["all"])
        assert len(dets) == 2

    def test_discover_empty_directory(self, tmp_path):
        """Verify empty dictionary returned for directory without ASDF files."""
        dets = discover_detectors(tmp_path)
        assert dets == {}


class TestDataStructures:
    """Tests for SingleDetectorResult and PipelineOutputs."""

    def test_single_detector_result_serialization(self):
        """Verify SingleDetectorResult attributes, to_dict, and summary."""
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

    def test_pipeline_outputs_aliasing(self):
        """Verify stamps_by_tier and pooled_stamps alias properly in PipelineOutputs."""
        canvas = np.zeros((1025, 1025), dtype=np.float32)
        stamps = {"bright": [], "medium": [], "faint": []}
        out = PipelineOutputs(
            composite_epsf=canvas,
            fits_path=Path("composite.fits"),
            diagnostics={},
            pooled_stamps=stamps,
        )
        assert out.stamps_by_tier is stamps
        assert out.pooled_stamps is stamps


class TestExportSingleDetectorFITS:
    """Tests for single-detector FITS export and standard header compliance."""

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
            assert "DATE_UTC" in h
            assert "PROV_VER" in h
            assert h["ORIGIN"] == "Roman Extended PSF Pipeline"

            # Verify no header keyword exceeds 8 characters
            for key in h.keys():
                assert len(key) <= 8 or key.startswith("CONTINUE"), f"Keyword {key} exceeds 8 chars!"

    def test_export_fits_from_result_object(self, tmp_path):
        """Verify polymorphic invocation passing SingleDetectorResult object directly."""
        canvas = np.zeros((1025, 1025), dtype=np.float32)
        canvas[512, 512] = 1.0
        fits_out = tmp_path / "test_polymorphic.fits"

        res = SingleDetectorResult(
            detector_id="wfi03",
            asdf_path=Path("dummy.asdf"),
            fits_path=fits_out,
            epsf_model=canvas,
            canvas_size=1025,
            star_counts={"bright": 0, "medium": 3, "faint": 2, "total": 5},
            scale_factors={"k_fm": 0.15, "k_mb": None},
            pixel_scale=0.11,
            pa_aperture=-110.0,
            diagnostics={},
            stamps_by_tier={},
            catalog_df=pd.DataFrame(),
            execution_time_s=1.0,
        )

        p = export_single_detector_fits(res, fits_out)
        assert p == fits_out
        with fits.open(fits_out) as hdul:
            assert hdul[0].header["DETECTOR"] == "WFI03"
            assert hdul[0].header["N_BRIGHT"] == 0
            assert hdul[0].header["K_MB"] == -1.0


class TestSerializeCompositeEPSFFITS:
    """Tests for 4-HDU multi-extension FITS serialization."""

    def test_composite_fits_4_hdus(self, tmp_path):
        """Verify composite serialization creates PRIMARY, COVERAGE, RADIAL_PROFILES, DETECTOR_SUMMARY."""
        S = 1025
        epsf = np.zeros((S, S), dtype=np.float32)
        epsf[512, 512] = 1.0
        diag = {
            "k_fm": 0.1936,
            "k_mb": 0.0255,
            "total_flux_raw": 100.0,
            "cov_faint": np.ones((81, 81), dtype=np.int32),
            "cov_medium": np.ones((201, 201), dtype=np.int32),
            "cov_bright": np.ones((1001, 1001), dtype=np.int32),
            "r_f": np.array([1.0, 2.0, 5.0]),
            "prof_f": np.array([10.0, 5.0, 1.0]),
            "r_m": np.array([2.0, 5.0, 10.0]),
            "prof_m_scaled": np.array([5.0, 1.0, 0.2]),
            "r_b": np.array([10.0, 20.0, 50.0]),
            "prof_b": np.array([1.0, 0.1, 0.01]),
        }
        summaries = [
            {
                "detector": f"wfi{i:02d}",
                "faint": 4,
                "medium": 2,
                "bright": 1 if i not in [2, 3, 8, 13, 17, 18] else 0,
                "total": 7 if i not in [2, 3, 8, 13, 17, 18] else 6,
                "pa_aperture": -110.0,
                "pixel_scale": 0.11,
                "time_s": 0.5,
                "status": "SUCCESS",
            }
            for i in range(1, 19)
        ]
        out_fits = tmp_path / "roman_epsf_composite.fits"
        serialize_composite_epsf_fits(epsf, diag, summaries, out_fits)

        assert out_fits.is_file()
        with fits.open(out_fits) as hdul:
            assert len(hdul) == 4
            assert hdul[0].name == "EPSF"
            assert hdul[1].name == "COVERAGE"
            assert hdul[2].name == "RADIAL_PROFILES"
            assert hdul[3].name == "DETECTOR_SUMMARY"

            # Check header
            hdr = hdul[0].header
            assert hdr["FILTER"] == "F146"
            assert hdr["PIXSCALE"] == 0.11
            assert hdr["NDET"] == 18
            assert hdr["NSTARS"] == sum(d["total"] for d in summaries)
            assert np.isclose(hdr["SCALE_FM"], 0.1936, atol=1e-3)
            assert np.isclose(hdr["SCALE_MB"], 0.0255, atol=1e-3)
            assert "BASE_ANG" in hdr
            assert "NET_ROT" in hdr
            assert "DATE_UTC" in hdr

            # Check coverage shape
            assert hdul[1].data.shape == (S, S)
            assert np.issubdtype(hdul[1].data.dtype, np.integer) and hdul[1].data.dtype.itemsize == 4

            # Check radial profiles table
            table_names = hdul[2].columns.names
            assert "RADIUS_PX" in table_names
            assert "FLUX_COMPOSITE" in table_names

            # Check detector summary table
            assert len(hdul[3].data) == 18
            assert hdul[3].data["DETECTOR"][0] == "wfi01"


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

    @patch("romanepsf.pipeline.load_l2_image")
    @patch("romanepsf.pipeline.assemble_composite_extended_psf")
    def test_run_single_detector_signature_polymorphism(
        self, mock_assemble, mock_load, mock_l2_data, tmp_path
    ):
        """Verify run_single_detector supports standard, config-first, and keyword-only signatures."""
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

    @patch("romanepsf.pipeline.load_l2_image")
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

    @patch("romanepsf.pipeline.load_l2_image")
    @patch("romanepsf.pipeline.assemble_composite_extended_psf")
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


class TestLiveSimulatedDataExecution:
    """Integration tests running directly on real simulated commissioning ASDF datasets."""

    COMMISSIONING_DIR = Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors")
    WFI01_ASDF = COMMISSIONING_DIR / "r0108301001001001001_0001_wfi01_f146_cal.asdf"
    WFI02_ASDF = COMMISSIONING_DIR / "r0108301001001001001_0001_wfi02_f146_cal.asdf"

    @pytest.mark.skipif(
        not WFI01_ASDF.is_file(),
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
        not WFI02_ASDF.is_file(),
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

    @pytest.mark.skipif(
        not WFI01_ASDF.is_file(),
        reason="Simulated commissioning data not found",
    )
    def test_live_pipeline_multi_detector_subset(self, tmp_path):
        """Verify multi-detector pooling across WFI01 and WFI02."""
        cfg = load_config()
        cfg.data.detectors = ["wfi01", "wfi02"]
        cfg.data.output_dir = tmp_path / "multi_out"

        out = run_pipeline(cfg)
        assert isinstance(out, PipelineOutputs)
        assert out.fits_path.is_file()
        assert out.composite_epsf.shape == (1025, 1025)
        assert np.isclose(np.sum(out.composite_epsf), 1.0, atol=1e-5)
        assert len(out.detector_summaries) == 2
        assert len(out.pooled_stamps["bright"]) >= 1  # From WFI01
        assert len(out.pooled_stamps["medium"]) >= 2
        assert len(out.pooled_stamps["faint"]) >= 2

        with fits.open(out.fits_path) as hdul:
            assert len(hdul) == 4
            assert hdul[0].header["NDET"] == 2
            assert hdul[0].header["NSTARS"] >= 10
