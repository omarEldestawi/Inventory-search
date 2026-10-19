# سجل التغييرات والإصدارات (Changelog)
All notable changes to the **Egyptian Pharma Procurement Optimizer** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.9] - 2026-10-19

### 🚀 Added & Improved
- **Per-Warehouse Above-Average Discounts Secondary Table**:
  - Integrated per-supplier discount opportunity tables directly into each warehouse purchase order sheet (`طلب شراء - [اسم المخزن]`) below the primary PO items list.
  - Strictly filters for available products where `Unit Saving = Base Price * (Warehouse Discount - Reference Weighted Average Discount) >= 4.00 EGP` per pack. Items saving < 4.00 EGP are strictly excluded.
  - Secondary table columns: `[م, اسم الصنف في أرصدة المخازن, اسم الصنف في الكتالوج, سعر الجمهور للوحدة, الخصم المرجح %, خصم هذا المخزن %, أعلى خصم متاح %, المخزن صاحب أعلى خصم, فرق السعر (الوفر بالجنيه)]`.
  - Added clean notice row handling when a warehouse has 0 items meeting the >= 4.00 EGP threshold without errors.
- **Visual Price Status Highlighting**:
  - Styled Column 8 (`المخزن صاحب أعلى خصم`) in Soft Green (`#E2EFDA` / text `#375623`) if the warehouse offers the highest catalog discount across all warehouses.
  - Styled Column 8 in Soft Yellow (`#FFF2CC` / text `#7F6000`) if another warehouse offers a higher discount, clearly displaying the competing warehouse name and its higher discount.
- **Removed Standalone Discounts Sheet**:
  - Removed the dedicated worksheet `أصناف بخصم أعلى من المرجح` from generated workbooks in favor of per-warehouse integrated tables.
- **Version Bump to Release 1.9**:
  - Updated all version strings and identifiers across GUI (`app_gui.py`), installer (`installer.iss`), updater, and application metadata from 1.8 to 1.9.

---

## [1.8] - 2026-10-19

### 🚀 Added
- **Reference Weighted Average Discount (`خصم مرجح` / `أرصده المخازن`)**:
  - Bundled `data/average_discounts.xlsx` and `data/average_discounts.csv` (4,751 reference medication entries) and implemented `src/average_discounts.py` with `xx...xx` marker stripping, English drug name preservation, and decimal normalization.
  - Added auto-classification for `أرصده المخازن` / `خصم مرجح` files in `src/controller.py`, `--avg-discounts-file` CLI flag in `main.py`, and `AvgDiscounts` selector support in `app_gui.py`.
- **Above-Average Discount RTL Worksheet (`أصناف بخصم أعلى من المرجح`)**:
  - Implemented `evaluate_above_average_discounts()` in `src/allocator.py` to match all reference items against warehouse catalogs with full clinical safety gates (`is_safe_pharmaceutical_match`), filtering for `أعلى خصم متاح % > الخصم المرجح %` and sorting descending by `فرق الخصم %`.
  - Updated `src/report_generator.py` to generate the RTL sheet `أصناف بخصم أعلى من المرجح` and append `الخصم المرجح %` and `فرق الخصم %` to `المقارنة الشاملة وتوزيع الأصناف`.
- **Background WiFi Auto-Updater**:
  - Added `src/updater.py` with silent background querying of GitHub Releases and non-blocking download to `%TEMP%`.
  - Added dynamic "🚀 إعادة التشغيل والتحديث / Restart & Update" toolbar pill button and manual fallback in the Update Wizard modal.
- **Compiled Release Installer**: Generated `dist_installer/EgyptianPharmaOptimizer_Setup_v1.8.exe` via PyInstaller and Inno Setup 6.

---

## [1.1.5] - 2026-09-24

### 🛡️ Fixed & Improved
- **Order Parsing & Multi-Table Stacked Sheet Ingestion (`load_purchase_order`)**:
  - Eliminated single-character `'م'` from `code_keywords` which previously caused any Arabic column with the letter Meem (`إسم`, `المخزن`, `تم`, etc.) to be misidentified as a numeric code, resulting in order files (like `0924.xlsx` and `0912.xlsx`) reading dates as drug items.
  - Added exact code match boundaries and negative keyword filters (`عميل`, `زبون`, `مورد`, `مندوب`, `مخزن`, `تاريخ`, `customer`, `vendor`, `date`) ensuring customer names and warehouse columns in stacked daily sheets are never selected as requested items.
  - Added support for `أسم الصنف` / `أسم` variants and proper aggregation of quantities across stacked out-of-stock and sold-out tables (accurately extracting 551 distinct items from `0924.xlsx`).
- **Wholesaler Custom ERP Font Decoding & Multi-Ligature Map**:
  - Implemented complete custom font glyph mapping (`AL_HADABA_FONT_MAP`) and ERP font ligatures (`CUSTOM_CATALOG_LIGATURE_MAP`) for catalogs like `الهضبه الخميس نفدى.pdf`.
  - Accurately converts ERP Aboriginal/Runic symbols back into clean Arabic (`ﻟᣌᢔᡧ` -> `لبن`, `ᣃᡫ اب` -> `شراب`, `ᣌᢕᡧ` / `ᡧᢕᣌ` -> `ين`, `ᣌن` -> `ين`).
- **Smart Arabic Bi-Directional Reversal Detection**:
  - Enhanced `is_arabic_text_reversed()` with expanded pharmaceutical token vocabularies (`REVERSED_PHARMA_TOKENS`, `FORWARD_PHARMA_TOKENS`), Persian character unification (`ی`/`ک` -> `ي`/`ك`), structural letter checks (`ة`, `ى`, `لا`), and unit-number position heuristics (`مجم 90`, `ق 30`).
  - Guarantees natural forward text (e.g. `ابيدرم كريم`, `فاروفيجا 12 قرص`) is preserved without inversion, while backward-encoded items (e.g. `لوسغ ورت دلوج` -> `جولد ترو غسول`, `مج 25 میرك ىسوبیم` -> `ميبوسى كريم 25 جم`, `36 صرق 12 مجم 100 ارجادنا` -> `انداجرا 100 مجم 12 قرص 36`) are restored to natural Arabic reading order.
  - Multi-line table cell unzipping now inherits cell-level reversal context (`is_cell_reversed`) so sub-items lacking pharma tokens are correctly unreversed.
- **Bi-Directional Arabic/English Brand Matching**:
  - Enhanced `extract_canonical_brand` in `src/normalizer.py` to match both Arabic and English brand names bidirectionally (e.g. `اوجمنتين 1 جم` <-> `Augmentin 1 gm 14 Tab`).
- **OpenPyXL XML IllegalCharacterError Resolution**:
  - Eliminated corrupted ASCII control characters (`\x00-\x08`, `\x0b-\x0c`, `\x0e-\x1f`) across order parsing, catalog reading, and Excel report generation.
- **OCR Button Re-Read Reliability**:
  - `reread_catalog_with_ocr` directly runs RapidOCR on every page and updates the cache reliably.

---

## [1.1.4] - 2026-09-12

### 🚀 Added
- **Multi-Line Table Cell Unzipping (`_process_table`)**:
  - Implemented safe aligned multi-item unzipping for borderless PDF tables where PyMuPDF merges consecutive rows into a single table cell separated by `\n` (resolving item loss in catalogs like `الفرسان اسكندريه`).
  - Added line-wrap detection to prevent multi-line drug names from splitting into fake items or causing off-by-one price misattribution.
- **Explicit 0% Net Pricing Support ('صافي' / Net Items)**:
  - Enabled extraction of essential medicines sold at 0% discount / public price (`0`, `0.0`, `0%`, `صافي`, `net`).
  - Strict verification ensures empty, unparseable, or missing discount cells are never falsely admitted as 0%.
- **Shifted Column Inline Discount Recovery**:
  - Automatically recovers discounts that shifted into the product name column during PDF extraction (e.g. `سيدرال فورت ق \n 27`).
- **Packaging Deduplication by Base Price**:
  - Refined `drop_duplicates` to preserve different presentations (pack sizes/concentrations) that have distinct official public prices (`base_price`).
- **Dedicated Verification Suite**: Added `tests/test_v114_fixes.py` validating multi-line unzipping, wrap detection, 0% net pricing, shifted column recovery, and base price deduplication.

---

## [1.1.3] - 2026-09-11

### 🚀 Added
- **Tier 0 Fast Path Vector Extraction**: Added automated digital vector detection in `src/pdf_parser.py` (`len(page.get_text("words")) >= 10`). Skips heavy rasterization and CPU OCR on digital PDF catalogs, parsing whole catalogs in `< 500ms`.
- **Smart Order Auto-Classification**: Broadened regex in `src/controller.py:classify_files` to automatically identify pharmacy purchase orders named with numeric codes (e.g. `9011.xlsx`), date stamps (`11-9.xlsx`), or Arabic terms (`طلب`, `طلبية`, `نواقص`, `شراء`, `order`).
- **Catalog Noise Suppression Filter**: Added `is_catalog_noise()` to strip wholesaler telephone numbers, contact footers, tax IDs, and disclaimer headers from being misidentified as medicines.
- **Dedicated Verification Suite**: Added `tests/test_v113_fixes.py` covering fast path extraction, order filename heuristics, cache protection, and version string consistency.
- **Compiled Release Installer**: Generated `dist_installer/EgyptianPharmaOptimizer_Setup_v1.1.3.exe` (118 MB) with automated shortcuts and uninstaller.

### 🛡️ Fixed
- **OCR Freezing & Event Loop Lockup**:
  - Replaced CustomTkinter full widget hierarchy recreation (`_render_file_list()`) on every OCR page progress callback with targeted, in-place badge label updates (`_poll_ocr_queue`).
  - Lowered rasterization DPI from 300 to 150 for true scanned pages, speeding up processing by 400% and reducing RAM usage by 75%.
- **Excel Production Button Inactivity**:
  - Fixed issue where pharmacy order files (e.g. `9011.xlsx`) were misclassified as catalogs or unknown, keeping the "بدء التحسين والتوزيع" button disabled.
  - Added missing `import traceback` to `app_gui.py` to prevent silent exception crashes from locking UI buttons in a disabled state.
- **Windows File Handle Locks (`[WinError 32]`)**:
  - Wrapped all `fitz.Document` operations in explicit `finally: doc.close()` blocks across `src/pdf_parser.py`.
- **Cache Degradation Bug**:
  - Added safeguard in `src/controller.py:reread_catalog_with_ocr` to prevent empty or partial OCR runs from overwriting previously parsed valid catalog data.
- **Output Re-ingestion Loop**:
  - `FileListModel.add_paths` in `app_gui.py` now filters out previously generated export reports (`Procurement_Order_...` / `أفضل_اسعار_...`), preventing circular catalog corruption.

---

## [1.1.2] - 2026-09-11

### 🛡️ Fixed
- **Installation Directory Write Permissions**: Prohibited direct output file writing inside protected paths (`Program Files`, `Program Files (x86)`, `_internal`, `sys._MEIPASS`, `/Applications`).
- **Safe Output Directory Fallback**: Added `validate_directory_writable` probe before pipeline runs with automatic fallback to user-space (`~/Desktop/Pharma_Output` or `~/Documents/Pharma_Output`).
- **Runtime Excel Save Protection**: Intercepted `PermissionError` and `ENOSPC` during Excel file saving in `src/report_generator.py`.
- **Frozen Environment Model Paths**: Dynamic discovery of RapidOCR and RapidTable ONNX model weights in PyInstaller unpacked bundles.

---

## [1.1.1] - 2026-09-10

### ⚡ Performance
- **Asynchronous Catalog Inspection**: Moved catalog item counting and header inspection to background worker threads, eliminating GUI freeze when dragging large files into the app.
- **Read-Only Excel Parsing**: Switched `openpyxl` inspection mode to `read_only=True` for large supplier price sheets.

---

## [1.1.0] - 2026-09-09

### 🚀 Added
- **Integrated RapidOCR & RapidTable**: Added local ONNX-based OCR engines for scanned PDF price sheets and faxed supplier lists.
- **Update Wizard Dialog**: Added `UpdateWizardDialog` in `app_gui.py` with version checking and release downloads.
- **Multi-Sheet Arabic Excel Reporting**: Enhanced `src/report_generator.py` with side-by-side wholesaler comparisons, winning supplier sheets, and out-of-stock tabs.

---

## [1.0.0] - 2026-09-02

### 🚀 Initial Release
- Two-pass deterministic procurement allocator maximizing discount rates per medicine item.
- Strict clinical safety gates for dosage forms, concentrations, and formulation modifiers.
- Support for top Egyptian pharmaceutical distributor catalogs (Al-Motahedon, Ibn Sina, Soficopharm, Al-Fares, etc.).
