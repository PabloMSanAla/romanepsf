"""
Unit Tests for --debug Mode, Tier Allocation, and Diagnostic Plot Generation.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from click.testing import CliRunner

from romanepsf.cli import cli
from romanepsf.config import PipelineConfig, load_config
from romanepsf.stamps import StellarStamp
from romanepsf.pipeline import allocate_debug_stars_per_tier
from romanepsf.debug_plots import (
    convert_to_ab_mag_arcsec2,
    generate_debug_figure1_masking_procedure,
    generate_debug_figure2_apertures_and_profile,
    generate_debug_figure3_profile_normalization,
    generate_debug_figure4_model_psf,
    generate_debug_figure5_final_profile,
    generate_all_debug_plots,
)


def test_allocate_debug_stars_per_tier_balanced():
    """Test even distribution when sufficient stars exist in all tiers."""
    avail = {"bright": 10, "medium": 20, "faint": 50}
    alloc = allocate_debug_stars_per_tier(6, avail)
    assert alloc == {"bright": 2, "medium": 2, "faint": 2}
    assert sum(alloc.values()) == 6


def test_allocate_debug_stars_per_tier_remainder():
    """Test distribution with remainder (e.g. 5 stars)."""
    avail = {"bright": 10, "medium": 20, "faint": 50}
    alloc = allocate_debug_stars_per_tier(5, avail)
    assert sum(alloc.values()) == 5
    assert alloc["bright"] >= 1
    assert alloc["medium"] >= 1
    assert alloc["faint"] >= 1


def test_allocate_debug_stars_per_tier_rebalancing():
    """Test rebalancing when bright tier has fewer stars than nominal target."""
    avail = {"bright": 1, "medium": 10, "faint": 20}
    alloc = allocate_debug_stars_per_tier(6, avail)
    assert alloc["bright"] == 1
    assert sum(alloc.values()) == 6
    assert alloc["medium"] + alloc["faint"] == 5


def test_config_debug_validation():
    """Verify debug integer validation in config."""
    cfg = PipelineConfig()
    cfg.pipeline.debug = 6
    cfg.validate()

    cfg.pipeline.debug = 0
    with pytest.raises(ValueError, match="pipeline.debug must be a positive integer"):
        cfg.validate()

    cfg.pipeline.debug = -5
    with pytest.raises(ValueError, match="pipeline.debug must be a positive integer"):
        cfg.validate()


def test_cli_debug_flag_propagation():
    """Verify --debug flag is parsed and passed to config in run and batch-run."""
    runner = CliRunner()
    with patch("romanepsf.pipeline.run_pipeline") as mock_run:
        mock_output = MagicMock()
        mock_output.fits_path = Path("out.fits")
        mock_run.return_value = mock_output

        result = runner.invoke(cli, ["run", "--debug", "9", "--detectors", "wfi01"])
        assert result.exit_code == 0
        call_cfg = mock_run.call_args[0][0]
        assert call_cfg.pipeline.debug == 9

    with patch("romanepsf.pipeline.run_sca_batch_pipeline") as mock_batch:
        mock_output = MagicMock()
        mock_output.fits_path = Path("out.fits")
        mock_batch.return_value = mock_output

        result = runner.invoke(cli, ["batch-run", "--file-list", "tests/test_files_wfi01.txt", "--debug", "6"])
        assert result.exit_code == 0
        call_cfg = mock_batch.call_args.kwargs["cfg"]
        assert call_cfg.pipeline.debug == 6


def test_convert_to_ab_mag_arcsec2():
    """Verify surface brightness calculation matches 20.472 - 2.5*log10(I_MJy/sr)."""
    # 1.0 MJy/sr should yield 20.472
    flux_cal = np.array([1.0, 10.0, 0.0, -1.0])
    mag_cal = convert_to_ab_mag_arcsec2(flux_cal, is_calibrated=True)
    assert np.isclose(mag_cal[0], 20.472, atol=1e-3)
    assert np.isclose(mag_cal[1], 20.472 - 2.5, atol=1e-3)
    assert np.isnan(mag_cal[2])
    assert np.isnan(mag_cal[3])

    # Uncalibrated: DN/s * conversion_factor
    flux_raw = np.array([10.0])
    mag_uncal = convert_to_ab_mag_arcsec2(flux_raw, conversion_factor=0.1, is_calibrated=False)
    assert np.isclose(mag_uncal[0], 20.472, atol=1e-3)


def test_generate_all_debug_plots_end_to_end(tmp_path):
    """Verify generation of all 5 figures in output/debug directory."""
    debug_dir = tmp_path / "debug"

    # Synthetic stamps
    stamps = {"bright": [], "medium": [], "faint": []}
    for tier, sz, sid in [("bright", 121, 101), ("medium", 81, 102), ("faint", 41, 103)]:
        img = np.ones((sz, sz), dtype=np.float32) * 5.0
        mask = np.zeros((sz, sz), dtype=bool)
        res = np.zeros_like(img)
        rad_mod = img.copy()
        stamp = StellarStamp(
            source_id=sid,
            tier=tier,
            mag=12.0,
            data=img,
            mask=mask,
            center_original=(sz / 2.0, sz / 2.0),
            size=sz,
            debug_info={
                "raw_stamp": img,
                "unaligned_mask": mask,
                "residual": res,
                "radial_model": rad_mod,
                "conversion_factor": 1.0,
                "is_calibrated": True,
                "center_stamp": (sz / 2.0, sz / 2.0),
            },
        )
        stamps[tier].append(stamp)

    canvas_sz = 101
    comp_epsf = np.ones((canvas_sz, canvas_sz), dtype=np.float32) / (canvas_sz * canvas_sz)
    diagnostics = {
        "k_fm": 1.2,
        "k_mb": 1.5,
        "r_fm_min": 25.0,
        "r_fm_max": 40.0,
        "r_mb_min": 100.0,
        "r_mb_max": 160.0,
    }

    out_files = generate_all_debug_plots(
        pooled_stamps=stamps,
        composite_epsf=comp_epsf,
        diagnostics=diagnostics,
        output_dir=debug_dir,
        sca_name="WFI01",
        growth_rate=1.03,
    )

    # Check that canonical debug figures 1 to 5 exist
    assert (debug_dir / "debug_1_masking_procedure.png").is_file()
    assert (debug_dir / "debug_2_apertures_and_profile.png").is_file()
    assert (debug_dir / "debug_3_profile_normalization.png").is_file()
    assert (debug_dir / "debug_4_model_psf.png").is_file()
    assert (debug_dir / "debug_5_final_profile_normalized.png").is_file()

    # Check that SCA-named debug figures exist
    assert (debug_dir / "debug_1_wfi01_masking_procedure.png").is_file()
    assert (debug_dir / "debug_2_wfi01_apertures_and_profile.png").is_file()
    assert (debug_dir / "debug_3_wfi01_profile_normalization.png").is_file()
    assert (debug_dir / "debug_4_wfi01_model_psf.png").is_file()
    assert (debug_dir / "debug_5_wfi01_final_profile_normalized.png").is_file()
    assert (debug_dir / "debug_6_wfi01_spike_process.png").is_file()
    assert (debug_dir / "debug_spike_process_wfi01.png").is_file()

    # Check that individual star figures exist
    assert (debug_dir / "debug_1_masking_procedure_bright_101.png").is_file()
    assert (debug_dir / "debug_2_apertures_and_profile_bright_101.png").is_file()
    assert (debug_dir / "debug_3_profile_normalization_bright_101.png").is_file()
    assert (debug_dir / "debug_1_wfi01_masking_procedure_bright_101.png").is_file()
