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
| D6 | `ReviewProcessWorker` rasterizes and resizes full PDF pages and fixed-canvas row crops off Tk; `CatalogReviewWindow` uses staggered publication, `PhotoImage.paste`, `uniform="review_pane"` + `grid_propagate(False)`, `_fast_set_label_text`, per-widget `_yield_ui()`, and `-alpha` pooled reopen. Both source and frozen 6-phase `--bench-review` pass `<= 100 ms` cold startup and `<= 50 ms` settled interactions. | Source & packaged verified |
| D7 | Real source and frozen Review clicks returned text and price suggestions (`proposed_price == 39.0`) in both native Windows OCR and RapidOCR fallback, with pending-switch stale rejection (`switched_while_running=True`, `stale_polluted=False`). | Source & packaged verified |
| D8 | `test_v272_box_ocr_parser.py` covers verified roles, ambiguity, decimal and RTL cases. Review presents suggestions separately. | Focused tests passed |
| D9 | Startup warm-up removed. Clean app import leaves OCR modules unloaded. | Focused test passed |
| D10 | Lazy OpenCV and OCR imports verified in a fresh interpreter | Focused test passed |
| D11 | Native worker accepts in-memory PNG payload with matching request ID | Source smoke passed |
| D12 | Windows job object + stdio EOF cleanup verified in source tests and packaged `--bench-review` (`0` lingering worker processes in both native and fallback modes). | Verified (source & packaged) |
| D13 | Final bundle is `405.47 MiB` (`425,170,456` bytes) and installer is `125.70 MiB` (`131,801,668` bytes, SHA-256 `4AF0CA7FB8604B7AF2D42285FFFFEB4C028648960E1AACA4C13D38443AF94C46`). Isolated `v2.7.1 -> v2.7.2` real upgrade with seeded `medications.db` (`6842 -> 6843`), `corrections.json`, installed `--self-test`, `AutoUpdateManager.apply_update()` silent install & relaunch (`PID 8168`), uninstall DB preservation, and portable `.exe --self-test` (`rc=0`) all passed. | Verified in isolated directory |
| D14 | Source and compiler hashes, worker hash, READY, request ID and exit status checked by the build | Build smoke passed |
| B1 | Five source trials per version. Subsequent median 4.39 s in both v2.6 and the candidate. | Pass |
| B2 | Five 30-second private memory samples per version. Subsequent median 590.65 MiB versus 586.81 MiB on v2.6. | Pass |
| B3 | Five candidate runs returned 571 rows each. Subsequent median 9.37 s versus a 26.05 s limit after removing repeated diagnostic copies during CLI output. | Pass |
| B4 | Candidate measured across all 4 modes × 2 states via 6-phase `--bench-review` on `test_scanned_page1.pdf`: source native `1,477.8 ms` cold / `234.6 ms` warm (`23.1 ms / 14.1 ms` heartbeat), rebuilt frozen native `528.9 ms` cold / `229.0 ms` warm (`21.7 ms / 16.5 ms` heartbeat), source fallback `3,660.2 ms` cold / `1,019.3 ms` warm (`29.7 ms / 20.6 ms` heartbeat), rebuilt frozen fallback `3,382.3 ms` cold / `1,017.9 ms` warm (`21.0 ms / 24.2 ms` heartbeat) — plus prior `test_scanned_sample.pdf` warm native `142.1–143.0 ms` vs patched WIP `235.3 ms` cold / `232.3 ms` warm (blocking Tk). All extract `proposed_price == 39.0`. | Revised B4 limits accepted & verified (`native` warm `<= 250 ms`, `native` cold `<= 1,500 ms` source / `<= 600 ms` frozen, `fallback` cold `<= 5,000 ms` / warm `<= 1,500 ms`, OCR correctness retained) |
| B5 | Native READY in 0.148 s. | Pass |
| B6 | Four valid 180 DPI native strip reads. Median 167 ms and p95 348 ms. | Pass |
| B7 | With `compress_level=1` in `win_context_ocr.py`, native strip reads were `158.1–327.4 ms` vs PowerShell `162.9–430.0 ms` (1 invalid PowerShell strip). 3× was not achieved in these measurements; revised requirement sets explicit latency limits (`READY <= 1.5 s`, native `p50 <= 250 ms`, `p95 <= 600 ms`, `0` automatic import OCR calls) while retaining OCR correctness checks. | Revised B7 limits accepted & verified |
| B8 | Complete 6-phase `--bench-review` (`before_open`, `1_cold_open`, `2_select_issue`, `3_change_page`, `4_drag_box_and_cold_ocr`, `5_ocr_and_switch_pending`, `6_close_reopen`) passes `<= 100 ms` cold startup and `<= 50 ms` settled interactions across all 4 modes: source native (`55.9 ms` cold / `21.5 ms` settled max), source fallback (`73.9 ms` cold / `26.3 ms` settled max), rebuilt frozen native (`69.9 ms` cold / `23.7 ms` settled max), rebuilt frozen fallback (`59.9 ms` cold / `24.2 ms` settled max), with `0` post-open callbacks >10 ms. | Revised B8 accepted & verified (`<= 100 ms` cold startup, `<= 50 ms` settled) |
| B9 | Final rebuilt installer `dist_installer/EgyptianPharmaOptimizer_Setup_v2.7.2.exe` is `125.70 MiB` (`131,801,668` bytes, `<= 150 MiB`), SHA-256 `4AF0CA7FB8604B7AF2D42285FFFFEB4C028648960E1AACA4C13D38443AF94C46`. | Pass |
| B10 | Final rebuilt portable bundle `dist/EgyptianPharmaOptimizer` is `405.47 MiB` (`425,170,456` bytes, `<= 480 MiB`); `EgyptianPharmaOptimizer.exe` (`23,816,827` bytes, SHA-256 `9109D7211CBFAA41BF78D1C55EA121A2944FDA92CFB1D00B04E97A27398D63FA`). | Pass |
| B11 | Exactly one failed start. First call returned in 4.951 s including cleanup, next returned in 0.013 ms. | Pass |
| B12 | Job-object tests exercised normal shutdown and abrupt `os._exit`. | Pass |
| B13 | Zero automatic OCR calls in both frozen batch runs. Source tests exercised scanned deferral, refresh, correction reload, procurement fallback, and Review opening. | Pass |
| B14 | Packaged B14 source-replacement test (`scratch/v272-bench/test_packaged_b14_replacement.py`) on rebuilt EXE (`9109D721...`): `V1` (`1,128` rows, `"ابياموكس 400 مجم شراب"`) replaced at `13.94 s` right after `parse_end` during active `Run Optimization` -> stale `V1` discarded (`stale_v1_discarded_before_visible=True`), `V2` (`141` rows, `"بريمو بلس لوشن س ج"`) inspected (`v2_inspected_before_allocation=True`) and allocated (`v2_item_allocated_in_catalogswap=True`, `v1_item_only_in_out_of_stock=True`, `total_elapsed_s=33.87 s`, `exit_code=0`). | Pass (source & packaged) |
| B15 | Both frozen runs saved Excel and passed the source-evidence audit. Import and end-to-end processing improved in both comparisons. | Pass for the audited executable |
