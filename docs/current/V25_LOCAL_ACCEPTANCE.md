# Version 2.5 local acceptance — 2026-10-28

Workspace: `C:\Users\omart\Desktop\Inventory-search-PC`.

**Result:** local build and verification completed. All **11 empirical audit tests**
passed in **230.20 seconds**, extracting **12,417 offers across 23 catalogs**.
The portable build succeeded, Inno Setup compiled successfully in **200.641 seconds**,
and both packaged executable smoke checks returned exit code 0.

## Delivered behavior

Version 2.5 adds source-linked review issues, automatic recovery from digital PDF
coordinates, wrapped text and unambiguous column roles, a shared catalog correction
service, visual review and mapping previews, and atomic correction storage keyed by
canonical path and SHA-256. Correction revisions invalidate stale caches and partial
import acknowledgments. Empty catalogs block procurement.

Import a digital catalog and inspect the recovery summary. Use **Review and fix**
to see the source page and highlighted issue, edit fields, or preview a table mapping.
Save a validated correction or leave the issue unresolved. Continue with available
items after acknowledging a partial import, or cancel. Saved corrections reload for
the same source file and enter procurement through the same service. Reset restores
fresh extraction. A changed file does not inherit the previous file's corrections.

## Verification performed in this continuation

The selected regression run passed **417 tests and 35 subtests**. It covered
diagnostics/cache, table groups, service contracts, extraction/recovery, persistence,
GUI contracts, adversarial geometry and storage, recovery stress, and Targets 1–3.
The strengthened Target 3 suite separately passed **7 tests**. These runs overlap;
their totals must not be added together.

The first regression attempt hit PyMuPDF permission errors in the sandbox's default
temporary directory. The successful run used a workspace temporary directory:

```powershell
$env:TEMP = (Resolve-Path scratch/v25-release-tmp).Path
$env:TMP = $env:TEMP
python -m pytest tests/test_v23_diagnostics_cache.py tests/test_v23_pdf_table_groups.py tests/test_m1_contracts_service.py tests/test_adversarial_challenger_m1.py tests/test_adversarial_challenger_m1_iter2.py tests/test_m2a_extraction_recovery.py tests/test_m2b_persistence.py tests/test_m2c_gui_contracts.py tests/test_adversarial_challenger_m3_recovery.py tests/test_adversarial_challenger_m3_storage.py tests/test_challenger_m3_iter2_recovery_stress.py tests/test_v25_target1_recovery.py tests/test_v25_target2_corrections.py tests/test_v25_target3_procurement_e2e.py -q --durations=10 --junitxml=output/v25-release-regression-retry.xml
python -m pytest tests/test_v25_target3_procurement_e2e.py -q --junitxml=output/v25-procurement-e2e.xml
python -m pytest tests/test_adversarial_catalog_deep.py -v -s --durations=12 --junitxml=output/v25-catalog-audit.xml
```

Saved logs: `output/v25-release-regression-retry.log`,
`output/v25-procurement-e2e.log`, and `output/v25-catalog-audit.log`.
JUnit XML files accompany each successful run.
Machine-readable extraction counts are in `output/v25-catalog-counts.json`.

The audit's two name-hygiene loops now iterate directly over the same name columns.
This avoids repeated pandas diagnostic-metadata copying without weakening assertions.

## Representative extraction counts

| Catalog | Baseline or incoming handoff | Fresh v2.5 verification |
|---|---:|---:|
| Hayah Shibin | 571 | 571 |
| Dawlia | 529 | 529 |
| Zahra | 1,167 | 1,167 |
| Stroka | 1,164 | 1,164 |
| Al-Qemma | 416 | 416 |
| Wael Samir | 380 | 380 |

The first three counts are preserved baseline fixtures checked by Target 1; the
last three are incoming handoff counts reproduced by the fresh 23-catalog audit.
These are comparisons with the supplied baseline/handoff, not a new execution of
an older source revision. Historical pre-v2.3 Hayah extraction was 195; the existing
troubleshooting report documents its improvement to 571 before this continuation.
The 23-catalog train audit is a separate corpus from the three baseline fixtures.

## Recovery and correction reaching procurement

`test_pdf_coordinate_recovery_and_reloaded_correction_reach_procurement` creates a
real vector PDF containing Concor's name, price and discount. Its controlled initial
extraction result omits the Concor offer and records a missing-price issue. The real
coordinate recovery engine resolves it from the PDF text stream, marks provenance
`automatic_recovery`, and grows the accepted catalog from **1 to 2** items.

The test saves Cataflam's discount correction from **10% to 28%**, creates a fresh
service instance to verify disk reload, and runs the real procurement pipeline. Both
ordered items match, a report workbook is generated, and the comparison output
contains Concor at **22%** and Cataflam at **28%**. Only the initial extraction
boundary is controlled; recovery, correction persistence, service reload, allocation
and workbook generation execute normally. This does not claim an independently
observed natural extraction failure for that synthetic PDF.

The earlier Excel test was renamed to describe valid original rows accurately; it
never actually recovered its Concor row.

## Local builds and binary checks

Commands executed:

```powershell
python build_exe.py
& "C:\Users\omart\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
.\dist\EgyptianPharmaOptimizer\EgyptianPharmaOptimizer.exe --self-test
.\dist\EgyptianPharmaOptimizer\EgyptianPharmaOptimizer.exe --test-catalog tests/fixtures/hayah_shibin.pdf
```

Both executable checks returned **exit code 0**. The self-test initialized and
validated the GUI, parsed the real Hayah fixture, and rendered its catalog card.
The catalog command's JSON was independently checked: **571 items**, `complete`,
571 candidate and accepted rows, zero rejected and unprocessed rows, and 571
serialized offers. Full captured output is in `output/v25-binary-smoke.json`.

The sandbox emitted a CustomTkinter font-loading warning and used its circle-shape
fallback. GUI initialization passed; this is not an exhaustive visual review of
every interactive correction dialog or a clean-machine installation test.

Portable application entry point:
`C:\Users\omart\Desktop\Inventory-search-PC\dist\EgyptianPharmaOptimizer\EgyptianPharmaOptimizer.exe`.
Keep the entire containing folder, including `_internal`, together.

Installer:
`C:\Users\omart\Desktop\Inventory-search-PC\dist_installer\EgyptianPharmaOptimizer_Setup_v2.5.exe`.

Build logs: `output/v25-build.log` and `output/v25-installer-build.log`.
SHA-256 comparisons confirmed that the bundled copies of `pdf_parser.py`,
`catalog_reader.py`, `catalog_recovery.py`, `normalizer.py`, `catalog_service.py`
and `catalog_corrections.py` exactly match the workspace source used for this build.
Artifact hashes and sizes are recorded in `output/v25-artifacts.json`:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Portable EXE | 20,270,584 | `c668b7cad0692592935354129bd3486c4cef03c614671b843390da175dd2c0cd` |
| v2.5 installer | 130,845,315 | `df4643bba481287a43085e6edad794b9891a0a61c49bd6646d8a2c6c2c866caa` |

The README installer filename was corrected to v2.5. No release was published,
pushed, or tagged, and the installer was not installed over the user's application.
