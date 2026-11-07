# Progress Log — Explorer Survey 1 (Data & Catalog)

- Last visited: 2026-11-06T09:05:00Z
- Status: Investigation complete. Synthesizing handoff report.

## Tasks
- [x] 1. Inspect detector directory `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/`
  - Verified 18 `_cal.asdf` files, sizes (203.0 - 208.0 MB), directory structure (`code`, `fits`, `psf`).
- [x] 2. Inspect ASDF structure and metadata using python `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`
  - ASDF tree: `['asdf_library', 'history', 'roman']`. Model type: `roman_datamodels.datamodels._datamodels.ImageModel`.
  - Array shapes: `data` (4088, 4088) float32, `dq` (4088, 4088) uint32, `err` (4088, 4088) float16, `var_poisson` (4088, 4088) float16. Border reference pixels stored in separate border arrays.
  - WCS, pointing & angles: `meta.pointing.pa_v3` (250.04 deg), `meta.pointing.pa_aperture` (-110.13 to -109.87 deg), `meta.wcs` GWCS model.
  - Saturation flags: `SATURATED` = 2, `DO_NOT_USE` = 1, `JUMP_DET` = 4. Saturated pixels present as either NaNs or extreme values (-30,283 to +20,000 DN/s).
- [x] 3. Inspect source catalog `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv`
  - Columns: 46 columns (Gaia, 2MASS, WISE, `mag_lambda`, `cat_id`).
  - Coordinate system: `ra`, `dec` in degrees; no detector IDs or pixel coords provided in catalog.
  - Filter: `mag_lambda` is synthetic Roman F146 magnitude (effective wavelength 1.46 um).
  - WCS mapping: Discovered that GWCS `backward_transform` unconstrained polynomial produces spurious out-of-footprint matches; established mandatory forward roundtrip verification (`diff_arcsec < 0.5`).
  - Total verified in-field stars: 194 unique stars across all 18 detectors.
  - Dynamic range: `mag_lambda` 7.371 to 14.844 (7.47 mag span, ~975x flux).
  - Tier partitioning recommendation: Bright (<11.0, 17 stars), Medium (11.0-13.0, 50 stars), Faint (>=13.0, 127 stars).
  - Saturation radii: Bright stars (17 - 56 pix), Medium (6 - 16 pix), Faint (0 - 6 pix).
  - Diffraction spikes: 6-fold pupil geometry with base angles [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] adjusted by PA_APER (-110.08 deg -> delta ~ -10 deg).
- [ ] 4. Synthesize findings into handoff.md and update BRIEFING.md
- [ ] 5. Send completion message to parent
