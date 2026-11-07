## 2026-11-07T00:20:26Z
You are Explorer 2 for Milestone 3 (Single-Detector Validation & 18-Detector Pipeline Execution) of the Roman Extended PSF (ePSF) pipeline project.
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_2
Project root: /Users/pmsanch1/code/romanepsf
Python executable: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python

MANDATORY FIRST STEP:
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/

Your task:
Investigate scalable execution and memory management across all 18 Roman WFI detectors (`wfi01` to `wfi18`):
1. Investigate the 18 ASDF file sizes, loading times, and memory footprint.
   - Each file is ~134 MB on disk, with (4088, 4088) float32 arrays (data, err, dq).
   - Evaluate memory usage when keeping ASDF objects open vs immediately extracting numpy arrays and closing the ASDF file.
   - Design an explicit resource lifecycle / context manager to ensure peak resident set size (RSS) RAM stays strictly below 4 GB (requirement R3).
2. Investigate parallelization vs sequential processing:
   - Profile processing time per detector on Apple Silicon.
   - Evaluate `concurrent.futures.ProcessPoolExecutor` vs batch sequential processing with PyTorch MPS acceleration or multi-threading.
   - Check whether PyTorch MPS tensors require process isolation or if CPU fallback is cleaner for multiprocessing.
3. Design the full execution runner:
   - Discovering all 18 detectors (`*_cal.asdf`) in the input directory.
   - Handling individual detector execution failures gracefully without terminating the entire run.
   - Logging per-detector statistics (processing time, memory RSS, star counts by tier).
4. Deliver a structured handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_2/handoff.md`.
Notify the orchestrator with send_message upon completion.
