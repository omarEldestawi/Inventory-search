# Egyptian Pharma Procurement Optimizer v2.6 — User Guide
# دليل المستخدم لنظام المشتريات الصيدلانية v2.6

---

## 1. Overview / نظرة عامة
Version 2.6 introduces the **Arabic OCR Recovery Pipeline**, enabling pharmacy managers to automatically ingest supplier catalogs in all formats:
- Clean digital PDFs and Excel price lists (`.xlsx`, `.xls`, `.csv`).
- Corrupted digital PDFs with non-standard Arabic font encodings (e.g. Al-Abed, Tebaa).
- Scanned raster image PDFs from mobile photos or photocopiers.

All operations execute **100% locally and offline** on your computer. Your catalog data and pricing remain completely private.

---

## 2. Catalog Lifecycle States / حالات فحص الكتالوج

When you load a catalog into the application, each file progresses through five plain-language lifecycle states:

| Lifecycle State | Arabic Label | Description |
|---|---|---|
| **Reading** | قيد القراءة / Reading... | The application is inspecting the document structure, classifying page types (vector vs scanned), and reading items. |
| **Automatically retrying** | إعادة المحاولة التلقائية / Retrying... | For pages with low contrast or rotation, the system automatically applies bounded enhancement (200 DPI, CLAHE contrast, deskewing). |
| **Ready** | جاهز / Ready | All items were successfully extracted, validated, and verified (0 review issues). Ready for automatic procurement. |
| **Partially recovered** | مسترد جزئياً / Partially recovered | Some items were recovered, but certain rows or pages had visual noise, unmapped regions, or incomplete pricing. |
| **Could not verify** | تعذر التحقق / Could not verify | The file could not produce verified items (e.g., completely unreadable scan or corrupted layout). Zero items accepted. |

---

## 3. Zero Forced Transcription / لا كتابة أو تفريغ يدوي إجباري

In previous versions or traditional software, unreadable rows forced pharmacists to manually type in medicine names and prices.  
**In v2.6, manual typing is never required as a normal fallback.**

When a catalog has unresolved items, the **Catalog Review & Correction** dialog provides two one-click automated actions:

### 1. 🔄 Auto Retry (200 DPI CLAHE deskew) / إعادة المحاولة التلقائية البديلة
- Re-analyzes the catalog with enhanced resolution (200 DPI), CLAHE local adaptive contrast, and rotational deskewing.
- Automatically captures items that were missed during initial reading due to slight rotation or faint print.

### 2. 📄 Replace with Clearer Source / استبدال بمصدر أوضح
- If a wholesaler sent a blurry photo, simply select a clearer scan, digital PDF, or Excel file from your computer.
- The system immediately swaps the catalog and refreshes the data without losing your current purchase order or session work.

---

## 4. Procurement Safeguards / حماية المشتريات الصيدلانية

### Strict Exclusion of Unverified Data
- **Safety Rule**: **Only verified items are ever allocated to purchase orders.**
- Any item with unreadable prices, uncertain discounts, or blurred names is strictly excluded from automated purchasing.
- Even if you acknowledge a "Partially Recovered" catalog to proceed with verified items, unverified rows are **NEVER** guessed, invented, or silently accepted.

### Acknowledgment Token Gating
- If a catalog has unresolved issues, the system issues a cryptographically secure token tied to that specific version of the catalog.
- Procurement cannot proceed until the user explicitly chooses to proceed with verified items only. If a catalog produces 0 valid items, procurement is strictly blocked until the file is replaced or removed.

---

## 5. Step-by-Step Workflow / خطوات العمل

1. **Add Order Files**: Click **Add Files** or drag-and-drop your pharmacy purchase orders (`.xlsx` or `.csv`).
2. **Add Supplier Catalogs**: Add catalogs from El-Abed, Tebaa, Hayah, Ibn Sina, or any wholesaler.
3. **Inspect Diagnostics**: Observe the lifecycle status badges on each file card (`Ready`, `Partially recovered`, etc.).
4. **Review Issues (Optional)**: Click **Review Issues** on any catalog card to view the visual PDF crop alongside extracted data.
5. **Execute Optimization**: Click **Run Procurement Optimization** to run clinical matching, discount comparisons, and generate the final Excel procurement workbook.
