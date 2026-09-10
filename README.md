# 🏥 Medicine Price & Discount Comparator (نظام مقارنة أسعار وخصومات الأدوية الذكي)

Automated procurement optimization pipeline that ingests daily pharmaceutical warehouse PDF/Excel catalogs, maximizes discount rates per item, and generates professionally formatted Arabic Excel purchase orders (`أفضل_اسعار_YYYY-MM-DD.xlsx`).

---

## ⚡ Hybrid Architecture (Option B)

1. **Pass 1: Deterministic Engine (Ultra-Fast, 0ms, 0 API Calls)**:
   - Evaluates 95%+ of items using normalized Arabic root matching, character normalization, digit mapping, and unit dosage extraction.
2. **Pass 2: Gemini 3.6 Flash Semantic Assistant**:
   - Automatically handles English <-> Arabic trade name transliteration (e.g., `بانادول اكسترا` ↔ `Panadol Extra`, `اوجمنتين` ↔ `Augmentin`).
   - Resolves brand aliases and spelling typos in order lists with millisecond response times.
3. **Hard Clinical Safety Gates**:
   - Every match must strictly satisfy:
     - **Exact Dosage Form Category** (`قرص/كبسول` $\ne$ `شراب` $\ne$ `حقن` $\ne$ `كريم`).
     - **Exact Strength / Combination Ratio** (`500mg` $\ne$ `1000mg`, `10/160` $\ne$ `10/320`).
     - **Formulation Modifiers** (`Extra` $\ne$ Plain $\ne$ `XR/SR` $\ne$ `Cold & Flu`).
     - **Infant Milk Stages** (Stage 1 $\ne$ Stage 2).

---

## 📁 Directory Structure

```text
Inventory-search/
├── .env                <-- Configures GEMINI_API_KEY and GEMINI_MODEL (gemini-3.6-flash)
├── input/
│   ├── catalogs/       <-- Warehouse catalogs (PDF or Excel, e.g. Ibn_Sina.pdf, United.pdf)
│   └── orders/         <-- Requested purchase order lists (Excel or CSV)
├── output/             <-- Multi-sheet Arabic Excel orders saved here
├── src/
│   ├── allocator.py    <-- Two-pass hybrid allocator & discount maximization
│   ├── gemini_matcher.py <-- Gemini 3.6 Flash semantic assistant + Hard Safety Gates
│   ├── pharma_matcher.py <-- Strict clinical safety validator & modifier gates
│   ├── normalizer.py   <-- Arabic text normalization & dosage entity parser
│   ├── pdf_parser.py   <-- Arabic table extractor with RTL support
│   ├── excel_parser.py <-- Order & Excel ingestion with deduplication
│   └── report_generator.py <-- RTL Arabic multi-sheet Excel generator
├── watcher.py          <-- Automated directory watcher for continuous polling
├── run_daily.bat       <-- 1-Click Windows launcher / Task Scheduler script
├── main.py             <-- Main CLI execution pipeline
└── README.md
```

---

## 🚀 How to Run

### Option 1: One-Click Daily Execution (Windows)
Double-click `run_daily.bat` or run:
```bash
python main.py
```

### Option 2: Continuous Folder Watcher Mode
To monitor the `input/` folder continuously and process files as soon as they are dropped:
```bash
python watcher.py --watch --interval 15
```

### Optional Arguments
- Specify a custom purchase order file:
  ```bash
  python main.py --order-file input/orders/طلبية_عربي_اختبار.xlsx
  ```
- Specify a custom report date:
  ```bash
  python main.py --date 2026-09-10
  ```

---

## 📊 Excel Output Structure (`أفضل_اسعار_YYYY-MM-DD.xlsx`)

1. **المقارنة الشاملة والملخص (Master Comparison & Executive KPI Cards)**:
   - Complete item matrix showing side-by-side discounts across all warehouses.
   - Winning warehouse selection based on `max(discount_rate)`.
   - KPI Summary Cards: Total Items, Matched Items, Out of Stock Count, Average Order Discount %.
   - Remarks column clearly distinguishing deterministic vs approved AI-matched items.
2. **Individual Supplier Purchase Sheets (`طلبية_اسم_المخزن`)**:
   - Ready-to-send purchase orders for each supplier containing only their won items, quantities, agreed discount %, and net totals.
3. **النواقص وغير المتوفر (Out of Stock Review)**:
   - Dedicated tab highlighting items not available in any catalog for manual review or alternatives.
