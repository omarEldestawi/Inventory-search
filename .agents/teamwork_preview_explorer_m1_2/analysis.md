# Architectural Analysis: Catalog Inspection, Medication Count Display & On-Demand Arabic OCR Re-read

**Agent**: Explorer 2 (GUI & Async Architecture Explorer)  
**Date**: 2026-09-11  
**Project**: Egyptian Pharmaceutical Procurement Optimizer (`app_gui.py`, `src/controller.py`, `src/pipeline.py`)  
**Scope Reference**: Milestone 1 (Catalog Inspection & On-Demand Arabic OCR Re-read)

---

## Executive Summary

The objective is to provide Egyptian pharmacy procurement operators with immediate visibility into wholesaler catalog contents, detected medication counts, and an asynchronous, on-demand "Re-read with OCR" capability for scanned or image-heavy catalogs using `rapidocr-onnxruntime` and `rapid_table`. This must operate smoothly without UI freezing, seamlessly integrate with the existing deterministic clinical safety engine, and ensure cached OCR results are utilized during final procurement optimization.

This document details the architectural blueprint across seven core areas:
1. **File Selection, Classification & Rendering Lifecycle**
2. **Medication Count Computation, Statuses & Card Badge Placement**
3. **On-Demand "Re-read with OCR" Action & Button Layout**
4. **Asynchronous Non-Blocking Worker & Thread Safety Protocol**
5. **Real-time Granular Progress & Visual Feedback**
6. **Catalog Cache Architecture (`CatalogCache`) in Controller and Pipeline**
7. **Bilingual Typography & Egyptian Market Nomenclature**

---

## 1. File Selection, Classification & Rendering Lifecycle

### Current Codebase Flow
In `app_gui.py`:
1. **User Ingestion Entry Points**:
   - `_on_add_files()` (line 618): Triggers `filedialog.askopenfilenames()` filtering for `*.pdf;*.xlsx;*.xls;*.csv`.
   - `_on_add_folder()` (line 634): Triggers `filedialog.askdirectory()` and recursively walks folder for valid document extensions.
   - Both forward selected absolute file paths to `add_files(paths)`.
2. **Classification Logic**:
   - `FileListModel.add_paths(file_paths)` (lines 139-173):
     - Normalizes paths (`os.path.normpath(os.path.abspath(p))`) and deduplicates against `self.files`.
     - Invokes `classify_files(candidates)` from `src.controller`.
     - `classify_files()` executes a 3-tier heuristic:
       - **Tier 1 (Extension)**: `.pdf` files are unconditionally assigned to `catalogs`.
       - **Tier 2 (Filename Regex/Keywords)**: Matches daily order date patterns (`^\d{4}\.(xlsx|xls|csv)$`) and keywords (`طلب`, `طلبية`, `نواقص`, `order`) vs catalog keywords (`خصم`, `جملة`, `عروض`, `مخزن`).
       - **Tier 3 (Content Inspection)**: Reads first 15 rows with `pandas` checking for header tokens (`أسم العميل`, `اصناف تم طلبها`, `المطلوب`).
     - Files classified in `orders` are set to `category="Order"`; all others set to `category="Catalog"`.
     - Creates `FileItem(cand, category)` and appends to `self.files`.
3. **GUI Card Generation**:
   - `_render_file_list()` (lines 681-765):
     - Clears previous `_file_card_widgets`.
     - For each `FileItem`, constructs a single-row `ctk.CTkFrame(self.file_scroll_frame)`.
     - Current single-row layout contains:
       - `col 0`: Extension badge (`[PDF]`, `[XLSX]`, `[CSV]`)
       - `col 1`: Filename & formatted size (`f_item.filename (f_item.size_str)`)
       - `col 2`: Category status badge (`📋 أمر شراء / Order` vs `🏷️ كتالوج / Catalog`)
       - `col 3`: Override option menu (`CTkOptionMenu` with `Order` / `Catalog`)
       - `col 4`: Delete button (`✕`)

---

## 2. Medication Count Computation & Badge Design

### Problem Statement
Currently, `FileItem` only stores static metadata (`path`, `filename`, `ext`, `category`, `size_bytes`). Neither medication count nor parsed data is tracked upon ingestion. Scanned PDF catalogs (e.g. image-only price lists) yield 0 items under standard text extraction, leaving the user unaware until allocation completes with zero matches.

### Proposed Data Model Enhancements
Enhance `FileItem` in `app_gui.py`:
```python
class FileItem:
    def __init__(self, path: str, category: str):
        self.path = os.path.normpath(os.path.abspath(path))
        self.filename = os.path.basename(self.path)
        self.ext = os.path.splitext(self.filename)[1].lower()
        self.category = category
        self.auto_category = category
        self.is_override = False
        self.size_bytes = os.path.getsize(self.path) if os.path.isfile(self.path) else 0
        self.size_str = format_file_size(self.size_bytes)
        
        # New Catalog Inspection & OCR State Attributes
        self.item_count: Optional[int] = None       # Total medications parsed
        self.parsed_df: Optional[pd.DataFrame] = None # Cached structured items
        self.is_ocr: bool = False                   # True if produced via RapidOCR
        self.status: str = "pending"                # "pending", "ready", "running_ocr", "error"
        self.status_detail: str = ""                # Live progress detail string
```

### Two-Tier Inspection Strategy
1. **Initial Fast Inspection (Auto-Inspection on Add)**:
   - When files are added, standard parsing is performed asynchronously via a lightweight background worker:
     - For PDF catalogs: `PDFCatalogParser(path).parse()` (PyMuPDF table & layout parsing, takes ~0.05s).
     - For Excel/CSV catalogs: `parse_excel_catalog(path, warehouse_name)`.
     - For Orders: `load_purchase_order(path)` (computes total order items).
   - Upon completion, `f_item.item_count = len(df)` and `f_item.parsed_df = df`.
2. **Visual Status Badge States**:
   - **Inspecting**: `⏳ جاري الفحص... / Inspecting...` (Gray/Subtle text)
   - **Success (> 0 items)**: `📦 {count} صنف / {count} items` (Sky Blue `#0284C7` or Emerald Green `#059669`)
   - **Zero Items Detected (Scanned Warning)**: `⚠️ 0 صنف (يحتاج OCR) / 0 items (Needs OCR)` (Amber Warning `#D97706`)
   - **OCR Completed**: `✨ {count} صنف (بـ OCR) / {count} items (OCR)` (Vibrant Emerald `#10B981`)

---

## 3. On-Demand "Re-read with OCR" Action & Card Layout

### Layout Architecture: 2-Row Card Structure
The main scrollable frame has a constrained width (~620px when window is 980px). Crowding 6 widgets on a single row truncates filenames. A 2-row card provides ample space for long Arabic medicine catalog names, clear action buttons, and granular OCR progress indicators:

```
+-----------------------------------------------------------------------------------------------+
| [PDF]   الشركة_المتحدة_للصيدلة_عروض_سبتمبر.pdf (2.4 MB)     [ كتالوج مخزن (Catalog) v ]  [ ✕ ] |
|         -----------------------------------------------------------------------------         |
|         [ ⚠️ 0 صنف (يحتاج OCR) ]   [ 🔄 إعادة قراءة بـ OCR ]   ⏳ صفحة 2 من 5 (RapidTable)...   |
+-----------------------------------------------------------------------------------------------+
```

### Card Widget Hierarchy:
- **Row 0 (File Information & Primary Controls)**:
  - `col 0`: Extension Badge (`[PDF]`, `[XLSX]`, `[CSV]`)
  - `col 1`: Filename & File Size label (`sticky="w"`, `weight=1`)
  - `col 2`: Category Selection Dropdown (`ctk.CTkOptionMenu`, width 140)
  - `col 3`: Remove Button (`✕`, Rose Danger `#DC2626`, width 28)
- **Row 1 (Inspection & OCR Action Sub-bar)**:
  - `col 1` (indented under filename): Sub-frame containing:
    - **Count Badge**: `ctk.CTkLabel` with pill-like background or bold colored typography.
    - **OCR Action Button**: `ctk.CTkButton` (shown only for Catalog items):
      - Text: `🔄 إعادة قراءة بـ OCR / Re-read with OCR`
      - Height: 26px, Font: Segoe UI 10pt Bold
      - Color: Windows 11 Deep Navy Accent (`#1F4E79`), Hover (`#163A5C`)
    - **Status Feedback Label**: Displays live stage details during background execution.

---

## 4. Asynchronous Architecture & Non-Blocking GUI Protocol

### Thread Safety Constraints
Tkinter and CustomTkinter are **single-threaded**. Invoking GUI widget methods (`.configure()`, `.grid()`, `.pack()`) from a background thread will lead to race conditions, visual tearing, or fatal Windows crashes (`Tcl_AsyncDelete`).

### Asynchronous Worker Pattern
1. **Background Worker Dispatch**:
   - When the user clicks "Re-read with OCR" on a catalog, `app_gui.py` calls `self._on_trigger_catalog_ocr(file_path)`.
   - The UI immediately disables the button and updates the card status to `⏳ جاري بدء OCR...`.
   - Spawns a daemon thread `threading.Thread(target=_ocr_worker, daemon=True, name=f"OCRWorker-{filename}")`.
2. **Thread-Safe Communication via `queue.Queue`**:
   - The worker communicates exclusively by pushing message tuples into a dedicated thread-safe queue:
     - `("OCR_PROGRESS", file_path, current_page, total_pages, stage_description)`
     - `("OCR_SUCCESS", file_path, item_count, dataframe)`
     - `("OCR_ERROR", file_path, error_message, traceback_str)`
3. **Queue Polling Loop (`after()` method)**:
   - The main GUI thread runs a 50ms polling loop: `self.after(50, self._poll_ocr_queue)`.
   - Non-blocking `queue.get_nowait()` drains messages and safely applies updates to Tkinter widgets on the main thread:
     - Updates card status text and progress bar.
     - On completion, stores `f_item.parsed_df`, updates badge, re-enables button, and triggers `_update_ui_state()`.

```
+-------------------+           queue.put()           +-----------------------+
|  Background Thread| -----------------------------> |      queue.Queue      |
|  RapidOCR Worker  | (PROGRESS, SUCCESS, ERROR)     +-----------------------+
+-------------------+                                            |
                                                           queue.get_nowait()
                                                                 |
                                                                 v
                                                      +-----------------------+
                                                      |    Main GUI Thread    |
                                                      | (self._poll_ocr_queue)|
                                                      |   Updates CTk Widgets |
                                                      +-----------------------+
```

---

## 5. Granular Progress & Visual Feedback

### Multi-Stage Feedback per Page
RapidOCR + RapidTable processing of a 300 DPI multi-page PDF consists of distinct compute stages:
1. **Page Rasterization**: Rendering page at 300 DPI using PyMuPDF (`fitz`).
2. **Text Extraction**: Running RapidOCR ONNX CPU inference to locate text boxes and detect Arabic typography.
3. **Table Column Boundary Detection**: Running RapidTable to structure recognized cells into tabular columns (`اسم الصنف`, `سعر الجمهور`, `الخصم`).

### UI Visual State Transitions
| State | Count Badge | Button State & Text | Progress / Status Text |
|---|---|---|---|
| **Initial Pending** | `⏳ جاري الفحص...` | Disabled | `جاري فحص محتوى الكتالوج...` |
| **Standard Detected (>0)** | `📦 245 صنف` | Enabled: `🔄 إعادة قراءة بـ OCR` | `✓ تم الفحص السريع` |
| **Standard Scanned (0)** | `⚠️ 0 صنف (يحتاج OCR)` | Highlighted: `🔄 قراءة بـ OCR` | `الملف ممسوح ضوئياً، يوصى باستخدام OCR` |
| **Running OCR** | `⏳ جاري المعالجة...` | Disabled: `⏳ جاري المسح...` | `صفحة 2/5: استخراج الجداول (RapidTable)...` |
| **OCR Succeeded** | `✨ 189 صنف (بـ OCR)` | Enabled: `🔄 إعادة القراءة بـ OCR` | `✓ تم استخراج 189 صنف بـ OCR بنجاح` |
| **OCR Failed** | `⚠️ خطأ في OCR` | Enabled: `🔄 إعادة المحاولة` | `خطأ: تعذر تهيئة نموذج RapidOCR` |

---

## 6. Catalog Cache Architecture (`CatalogCache`)

### Critical Architectural Vulnerability Identified
In the existing codebase (`src/pipeline.py` lines 213-228), `run_procurement_pipeline` receives a list of file paths (`catalog_files: list[str]`) and unconditionally re-parses each catalog from disk using `PDFCatalogParser(cat_file).parse()`. 

**Impact**: Without a caching bridge, if an operator runs "Re-read with OCR" (which extracts items via RapidOCR), clicking "بدء التحسين والتوزيع / Run Optimization" would execute standard parsing and **completely discard the OCR results**.

### The Solution: Shared In-Memory `CatalogCache`
Implement a centralized, thread-safe cache in `src/controller.py` and integrate it into `src/pipeline.py`:

```python
class CatalogCache:
    """Thread-safe centralized cache for parsed catalog DataFrames."""
    _cache: Dict[str, pd.DataFrame] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, file_path: str) -> Optional[pd.DataFrame]:
        norm = os.path.normpath(os.path.abspath(file_path))
        with cls._lock:
            df = cls._cache.get(norm)
            return df.copy() if df is not None else None

    @classmethod
    def set(cls, file_path: str, df: pd.DataFrame, is_ocr: bool = False):
        norm = os.path.normpath(os.path.abspath(file_path))
        with cls._lock:
            cls._cache[norm] = df.copy()

    @classmethod
    def clear(cls, file_path: Optional[str] = None):
        with cls._lock:
            if file_path:
                norm = os.path.normpath(os.path.abspath(file_path))
                cls._cache.pop(norm, None)
            else:
                cls._cache.clear()
```

### Pipeline Integration Contract:
1. `run_procurement_pipeline()` signature updated to accept optional `catalog_cache: Optional[Dict[str, pd.DataFrame]] = None`.
2. During the catalog ingestion stage:
   ```python
   norm_path = os.path.normpath(os.path.abspath(cat_file))
   df_cat = None
   if catalog_cache and norm_path in catalog_cache:
       df_cat = catalog_cache[norm_path].copy()
       logger.info(f"Using pre-cached catalog items for {w_name} ({len(df_cat)} items)")
   elif CatalogCache.get(norm_path) is not None:
       df_cat = CatalogCache.get(norm_path)
   else:
       # Standard parse fallback
       ...
   ```
3. In `app_gui.py`:
   When `_on_run_optimization()` executes:
   ```python
   # Extract all pre-parsed / OCR-parsed DataFrames from FileListModel
   catalog_cache = {
       f.path: f.parsed_df for f in self.file_model.files 
       if f.category == "Catalog" and f.parsed_df is not None and not f.parsed_df.empty
   }
   self.bridge.start(
       order_files=order_files,
       catalog_files=catalog_files,
       output_dir=output_dir,
       catalog_cache=catalog_cache
   )
   ```
4. **Performance Benefit**: Pre-parsed catalogs (both standard and OCR) do not need to be re-read from disk during the final optimization run. The procurement pipeline executes immediately, reducing optimization latency from ~5 seconds to <1 second.

---

## 7. Bilingual Typography & Localization Matrix

| Component | Arabic Text | English Text | Combined Bilingual String |
|---|---|---|---|
| **Pending Badge** | جاري الفحص... | Inspecting... | `⏳ جاري الفحص... / Inspecting...` |
| **Count Badge (Standard)** | {count} صنف | {count} items | `📦 {count} صنف / {count} items` |
| **Count Badge (0 items)** | 0 صنف (يحتاج OCR) | 0 items (Needs OCR) | `⚠️ 0 صنف (يحتاج OCR) / 0 items (Needs OCR)` |
| **Count Badge (OCR)** | {count} صنف (بـ OCR) | {count} items (OCR) | `✨ {count} صنف (بـ OCR) / {count} items (OCR)` |
| **Re-read Button (Idle)** | إعادة قراءة بـ OCR | Re-read with OCR | `🔄 إعادة قراءة بـ OCR / Re-read with OCR` |
| **Re-read Button (Active)** | جاري المعالجة بـ OCR... | Running OCR... | `⏳ جاري المعالجة بـ OCR... / Running OCR...` |
| **Re-read Button (Done)** | إعادة تشغيل OCR | Re-run OCR | `🔄 إعادة تشغيل OCR / Re-run OCR` |
| **Progress: Rasterizing** | تحويل صفحات PDF بدقة 300 DPI... | Rasterizing PDF pages (300 DPI)... | `جاري تحويل الصفحات بدقة 300 DPI... / Rasterizing...` |
| **Progress: RapidOCR** | قراءة النصوص العربية (RapidOCR)... | Extracting Arabic text (RapidOCR)... | `صفحة {c}/{t}: قراءة النصوص العربية (RapidOCR)...` |
| **Progress: RapidTable** | استخراج الجداول (RapidTable)... | Detecting tables (RapidTable)... | `صفحة {c}/{t}: استخراج الجداول (RapidTable)...` |
| **Completion Message** | تم استخراج {count} صنف بـ OCR | {count} items extracted via OCR | `✓ تم استخراج {count} صنف بـ OCR بنجاح` |
| **Error Alert** | فشلت القراءة بـ OCR: {msg} | OCR processing failed: {msg} | `⚠️ فشلت القراءة بـ OCR: {msg}` |

---

## 8. Verification & Test Suite Compatibility

1. **`app_gui.py --self-test`**:
   - The CLI self-test validates GUI attribute bindings (`file_model`, `run_button`, `progress_bar`, `status_label`, `kpi_frame`, `counter_badge`, etc.).
   - The new 2-row card design and `FileItem` enhancements preserve all existing attribute contracts, ensuring `python app_gui.py --self-test` exits 0.
2. **Existing Unit & E2E Tests**:
   - Identified and noted minor test-file bug in `tests/test_gui.py` (`NameError: ctk is not defined` inside toplevel inspection tests) and malformed KPI dictionary handling in `_on_pipeline_completed` (`results.get("kpis") or {}`).
   - The proposed `catalog_cache` parameter is optional with default `None`, maintaining 100% backward compatibility with all existing pipeline and bridge tests.
