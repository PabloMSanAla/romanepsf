# BRIEFING — 2026-11-06T09:05:00Z

## Mission
Thoroughly inspect /Users/pmsanch1/code/ROSALIA, /Users/pmsanch1/code/romanepsf, and the Python environment (/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python) to identify reusable components, available libraries, existing codebase state, and architecture options.

## 🔒 My Identity
- Archetype: explorer
- Roles: Codebase & Environment Explorer, Synthesis
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: Survey & Discovery

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Write only to working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2/
- Update progress.md regularly for liveness heartbeat
- Provide structured 5-component handoff.md

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: 2026-11-06T09:05:00Z

## Investigation State
- **Explored paths**:
  - `/Users/pmsanch1/code/ROSALIA/rosalia` (psf.py, core.py, inspector.py, utils.py, telescopes.py, detectors.py)
  - `/Users/pmsanch1/code/romanepsf/src` (loader.py, catalog.py, stamps.py, masking.py, profile.py, assembly.py)
  - `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors` (18 ASDF files, source catalog, star_modelling.ipynb)
  - `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python` environment
- **Key findings**:
  - ROSALIA is installed editable (`rosalia-wfi 1.3.9.dev0`). Provides SIAF transforms (`_roman_apertures`, `_detector_to_canvas`), Roman filter curves, and spike/Moffat analytic extensions (`get_psf_extension_spikes`, `get_psf_extension_moffat`).
  - Gnuastro CLI commands are absent; ROSALIA's `astscript_*` cannot be used; `romanepsf`'s native PyTorch `profile.py` is the correct path.
  - Three critical bugs identified in existing `src/`: (1) IndexError in `assembly.py:determine_overlap_scale_factor`, (2) duplicate column rename in `catalog.py:query_gaia_for_detector`, (3) DQ bit 1 over-masking causing hollow core in faint stars.
  - PDF generation: `matplotlib.backends.backend_pdf.PdfPages` is fully functional; `pdflatex` also present.
- **Unexplored areas**: None for survey scope. Ready for handoff.

## Key Decisions Made
- Use `matplotlib.backends.backend_pdf.PdfPages` for robust, multi-page vector PDF report generation.
- Recommend clean modular layout under `src/romanepsf` or `src/` with `pyproject.toml` and CLI.

## Artifact Index
- DISPATCH.md — Dispatch log
- BRIEFING.md — Situational awareness
- progress.md — Liveness heartbeat and task tracker
- test_report.pdf — Test output verifying PdfPages capability
- handoff.md — Final structured handoff report
