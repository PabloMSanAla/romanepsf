"""
Pytest plugin that applies all 3 unified patches (Pages 6, 7, 8) before running test suites.
"""
import sys
from pathlib import Path

# Add current folder to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from unified_verification import apply_patches

def pytest_configure(config):
    apply_patches()
    print("\n[UNIFIED_PLUGIN] Applied Page 6, Page 7, Page 8 patches into romanepsf.report")
