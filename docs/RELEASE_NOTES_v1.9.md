# 🏥 Egyptian Pharma Procurement Optimizer v1.9

### 🌟 What's New in Version 1.9 / الجديد في هذا التحديث

- 📊 **Per-Warehouse Above-Average Discounts Secondary Table**: Integrates supplier-specific discount opportunity tables directly into each warehouse purchase order sheet (`طلب شراء - [اسم المخزن]`) below the primary purchase order items list.
- 💰 **Strict Unit Saving Threshold (>= 4.00 EGP per pack)**: Products are strictly evaluated and included if and only if `Unit Saving = Base Price * (Warehouse Discount - Reference Weighted Average Discount) >= 4.00 EGP`. Items saving < 4.00 EGP are strictly excluded.
- 🎨 **Visual Price Status Highlighting (Soft Green & Soft Yellow)**:
  - **Soft Green fill (#E2EFDA / text #375623)**: Highlights Column 8 (`المخزن صاحب أعلى خصم`) when this warehouse offers the highest catalog discount across all suppliers.
  - **Soft Yellow fill (#FFF2CC / text #7F6000)**: Highlights Column 8 when another warehouse offers a higher discount, clearly displaying the winning warehouse name and its higher rate (e.g. `مخزن السلام فارم (25.0%)`).
- 🧹 **Clean Consolidated Workbook**: Removed the standalone sheet `أصناف بخصم أعلى من المرجح` in favor of per-supplier actionable purchase order sheets. Primary purchase orders, master comparison, out-of-stock, and recommendations sheets retain 100% data integrity and accounting formulas.
- 🛡️ **Zero-Item Empty Resilience**: If a supplier has 0 items meeting the >= 4.00 EGP threshold, a clean Arabic notice message row is displayed without error.

---

### 📥 Download & Installation / التحميل والتثبيت

1. Download **`EgyptianPharmaOptimizer_Setup_v1.9.exe`** from the Assets below.
2. Run the installer. If you have an earlier version installed, it will automatically update it in place.
3. Launch **Egyptian Pharma Optimizer** from your desktop or start menu.
