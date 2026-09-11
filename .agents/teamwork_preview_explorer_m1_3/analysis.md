# Technical Analysis: Dependency, Execution Environment & Verification Suite

**Agent**: Explorer 3 (Dependency & Verification Explorer)  
**Milestone**: M1 (Catalog Inspection & OCR Investigation)  
**Date**: 2026-09-11  
**Project Root**: `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search`

---

## Executive Summary

This investigation performed live execution, interface inspection, real data testing, and test suite verification for the Egyptian Pharmaceutical Procurement desktop application.

Key findings:
1. **RapidOCR (`rapidocr_onnxruntime` v1.2.3)** is installed and verified. It bundles default ONNX models (`ch_PP-OCRv3_det_infer.onnx`, `ch_PP-OCRv3_rec_infer.onnx`, `ch_ppocr_mobile_v2.0_cls_infer.onnx`). Runs completely offline on CPU in ~0.8-1.1s.
2. **RapidTable (`rapid_table` v3.0.2)** is installed. It required `tqdm` (missing dependency resolved via `pip install tqdm`). Furthermore, its default model loader hardcodes downloads from `modelscope.cn`, which fails DNS resolution (`cdn-lfs-cn-1.modelscope.cn`). We downloaded the official `slanet-plus.onnx` (7.4 MB, SHA256 verified) from RapidAI GitHub releases into `site-packages/rapid_table/models/slanet-plus.onnx`. RapidTable now initializes offline and executes in ~0.1-0.25s.
3. **Critical Interface Handshake**: RapidOCR returns `[[dt_box, text, score], ...]`, but RapidTable expects a list of per-image tuples: `[(dt_boxes_array, rec_res_list, scores_list)]` where `dt_boxes_array` is shape `(N, 4, 2)`. Direct passing triggers a numpy broadcast ValueError. A format adapter is mandatory.
4. **PyMuPDF 300 DPI Rasterization**: Verified on `input/catalogs/الشركة_المتحدة.pdf`. Page 0 rasterized in 0.01s at 300 DPI (2550x3300), successfully parsed through RapidOCR and RapidTable into structured HTML table cells in under 7 seconds total.
5. **Table to DataFrame**: `pd.read_html` fails because `lxml` is not installed. A lightweight, zero-dependency regex/standard library HTML parser (`html_table_to_df`) reliably converts the output table into a pandas DataFrame.
6. **`app_gui.py --self-test`**: Verified operational, completing in 5 seconds with exit code 0.
7. **Test Suite**: 110 of 120 tests in `tests/` pass. Failures are isolated to legacy pandas 3.0 uppercase extension quirks (`.XLSX`), an undefined name `ctk` in one challenger test, and pairwise catalog tie-breaker assertions.
8. **Packaging & Tooling Environment**: PyInstaller 6.22.2 is functional (`python -m PyInstaller`). Inno Setup `ISCC.EXE` is on PATH. Git 2.55.0 is verified at `%LOCALAPPDATA%\Programs\Git\cmd\git.EXE` with remote `git@github.com:omarEldestawi/Inventory-search.git`.

---

## 1. RapidOCR & RapidTable Import Signatures & Minimal Working Example

### 1.1 Environment Details
- **Python Version**: 3.14.3 (64-bit AMD64)
- **rapidocr-onnxruntime**: 1.2.3
- **rapid_table**: 3.0.2
- **onnxruntime**: 1.30.0
- **pymupdf**: 1.28.2
- **customtkinter**: 6.0.0
- **tqdm**: 4.70.0 (installed to satisfy rapid_table dependency)

### 1.2 RapidOCR Interface & Behavior
```python
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR()
ocr_result, elapse_list = ocr(img_np)
```
- **Input**: `img_content: str | numpy.ndarray | bytes | pathlib.Path` (RGB numpy array recommended: shape `(H, W, 3)`, dtype `uint8`).
- **Return Signature**: `Tuple[Optional[List[List]], List[float]]`
  - `ocr_result`: List of elements `[box, text, score]` or `None` if no text detected.
    - `box`: `List[List[float]]` of shape `(4, 2)` representing corner coordinates `[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]`.
    - `text`: `str` representing recognized text (supports Arabic & English).
    - `score`: `str` or `float` confidence score (e.g. `'0.8974'`).
  - `elapse_list`: 3-element float list `[detect_time, classify_time, rec_time]`.
- **Pre-packaged Models**: Stored locally in `site-packages/rapidocr_onnxruntime/models/`:
  - `ch_PP-OCRv3_det_infer.onnx` (detection)
  - `ch_PP-OCRv3_rec_infer.onnx` (recognition)
  - `ch_ppocr_mobile_v2.0_cls_infer.onnx` (direction classifier)
  - Zero external downloads required at runtime.

### 1.3 RapidTable Interface & Behavior
```python
from rapid_table import RapidTable
table_engine = RapidTable()
```
- **Initialization Requirements**:
  - Missing dependency: `rapid_table.main` executes `from tqdm import tqdm`. `tqdm` is not declared in `rapid_table` package metadata. Must ensure `tqdm` is present in the environment and bundled in PyInstaller spec.
  - Model weights: RapidTable looks for `slanet-plus.onnx` inside `site-packages/rapid_table/models/slanet-plus.onnx`.
    - If absent, it attempts to download from `https://www.modelscope.cn/models/RapidAI/RapidTable/resolve/v2.0.0/slanet-plus.onnx`.
    - ModelScope redirects to `cdn-lfs-cn-1.modelscope.cn` which fails DNS resolution outside mainland China (`socket.gaierror: [Errno 11002]`).
    - Verified fix: Pre-bundle `slanet-plus.onnx` (7,758,305 bytes, SHA256: `d57a942af6a2f57d6a4a0372573c696a2379bf5857c45e2ac69993f3b334514b`) in `site-packages/rapid_table/models/` or pass explicit path via `RapidTableInput(model_dir_or_path=...)`.
- **Calling Signature**:
  ```python
  table_out = table_engine(img_contents, ocr_results=batch_ocr, batch_size=1)
  ```
- **CRITICAL Data Structure Handshake**:
  RapidTable `__call__` expects `ocr_results` to be a **list of per-image tuples** matching `imgs`:
  ```python
  # CORRECT ADAPTER PATTERN:
  dt_boxes = np.array([x[0] for x in ocr_result])  # shape (N, 4, 2)
  rec_res = [x[1] for x in ocr_result]             # list of strings, length N
  scores = [float(x[2]) for x in ocr_result]       # list of floats, length N

  batch_ocr = [(dt_boxes, rec_res, scores)]
  table_out = table_engine(img_np, ocr_results=batch_ocr)
  ```
  If `ocr_result` from RapidOCR is passed directly without wrapping, `rapid_table.utils.format_ocr_results` crashes with:
  `ValueError: operands could not be broadcast together with shapes (4,) (2,)`
- **Output Structure**: `RapidTableOutput` dataclass:
  - `table_out.pred_htmls`: `list[str]` containing HTML table tags, e.g. `['<html><body><table><tr><td>Item</td><td>Price</td><td>Discount</td></tr>...</table></body></html>']`.
  - `table_out.cell_bboxes`: `list[np.ndarray]` bounding boxes for all reconstructed table cells.
  - `table_out.elapse`: inference execution duration.

### 1.4 Minimal Working Pipeline Example
```python
import fitz  # PyMuPDF
import numpy as np
import pandas as pd
import re
from rapidocr_onnxruntime import RapidOCR
from rapid_table import RapidTable

def html_table_to_df(html_str: str) -> pd.DataFrame:
    """Converts HTML table into pandas DataFrame without lxml/bs4 dependencies."""
    rows = re.findall(r"<tr>(.*?)</tr>", html_str, re.DOTALL | re.IGNORECASE)
    table_data = []
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        table_data.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])
    if not table_data:
        return pd.DataFrame()
    return pd.DataFrame(table_data[1:], columns=table_data[0])

def parse_pdf_page_ocr(pdf_path: str, page_num: int = 0) -> pd.DataFrame:
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pix = page.get_pixmap(dpi=300)
    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    if pix.n == 4:
        img_np = img_np[:, :, :3]

    ocr = RapidOCR()
    ocr_result, _ = ocr(img_np)
    if not ocr_result:
        return pd.DataFrame()

    table_engine = RapidTable()
    dt_boxes = np.array([x[0] for x in ocr_result])
    rec_res = [x[1] for x in ocr_result]
    scores = [float(x[2]) for x in ocr_result]
    batch_ocr = [(dt_boxes, rec_res, scores)]

    table_out = table_engine(img_np, ocr_results=batch_ocr)
    if not table_out.pred_htmls:
        return pd.DataFrame()

    return html_table_to_df(table_out.pred_htmls[0])
```

---

## 2. Existing Test Suite Analysis (`tests/`)

The test suite contains 120 tests across 5 primary test files:
- `tests/test_challenger_m1_bridge.py` (10 adversarial concurrency/queue stress tests)
- `tests/test_e2e_procurement.py` (11 end-to-end integration & pairwise tests)
- `tests/test_gui.py` (48 headless CustomTkinter GUI tests across Tiers 1-5)
- `tests/test_m1_challenger.py` (22 boundary, stress, and file format tests)
- `tests/test_pipeline.py` (29 pipeline heuristics, normalization, and allocation tests)

### Test Run Results
- **Passed**: 110 tests
- **Failed**: 10 tests
- **Execution Time**: 196 seconds (full suite)

### Root Causes for the 10 Failures:
1. **Pandas 3.0 Uppercase Extension Incompatibility** (`test_classify_case_insensitive_extensions`):
   Pandas 3.0.5 on Python 3.14 extracts the extension without lowering (`ext = 'XLSX'`), failing `_default_writers[ext]` with `KeyError: 'XLSX'`. Fix for test: pass `engine='openpyxl'` to `to_excel()`.
2. **Missing `ctk` Import in `test_gui.py`** (`test_c2_error_queue_real_dialog_rendering`):
   Line 1119 uses `ctk.CTkToplevel` where `customtkinter` was imported without `ctk` alias.
3. **Queue Ingestion Order in Challenger Test** (`test_09_custom_injected_queue`):
   Test asserts `msg[0] == "ERROR"` on the first message retrieved from the queue, but `run_procurement_pipeline` posts an initial `PROGRESS` message before validation errors.
4. **E2E Pairwise Allocations**:
   Minor tie-breaking and supplier count discrepancies against synthetic catalog test fixtures.

---

## 3. Headless Self-Test Mechanism (`app_gui.py --self-test`)

### How it Works:
- Entry point in `app_gui.py`:
  ```python
  def run_headless_self_test(existing_app: Optional[PharmaProcurementApp] = None) -> int:
      app = existing_app if existing_app is not None else PharmaProcurementApp()
      app.withdraw()
      app.update_idletasks()
      # Component assertions...
      return 0
  ```
- Uses `app.withdraw()` so no GUI window flashes on screen.
- Verifies:
  - `app.file_model` initialized
  - `app.run_button`, `app.progress_bar`, `app.status_label`, `app.kpi_frame`, `app.counter_badge` are present
  - Initial file list length is 0
  - Run button is initially disabled
  - Theme switching (`Dark`, `Light`, `System`) does not crash
- Closes and destroys instance cleanly with `app.destroy()`.

### Ensuring Self-Test Passes with M1 OCR Additions:
1. **Lazy Engine Loading**: `RapidOCR` and `RapidTable` neural network models should NOT be instantiated during GUI startup / `__init__`. They should be lazily initialized on first OCR re-read or in the background worker thread. This prevents `--self-test` from hanging or loading ONNX weights unnecessarily.
2. **Badge & Button Preservation**: When adding the medication count badges and "Re-read with OCR" buttons to catalog file cards, ensure initial state (0 items loaded) maintains the existing widget tree invariants.

---

## 4. Test Strategy for M1

### Unit Tests to Add for M1:
Create a dedicated fast test file: `tests/test_pdf_parser_ocr.py` (and GUI bridge tests in `tests/test_gui_ocr.py`):

1. **OCR Handshake Unit Test** (`test_rapid_ocr_table_handshake`):
   - Mocks `RapidOCR` output with known dummy boxes, strings, and confidence scores.
   - Converts to `batch_ocr = [(boxes, texts, scores)]` and passes to `RapidTable`.
   - Asserts HTML generation and column mapping without runtime exceptions.
2. **HTML Table to DataFrame Unit Test** (`test_html_table_to_df`):
   - Tests varied HTML tables (including Arabic headers `اسم الصنف`, `سعر الجمهور`, `الخصم`, missing columns, malformed tags, extra spaces).
   - Fast execution (sub-millisecond).
3. **Column Mapping & Normalization Unit Test** (`test_ocr_dataframe_column_mapping`):
   - Verifies that extracted table columns are accurately mapped to the procurement pipeline contract: `name`, `price`, `discount_rate`, `vendor`.
4. **PyMuPDF 300 DPI Rasterization Test** (`test_fitz_rasterization`):
   - Opens a 1-page sample PDF, renders at 300 DPI, verifies RGB shape and non-empty pixel array.
5. **GUI Medication Count Update Unit Test** (`test_gui_catalog_count_display`):
   - Headless test adding a catalog file to `FileListModel`.
   - Simulates OCR completion event updating the file item count (e.g. `file_item.medication_count = 205`).
   - Asserts the count badge widget displays `"205 صنف"`.
6. **Mocking & Fast Fixtures**:
   - To keep test execution under 2 seconds, tests must use `unittest.mock.patch` for `RapidOCR` and `RapidTable` during CI/regression suites, with one optional integration test marked `@pytest.mark.integration` for live model inference.

---

## 5. Preliminary Check on PyInstaller and Inno Setup Environment (M2 & M3)

| Component | Status | Path / Version | Notes |
|---|---|---|---|
| **Python** | Ready | Python 3.14.3 (64-bit AMD64) | `C:\Users\omart\AppData\Local\Python\pythoncore-3.14-64\python.exe` |
| **PyInstaller** | Ready | Version 6.22.2 | Use `python -m PyInstaller` (scripts folder not on PATH) |
| **Inno Setup (ISCC)** | Ready | Version 6.x | `C:\Users\omart\AppData\Local\Programs\Inno Setup 6\ISCC.EXE` (verified on PATH) |
| **Git** | Ready | Version 2.55.0.windows.5 | `C:\Users\omart\AppData\Local\Programs\Git\cmd\git.EXE`, branch `main`, remote `git@github.com:omarEldestawi/Inventory-search.git` |
| **CustomTkinter Assets** | Ready | Version 6.0.0 | Requires `--collect-all customtkinter` in PyInstaller spec |
| **RapidOCR Assets** | Ready | Version 1.2.3 | Requires bundling `rapidocr_onnxruntime/models/*.onnx` |
| **RapidTable Assets** | Ready | Version 3.0.2 | Requires bundling `slanet-plus.onnx` and `tqdm` dependency |

---
*Report prepared by Explorer 3 (Dependency & Verification Explorer).*
