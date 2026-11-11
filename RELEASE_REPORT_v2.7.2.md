# Egyptian Pharma Procurement Optimizer 2.7.2 release candidate

The candidate is under verification on `release/v2.7.2`. Release approval requires the full regression suite, the remaining benchmark evidence, and the disposable-profile installer lifecycle checks.

## Row preview follow-up

- Row crops rotate padded source bounds into display coordinates before clipping. The preview worker bounds crop rasterization to the thumbnail size and discards crops from a superseded issue selection.
- The focused run passed 72 tests, including crop placement at all four rotations, rapid issue selection, and both scanned fixture OCR tests. The previous full-suite attempt stopped at an older scanned test after 188 passes. That test now checks deferral and preserves the original 20-row minimum under explicit OCR.
- A visible source run exercised issue selection, page changes, dragging, and real Windows OCR. Both trials displayed a row crop and returned suggestions. The largest heartbeat gaps were 443 ms on the early trial and 102 ms on repeat. B8 remains open.
- The rebuilt 125.70 MiB installer is at `scratch/v272-baseline/row-preview-candidate/EgyptianPharmaOptimizer_Setup_v2.7.2.exe`. Its SHA-256 is `92C3F4D3BA556ADCCCB15939CD1CBAB7B5338EE99208C5682BA5076F731A95AF`. The rebuilt portable bundle passed `--self-test`, including the 571-row PDF fixture and correction persistence. Installer lifecycle checks in a disposable Windows profile remain open.
- The latest full-suite run stopped after 357 passes at `test_adv_09_multi_table_mixed_outcomes_reconciliation_invariant`. Its exact strategy-name assertion expects `structural_table_t0`, and the parser emits group-qualified names such as `structural_table_t0_g0`. The same test fails with the same output on `v2.7.1`.

## Review follow-up

- Full-page Review regions use unrotated source coordinates. Tests saved a row near the bottom of a 300×500 scanned page at both 90° and 270° rotation.
- PDF preview rendering and resizing run in a background thread. Tk installs only the latest preview and ignores drag input while its coordinate mapping is unavailable.
- The scanned sample test verifies text-only deferral with zero OCR calls, then runs explicit OCR and checks the original row-count, identity, price, and discount assertions.
- The follow-up source run passed 67 focused tests.
- The visible source test changed pages, dragged a box, and received Windows OCR suggestions. Maximum Tk heartbeat gaps were 402 ms on the early trial and 44 ms on the repeat. B8 remains open.

The historical package and benchmark measurements below apply to the build before these follow-ups.

## Source baselines

Each source record contains five launches. Startup, private memory at 30 seconds, and digital parsing below are medians of the four subsequent trials. Every trial returned 571 digital fixture rows.

| Measurement | v2.6 | v2.7.2 WIP | Candidate |
| --- | ---: | ---: | ---: |
| Visible window | 4.39 s | 4.91 s | 4.39 s |
| Private memory | 586.81 MiB | 640.45 MiB | 590.65 MiB |
| Digital fixture | 24.81 s | 43.45 s | 9.37 s |
| Scanned fixture CLI | 3.16 s | 6.43 s | 3.19 s |

The scanned fixture returned zero rows on v2.6 and 27 automatic OCR rows on the WIP. The candidate defers the page to Review, so scanned import times describe different behavior.

## Original four-PDF workflow

The package benchmarks used the four original PDFs and `نواقص11-11.xlsx`. They exercised Run Optimization while the catalogs were loading and ended at the successful Excel save. The candidate executable contains the correction to the pack digit on the Urgent catalog row. The first WIP run attempted Gemini calls on an offline connection. The subsequent WIP run and both candidate runs explicitly disabled Gemini.

| Measurement | WIP first | WIP subsequent | Candidate first | Candidate subsequent |
| --- | ---: | ---: | ---: | ---: |
| First result | 18.69 s | 18.30 s | 4.32 s | 4.20 s |
| Catalog inspection | 181.85 s | 178.30 s | 31.21 s | 29.73 s |
| Processing to Excel, excluding acknowledgment | 340.43 s | 336.42 s | 155.02 s | 153.31 s |
| Parse starts per PDF | 2 | 2 | 1 | 1 |
| OCR calls during import | 2,672 | See baseline record | 0 | 0 |

Both candidate runs passed the source manifest checks for 14 visually transcribed names and 3,822 digital financial pairs. The Urgent catalog row preserves its 550 price, 29% discount, and `1 + 1` pack. Two printed discounts of 86% remain in source-linked Review issues under the existing 85% validation limit. The batch records contain per-stage allocation, reference-discount, Excel save, and acknowledgment times.

## Verification status

- The comparison passed 12 of 15 gates. B4, B7, and B8 remain open. The executable has no release tag.
- The final focused run passed 56 tests. Focused tests cover text-only import, source geometry, corrections, worker timeouts and abrupt exit, OCR ambiguity, preflight sequencing, and resource and database checks. The WIP full regression run reached its 30-minute deadline with failures. The candidate fixed the digital schema regression and reran it successfully. A subsequent fail-fast run stopped on a test that relied on automatic OCR. The test now verifies text-only deferral and preserves its deduplication assertions under explicit OCR. The targeted rerun passed.
- Source and packaged `--self-test` passed with writable temporary directories and confirmed all 571 fixture rows, correction persistence, and procurement blocking. Packaged scanned CLI returned zero accepted rows.
- The settled visible Review window returned OCR suggestions through both native Windows OCR and RapidOCR. Heartbeat gaps stayed below 31 ms in those trials. An early click in the visible window produced a 511 ms gap. The WIP explicit action fails before producing suggestions, leaving B4 without a comparable working baseline.
- Native worker READY took 0.148 seconds. Four valid native strip reads had a 167 ms median and a 348 ms p95. The PowerShell comparison produced an invalid result on one strip and did not demonstrate the required 3× speed ratio.
- The audited portable bundle measured 405.6 MiB and its installer measured 125.69 MiB. The installer SHA-256 is `CBF281ECC010BCF9BB1EF9E58087274E15AECC71499C87CA41BA7182C9ED2E74`. Upgrade, auto-update, and uninstall acceptance remain pending in a disposable Windows profile.

See [the release evidence checklist](diagnostics/v272_release_checklist.md), [the WIP batch record](diagnostics/batch_wip.json), and [the candidate batch record](diagnostics/batch_v2.7.2.json) for gate status and recorded measurements.
