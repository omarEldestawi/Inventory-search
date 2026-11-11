# v2.7.2 release evidence

| Requirement | Evidence | Status |
| --- | --- | --- |
| Phase 0 snapshot | `491e793` on `release/v2.7.2`, protected-file diff empty against `v2.7.1` | Recorded |
| Phase 0 dependencies | `d62bfd0`, `pytest` and `psutil` installed under Python 3.12.10 | Recorded |
| Original batch | Four PDFs from the slow-import diagnosis and user-confirmed `نواقص11-11.xlsx`, with hashes in `scratch/v272-baseline/inputs.json` | Inputs identified |
| Section 0.1 | `scratch/v272-baseline/source_evidence.json` records financial column coordinates throughout the batch and 14 visually checked first-page rows | Baseline source evidence captured, candidate verification pending |
| Section 0.2 | First packaged WIP trace in `scratch/v272-baseline/batch-first/events` recorded two parse starts for each of the four PDFs | Duplicate work reproduced, implementation and candidate checks pending |
| D1 | Dead-worker lock and restart regression | Pending |
| D2 | Request deadline and stalled-pipe test | Pending |
| D3 | READY deadline and startup-failure test | Pending |
| D4 | Stderr drain test | Pending |
| D5 | Session circuit breaker test | Pending |
| D6 | Review threading and actual Tk heartbeat | Pending |
| D7 | Real Review action exercising clipped render and OCR | Pending |
| D8 | `tests/test_v272_box_ocr_parser.py` covers financial roles, ambiguity, decimal and RTL cases | Parser tests passed, Review integration pending |
| D9 | Startup OCR-idle test in source and package | Pending |
| D10 | Startup import trace and lazy OpenCV test | Pending |
| D11 | Base64 worker transport test | Pending |
| D12 | Normal exit and `os._exit` worker ownership tests | Pending |
| D13 | Bundle manifest and clean install or upgrade tests | Pending |
| D14 | Source-hash rebuild and READY/exit smoke test | Pending |
| B1 | `bench_v2.6.json` and `bench_v2.7.2_wip.json` contain five startup trials each | Baselines recorded, candidate pending |
| B2 | Both source baseline records contain five 30-second private memory samples | Baselines recorded, candidate pending |
| B3 | Both source baseline records contain five digital catalog trials with 571 rows each | Baselines recorded, candidate pending |
| B4 | Comparable cold and warm explicit Review OCR in source and package | Pending |
| B5 | Native worker READY timing | Pending |
| B6 | Native 180 DPI strip p50 and p95 | Pending |
| B7 | Matched uncached native and PowerShell strip timings | Pending |
| B8 | Maximum actual Tk stall | Pending |
| B9 | Installer size | Pending |
| B10 | Distribution size | Pending |
| B11 | Time spent on unavailable worker per session | Pending |
| B12 | Orphan count after exit | Pending |
| B13 | Automatic OCR invocation counts and scanned deferral | Pending |
| B14 | Parse counts during optimization, error and replacement cases | Pending |
| B15 | Packaged before/after timings, final Excel save and verified extraction | Pending |
