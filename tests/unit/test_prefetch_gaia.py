"""
Unit Tests for prefetch_gaia_for_files and Gaia Spatial Prefetching.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from romanepsf.pipeline import prefetch_gaia_for_files
from romanepsf.config import Config


def test_prefetch_gaia_for_files_basic(tmp_path):
    """Test prefetching Gaia tiles for a list of files."""
    f1 = tmp_path / "r001_wfi01_cal.asdf"
    f2 = tmp_path / "r002_wfi01_cal.asdf"
    f1.touch()
    f2.touch()

    file_list = tmp_path / "files.txt"
    file_list.write_text(f"{f1}\n{f2}\n")

    cache_dir = tmp_path / "gaia_cache"

    fake_footprint_1 = ("wfi01", (10.0, -20.0, 0.1, 9.9, 10.1, -20.1, -19.9))
    fake_footprint_2 = ("wfi01", (10.05, -20.05, 0.1, 9.95, 10.15, -20.15, -19.95))

    with patch("romanepsf.pipeline.fast_scan_asdf_footprint") as mock_scan, \
         patch("romanepsf.pipeline.GaiaSpatialManager") as mock_mgr_cls:

        mock_scan.side_effect = [fake_footprint_1, fake_footprint_2]
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr

        # Tiles returned
        mock_mgr.query_disc_tiles.side_effect = [[101, 102], [102, 103]]
        # Missing tiles: first check returns [101, 103]; after local partition check still [101, 103]
        mock_mgr.get_missing_tiles.side_effect = [
            [101, 103],
            [101, 103],
        ]
        mock_mgr.fetch_missing_tiles_polite.return_value = 2

        summary = prefetch_gaia_for_files(
            files=file_list,
            sca_id="1",
            gaia_cache_dir=cache_dir,
            master_catalog_path=tmp_path / "nonexistent.csv",
            delay_seconds=0.1,
        )

        assert summary["total_files"] == 2
        assert summary["scanned_files"] == 2
        assert summary["unique_tiles"] == 3
        assert summary["downloaded_tiles"] == 2
        assert mock_mgr.fetch_missing_tiles_polite.called


def test_prefetch_gaia_sca_filtering(tmp_path):
    """Test that prefetch_gaia_for_files only scans files matching target sca_id."""
    f1 = tmp_path / "f1.asdf"
    f2 = tmp_path / "f2.asdf"
    f1.touch()
    f2.touch()

    with patch("romanepsf.pipeline.fast_scan_asdf_footprint") as mock_scan, \
         patch("romanepsf.pipeline.GaiaSpatialManager") as mock_mgr_cls:

        mock_scan.side_effect = [
            ("wfi01", (10.0, -20.0, 0.1, 9.9, 10.1, -20.1, -19.9)),
            ("wfi02", (15.0, -25.0, 0.1, 14.9, 15.1, -25.1, -24.9)),
        ]
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr
        mock_mgr.query_disc_tiles.return_value = [500]
        mock_mgr.get_missing_tiles.return_value = []

        summary = prefetch_gaia_for_files(
            files=[f1, f2],
            sca_id="wfi01",
            gaia_cache_dir=tmp_path / "gaia",
        )

        assert summary["total_files"] == 2
        assert summary["scanned_files"] == 1
        assert summary["unique_tiles"] == 1
        assert summary["missing_tiles"] == 0
        assert summary["downloaded_tiles"] == 0


def test_prefetch_gaia_no_files_found(tmp_path):
    """Test that prefetch_gaia_for_files raises ValueError if no valid files exist."""
    with pytest.raises(ValueError, match="No valid input L2 ASDF files found"):
        prefetch_gaia_for_files(files=[])
