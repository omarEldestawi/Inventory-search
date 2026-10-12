# Original User Request

## Initial Request — 2026-09-27T04:27:39+03:00

You are teamwork_preview_swe, the orchestrator for SWE Light.
Your working directory is: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\swe_light_2
Project workspace: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search
Authoritative user request: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md

Task:
Enforce zero-risk clinical pharmaceutical allocation across Egyptian pharmacy wholesaler catalogs, expand aboriginal runic glyph decoding in PDF parsing, add a separate procurement recommendations tab in the output workbook, and verify against test suites and legacy diffs.

## Requirements

### R1. Strict Clinical Safety & Zero Cross-Form Substitutions
- Commercial substitutes marked with `بديل` or `substitute` (e.g., `بديل ميبو`, `بديل كولشيسين`) must be strictly rejected from primary procurement allocation.
- Enforce zero cross-form substitutions (`SOLID_ORAL` vs `ORAL_LIQUID`, `INJECTABLE` vs `SUPPOSITORY`, `SACHET` vs oral tablets, `TOPICAL_GEL` vs `TOPICAL_SOLUTION`).
- Ensure exact strength, ratio, and pediatric/infant milk stages match without dangerous substitutions.

### R2. Aboriginal Runic Glyph Translation & De-spacing (`src/pdf_parser.py` & `src/normalizer.py`)
- Expand the glyph translation map in `PDFCatalogParser` for Al-Hadhaba PDF format to translate:
  - `ᗷ` → `ب`
  - `ᜧ` → `ك`
  - `ᣂ` → `ر`
  - `ᢕ` → `و`
  - `ᛞ` → `س`
  - `ᘌ` → `ي`
  - `ᘭ` → `ل`
- Normalize OCR-split multi-word Arabic medication names (e.g., `سباز موبير الجين` / `سبازموبي رالجي ني` → `سبازموبيرالجين`).

### R3. Dedicated Recommendations Sheet in Excel Output (`src/report_generator.py`)
- Add a dedicated "توصيات وبدائل النواقص" (Recommendations & Alternatives) tab at the end of the final Excel workbook.
- In this tab, list available commercial alternatives for out-of-stock items as optional suggestions for pharmacist review, keeping the primary wholesaler order sheets strictly unadulterated.

### R4. Audit Diff Comparison Report
- Generate an audit diff report comparing the resulting procurement workbook against `Procurement_Order_Optimized_2026-09-24 (1).xlsx` (in Downloads), documenting confirmed matches, blocked false positives, and recovered legitimate items.

## Verification Resources & Acceptance Criteria

### Verification Resources
- Adversarial test suite: `python -m unittest tests/test_adversarial_m3_challenger.py`
- Adversarial M3 suite: `python -m unittest tests/test_m3_adversarial.py`
- Full benchmark suite: `python -m unittest tests/test_full_train_benchmark.py`
- Benchmark order file: `input/orders/0924.xlsx`
- Legacy benchmark file: `Procurement_Order_Optimized_2026-09-24 (1).xlsx`

### Acceptance Criteria
- [ ] All three test suites (`test_adversarial_m3_challenger.py`, `test_m3_adversarial.py`, `test_full_train_benchmark.py`) pass with 0 failures and 0 errors.
- [ ] 0 commercial substitutes (`بديل`) matched in the primary procurement allocation orders.
- [ ] 0 cross-form substitutions in the allocated order.
- [ ] Al-Hadhaba runic ligatures (`ᗷ`, `ᜧ`, `ᣂ`, `ᢕ`, `ᛞ`, `ᘌ`, `ᘭ`) are correctly translated to standard Arabic letters during PDF catalog ingestion.
- [ ] The generated Excel workbook includes the new "توصيات وبدائل النواقص" sheet with clean formatting and pharmacist guidance.
- [ ] Audit diff report generated and verified against `Procurement_Order_Optimized_2026-09-24 (1).xlsx`.

Domain skill: `egyptian-pharma-procurement` located at `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md`.

Execute the SWE Light workflow: run an implementer on the task, followed by reviewer rounds, establishing correctness with tests. When finished, send a completion report back to parent.

## 2026-09-28T02:05:17+03:00

Execute complete reconciliation and permanent architectural fixes for Egyptian Pharmacy Procurement pipeline to match the golden reference benchmark (`أفضل_اسعار_2026-09-28.xlsx`) against daily inputs (`279.xlsx` and 7 wholesaler PDFs in `C:\Users\omart\Downloads`).

Working directory: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search
Integrity mode: development

## Requirements

### R1. Purchase Order Ingestion & Deduplication
- Preserve all 572 distinct order items from `279.xlsx` by grouping strictly on original `requested_item` text (preventing collapse of distinct pricing states such as 'س ج' vs 'س ق').
- Exclude noise headers and junk tokens such as isolated non-medication string 'AE' (quantity 3).
- Do not overwrite `requested_item` with `canonical_item`.

### R2. Wholesaler Catalog Ingestion & Glyph Decoding
- Parse Al-Hadhaba catalog PDF with dynamic 4-column detection `[Code, Name, Price, Discount]`, decoding custom aboriginal glyphs and ligatures (`ᛞ` -> 'ب', `ᘭ` -> 'ي', `ᣂᢕﺘᜧﻻ` -> 'الاكتيز').
- Ensure `is_catalog_noise` executes after glyph decoding and does not reject valid glyph presentation ranges.
- Normalize wholesaler names to standard clean names ('الرواد', 'مخزن الحياة فارم', 'مخزن السلطان', 'مخزن المكرومي', 'مخزن الهضبة فارم', 'كيور فارما', 'مصر لتجارة الأدوية').

### R3. Pharmaceutical Clinical Safety Gates
- Enforce strict brand sub-type matching on umbrella brands (e.g., prevent cross-matching Limitless Osteodance to Limitless Chromax).
- Correct decimal strength extraction (e.g., `5.` parsed as `0.5 mg`, preventing Dostinex 0.5mg from matching Dostinex 5mg).
- Block cross-form substitutions across slash separators (e.g., lotion cannot match tablets).

### R4. Report Parity & Standalone Executable Rebuild
- Generate 10-sheet RTL Excel workbook with 100% column header and formula parity matching `أفضل_اسعار_2026-09-28.xlsx`, including Sheet 10 ('توصيات وبدائل النواقص') with 490 recommendations.
- Recompile frozen executable using `python build_exe.py` so the standalone application in `dist/EgyptianPharmaOptimizer` incorporates all fixes.

## Acceptance Criteria

### KPI Parity on 2026-09-28 Daily Inputs
- [ ] Total requested items: exactly 572 items (0 missing, no 'AE' row).
- [ ] Total allocated items: exactly 154 items.
- [ ] Shortages (out of stock): exactly 418 items.
- [ ] Total savings achieved: 97,898.87 EGP (32.3% of public value).
- [ ] Al-Hadhaba allocated items: exactly 49 items.
- [ ] Workbook structure: exactly 10 RTL sheets generated, including 'توصيات وبدائل النواقص' with 490 rows.
- [ ] 0 false positive cross-form matches and 0 umbrella brand cross-matches.
- [ ] Executable `dist/EgyptianPharmaOptimizer/EgyptianPharmaOptimizer.exe` cleanly rebuilt and runs without errors.


## 2026-10-11T00:47:30Z

This is a focused execution and parser adaptation task: Ingest all 23 wholesaler PDF catalogs and 2 order sheets in C:\Users\omart\Desktop\train, learn and verify correct data extraction across every PDF catalog (resolving layout, font, number, and Arabic text direction quirks), extract all medication names and their variations/reversed forms into data/medications.db, and run order reconciliation and multi-vendor discount allocation.

Working directory: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search
Integrity mode: development

## Requirements

### R1. Full Training Dataset Ingestion & Adaptive Extraction Learning
Inspect and parse every one of the 23 PDF catalogs in C:\Users\omart\Desktop\train:
- Learn and adapt to each catalog's layout (2-column accounting formats, whitespace layouts, table grids).
- Accurately decouple glued digits, dosage units, and discounts (e.g. 20% or سعر جديد).
- Accurately decode font encodings (Arwasoft, Al-Hadaba, Greek/custom glyphs) and reverse visual LTR Arabic text streams to correct logical RTL Arabic.
- Ensure 100% of the 23 catalogs yield clean, non-empty, well-structured inventory tables.

### R2. Canonical Medication & Alias Knowledge Base Expansion
Extract all unique medication names and variants from the parsed catalogs and purchase orders. Ingest them into data/medications.db, establishing canonical standard medications while registering all raw, reversed, and OCR alias variations so future lookups are instantaneous (< 1 ms).

### R3. Deterministic Procurement Allocation & Optimization
Reconcile and optimize daily purchase orders 0911.xlsx and 0912.xlsx from C:\Users\omart\Desktop\train against the consolidated vendor inventory. Enforce strict pharmaceutical safety gates (zero cross-drug substitutions, matching forms and strengths) and maximize discount rates across available wholesaler offers.

### R4. Benchmark Diagnostics & Reporting
Generate multi-sheet RTL Excel procurement workbooks for each purchase order and output benchmark diagnostics:
- Per-catalog extraction metrics (items extracted, columns recognized, encoding health) across all 23 wholesaler catalogs
- Total unique standard medications and total registered aliases in medications.db
- Match rate and savings breakdown for 0911.xlsx and 0912.xlsx

## Verification Resources & Acceptance Criteria

### Verification Commands
```powershell
# 1. Verify all 23 catalogs are successfully parsed and extraction rates
python scripts/survey_inventory.py

# 2. Verify database integrity and total aliases
python -c "from src.medication_db import MedicationDB; db = MedicationDB(); print(db.stats())"

# 3. Run unit and end-to-end allocation test suite
python -m pytest tests/test_medication_db.py tests/test_e2e_medication_db_allocation.py -v
```

### Acceptance Criteria
- [ ] All 23 PDF catalogs in C:\Users\omart\Desktop\train parse accurately with zero crashes, extracting items, prices, and discounts.
- [ ] Specific extraction issues (Arwasoft glyphs, 2-column tables, reversed text, glued numbers) are resolved and verified.
- [ ] data/medications.db is populated with canonical standard medications and all discovered aliases.
- [ ] Order allocation for 0911.xlsx and 0912.xlsx succeeds with 0 dangerous drug substitutions.
- [ ] Benchmark KPIs and RTL Excel allocation reports are generated.
- [ ] Automated test suite (test_medication_db.py, test_e2e_medication_db_allocation.py) passes 100%.
