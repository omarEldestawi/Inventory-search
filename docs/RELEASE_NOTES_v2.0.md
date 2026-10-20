# 🏥 Egyptian Pharma Procurement Optimizer v2.0

### 🌟 What's New in Version 2.0 / الجديد في الإصدار 2.0

- 🛡️ **Automated Price & Discount Sanity Check (`فحص ذكي لتبديل السعر والخصم`)**:
  - Implemented multi-signal column-level (`_should_swap_price_and_discount`) and per-item row-level (`_sanity_check_item_price_and_discount`) sanity checks in `src/pdf_parser.py`.
  - Automatically detects and corrects PDF catalogs where **Price (`السعر`)** and **Discount (`الخصم`)** columns are switched (such as `شركة مخزن الدولية الحديثة للادوية`) using header coordinate/text order, pharmaceutical discount bounds (`> 85%`), inline public price mentions (`سعر 144`, `41.5ج`, `س 81 س ج`), and numeric distribution heuristics.
- 📄 **Enhanced 2-Column ArwaSoft & Arabic Decimal Extraction**:
  - Full RTL word reconstruction and sub-word glyph stitching on right-column ArwaSoft layouts (`_extract_arwasoft_right_column`), expanded vertical bounds (`88 < Y < 795`) to capture top-of-page items, table-level Arabic reversal voting (`is_table_reversed`), and Arabic decimal separator (`٫`) preservation.
  - Improved headerless continuation page handling in `_process_table()` and `_find_column_indices()`.
- 💊 **Expanded Medication Knowledge Base (`data/medications.db`)**:
  - Added `شركة مخزن الدولية الحديثة للادوية` catalog (529 items) and expanded `medications.db` to **6,260 standard medications** and **108,094 aliases**, with automatic synchronization to `%LOCALAPPDATA%\EgyptianPharmaOptimizer\data\medications.db` on upgrade.
- 📜 **Developer Onboarding & Project History (`PROJECT_HISTORY.md`)**:
  - Added comprehensive architectural and historical documentation covering the evolution from `v1.0.0` to `v2.0`.

---

### 📥 Download & Installation / التحميل والتثبيت

1. Download **`EgyptianPharmaOptimizer_Setup_v2.0.exe`** from the Assets below.
2. Run the installer (no administrator privileges required). If you have an earlier version installed, it will automatically upgrade it in place.
3. Launch **Egyptian Pharma Optimizer v2.0** from your Desktop or Start Menu.
