## 2026-11-07T00:20:37Z

Sender: e80d314a-b5a0-43fb-be2e-ceabc982347e
Priority: MESSAGE_PRIORITY_HIGH

You are Explorer 3 for Milestone 3 (Single-Detector Validation & 18-Detector Pipeline Execution) of the Roman Extended PSF (ePSF) pipeline project.
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_3
Project root: /Users/pmsanch1/code/romanepsf
Python executable: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python

MANDATORY FIRST STEP:
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/src/romanepsf/assembly.py

Your task:
Investigate and design multi-detector cross-SCA stamp pooling and composite extended PSF canvas assembly:
1. Multi-detector stamp pooling strategy:
   - How stamps from all 18 SCAs should be accumulated into global tiers (`faint`, `medium`, `bright`).
   - Notice that 6 detectors lack bright stars, but when pooling across all 18 detectors, all 3 tiers are populated!
   - How cross-tier scale factors $k_{\text{FM}}$ and $k_{\text{MB}}$ should be determined across the pooled stamps.
   - Sizing the composite extended PSF canvas: configurable between 1024x1024 and 2048x2048 pixels (e.g. 1025x1025 or 2049x2049 odd dimensions).
2. FITS output serialization:
   - Primary HDU with composite ePSF image data (float32).
   - Additional HDU extensions or header keywords:
     * Filter name: F146
     * Pixel scale: 0.11 arcsec/pixel
     * Number of contributing detectors (18)
     * Total stars used in Faint, Medium, Bright tiers
     * Derived scale factors $k_{\text{FM}}$, $k_{\text{MB}}$
     * Theoretical base spike angles and net orientation
     * Provenance / timestamp
   - Secondary HDUs: coverage map, 1D radial profiles, per-detector summary table.
3. Design CLI subcommand `romanepsf run`:
   - Arguments and options: `--input-dir`, `--catalog`, `--config`, `--output-dir`, `--canvas-size` (default 1025 or 2049), `--device`.
4. Synthesize a unified blueprint and provide draft unit and integration tests.
5. Deliver a structured handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_3/handoff.md`.
Notify the orchestrator with send_message upon completion.
