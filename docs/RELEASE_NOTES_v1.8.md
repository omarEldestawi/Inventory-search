# 🏥 Egyptian Pharma Procurement Optimizer v1.8

### 🌟 What's New in Version 1.8 / الجديد في هذا التحديث

- 📊 **Reference Weighted Average Discount (`خصم مرجح` / `أرصده المخازن`)**: Bundles the 4,751-medication reference average discount dataset (`data/average_discounts.xlsx`) as a built-in benchmark and supports uploading newer `أرصده المخازن` Excel/CSV files via the GUI, CLI (`--avg-discounts-file`), or input folder.
- 📑 **Above-Average Discount RTL Worksheet (`أصناف بخصم أعلى من المرجح`)**: Evaluates all 4,751 medications in `أرصده المخازن` against all ingested wholesaler catalogs using the clinical safety engine (`MedicationDB` + `is_safe_pharmaceutical_match`) and generates a dedicated RTL sheet sorted descending by largest discount gain (`فرق الخصم % = أعلى خصم متاح % - الخصم المرجح %`).
- 📈 **Master Comparison Discount Gain Columns**: Enriches `المقارنة الشاملة وتوزيع الأصناف` with `الخصم المرجح %` and `فرق الخصم %` columns while preserving `=SUM(...)` accounting formulas.
- 🔄 **Modern In-Place Update Flow**: Supports direct in-place upgrading over existing installations without modifying saved orders or history.

---

### 📥 Download & Installation / التحميل والتثبيت

1. Download **`EgyptianPharmaOptimizer_Setup_v1.8.exe`** from the Assets below.
2. Run the installer. If you have an earlier version installed, it will automatically update it in place.
3. Launch **Egyptian Pharma Optimizer** from your desktop or start menu.
