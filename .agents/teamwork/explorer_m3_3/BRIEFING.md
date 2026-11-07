# BRIEFING — 2026-11-07T00:27:00Z

## Mission
Investigate and design multi-detector cross-SCA stamp pooling, composite extended PSF canvas assembly, FITS serialization, and the `romanepsf run` CLI subcommand for Milestone 3.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_3
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: Milestone 3 (Single-Detector Validation & 18-Detector Pipeline Execution)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement source code directly
- Document blueprints, designs, proposed diffs/patches, and unit/integration test specifications
- Produce 5-component handoff.md in working directory
- Notify parent agent upon completion via send_message

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: 2026-11-07T00:21:00Z

## Investigation State
- **Explored paths**:
  * Simulated commissioning data `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/` (all 18 `*_cal.asdf` files and catalog CSV).
  * Existing modules: `assembly.py`, `stamps.py`, `masking.py`, `loader.py`, `catalog.py`, `cli.py`, `config.py`.
  * Test suites: `tests/unit/test_cli.py`, `tests/e2e/test_tier1_features.py`, `tests/e2e/test_tier4_scenarios.py`.
- **Key findings**:
  * Confirmed exactly 6 detectors lack bright stars: `wfi02`, `wfi03`, `wfi08`, `wfi13`, `wfi17`, `wfi18`.
  * Across all 18 detectors, pooling yields: 89 faint stars, 39 medium stars, 12 bright stars (total 140 isolated, centroid-refined stars).
  * Empirical scale factors determined on pooled 18-SCA stamps: $k_{\text{FM}} = 0.193659$, $k_{\text{MB}} = 0.025527$.
  * End-to-end sequential extraction of all 18 detectors took only 9.78s; 1025x1025 assembly took 0.31s; 2049x2049 assembly took 0.33s.
  * Odd canvas dimensions (1025x1025, 2049x2049) ensure integer centering at $((S-1)/2, (S-1)/2)$.
  * Designed 4-HDU FITS output architecture: Primary (ePSF float32), HDU 1 (COVERAGE int32), HDU 2 (RADIAL_PROFILES BinTable), HDU 3 (DETECTOR_SUMMARY BinTable). All keywords strictly conform to standard 8-character FITS conventions (no HIERARCH warnings).
  * Designed CLI enhancements for `romanepsf run` supporting `--input-dir`, `--catalog`, `--config`, `--output-dir`, `--canvas-size`, `--device`, `--detectors`, `--num-workers`.
- **Unexplored areas**: None. All 5 prompt objectives thoroughly researched, empirically validated, and designed.

## Key Decisions Made
- Multi-detector stamp pooling aggregates all 18 SCAs into a single 3-tier dictionary (`pooled_stamps: Dict[str, List[StellarStamp]]`).
- Cross-tier scale factors $k_{\text{FM}}$ and $k_{\text{MB}}$ are determined globally on the pooled 18-SCA tier profiles, overcoming local tier sparsity.
- FITS header keywords strictly follow the <= 8-character standard (`NSTARS`, `NSTAR_F`, `SCALE_FM`, `SCALE_MB`, `BASE_ANG`, `PA_APER`, `NET_ROT`, etc.).
- Designed `serialize_composite_epsf_fits` function and complete blueprint for `src/romanepsf/pipeline.py` and `src/romanepsf/cli.py`.

## Artifact Index
- DISPATCH.md — incoming dispatch instructions
- BRIEFING.md — persistent state and context
- progress.md — liveness heartbeat
- handoff.md — final handoff report
