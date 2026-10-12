# TEST_INFRA.md — End-to-End Test Architecture & Infrastructure

## 1. Overview & Objectives

The End-to-End (E2E) Test Suite for the **Egyptian Pharmacy Procurement Pipeline** (`tests/test_e2e_reconciliation.py`) provides requirement-driven, opaque-box verification across the entire procurement reconciliation engine.

The infrastructure verifies:
1. **Purchase Order Ingestion & Deduplication (R1)**: Accurate extraction and aggregation of purchase order items without collapsing pricing states or admitting noise tokens.
2. **Wholesaler Catalog Ingestion & Glyph Decoding (R2)**: Multi-column PDF parsing, table structure recognition under presentation forms, and aboriginal runic glyph translation.
3. **Clinical Safety Gates (R3)**: Zero cross-form substitutions, strict umbrella brand discrimination, and exact decimal strength matching preventing lethal dosing errors.
4. **Report Parity & Allocation (R4)**: 100% parity with the golden reference benchmark (`أفضل_اسعار_2026-09-28.xlsx`), generating 10 Right-to-Left (RTL) sheets with complete formula and KPI integrity, including Sheet 10 recommendations.

---

## 2. 4-Tier Test Architecture

The test suite is structured into four distinct, hierarchically rigorous tiers:

```
┌────────────────────────────────────────────────────────┐
│     Tier 4: Real-World Acceptance Workload             │
│     (279.xlsx + 7 Wholesaler PDFs Golden Benchmark)     │
├────────────────────────────────────────────────────────┤
│     Tier 3: Cross-Feature Combinations                 │
│     (Pairwise feature interactions & state transitions)│
├────────────────────────────────────────────────────────┤
│     Tier 2: Boundary & Corner Cases                    │
│     (Empty inputs, noise tokens, extreme values)       │
├────────────────────────────────────────────────────────┤
│     Tier 1: Comprehensive Feature Coverage             │
│     (≥5 tests per feature across all 9 core features)  │
└────────────────────────────────────────────────────────┘
```

### Tier 1: Feature Coverage (≥5 Tests Per Feature)
Verifies each feature independently under clean, synthetic, and isolated inputs:
1. **PO Ingestion & Deduplication**:
   - Preservation of 572 distinct items.
   - Deduplication strictly by `requested_item` (not `canonical_item`).
   - Exclusion of isolated noise token `'AE'` (qty 3).
   - Exclusion of internal repeated table headers (`'أسم الصنف'`, `'إسم الصنف'`, `'رقم الصنف'`).
   - Preservation of distinct pricing states (`س ج` vs `س ق`).
   - Non-overwriting of `requested_item` with `canonical_item`.
2. **Al-Hadhaba Dynamic 4-Column Detection**:
   - Detection of `[Code, Name, Price, Discount]`.
   - Resolution of Arabic Presentation Forms in table headers (`['ﻒﻨﺼﻟا ﻢﻗر', 'ﻒﻨﺼﻟا ﻢﺳإ', 'ﺮﻌﺴﻟا', 'ᣒﺎﺳا ﻢﺼﺧ']`).
   - Discrimination against conflicting 4-column schemas (e.g., Special Pharma `[Discount, Name, Code, Price]`).
   - Parsing bounding box boundaries without column index corruption.
   - Numeric extraction of public prices and discount percentages.
3. **Glyph & Ligature Translation**:
   - `ᛞ` (U+16DE) → `ب` (e.g., `ﻛᛞﺴﻮل` → `كبسول`).
   - `ᘭ` (U+162D) → `ي` (e.g., `ﺪᘭﺳﻮﺒﺳا` → `اسبوسيد`).
   - `ᣂᢕﺘᜧﻻ` / `ᡧᢕᣂﻻᜧﺘ` → `الاكتيز` (Lactase compound).
   - `ᢔ` (U+1894) → `ب` (e.g., `وᣂ ᢔﻴﺳ` → `سيبرو`).
   - Runic letter mappings (`ᗷ` → `ب`, `ᜧ` → `ك`, `ᣂ` → `ر`, `ᢕ` → `و`).
   - Execution ordering: `is_catalog_noise` executes strictly AFTER glyph translation.
4. **Wholesaler Name Normalization**:
   - `الرواد كفر الدوار مميز.pdf` → `الرواد` (not `شركة رواد الدواء`).
   - `مخزن الحياة فارم اسكندريه-220.pdf` → `مخزن الحياة فارم` (with `ة` not `ه`).
   - `السلطان جمله 22.pdf` → `مخزن السلطان`.
   - `المكرومي المنصورة.pdf` → `مخزن المكرومي`.
   - `الهضبة الزقازيق الاثنين نفدى.pdf` → `مخزن الهضبة فارم`.
   - `كيوررررر خاص.pdf` → `كيور فارما`.
   - `مصر فارم شبين كاااش-179.pdf` → `مصر لتجارة الأدوية`.
5. **Umbrella Brand Sub-type Matching**:
   - Prevention of cross-matching between distinct sub-brands (e.g., `ليمتلس اوستيودانس` vs `ليمتلس كروماكس`).
   - Sub-brand token isolation in multi-part brand names.
   - Matching identical sub-brands across phrasing variations.
   - Rejection of umbrella match when distinctive sub-type differs despite shared root `limitless`.
   - Discrimination among brand families: `panthenol` sub-brands (`هيبتا` vs `ماكرو`).
6. **Decimal Strength Precision**:
   - Parsing Egyptian shorthand `5.` as `0.5 mg`.
   - Blocking `دوستينكس 5. اقراص` from matching `دوستينكس 5 مجم قرص` (preventing 10-fold overdose).
   - Matching `دوستينكس 5. اقراص` to `دوستينكس 0.5 مجم قرص`.
   - Preservation of decimal points in `clean_arabic_string` (preventing dot stripping to space).
   - Pack count stripping protection for fractional numbers (e.g., `0.5 قرص`).
   - Boundary fractions: `0.25`, `1.5`, `2.5`, `12.5`.
7. **Cross-Form Slash Blocking**:
   - Prohibition of cross-form matches across slashes (e.g., `لوشن / اقراص` blocking lotion from tablet).
   - Ointment vs injectable ampoule blocking (`زادميسن 20 مجم مرهم/جاراميسين` vs `جاراميسين 40 مجم`).
   - Inclusion of `TOPICAL_OINTMENT`, `TOPICAL_CREAM`, `SOLID_ORAL` in strict non-unknown forms.
   - Symmetric slash parsing on candidate catalog lines.
   - Strict rejection of commercial substitutes (`بديل` / `substitute`) in primary allocation.
8. **10-Sheet RTL Excel Workbook Parity**:
   - Generation of exactly 10 sheets with standard Arabic titles.
   - `sheetView[0].rightToLeft = True` asserted across all 10 sheets.
   - Master summary sheet formula parity (`=SUM(...)` in row 163).
   - Wholesaler PO sheet summary formula parity (`=SUM(...)` in last row of sheets 2..8).
   - Header formatting, styling, and KPI card blocks in rows 4–5 of Sheet 1.
9. **Sheet 10 Recommendations ('توصيات وبدائل النواقص')**:
   - Dedicated recommendations tab located at Sheet 10.
   - Schema adherence: 9 columns with exact Arabic headers.
   - 351 fallback rows for shortages without commercial alternatives.
   - 139 expanded alternative rows for shortages with viable catalog options.
   - Zero leakage of commercial substitutes (`بديل`) into primary wholesaler sheets (Sheets 2–8).

### Tier 2: Boundary & Corner Cases
Tests system resilience under extreme and malformed inputs:
- Empty order file / DataFrame (clean error handling or empty result).
- Single-item order file (proper table structures, summary rows with 1 row).
- Extreme noise strings, unicode control characters, non-medication strings.
- Extreme discount values (0%, 99.9%, negative discounts, >100% rates).
- Stacked and malformed Canadian/Mongolian unicode sequences.
- Decimal strength boundary inputs (`0.0`, `.5`, `5.`, `0.25`, `5.00`, `12.5 mg`).

### Tier 3: Cross-Feature Combinations
Tests pairwise interactions across pipeline stages:
- Al-Hadhaba catalog item with aboriginal glyphs + decimal strength (`5.`) + order pricing state (`س ج`).
- Multi-supplier competitive allocation where Al-Hadhaba competes with Cure Pharma on items with glyphs.
- Slash-separated multi-brand request against catalog candidate with runic ligatures.
- Shortage item with pricing state (`س ق`) generating Sheet 10 recommendation from Al-Hadhaba inventory.
- Tie-breaking logic under equal discounts with supplier consolidation.

### Tier 4: Real-World Acceptance Workload
Opaque-box execution on benchmark order and catalog files (`279.xlsx` + 7 PDFs):
- Total requested items: **exactly 572** items (0 missing, no `'AE'` row).
- Total allocated items: **exactly 154** items.
- Total shortage items: **exactly 418** items.
- Al-Hadhaba allocated items: **exactly 49** items.
- Total savings achieved: **97,898.87 EGP** (32.3% of public value).
- Total public price value: **303,523.00 EGP**.
- Total net purchase cost: **205,624.13 EGP**.
- Total allocated units: **2,705** units.
- Workbook structure: **exactly 10 RTL sheets**.
- Sheet 10 recommendation rows: **exactly 490 rows** (351 fallback + 139 alternatives).
- Clinical safety: **0 cross-form substitutions** and **0 umbrella brand cross-matches**.

---

## 3. Test Execution Guidelines

### Running the Full Test Suite
```bash
python -m pytest tests/test_e2e_reconciliation.py -v
```

### Running Specific Tiers
```bash
# Tier 1: Feature Coverage
python -m pytest tests/test_e2e_reconciliation.py -k "TestTier1" -v

# Tier 2: Boundary & Corner Cases
python -m pytest tests/test_e2e_reconciliation.py -k "TestTier2" -v

# Tier 3: Cross-Feature Combinations
python -m pytest tests/test_e2e_reconciliation.py -k "TestTier3" -v

# Tier 4: Golden Real-World Acceptance
python -m pytest tests/test_e2e_reconciliation.py -k "TestTier4" -v
```

---

## 4. Authoritative Output Derivation

All expected values in the test suite are derived from:
1. `ORIGINAL_REQUEST.md` (authoritative customer specification).
2. `survey_spec.md` (empirical inspection of golden reference `أفضل_اسعار_2026-09-28.xlsx`).
3. `survey_clinical_build.md` (clinical safety gate and build survey).
4. Physical golden reference workbook `أفضل_اسعار_2026-09-28.xlsx`.
