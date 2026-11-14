"""
Site-wide customization script to suppress harmless AsdfPackageVersionWarning
when opening Roman ASDF files created with newer extension URIs.

Usage:
Copy this file into your conda environment's site-packages:
  cp scripts/sitecustomize.py /opt/conda/envs/RomanNexus-2026.2/lib/python3.13/site-packages/
"""

import warnings

try:
    from asdf.exceptions import AsdfPackageVersionWarning
    warnings.filterwarnings("ignore", category=AsdfPackageVersionWarning)
except ImportError:
    pass

warnings.filterwarnings("ignore", message=r".*was created with extension URI.*")
warnings.filterwarnings("ignore", message=r".*AsdfPackageVersionWarning.*")
