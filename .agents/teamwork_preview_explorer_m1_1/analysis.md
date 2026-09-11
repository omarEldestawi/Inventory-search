# Comprehensive Technical Analysis: RapidOCR & RapidTable Catalog Parsing Architecture

**Agent**: Explorer 1 (Codebase & Parser Explorer)  
**Date**: 2026-09-11  
**Milestone**: M1 - RapidOCR & RapidTable Catalog Parsing Architecture  
**Target Module**: `src/pdf_parser.py`, `src/controller.py`, `app_gui.py`  

---

## 1. Executive Summary

This investigation provides the complete architectural design and interface contracts for integrating the **RapidOCR + RapidTable** on-device OCR pipeline into `src/pdf_parser.py`, `src/controller.py`, and `app_gui.py` in strict compliance with the user mandate:
- **PyMuPDF (fitz)**: Renders PDF pages locally at 300 DPI (`page.get_pixmap(dpi=300)`).
- **RapidOCR (`rapidocr_onnxruntime`)**: Performs CPU-optimized ONNX inference for Arabic text extraction (PaddleOCR weights converted to ONNX, zero CUDA/C++ dependencies).
- **RapidTable (`rapid_table`)**: Detects table cell and column boundaries (`اسم الصنف`, `سعر الجمهور`, `الخصم`) and outputs structured HTML converted into clean `pandas.DataFrame`.
- **Pipeline Integration**: Reconstructs standard schema records and pipes them into existing normalizers (`normalize_arabic_text`, `clean_drug_name`, `parse_discount`, `parse_dosage_and_pack`, `normalize_vendor_name`).
- **Resilience & Fallback**: Multi-tier degradation (RapidTable → RapidOCR geometric line parser → PyMuPDF vector fallback) guaranteeing zero pipeline failures on non-tabular or low-contrast pages.

---

## 2. Current Codebase & `src/pdf_parser.py` Audit

### 2.1 Current Class Hierarchy & Responsibilities
`src/pdf_parser.py` contains 429 lines implementing `PDFCatalogParser`:

| Method / Function | Input | Output | Purpose & Logic |
|---|---|---|---|
| `fix_arabic_bidi_if_needed(text)` | `str` | `str` | Standalone helper. Detects reversed Arabic glyphs (e.g. `ﺹﺍﺮﻗﺍ`) and reverses them back to natural order without flipping digits. |
| `PDFCatalogParser.__init__(pdf_path, warehouse_name=None)` | `str`, `Optional[str]` | `None` | Resolves canonical vendor entity name via `normalize_vendor_name()`. |
| `PDFCatalogParser.parse()` | None | `pd.DataFrame` | Primary ingestion method. Opens PDF via `pymupdf.open()`, checks for warehouse-specific layouts (`ميجا`, `كيور`, `المكرومي`), uses `page.find_tables()` for digital vector tables with fallback to `_process_page_blocks()`. Deduplicates items keeping highest discount. |
| `_process_table(table)` | `list[list]` | `list[dict]` | Converts 2D extracted table into list of dictionaries. Handles multi-column side-by-side splits (e.g. 6-column 3+3 tables) and single concatenated cell text. |
| `_find_column_indices(headers, sample_rows)` | `list[str]`, `list[list]` | `tuple[4]` | Keyword search across Arabic and English terms for `name_idx`, `price_idx`, `discount_idx`, `stock_idx`. If headers fail, employs statistical data-driven scoring (word counts, `%` presence, numeric ranges `1.0 <= n <= 75.0`). |
| `_parse_price(val)` | `Any` | `float` | Regex extractor for monetary floats, handles comma decimal separators and Eastern Arabic numerals. |
| `_process_page_blocks(page)` | `fitz.Page` | `list[dict]` | PyMuPDF text block parser for unstructured whitespace catalogs (Mega Farm). |
| `_extract_cure_right_column(page)` | `fitz.Page` | `list[dict]` | Bounding-box word clustering for Cure Pharma's 2-column ArwaSoft accounting format. |
| `_extract_makramy_columns(page)` | `fitz.Page` | `list[dict]` | Text-block regex splitter for Makramy's 3-column ArwaSoft accounting format. |

### 2.2 Output Schema Contract
The output of `PDFCatalogParser.parse()` is a `pd.DataFrame` with exactly 8 canonical columns:
```python
COLUMNS = [
    'warehouse_name',   # str: Normalized wholesaler name (e.g. "مصر لتجارة الأدوية")
    'item_name',        # str: Extracted product string with bidi fixed (e.g. "كونجستال 24 قرص")
    'normalized_name',  # str: Lowercased, noise-stripped, character-mapped name for matching
    'dosage',           # str: Extracted strength (e.g. "500mg", "1gm")
    'unit_size',        # str: Extracted pack size (e.g. "24 tab", "100ml")
    'base_price',       # float: Official public price (سعر الجمهور)
    'discount_rate',    # float: Normalized decimal rate (e.g. 0.225 for 22.5%)
    'stock_status'      # bool: True if available, False if out-of-stock
]
```
Any OCR method must output rows strictly matching this schema so that downstream modules (`src/allocator.py`, `src/pharma_matcher.py`, `src/report_generator.py`) operate without modification.

---

## 3. High-Resolution 300 DPI PyMuPDF Rasterization Architecture

### 3.1 Mandate & Technical Requirements
PyMuPDF (`pymupdf` or `fitz`) provides high-fidelity PDF rendering. The user mandate specifies:
`pix = page.get_pixmap(dpi=300)`

At 300 DPI, an A4 page (8.27 × 11.69 inches) produces a raster of approximately **2480 × 3508 pixels** (~8.7 megapixels). This resolution is ideal for Arabic OCR, where diacritics (dots on `ب`, `ت`, `ث`, `ن`, `ي`) and small ligature features require crisp edges.

### 3.2 In-Memory Conversion Pipeline (Zero Disk I/O)
Writing rendered images to temporary files on disk introduces severe I/O bottlenecks and cleanup risks. Instead, convert `pixmap` directly in-memory to NumPy BGR arrays or raw image bytes:

```python
import pymupdf  # fitz
import numpy as np

def rasterize_page_to_bgr(page: pymupdf.Page, dpi: int = 300) -> np.ndarray:
    """
    Renders a PDF page to a BGR NumPy array at specified DPI in memory.
    RapidOCR and RapidTable expect OpenCV-standard BGR images.
    """
    pix = page.get_pixmap(dpi=dpi)
    
    # Raw byte buffer from PyMuPDF
    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    
    if pix.n == 4:
        # RGBA -> BGR: drop alpha and reverse RGB to BGR
        img_bgr = img_np[:, :, :3][:, :, ::-1].copy()
    elif pix.n == 3:
        # RGB -> BGR
        img_bgr = img_np[:, :, ::-1].copy()
    elif pix.n == 1:
        # Grayscale -> BGR
        img_bgr = np.repeat(img_np, 3, axis=2)
    else:
        img_bgr = img_np
        
    return img_bgr
```

### 3.3 Memory Optimization & Garbage Collection
Processing 30+ pages at 8.7 MP each in memory can consume several gigabytes if pixmaps are kept alive. To maintain a constant ~150 MB memory profile:
1. Process page by page.
2. Explicitly delete `pix` and `img_bgr` immediately after OCR table extraction.
3. Call `gc.collect()` at page intervals.

---

## 4. RapidOCR & RapidTable Library Interaction & Signatures

### 4.1 Dependency Ecosystem & Separation
- **`rapidocr-onnxruntime`**:
  - Module import: `from rapidocr_onnxruntime import RapidOCR`
  - Engine initialization: `ocr_engine = RapidOCR()`
  - Input: BGR `np.ndarray`, `PIL.Image`, `bytes`, or image file path.
  - Return: `result, elapse = ocr_engine(img)`
  - Format of `result`:
    When text is found: `[[box, text, score], ...]`
    - `box`: 4-point list `[[x0, y0], [x1, y1], [x2, y2], [x3, y3]]` (or `np.ndarray` of shape `(4, 2)`)
    - `text`: Arabic or English text string (e.g. `'كونجستال أقراص'`)
    - `score`: Confidence score float (e.g. `0.942`)
    When no text is found: `None` or `[]`.

- **`rapid_table`**:
  - Module import: `from rapid_table import RapidTable`
  - Engine initialization: `table_engine = RapidTable()`
  - Model weights: Default `slanet-plus.onnx` or `ppstructure_zh.onnx` executed via ONNX Runtime CPU.
  - Call signature: `table_out = table_engine(img, ocr_results=ocr_results)`

### 4.2 Interaction Protocol
`RapidTable` accepts pre-computed OCR results to reconstruct the table structure and assign recognized text into table cells.

```python
# 1. Run RapidOCR
ocr_res, elapse = ocr_engine(img_bgr)

# 2. Structure OCR results for RapidTable
if ocr_res:
    # Handles both list-of-lists and class attributes
    if hasattr(ocr_res, 'boxes'):
        boxes, txts, scores = ocr_res.boxes, ocr_res.txts, ocr_res.scores
    else:
        boxes = [item[0] for item in ocr_res]
        txts = [item[1] for item in ocr_res]
        scores = [item[2] for item in ocr_res]
    formatted_ocr = [(boxes, txts, scores)]
else:
    formatted_ocr = None

# 3. Reconstruct Table via RapidTable
table_out = table_engine(img_bgr, ocr_results=formatted_ocr)

# 4. Extract HTML string across library versions
html_str = ""
if hasattr(table_out, 'pred_html'):
    html_str = table_out.pred_html
elif isinstance(table_out, tuple) and len(table_out) >= 1:
    html_str = table_out[0]
elif isinstance(table_out, str):
    html_str = table_out
```

### 4.3 Converting RapidTable HTML to `pandas.DataFrame`
RapidTable produces standard HTML:
`<html><body><table><tr><td>اسم الصنف</td><td>سعر الجمهور</td><td>الخصم</td></tr><tr><td>PANADOL EXTRA</td><td>50.0</td><td>20%</td></tr></table></body></html>`

To parse this reliably into a DataFrame without hard dependency on external C-libraries:
```python
import io
import pandas as pd

def html_to_dataframes(html_str: str) -> list[pd.DataFrame]:
    """Parses HTML table string into pandas DataFrames with parser fallback."""
    if not html_str or "<table" not in html_str.lower():
        return []
    
    # Primary: pandas read_html (uses lxml or html5lib or bs4)
    try:
        dfs = pd.read_html(io.StringIO(html_str))
        if dfs:
            return dfs
    except Exception:
        pass

    # Built-in Fallback: html.parser or regex table row parser
    try:
        from html.parser import HTMLParser
        class SimpleTableParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows = []
                self.current_row = []
                self.current_cell = []
                self.in_cell = False

            def handle_starttag(self, tag, attrs):
                if tag in ('td', 'th'):
                    self.in_cell = True
                    self.current_cell = []
                elif tag == 'tr':
                    self.current_row = []

            def handle_endtag(self, tag):
                if tag in ('td', 'th'):
                    self.in_cell = False
                    self.current_row.append(''.join(self.current_cell).strip())
                elif tag == 'tr':
                    if self.current_row:
                        self.rows.append(self.current_row)

            def handle_data(self, data):
                if self.in_cell:
                    self.current_cell.append(data)

        parser = SimpleTableParser()
        parser.feed(html_str)
        if parser.rows and len(parser.rows) > 1:
            headers = parser.rows[0]
            # Ensure unique headers
            clean_headers = [h if h else f"col_{i}" for i, h in enumerate(headers)]
            data = parser.rows[1:]
            return [pd.DataFrame(data, columns=clean_headers)]
    except Exception as parse_err:
        logger.warning(f"Fallback HTML table parser failed: {parse_err}")

    return []
```

---

## 5. Column Identification & Domain Entity Normalization

### 5.1 Real-World Egyptian Pharmaceutical Column Vocabulary
Wholesalers format tables with various column headers and ordering. The mapping engine must match:

| Canonical Field | Arabic Synonyms | English / Transliterated Synonyms | Reversed Bidi Glyphs |
|---|---|---|---|
| **Drug Name** (`item_name`) | `اسم الصنف`, `الصنف`, `الاسم`, `البيان`, `دواء`, `المستحضر`, `اسم الدواء` | `Item`, `Product`, `Description`, `Item Name`, `Name` | `فنصلا مسإ`, `فنصلا`, `مسإ`, `مساف` |
| **Public Price** (`base_price`) | `سعر الجمهور`, `سعر`, `الجمهور`, `السعر الرسمي`, `سعر ج`, `س.ج`, `رسمي` | `Price`, `Public`, `Public Price`, `Base Price`, `Cost` | `رعسلا`, `روهمجلا`, `نلر` |
| **Discount Rate** (`discount_rate`) | `الخصم`, `نسبة الخصم`, `خصم`, `جملة`, `نسبة`, `الخصم %`, `خصم الصيدلي` | `Discount`, `Disc`, `Disc %`, `%`, `Rate` | `مصخلا`, `مصخ`, `ةلمج`, `ممم` |
| **Stock Status** (`stock_status`) | `الرصيد`, `الكمية`, `الحالة`, `المتاح`, `توفر`, `حالة الصنف` | `Stock`, `Qty`, `Available`, `Status` | `ديصرلا`, `ةلاحلا` |

### 5.2 Mapping Algorithm & Statistical Fallback
When headers are missing or OCR splits header text across cells:
1. **Keyword Scoring**: Match known synonyms across column headers.
2. **Column Heuristic Scoring** (already proven in `_find_column_indices`):
   - `name_idx`: Highest average text length and highest Arabic/Latin letter ratio.
   - `discount_idx`: Columns containing `%` signs, or numerical values falling predominantly in the range `1.0 <= n <= 75.0`.
   - `price_idx`: Column with numeric values outside typical discount ranges or with currency markers (`ج.م`, `جنيه`).
   - `stock_idx`: Column containing stock status words (`متوفر`, `غير متوفر`, `نفذ`, `out`).

### 5.3 Row-Level Entity Normalization Flow
For each table row:
1. **Raw Drug Name**:
   - Skip empty or header rows (`if any(k in raw_name for k in ['اسم الصنف', 'Item Name', ...])`).
   - Reverse bidi text if needed via `fix_arabic_bidi_if_needed(raw_name)`.
   - Extract strength and packaging via `dosage, unit_size = parse_dosage_and_pack(item_name)`.
   - Create normalized matching string via `norm_name = normalize_arabic_text(item_name)`.
2. **Public Price**:
   - Extract via `_parse_price(raw_price)`.
3. **Discount Rate**:
   - Extract via `parse_discount(raw_discount)`. Converts strings like `'22.5%'`, `'0.225'`, `'22,5'` to `0.225`.
   - Skip rows where `discount_rate <= 0` or `norm_name` length `< 2`.
4. **Stock Status**:
   - Defaults to `True`.
   - Set to `False` if stock text matches `['غير متوفر', 'نفذ', 'out', '0', 'لا يوجد']`.

---

## 6. Resilience, Fallback Mechanisms & Edge Case Handling

### 6.1 Multi-Tier Degradation Waterfall
To ensure OCR never crashes the application, enforce a 3-tier fallback waterfall per page:

```
┌────────────────────────────────────────────────────────┐
│ Tier 1: RapidTable + RapidOCR (Full Table Recognition) │
│ - Detects grid boundaries                              │
│ - Maps cells to columns                                │
└───────────────────────────┬────────────────────────────┘
                            │ (If no table found or 0 rows)
                            ▼
┌────────────────────────────────────────────────────────┐
│ Tier 2: RapidOCR Geometric Line Bounding-Box Parser    │
│ - Groups OCR boxes by Y-coordinate (rows)              │
│ - Parses line regex: <Name> <Price> <Discount%>        │
└───────────────────────────┬────────────────────────────┘
                            │ (If RapidOCR fails or errors)
                            ▼
┌────────────────────────────────────────────────────────┐
│ Tier 3: PyMuPDF Vector Text Parser                     │
│ - Uses existing page.find_tables() / get_text("blocks")│
└────────────────────────────────────────────────────────┘
```

### 6.2 Tier 2 Geometric Line Parser Specification
When a page has no grid lines (whitespace layout like Mega Farm):
1. Extract all text boxes: `[(box, text, score), ...]`.
2. Compute vertical center `y_center = (box[0][1] + box[2][1]) / 2`.
3. Cluster boxes into horizontal row buckets with threshold `|y1 - y2| <= 10` pixels.
4. For each row bucket:
   - Sort boxes horizontally.
   - Concatenate row text.
   - Run regex pattern: `r'^(.*?)(\d+(?:\.\d+)?)\s*(?:ج\.?م?)?\s+(\d+(?:\.\d+)?)\s*%?\s*$'`
   - Yield extracted product record.

### 6.3 Edge Case Matrix

| Edge Case | Failure Mode | Mitigation Strategy |
|---|---|---|
| **Cover Page / Ads** | Non-tabular, 0 items parsed | RapidTable returns empty, Tier 2 extracts 0 valid drug lines. Page skipped gracefully without error. |
| **Merged Columns** | Name and price in single cell | Cell parser splits on trailing digits via regex `(\d+(?:\.\d+)?)\s*$` (matches existing `_process_table` Case A). |
| **Reversed Bidi Digits** | "5.22" parsed as "22.5" or vice versa | `unreverse_arabic_text` preserves numbers while un-reversing Arabic letters. |
| **Rotated Page (Landscape)** | OCR orientation wrong | Check `page.rotation`. If rotated (90/270), PyMuPDF `get_pixmap` renders upright automatically or pass orientation flag. |
| **Corrupted PDF / Empty File** | Crash on open | Catch `pymupdf.FileDataError`, log descriptive warning, return empty DataFrame with schema. |

---

## 7. Concrete Implementation Design for `src/pdf_parser.py`

### 7.1 Proposed Method Signatures

```python
class PDFCatalogParser:
    def __init__(self, pdf_path: str, warehouse_name: str = None):
        ...
        
    def parse(self, use_ocr: bool = False) -> pd.DataFrame:
        """Standard parser entry point with optional OCR flag."""
        if use_ocr:
            return self.parse_ocr()
        # Existing PyMuPDF digital parsing...

    def parse_ocr(self, progress_callback: Optional[Callable[[float, str], None]] = None) -> pd.DataFrame:
        """
        Parses catalog pages at 300 DPI using RapidOCR and RapidTable.
        Returns deduplicated pd.DataFrame with the canonical 8-column schema.
        """
        ...

    @classmethod
    def parse_catalog_ocr(cls, pdf_path: str, warehouse_name: str = None) -> list[dict]:
        """
        Class method satisfying Scope Contract:
        PDFCatalogParser.parse_catalog_ocr(pdf_path: str) -> list[dict]
        """
        parser = cls(pdf_path, warehouse_name=warehouse_name)
        df = parser.parse_ocr()
        return df.to_dict(orient='records')
```

### 7.2 Lazy Engine Instantiation
To ensure fast GUI startup and prevent initializing ONNX models when parsing standard digital PDFs:
```python
_RAPID_OCR_INSTANCE = None
_RAPID_TABLE_INSTANCE = None

def get_ocr_engine():
    global _RAPID_OCR_INSTANCE
    if _RAPID_OCR_INSTANCE is None:
        from rapidocr_onnxruntime import RapidOCR
        _RAPID_OCR_INSTANCE = RapidOCR()
    return _RAPID_OCR_INSTANCE

def get_table_engine():
    global _RAPID_TABLE_INSTANCE
    if _RAPID_TABLE_INSTANCE is None:
        from rapid_table import RapidTable
        _RAPID_TABLE_INSTANCE = RapidTable()
    return _RAPID_TABLE_INSTANCE
```

---

## 8. Integration Architecture with GUI & Controller

### 8.1 Controller Bridge Extension (`src/controller.py`)
Add catalog inspection and background OCR re-reading to the controller:
```python
def inspect_catalog_counts(catalog_files: list[str]) -> dict[str, int]:
    """Fast inspection: parses digital text and returns medication count per file."""
    counts = {}
    for path in catalog_files:
        parser = PDFCatalogParser(path)
        df = parser.parse()
        counts[path] = len(df)
    return counts

def reread_catalog_with_ocr(catalog_file: str, progress_cb=None) -> tuple[str, int, list[dict]]:
    """Runs OCR re-read for a single catalog file, returning (path, count, records)."""
    parser = PDFCatalogParser(catalog_file)
    records = parser.parse_catalog_ocr(catalog_file)
    return catalog_file, len(records), records
```

### 8.2 GUI Design (`app_gui.py`)
1. **Medication Count Badge on File Cards**:
   - Each catalog card displays an item count badge: e.g. `🏷️ 245 صنف / items`.
   - Populated automatically on file addition or via fast background peek.
2. **"Re-read with OCR" Action Button**:
   - Added to each catalog card row:
     `[🔍 قراءة بـ OCR / Re-read with OCR]`
3. **Non-Blocking Background Threading**:
   - On click, disables the button and displays a pulsing status / progress indicator on that file card.
   - Spawns `threading.Thread(target=_ocr_worker, daemon=True)`.
   - On worker completion, GUI schedules a callback via `self.after(0, update_ui)` to:
     - Update the item count badge (e.g. `🏷️ 312 صنف [OCR]`).
     - Cache the OCR results in memory so the subsequent optimization run uses the high-accuracy OCR data directly.
     - Re-enable the button with a checkmark indicator (`✓ تم التحديث / Updated`).

---

## 9. Verification & Performance Benchmarks

### 9.1 Verification Commands
- **Unit Verification**:
  ```powershell
  python -m pytest tests/test_pipeline.py -v
  python -m pytest tests/test_gui.py -v
  ```
- **OCR Unit Test**:
  Create `tests/test_ocr_parser.py` testing:
  - `PDFCatalogParser.parse_catalog_ocr(pdf_path)` returns list of dicts with 8 canonical keys.
  - Verification on sample PDFs in `input/catalogs/`.
  - Fallback testing on corrupted / empty input.
- **GUI Self-Test**:
  ```powershell
  python app_gui.py --self-test
  ```

### 9.2 Expected Performance
- 300 DPI Rasterization: ~30-50 ms per page.
- RapidOCR Text Detection & Recognition: ~800-1200 ms per page (CPU ONNX Runtime).
- RapidTable Structure Inference: ~150 ms per page.
- Total processing rate: ~1.0 - 1.5 seconds per page on standard modern laptop CPU.
- 10-page catalog parses in ~12-15 seconds asynchronously without UI lag.
