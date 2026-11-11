# v2.7.2 release evidence

| Requirement | Evidence | Status |
| --- | --- | --- |
| Phase 0 snapshot | `491e793` on `release/v2.7.2`, protected-file diff empty against `v2.7.1` | Recorded |
| Phase 0 dependencies | `d62bfd0`, `pytest` and `psutil` installed under Python 3.12.10 | Recorded |
| Original batch | Four PDFs from the slow-import diagnosis and user-confirmed `نواقص11-11.xlsx`, with hashes in `scratch/v272-baseline/inputs.json` | Inputs identified |
| Section 0.1 | `scratch/v272-baseline/source_evidence.json` records financial column coordinates and 14 visually checked first-page rows. Both final packaged runs invoked zero OCR during import and passed the financial and name checks. | Verified |
| Section 0.2 | WIP parsed each PDF twice. Both final packaged runs parsed each PDF once and saved Excel. Tests cover stale success, stale failure, and repeated Run. | Verified |
| D1 | Serialized requests and separately owned lifecycle locks. `test_v272_native_worker.py` exercises shutdown during a request. | Focused tests passed |
| D2 | Absolute request deadline and bounded write, silent-response and partial-line tests | Focused tests passed |
| D3 | READY deadline opens the session breaker | Focused test passed |
| D4 | Native stdout and stderr drains tested with a flooded stderr pipe | Focused test passed |
| D5 | Startup breaker tested. Consecutive transport failures are counted. | Implemented |
| D6 | The preview worker rasterizes and resizes the full page and row crop off Tk. Tests cover stale results, crop placement at all rotations, and rotated region corrections. | Source tests passed, heartbeat budget still exceeded |
| D7 | Real source Review clicks returned text suggestions from both native and disabled-native fallback | Source smoke passed |
| D8 | `test_v272_box_ocr_parser.py` covers verified roles, ambiguity, decimal and RTL cases. Review presents suggestions separately. | Focused tests passed |
| D9 | Startup warm-up removed. Clean app import leaves OCR modules unloaded. | Focused test passed |
| D10 | Lazy OpenCV and OCR imports verified in a fresh interpreter | Focused test passed |
| D11 | Native worker accepts in-memory PNG payload with matching request ID | Source smoke passed |
| D12 | Windows job object kills the fake worker on abrupt parent exit | Focused test passed, final packaged check pending |
| D13 | Audited bundle is 405.6 MiB and installer is 125.69 MiB. Duplicate resource and user database preservation tests passed. | Disposable-profile lifecycle acceptance pending |
| D14 | Source and compiler hashes, worker hash, READY, request ID and exit status checked by the build | Build smoke passed |
| B1 | Five source trials per version. Subsequent median 4.39 s in both v2.6 and the candidate. | Pass |
| B2 | Five 30-second private memory samples per version. Subsequent median 590.65 MiB versus 586.81 MiB on v2.6. | Pass |
| B3 | Five candidate runs returned 571 rows each. Subsequent median 9.37 s versus a 26.05 s limit after removing repeated diagnostic copies during CLI output. | Pass |
| B4 | Candidate Review action measured in source. WIP Review action fails before producing suggestions, leaving no comparable baseline. | Fail |
| B5 | Native READY in 0.148 s. | Pass |
| B6 | Four valid 180 DPI native strip reads. Median 167 ms and p95 348 ms. | Pass |
| B7 | One invalid PowerShell result and the valid sample medians were 177 ms PowerShell and 167 ms native. | Fail |
| B8 | The latest visible source trial included issue selection, page navigation, dragging, and real OCR. The maximum gap was 443 ms early and 102 ms on repeat. | Fail |
| B9 | Rebuilt row-preview installer 125.70 MiB. | Pass |
| B10 | Audited portable bundle 405.6 MiB. | Pass |
| B11 | Exactly one failed start. First call returned in 4.951 s including cleanup, next returned in 0.013 ms. | Pass |
| B12 | Job-object tests exercised normal shutdown and abrupt `os._exit`. | Pass |
| B13 | Zero automatic OCR calls in both frozen batch runs. Source tests exercised scanned deferral, refresh, correction reload, procurement fallback, and Review opening. | Pass |
| B14 | One parse per PDF in both frozen runs. Source tests covered repeated Run, stale callbacks, and error recovery. | Pass in comparison; manual frozen replacement case pending |
| B15 | Both frozen runs saved Excel and passed the source-evidence audit. Import and end-to-end processing improved in both comparisons. | Pass for the audited executable |
