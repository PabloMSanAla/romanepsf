# BRIEFING — 2026-11-07T06:06:00Z

## Mission
Milestone 5 Phase 2 Adversarial Coverage Hardening: Conduct white-box source code analysis of the core pipeline modules (`loader.py`, `catalog.py`, `stamps.py`, `masking.py`, `assembly.py`, `profile.py`, `config.py`), identify edge cases and boundary limits, and author empirical adversarial stress tests in `tests/test_tier5_adversarial_core.py`.

## 🔒 My Identity
- Archetype: EMPIRICAL CHALLENGER
- Roles: critic, specialist
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m5_tier5_1
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: Milestone 5 Phase 2 (Adversarial Coverage Hardening)
- Instance: 1 of 1

## 🔒 Key Constraints
- Review-only — do NOT modify implementation code in `src/romanepsf/`
- Report any failures as findings — do NOT fix them yourself
- Write adversarial tests to `tests/test_tier5_adversarial_core.py`
- Verify everything empirically with `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest`
- Write handoff report to `handoff.md` and communicate via `send_message`

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: 2026-11-07T06:06:00Z

## Review Scope
- **Files reviewed**: `src/romanepsf/loader.py`, `src/romanepsf/catalog.py`, `src/romanepsf/stamps.py`, `src/romanepsf/masking.py`, `src/romanepsf/assembly.py`, `src/romanepsf/profile.py`, `src/romanepsf/config.py`
- **Interface contracts**: `PROJECT.md`, `ORIGINAL_REQUEST.md`, `DISPATCH.md`
- **Review criteria**: Robustness against extreme inputs, NaN/Inf masks, empty tiers, off-center stamps, invalid WCS/headers, boundary condition handling.

## Attack Surface
- **Hypotheses tested**:
  1. `loader.py`: Rejection of 3D/1D dimension mismatches, bit 30 in get_dq_mask, non-finite values (NaN, +Inf, -Inf) in get_effective_mask, unphysical conversion factors, and non-(4088, 4088) shapes under `validate_shape` flag.
  2. `catalog.py`: Rejection of extreme negative solar system magnitudes (Sun -26.9, Moon, planets), out-of-bounds coordinates, duplicate column collision resolution, centroid divergence protection on image boundaries, deterministic tie-breaking in crowding, and exact tier boundaries (11.0, 13.0).
  3. `stamps.py`: Odd integer sizing guarantee across tiers, off-detector cutout extraction with NaN fill, background estimation on all-NaN / flat stamps, subpixel recentering with exposed boundary masking, and faint core DQ bit 1 protection.
  4. `masking.py`: Periodicity and rotation invariance of 12 theoretical spike angles, core exclusion radius in geometric spike mask, morphological spike discrimination vs circular companion blobs, and dual-prior invariant protecting spikes from contaminant masking.
  5. `profile.py`: Boundary ellipticity (eps -> 1.0), parallel robust single-bin sigma clipping on extreme outliers (1e9), 1D/3D input shape validation, big-endian `>f4` handling, and Moffat beta parameter enforcement (beta > 1.0).
  6. `assembly.py`: Outlier rejection in tensor stacking with 3+ stamps and hollow core recovery, pathological overlap scale factor boundaries (disjoint, inverted, zero flux), raised-cosine partition of unity, graceful tier degradation across all 1-tier and 2-tier permutations, and multi-extension FITS serialization with empty summaries.
- **Vulnerabilities found**:
  1. `catalog.py`: `get_psf_extension_moffat` does not guard `beta <= 1.0` (unlike `profile.py`), which would cause `ZeroDivisionError` if `beta == 1.0`. In practice, default `beta = 1.52`.
  2. `assembly.py`: `assemble_composite_extended_psf` looks up tier names using exact lowercase keys (`"faint"`, `"medium"`, `"bright"`). If a caller passes uppercase or whitespace-padded keys, they are treated as unpopulated tiers.
  3. Mathematical finding: For Moffat extension at depth 28.0 mag/arcsec^2, the analytical cutoff radius drops to 0.0 only when `mu0 >= depth` (`mag >= 31.54`), not at `mag = 30.0` (where extension is still ~0.0989 arcsec).
- **Untested angles**:
  - Full hardware GPU execution on CUDA (tested on CPU / MPS architecture available on host).

## Key Decisions Made
- Authored 39 empirical stress test cases in `tests/test_tier5_adversarial_core.py`.
- Verified 39/39 passed in 2.28s via `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_tier5_adversarial_core.py -v`.
- Verified full regression test across `tests/unit/` (612/612 passed in 48.54s).

## Artifact Index
- `DISPATCH.md` — Dispatch instructions from orchestrator
- `BRIEFING.md` — Situational awareness and persistent memory
- `progress.md` — Liveness heartbeat and step tracking
- `tests/test_tier5_adversarial_core.py` — Dedicated Tier 5 adversarial stress test suite (39 tests)
- `handoff.md` — 5-component handoff report
