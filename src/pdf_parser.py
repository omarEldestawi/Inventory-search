# -*- coding: utf-8 -*-
"""
High-performance PyMuPDF Catalog Parser with Multi-Column, Multi-Table, and Whitespace-Layout support.
Extracts items from Arabic PDF pharmaceutical catalogs in seconds.
"""
import os
import sys
import re
import logging
import unicodedata
from typing import Optional, List, Dict, Any, Tuple, Union
import pymupdf
import pandas as pd
import numpy as np

try:
    from .normalizer import (
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        unreverse_arabic_text,
        normalize_vendor_name,
        fix_arwasoft_arabic_numbers,
        decode_greek_arwasoft,
        EASTERN_ARABIC_DIGITS
    )
except ImportError:
    from normalizer import (
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        unreverse_arabic_text,
        normalize_vendor_name,
        fix_arwasoft_arabic_numbers,
        decode_greek_arwasoft,
        EASTERN_ARABIC_DIGITS
    )

logger = logging.getLogger("PDFCatalogParser")

_ocr_engine = None
_table_engine = None


def find_rapid_table_model() -> Optional[str]:
    """
    Locates the slanet-plus.onnx / table recognition model for RapidTable across
    frozen PyInstaller bundles (sys._MEIPASS), local models directories, and site-packages.
    """
    env_path = os.environ.get("RAPID_TABLE_MODEL_PATH")
    if env_path and os.path.isfile(env_path):
        return os.path.normpath(os.path.abspath(env_path))

    candidates = []
    model_names = ["slanet-plus.onnx", "slanet.onnx", "table_rec.onnx", "table_structure.onnx"]

    # 1. PyInstaller _MEIPASS extraction directory (onefile or onedir)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for name in model_names:
            candidates.extend([
                os.path.join(meipass, "rapid_table", "models", name),
                os.path.join(meipass, "models", name),
                os.path.join(meipass, "rapid_table", name),
                os.path.join(meipass, name),
                os.path.join(meipass, "_internal", "rapid_table", "models", name),
                os.path.join(meipass, "_internal", "models", name),
                os.path.join(meipass, "_internal", "rapid_table", name),
                os.path.join(meipass, "_internal", name),
            ])

    # 2. Executable directory (onedir build)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        for name in model_names:
            candidates.extend([
                os.path.join(exe_dir, "_internal", "rapid_table", "models", name),
                os.path.join(exe_dir, "_internal", "models", name),
                os.path.join(exe_dir, "_internal", "rapid_table", name),
                os.path.join(exe_dir, "_internal", name),
                os.path.join(exe_dir, "models", name),
                os.path.join(exe_dir, "rapid_table", "models", name),
                os.path.join(exe_dir, "rapid_table", name),
                os.path.join(exe_dir, name),
            ])

    # 3. Project root directory models/
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in model_names:
        candidates.extend([
            os.path.join(project_root, "models", name),
            os.path.join(project_root, name),
            os.path.join(project_root, "assets", name),
            os.path.join(project_root, "src", "models", name),
        ])

    # 4. RapidTable installed package default directory
    try:
        import rapid_table
        pkg_dir = os.path.dirname(rapid_table.__file__)
        for name in model_names:
            candidates.extend([
                os.path.join(pkg_dir, "models", name),
                os.path.join(pkg_dir, name),
            ])
    except Exception:
        pass

    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.normpath(os.path.abspath(path))

    return None


def find_rapid_ocr_assets() -> Tuple[Optional[str], Dict[str, Optional[str]]]:
    """
    Locates bundled config.yaml and ONNX models (det, rec, cls) for RapidOCR across
    frozen PyInstaller bundles (sys._MEIPASS), executable directories, and site-packages.
    Returns (config_path, {"det_model_path": ..., "rec_model_path": ..., "cls_model_path": ...}).
    """
    # 1. Config path search
    config_candidates = []
    env_cfg = os.environ.get("RAPID_OCR_CONFIG_PATH")
    if env_cfg:
        config_candidates.append(env_cfg)

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        config_candidates.extend([
            os.path.join(meipass, "rapidocr_onnxruntime", "config.yaml"),
            os.path.join(meipass, "config.yaml"),
            os.path.join(meipass, "models", "config.yaml"),
            os.path.join(meipass, "_internal", "rapidocr_onnxruntime", "config.yaml"),
            os.path.join(meipass, "_internal", "config.yaml"),
        ])

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        config_candidates.extend([
            os.path.join(exe_dir, "_internal", "rapidocr_onnxruntime", "config.yaml"),
            os.path.join(exe_dir, "rapidocr_onnxruntime", "config.yaml"),
            os.path.join(exe_dir, "config.yaml"),
            os.path.join(exe_dir, "models", "config.yaml"),
        ])

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_candidates.extend([
        os.path.join(project_root, "config.yaml"),
        os.path.join(project_root, "models", "config.yaml"),
        os.path.join(project_root, "assets", "config.yaml"),
    ])

    try:
        import rapidocr_onnxruntime
        pkg_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
        config_candidates.extend([
            os.path.join(pkg_dir, "config.yaml"),
            os.path.join(pkg_dir, "models", "config.yaml"),
        ])
    except Exception:
        pass

    resolved_config = None
    for cp in config_candidates:
        if cp and os.path.isfile(cp):
            resolved_config = os.path.normpath(os.path.abspath(cp))
            break

    # 2. Model paths search
    model_keys = {
        "det_model_path": [
            "ch_PP-OCRv4_det_infer.onnx",
            "ch_PP-OCRv3_det_infer.onnx",
            "det.onnx",
            "ch_ppocr_server_v2.0_det_infer.onnx",
        ],
        "rec_model_path": [
            "ch_PP-OCRv4_rec_infer.onnx",
            "ch_PP-OCRv3_rec_infer.onnx",
            "rec.onnx",
            "ch_ppocr_server_v2.0_rec_infer.onnx",
        ],
        "cls_model_path": [
            "ch_ppocr_mobile_v2.0_cls_infer.onnx",
            "cls.onnx",
        ],
    }

    env_keys = {
        "det_model_path": "RAPID_OCR_DET_MODEL_PATH",
        "rec_model_path": "RAPID_OCR_REC_MODEL_PATH",
        "cls_model_path": "RAPID_OCR_CLS_MODEL_PATH",
    }

    search_dirs = []
    if meipass:
        search_dirs.extend([
            meipass,
            os.path.join(meipass, "rapidocr_onnxruntime"),
            os.path.join(meipass, "rapidocr_onnxruntime", "models"),
            os.path.join(meipass, "models"),
            os.path.join(meipass, "_internal"),
            os.path.join(meipass, "_internal", "rapidocr_onnxruntime"),
            os.path.join(meipass, "_internal", "rapidocr_onnxruntime", "models"),
            os.path.join(meipass, "_internal", "models"),
        ])
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        search_dirs.extend([
            exe_dir,
            os.path.join(exe_dir, "_internal"),
            os.path.join(exe_dir, "_internal", "rapidocr_onnxruntime"),
            os.path.join(exe_dir, "_internal", "rapidocr_onnxruntime", "models"),
            os.path.join(exe_dir, "_internal", "models"),
            os.path.join(exe_dir, "rapidocr_onnxruntime"),
            os.path.join(exe_dir, "models"),
        ])
    search_dirs.extend([
        project_root,
        os.path.join(project_root, "models"),
        os.path.join(project_root, "assets"),
    ])
    try:
        import rapidocr_onnxruntime
        pkg_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
        search_dirs.extend([
            pkg_dir,
            os.path.join(pkg_dir, "models"),
        ])
    except Exception:
        pass

    resolved_models = {}
    for param_name, filenames in model_keys.items():
        env_var = env_keys.get(param_name)
        if env_var and os.environ.get(env_var) and os.path.isfile(os.environ[env_var]):
            resolved_models[param_name] = os.path.normpath(os.path.abspath(os.environ[env_var]))
            continue

        found_path = None
        for sdir in search_dirs:
            for fname in filenames:
                candidate = os.path.join(sdir, fname)
                if os.path.isfile(candidate):
                    found_path = os.path.normpath(os.path.abspath(candidate))
                    break
            if found_path:
                break
        if found_path:
            resolved_models[param_name] = found_path

    return resolved_config, resolved_models


def get_ocr_engine():
    """Lazy singleton initializer for RapidOCR with frozen asset discovery and graceful degradation."""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as imp_err:
            logger.warning(
                f"RapidOCR or ONNX runtime dependency is missing ({imp_err}). "
                f"Optical character recognition is unavailable; falling back gracefully to digital text extraction."
            )
            return None
        except Exception as imp_exc:
            logger.warning(
                f"Failed to import RapidOCR ({imp_exc}). Falling back gracefully to digital text extraction."
            )
            return None

        try:
            config_path, model_paths = find_rapid_ocr_assets()
            ocr_kwargs = {}
            if config_path and os.path.isfile(config_path):
                logger.info(f"RapidOCR using config: {config_path}")
                ocr_kwargs["config_path"] = config_path
            for param_name, model_path in model_paths.items():
                if model_path and os.path.isfile(model_path):
                    logger.info(f"RapidOCR using {param_name}: {model_path}")
                    ocr_kwargs[param_name] = model_path

            try:
                _ocr_engine = RapidOCR(**ocr_kwargs) if ocr_kwargs else RapidOCR()
            except Exception as init_exc:
                if ocr_kwargs:
                    logger.warning(
                        f"RapidOCR initialization with discovered assets failed ({init_exc}). "
                        f"Retrying with default configuration..."
                    )
                    _ocr_engine = RapidOCR()
                else:
                    raise init_exc
        except Exception as exc:
            logger.warning(
                f"RapidOCR engine initialization failed: {exc}. "
                f"Model weights may be missing or corrupted; falling back gracefully to digital text extraction."
            )
            return None

    return _ocr_engine


def get_table_engine():
    """Lazy singleton initializer for RapidTable with frozen asset discovery and graceful degradation."""
    global _table_engine
    if _table_engine is None:
        try:
            from rapid_table import RapidTable, RapidTableInput
        except ImportError as imp_err:
            logger.warning(
                f"RapidTable dependency is missing ({imp_err}). "
                f"Table structure recognition is unavailable; falling back to line clustering."
            )
            return None
        except Exception as imp_exc:
            logger.warning(
                f"Failed to import RapidTable ({imp_exc}). Falling back to line clustering."
            )
            return None

        try:
            model_path = find_rapid_table_model()
            if model_path and os.path.isfile(model_path):
                logger.info(f"RapidTable using ONNX model at: {model_path}")
                try:
                    cfg = RapidTableInput(model_dir_or_path=model_path)
                    _table_engine = RapidTable(cfg=cfg)
                except Exception as cfg_exc:
                    logger.warning(
                        f"RapidTable failed with custom model ({cfg_exc}). "
                        f"Retrying with default configuration..."
                    )
                    _table_engine = RapidTable()
            else:
                _table_engine = RapidTable()
        except Exception as exc:
            logger.warning(
                f"RapidTable engine initialization failed: {exc}. "
                f"Table model weights may be missing or corrupted; falling back to line clustering."
            )
            return None

    return _table_engine


def html_table_to_rows(html_str: str) -> list[list[str]]:
    """Converts HTML table string to 2D list of cells (zero external dependencies, no lxml required)."""
    if not html_str or not isinstance(html_str, str):
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_str, re.DOTALL | re.IGNORECASE)
    table_data = []
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        clean_cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if any(clean_cells):
            table_data.append(clean_cells)
    return table_data


def html_table_to_df(html_str: str) -> pd.DataFrame:
    """Converts HTML table string to DataFrame without lxml dependency."""
    table_data = html_table_to_rows(html_str)
    if not table_data:
        return pd.DataFrame()
    header = table_data[0]
    clean_cols = []
    seen = {}
    for i, col in enumerate(header):
        name = col.strip() if col and col.strip() else f"col_{i}"
        if name in seen:
            seen[name] += 1
            clean_cols.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            clean_cols.append(name)
    data = table_data[1:]
    fixed_data = []
    num_cols = len(clean_cols)
    for r in data:
        if len(r) < num_cols:
            r = r + [''] * (num_cols - len(r))
        elif len(r) > num_cols:
            r = r[:num_cols]
        fixed_data.append(r)
    return pd.DataFrame(fixed_data, columns=clean_cols)


def fix_arabic_bidi_if_needed(text: str) -> str:
    """Detects reversed Arabic characters and returns normalized natural text."""
    if not text or not isinstance(text, str):
        return ""
    return unreverse_arabic_text(text).strip()

class PDFCatalogParser:
    def __init__(self, pdf_path: str, warehouse_name: str = None):
        self.pdf_path = pdf_path
        raw_name = warehouse_name or os.path.splitext(os.path.basename(pdf_path))[0]
        self.warehouse_name = normalize_vendor_name(raw_name)
        self.last_error: Optional[str] = None
        
    def parse(self) -> pd.DataFrame:
        """Extract catalog items from PDF into a structured DataFrame."""
        items = []
        self.last_error = None
        try:
            doc = pymupdf.open(self.pdf_path)
            
            # Check if this catalog uses whitespace block layout (e.g. Mega Farm)
            is_block_layout = 'ميجا' in self.warehouse_name or 'ميجـا' in self.warehouse_name
            is_cure = 'كيور' in self.warehouse_name
            is_makramy = 'المكرومي' in self.warehouse_name
            
            if is_block_layout:
                for page in doc:
                    block_items = self._process_page_blocks(page)
                    items.extend(block_items)
            else:
                for page_idx, page in enumerate(doc):
                    tables = page.find_tables()
                    page_items = []
                    if tables and len(tables.tables) > 0:
                        for table in tables:
                            table_data = table.extract()
                            if table_data and len(table_data) > 1:
                                parsed_items = self._process_table(table_data)
                                page_items.extend(parsed_items)
                    
                    # Fallback to block extraction if table extractor returned very few items on this page
                    if len(page_items) < 2 and not is_cure and not is_makramy:
                        block_items = self._process_page_blocks(page)
                        page_items.extend(block_items)
                        
                    # Multi-column accounting layout recovery (ArwaSoft PDFs)
                    if is_cure:
                        right_items = self._extract_cure_right_column(page)
                        page_items.extend(right_items)
                    elif is_makramy:
                        extra_cols = self._extract_makramy_columns(page)
                        page_items.extend(extra_cols)
                    elif tables and len(tables.tables) == 1:
                        t0 = tables.tables[0]
                        if t0.bbox[2] < page.rect.width * 0.55:
                            extra_cols = self._extract_makramy_columns(page)
                            page_items.extend(extra_cols)
                        
                    items.extend(page_items)
        except Exception as e:
            self.last_error = f"Corrupted or invalid PDF file ({os.path.basename(self.pdf_path)}): {e}"
            logger.warning(f"Error parsing PDF {self.warehouse_name}: {e}")

        # Fallback for scanned PDFs: if digital extraction returned 0 items, attempt OCR fallback
        if not items and self.last_error is None:
            logger.info(
                f"Digital extraction found 0 items for {self.warehouse_name} ({os.path.basename(self.pdf_path)}). "
                f"Attempting OCR fallback for scanned PDF..."
            )
            try:
                ocr_df = self.parse_ocr()
                if not ocr_df.empty:
                    return ocr_df
            except Exception as ocr_err:
                logger.warning(f"OCR fallback failed for scanned catalog {self.warehouse_name}: {ocr_err}")

        if not items:
            return pd.DataFrame(columns=[
                'warehouse_name', 'item_name', 'normalized_name', 'dosage',
                'unit_size', 'base_price', 'discount_rate', 'stock_status'
            ])
            
        df = pd.DataFrame(items)
        # Deduplicate & pick highest discount for same product in this warehouse
        df = df.sort_values(by='discount_rate', ascending=False).drop_duplicates(
            subset=['normalized_name', 'dosage', 'unit_size'], keep='first'
        )
        return df

    def _process_table(self, table: list) -> list:
        """Parse raw 2D list table into catalog items, supporting split side-by-side tables."""
        if not table or len(table) < 2:
            return []
            
        results = []
        headers = [str(col).strip() if col else '' for col in table[0]]
        
        # Filter rows to non-empty cells
        filtered_rows = [[str(c).strip() for c in r if c is not None and str(c).strip() != ''] for r in table]
        if not filtered_rows:
            return []

        # 1. Pattern: 6-element dual-item rows (e.g. Al-Fares, Al-Awael, New Active)
        rows_6 = [r for r in filtered_rows if len(r) == 6]
        if len(rows_6) >= 2 and (len(rows_6) / len(filtered_rows)) >= 0.4:
            for r in filtered_rows:
                if len(r) == 6:
                    for triplet in (r[0:3], r[3:6]):
                        c0, c1, c2 = triplet[0], triplet[1], triplet[2]
                        if any(h in c0 or h in c2 for h in ['سعر', 'رعس', 'خصم', 'مصخ', 'صنف', 'فنص', 'البيان', 'مسا', 'اسم', 'ممم', 'رلن']):
                            continue
                        # Determine which cell is price vs name
                        is_c0_num = bool(re.search(r'^\d+(?:\.\d+)?$', c0.translate(EASTERN_ARABIC_DIGITS)))
                        is_c2_num = bool(re.search(r'^\d+(?:\.\d+)?$', c2.translate(EASTERN_ARABIC_DIGITS)))
                        if is_c0_num and not is_c2_num:
                            p_val = self._parse_price(c0)
                            d_val = parse_discount(c1)
                            raw_name = c2
                        elif is_c2_num and not is_c0_num:
                            p_val = self._parse_price(c2)
                            d_val = parse_discount(c1)
                            raw_name = c0
                        else:
                            text_in_c0 = len(re.findall(r'[a-zA-Z\u0600-\u06ff\u0380-\u03ff]', c0))
                            text_in_c2 = len(re.findall(r'[a-zA-Z\u0600-\u06ff\u0380-\u03ff]', c2))
                            if text_in_c2 >= text_in_c0:
                                p_val = self._parse_price(c0)
                                d_val = parse_discount(c1)
                                raw_name = c2
                            else:
                                p_val = self._parse_price(c2)
                                d_val = parse_discount(c1)
                                raw_name = c0

                        if d_val > 0 and p_val > 0:
                            raw_name = decode_greek_arwasoft(raw_name)
                            item_name = fix_arabic_bidi_if_needed(raw_name)
                            norm_name = normalize_arabic_text(item_name)
                            dosage, unit_size = parse_dosage_and_pack(item_name)
                            if len(norm_name) >= 2:
                                results.append({
                                    'warehouse_name': self.warehouse_name,
                                    'item_name': item_name,
                                    'normalized_name': norm_name,
                                    'dosage': dosage,
                                    'unit_size': unit_size,
                                    'base_price': p_val,
                                    'discount_rate': d_val,
                                    'stock_status': True
                                })
            if results:
                return results

        # 2. Pattern: 4-element rows with item code (e.g. Special Pharma: [Discount, Name, Code, Price])
        rows_4 = [r for r in filtered_rows if len(r) == 4]
        if len(rows_4) >= 2 and (len(rows_4) / len(filtered_rows)) >= 0.4:
            for r in filtered_rows:
                if len(r) == 4:
                    if any(h in r[0] for h in ['مصخ', 'خصم', 'Disc']) or any(h in r[1] for h in ['صنف', 'اسم', 'Name']):
                        continue
                    d_val = parse_discount(r[0])
                    raw_name = r[1]
                    v2 = self._parse_price(r[2])
                    v3 = self._parse_price(r[3])
                    # If v2 is 6-digit code (>= 10,000) and v3 is reasonable price (< 10,000):
                    if v2 >= 10000 and 0 < v3 < 10000:
                        p_val = v3
                    elif v3 >= 10000 and 0 < v2 < 10000:
                        p_val = v2
                    else:
                        p_val = v3 if v3 > 0 else v2
                    
                    if d_val > 0 and p_val > 0:
                        raw_name = decode_greek_arwasoft(raw_name)
                        item_name = fix_arabic_bidi_if_needed(raw_name)
                        norm_name = normalize_arabic_text(item_name)
                        dosage, unit_size = parse_dosage_and_pack(item_name)
                        if len(norm_name) >= 2:
                            results.append({
                                'warehouse_name': self.warehouse_name,
                                'item_name': item_name,
                                'normalized_name': norm_name,
                                'dosage': dosage,
                                'unit_size': unit_size,
                                'base_price': p_val,
                                'discount_rate': d_val,
                                'stock_status': True
                            })
            if results:
                return results

        # Check if table has multiple side-by-side table blocks
        sub_tables = []
        num_cols = len(headers)
        if num_cols >= 6 and num_cols % 3 == 0:
            for start_c in range(0, num_cols, 3):
                sub_t = [[row[c] if c < len(row) else '' for c in range(start_c, start_c + 3)] for row in table]
                sub_tables.append(sub_t)
        elif num_cols >= 8 and num_cols % 4 == 0:
            for start_c in range(0, num_cols, 4):
                sub_t = [[row[c] if c < len(row) else '' for c in range(start_c, start_c + 4)] for row in table]
                sub_tables.append(sub_t)
        else:
            sub_tables.append(table)

        for sub_t in sub_tables:
            if not sub_t or len(sub_t) < 2:
                continue
            sub_headers = [str(col).strip() if col else '' for col in sub_t[0]]
            name_idx, price_idx, discount_idx, stock_idx = self._find_column_indices(sub_headers, sub_t[1:])
            
            for row in sub_t[1:]:
                if not row or all(not cell for cell in row):
                    continue

                # Case A: Row has merged single string with multiple columns
                non_empty_cells = [str(c).strip() for c in row if c and str(c).strip()]
                if len(non_empty_cells) == 1 and (' ' in non_empty_cells[0]):
                    cell_text = non_empty_cells[0].translate(EASTERN_ARABIC_DIGITS)
                    parts = cell_text.split()
                    if len(parts) >= 3:
                        m0 = re.match(r'^\d+(?:\.\d+)?$', parts[0])
                        m1 = re.match(r'^\d+(?:\.\d+)?$', parts[1])
                        if m0 and m1:
                            discount_val = parse_discount(parts[0])
                            price_val = float(parts[1])
                            raw_name = ' '.join(parts[2:])
                            item_name = fix_arabic_bidi_if_needed(raw_name)
                            norm_name = normalize_arabic_text(item_name)
                            dosage, unit_size = parse_dosage_and_pack(item_name)
                            if len(norm_name) >= 2:
                                results.append({
                                    'warehouse_name': self.warehouse_name,
                                    'item_name': item_name,
                                    'normalized_name': norm_name,
                                    'dosage': dosage,
                                    'unit_size': unit_size,
                                    'base_price': price_val,
                                    'discount_rate': discount_val,
                                    'stock_status': True
                                })
                            continue

                # Case B: Standard column row
                raw_name = str(row[name_idx]).strip() if name_idx is not None and name_idx < len(row) and row[name_idx] else ''
                if not raw_name or raw_name.isdigit() or len(raw_name) < 2:
                    continue
                    
                if any(h in raw_name for h in ['اسم الصنف', 'الصنف', 'Item Name', 'Product', 'البيان', 'فنصلا', 'مسإ', 'مساف']):
                    continue
                    
                raw_discount = row[discount_idx] if discount_idx is not None and discount_idx < len(row) else 0.0
                discount_val = parse_discount(raw_discount)
                
                raw_price = row[price_idx] if price_idx is not None and price_idx < len(row) else None
                price_val = self._parse_price(raw_price)

                # Recover glued price/discount if either was merged or missed
                if discount_val <= 0.0 or price_val <= 0.0:
                    for c_idx, cell in enumerate(row):
                        if c_idx == name_idx or not cell:
                            continue
                        c_str = str(cell).strip().translate(EASTERN_ARABIC_DIGITS)
                        m_both = re.search(r'(\d+(?:\.\d+)?)\s*%\s*(\d+(?:\.\d+)?)', c_str)
                        if m_both:
                            if discount_val <= 0.0:
                                discount_val = parse_discount(m_both.group(1))
                            if price_val <= 0.0:
                                price_val = float(m_both.group(2))
                            break
                        m_both2 = re.search(r'(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*%', c_str)
                        if m_both2:
                            if price_val <= 0.0:
                                price_val = float(m_both2.group(1))
                            if discount_val <= 0.0:
                                discount_val = parse_discount(m_both2.group(2))
                            break
                        m_both3 = re.search(r'(\d+(?:\.\d+)?)\s*%\s*$', c_str)
                        if m_both3 and discount_val <= 0.0:
                            discount_val = parse_discount(m_both3.group(1))

                
                stock_status = True
                if stock_idx is not None and stock_idx < len(row) and row[stock_idx]:
                    stock_text = str(row[stock_idx]).strip().lower()
                    if any(kw in stock_text for kw in ['غير متوفر', 'نفذ', 'out', '0', 'لا يوجد']):
                        stock_status = False
                        
                item_name = fix_arabic_bidi_if_needed(raw_name)
                norm_name = normalize_arabic_text(item_name)
                dosage, unit_size = parse_dosage_and_pack(item_name)
                
                if len(norm_name) >= 2 and discount_val > 0:
                    results.append({
                        'warehouse_name': self.warehouse_name,
                        'item_name': item_name,
                        'normalized_name': norm_name,
                        'dosage': dosage,
                        'unit_size': unit_size,
                        'base_price': price_val,
                        'discount_rate': discount_val,
                        'stock_status': stock_status
                    })
                
        return results

    def _find_column_indices(self, headers: list, sample_rows: list = None):
        name_idx = None
        price_idx = None
        discount_idx = None
        stock_idx = None
        
        name_keywords = ['اسم', 'صنف', 'البيان', 'دواء', 'name', 'item', 'product', 'description', 'فنصلا', 'مسإ', 'مساف']
        price_keywords = ['سعر', 'جمهور', 'رسمي', 'price', 'public', 'base', 'رعسلا', 'رعس', 'نلر']
        discount_keywords = ['خصم', 'نسبة', 'disc', 'discount', '%', 'مصخلا', 'مصخ', 'ةلمج', 'جملة', 'ممم']
        stock_keywords = ['رصيد', 'كمية', 'حالة', 'توفر', 'متاح', 'stock', 'qty', 'status', 'avail']
        code_keywords = ['كود', 'code', 'باركود', 'barcode', 'رمز', 'دوك', 'دوكلا']
        code_idx = None
        
        for idx, h in enumerate(headers):
            h_clean = h.lower().strip()
            if any(k in h_clean for k in code_keywords) and code_idx is None:
                code_idx = idx
            elif any(k in h_clean for k in name_keywords) and name_idx is None:
                name_idx = idx
            elif any(k in h_clean for k in discount_keywords) and discount_idx is None:
                discount_idx = idx
            elif any(k in h_clean for k in price_keywords) and price_idx is None:
                price_idx = idx
            elif any(k in h_clean for k in stock_keywords) and stock_idx is None:
                stock_idx = idx

        # Data-driven fallback if headers are missing or unreadable
        if sample_rows and (name_idx is None or discount_idx is None or price_idx is None):
            num_cols = len(sample_rows[0]) if sample_rows else len(headers)
            col_scores = [{'text_len': 0, 'has_pct': 0, 'numbers': [], 'words': 0} for _ in range(num_cols)]
            
            for row in sample_rows[:20]:
                for c_idx, cell in enumerate(row):
                    if c_idx >= num_cols or not cell:
                        continue
                    c_str = str(cell).strip()
                    col_scores[c_idx]['text_len'] += len(c_str)
                    if '%' in c_str:
                        col_scores[c_idx]['has_pct'] += 1
                    num_match = re.search(r'[-+]?\d*\.?\d+', c_str.translate(EASTERN_ARABIC_DIGITS))
                    if num_match:
                        try:
                            val = float(num_match.group())
                            col_scores[c_idx]['numbers'].append(val)
                        except ValueError:
                            pass
                    if re.search(r'[a-zA-Z\u0600-\u06FF]', c_str):
                        col_scores[c_idx]['words'] += 1

            if name_idx is None:
                name_idx = max(range(num_cols), key=lambda i: col_scores[i]['words'] * 10 + col_scores[i]['text_len'])

            if discount_idx is None:
                def discount_score(i):
                    if i == name_idx:
                        return -100
                    score = col_scores[i]['has_pct'] * 10
                    nums = col_scores[i]['numbers']
                    if nums:
                        in_range = sum(1 for n in nums if 1.0 <= n <= 75.0)
                        score += (in_range / len(nums)) * 5
                    return score
                discount_idx = max(range(num_cols), key=discount_score)

            if price_idx is None:
                def price_score(i):
                    if i in (name_idx, discount_idx):
                        return -100
                    if code_idx is not None and i == code_idx:
                        return -100
                    nums = col_scores[i]['numbers']
                    if not nums:
                        return -50
                    high_codes = sum(1 for n in nums if n >= 10000)
                    if high_codes / len(nums) > 0.4:
                        return -50
                    reasonable = sum(1 for n in nums if 2.0 <= n <= 5000.0)
                    return len(nums) + reasonable * 2
                price_idx = max(range(num_cols), key=price_score)

        # Sanity check: ensure price_idx is not an item code column with 6-digit IDs
        if price_idx is not None and sample_rows:
            price_nums = []
            for row in sample_rows[:20]:
                if price_idx < len(row) and row[price_idx]:
                    m = re.search(r'[-+]?\d*\.?\d+', str(row[price_idx]).translate(EASTERN_ARABIC_DIGITS))
                    if m:
                        try:
                            price_nums.append(float(m.group()))
                        except ValueError:
                            pass
            if price_nums and (sum(1 for n in price_nums if n >= 10000) / len(price_nums)) > 0.4:
                best_alt = None
                best_alt_score = -1
                for alt_i in range(len(sample_rows[0])):
                    if alt_i in (name_idx, discount_idx, price_idx):
                        continue
                    alt_nums = []
                    for row in sample_rows[:20]:
                        if alt_i < len(row) and row[alt_i]:
                            m = re.search(r'[-+]?\d*\.?\d+', str(row[alt_i]).translate(EASTERN_ARABIC_DIGITS))
                            if m:
                                try:
                                    alt_nums.append(float(m.group()))
                                except ValueError:
                                    pass
                    if alt_nums:
                        normal_cnt = sum(1 for n in alt_nums if 2.0 <= n <= 5000.0)
                        if normal_cnt > best_alt_score:
                            best_alt_score = normal_cnt
                            best_alt = alt_i
                if best_alt is not None and best_alt_score > 0:
                    price_idx = best_alt

        return name_idx, price_idx, discount_idx, stock_idx

    def _parse_price(self, val):
        if val is None:
            return 0.0
        val_str = str(val).strip().replace(',', '.').translate(EASTERN_ARABIC_DIGITS)
        match = re.search(r'[-+]?\d*\.?\d+', val_str)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return 0.0
        return 0.0

    def _process_page_blocks(self, page) -> list:
        """Extract lines using PyMuPDF text blocks for whitespace-layout PDFs."""
        items = []
        blocks = page.get_text("blocks")
        for b in blocks:
            text = b[4].strip()
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for full_line in lines:
                if any(k in full_line for k in ['لتجــارة', 'ميجــا', 'اسم الصنف', 'السعر', '0502384138', 'المنصـورة']):
                    continue
                
                full_line = full_line.translate(EASTERN_ARABIC_DIGITS)
                # Find price at end
                m = re.search(r'(\d+(?:\.\d+)?)\s*$', full_line)
                if m:
                    price_val = float(m.group(1))
                    prefix = full_line[:m.start()].strip()
                    # Find discount before price
                    m_disc = re.search(r'(\d+(?:\.\d+)?)\s*%?$', prefix)
                    if m_disc:
                        discount_val = parse_discount(m_disc.group(1))
                        raw_name = prefix[:m_disc.start()].strip()
                        if len(raw_name) >= 2 and discount_val > 0 and 0 < price_val < 10000:
                            raw_name = decode_greek_arwasoft(raw_name)
                            item_name = fix_arabic_bidi_if_needed(raw_name)
                            norm_name = normalize_arabic_text(item_name)
                            dosage, unit_size = parse_dosage_and_pack(item_name)
                            if len(norm_name) >= 2:
                                items.append({
                                    'warehouse_name': self.warehouse_name,
                                    'item_name': item_name,
                                    'normalized_name': norm_name,
                                    'dosage': dosage,
                                    'unit_size': unit_size,
                                    'base_price': price_val,
                                    'discount_rate': discount_val,
                                    'stock_status': True
                                })
        return items

    def _extract_cure_right_column(self, page) -> list:
        """Extracts right-column items for 2-column ArwaSoft accounting PDFs (Cure Pharma)."""
        right_rect = pymupdf.Rect(305, 80, page.rect.width - 5, 790)
        words = page.get_text("words", clip=right_rect)
        if not words:
            return []
            
        y_buckets = {}
        for w in words:
            y_val = round(w[1], 1)
            matched = None
            for b in y_buckets:
                if abs(b - y_val) <= 3.5:
                    matched = b
                    break
            if matched is None:
                matched = y_val
                y_buckets[matched] = []
            y_buckets[matched].append(w)
            
        items = []
        for y in sorted(y_buckets.keys()):
            row_words = y_buckets[y]
            sorted_by_x = sorted(row_words, key=lambda w: w[0])
            discs = [w for w in sorted_by_x if 315 <= w[0] <= 345]
            prices = [w for w in sorted_by_x if 355 <= w[0] <= 405]
            names = [w for w in sorted_by_x if w[0] >= 405]
            
            disc_val = 0.0
            price_val = 0.0
            if discs:
                disc_val = parse_discount(discs[0][4])
            if prices:
                try:
                    price_val = float(prices[0][4].translate(EASTERN_ARABIC_DIGITS))
                except ValueError:
                    m = re.search(r'[-+]?\d*\.?\d+', prices[0][4].translate(EASTERN_ARABIC_DIGITS))
                    if m:
                        price_val = float(m.group())
                        
            name_words_sorted = sorted(names, key=lambda w: w[0], reverse=True)
            raw_name = ' '.join(w[4] for w in name_words_sorted).strip()
            raw_name = unicodedata.normalize('NFKD', raw_name)
            raw_name = fix_arwasoft_arabic_numbers(raw_name)
            
            if raw_name and price_val > 0 and disc_val > 0:
                norm_name = normalize_arabic_text(raw_name)
                dosage, unit_size = parse_dosage_and_pack(raw_name)
                items.append({
                    'warehouse_name': self.warehouse_name,
                    'item_name': raw_name,
                    'normalized_name': norm_name,
                    'dosage': dosage,
                    'unit_size': unit_size,
                    'base_price': price_val,
                    'discount_rate': disc_val,
                    'stock_status': True
                })
        return items

    def _extract_makramy_columns(self, page) -> list:
        """Extracts right columns (columns 2 & 3) for 3-column ArwaSoft accounting PDFs (Makramy)."""
        blocks = page.get_text("blocks")
        items = []
        for b in blocks:
            if b[0] < 210 or b[1] < 80 or b[3] > 800:
                continue
            raw_text = b[4].strip()
            if not raw_text or any(h in raw_text for h in ['الخصم', 'السعر', 'الصنف', 'المخزن', 'أصناف', 'شركة اروى']):
                continue
                
            text = unicodedata.normalize('NFKD', raw_text)
            text = fix_arwasoft_arabic_numbers(text)
            text = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d+)', r'\1 \2', text)
            text = re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)
            text = text.translate(EASTERN_ARABIC_DIGITS)
            
            line = ' '.join(text.split()).strip()
            m = re.search(r'(\d+(?:\.\d+)?)\s*$', line)
            if not m:
                continue
            disc_val = parse_discount(m.group(1))
            prefix = line[:m.start()].strip()
            
            m_price = re.search(r'(\d+(?:\.\d+)?)\s*(?:ج|جنيه)?\s*$', prefix)
            if not m_price:
                continue
            price_val = float(m_price.group(1))
            raw_name = prefix[:m_price.start()].strip()
            raw_name = re.sub(r'\b(?:ج|جنيه|س\.ج|س\.ق|سعر|جديد|قديم)\b', ' ', raw_name)
            raw_name = re.sub(r'[\s/]+$', '', raw_name).strip()
            
            if len(raw_name) >= 2 and disc_val > 0 and price_val > 0:
                norm_name = normalize_arabic_text(raw_name)
                dosage, unit_size = parse_dosage_and_pack(raw_name)
                items.append({
                    'warehouse_name': self.warehouse_name,
                    'item_name': raw_name,
                    'normalized_name': norm_name,
                    'dosage': dosage,
                    'unit_size': unit_size,
                    'base_price': price_val,
                    'discount_rate': disc_val,
                    'stock_status': True
                })
        return items

    def _parse_line_for_item(self, line_text: str) -> dict:
        """Extracts a catalog item dict from a clustered text line containing name, price, and discount."""
        if not line_text or len(line_text) < 4:
            return None
        clean_line = line_text.translate(EASTERN_ARABIC_DIGITS).strip()
        # Case 1: Name ... Price ... Discount%
        m1 = re.search(r'(\d+(?:\.\d+)?)\s*(?:ج|جنيه|egp)?\s+(\d+(?:\.\d+)?)\s*%\s*$', clean_line, re.IGNORECASE)
        if m1:
            price_val = float(m1.group(1))
            disc_val = parse_discount(m1.group(2))
            raw_name = clean_line[:m1.start()].strip()
            if len(raw_name) >= 2 and disc_val > 0:
                item_name = fix_arabic_bidi_if_needed(raw_name)
                norm_name = normalize_arabic_text(item_name)
                dosage, unit_size = parse_dosage_and_pack(item_name)
                if len(norm_name) >= 2:
                    return {
                        'warehouse_name': self.warehouse_name,
                        'item_name': item_name,
                        'normalized_name': norm_name,
                        'dosage': dosage,
                        'unit_size': unit_size,
                        'base_price': price_val,
                        'discount_rate': disc_val,
                        'stock_status': True
                    }
        # Case 2: Name ... Discount% ... Price
        m2 = re.search(r'(\d+(?:\.\d+)?)\s*%\s+(\d+(?:\.\d+)?)\s*$', clean_line)
        if m2:
            disc_val = parse_discount(m2.group(1))
            price_val = float(m2.group(2))
            raw_name = clean_line[:m2.start()].strip()
            if len(raw_name) >= 2 and disc_val > 0:
                item_name = fix_arabic_bidi_if_needed(raw_name)
                norm_name = normalize_arabic_text(item_name)
                dosage, unit_size = parse_dosage_and_pack(item_name)
                if len(norm_name) >= 2:
                    return {
                        'warehouse_name': self.warehouse_name,
                        'item_name': item_name,
                        'normalized_name': norm_name,
                        'dosage': dosage,
                        'unit_size': unit_size,
                        'base_price': price_val,
                        'discount_rate': disc_val,
                        'stock_status': True
                    }
        # Case 3: Standard single price + discount pattern
        m3 = re.search(r'(\d+(?:\.\d+)?)\s*%\s*$', clean_line)
        if m3:
            disc_val = parse_discount(m3.group(1))
            prefix = clean_line[:m3.start()].strip()
            m_pr = re.search(r'(\d+(?:\.\d+)?)\s*$', prefix)
            if m_pr:
                price_val = float(m_pr.group(1))
                raw_name = prefix[:m_pr.start()].strip()
                if len(raw_name) >= 2 and disc_val > 0:
                    item_name = fix_arabic_bidi_if_needed(raw_name)
                    norm_name = normalize_arabic_text(item_name)
                    dosage, unit_size = parse_dosage_and_pack(item_name)
                    if len(norm_name) >= 2:
                        return {
                            'warehouse_name': self.warehouse_name,
                            'item_name': item_name,
                            'normalized_name': norm_name,
                            'dosage': dosage,
                            'unit_size': unit_size,
                            'base_price': price_val,
                            'discount_rate': disc_val,
                            'stock_status': True
                        }
        return None

    def _process_ocr_lines(self, ocr_res: list) -> list:
        """Clusters RapidOCR bounding boxes into horizontal lines and extracts catalog items."""
        if not ocr_res:
            return []

        word_items = []
        for item in ocr_res:
            if not item or len(item) < 2:
                continue
            box = item[0]
            txt = str(item[1]).strip()
            if not txt:
                continue
            box_np = np.array(box)
            y_center = float(np.mean(box_np[:, 1]))
            x_left = float(np.min(box_np[:, 0]))
            word_items.append({
                'y': y_center,
                'x': x_left,
                'text': txt
            })

        if not word_items:
            return []

        # Group words by Y proximity (threshold ~18px for 300 DPI)
        y_groups = []
        for w in sorted(word_items, key=lambda i: i['y']):
            matched_group = None
            for group in y_groups:
                if abs(group['y'] - w['y']) <= 18.0:
                    matched_group = group
                    break
            if matched_group:
                matched_group['words'].append(w)
                matched_group['y'] = sum(x['y'] for x in matched_group['words']) / len(matched_group['words'])
            else:
                y_groups.append({'y': w['y'], 'words': [w]})

        items = []
        for group in sorted(y_groups, key=lambda g: g['y']):
            sorted_words = sorted(group['words'], key=lambda w: w['x'])
            line_str = ' '.join(w['text'] for w in sorted_words)
            parsed_item = self._parse_line_for_item(line_str)
            if parsed_item:
                items.append(parsed_item)

        return items

    def parse_ocr(self, progress_callback=None) -> pd.DataFrame:
        """
        Extracts catalog items from PDF using RapidOCR (ONNX CPU) and RapidTable.
        Uses 300 DPI PyMuPDF rasterization with a 3-tier degradation waterfall:
          Tier 1: RapidTable HTML table reconstruction.
          Tier 2: RapidOCR vertical line clustering.
          Tier 3: PyMuPDF digital vector text block extraction.
        """
        items = []
        self.last_error = None
        try:
            try:
                doc = pymupdf.open(self.pdf_path)
            except Exception as pdf_err:
                self.last_error = f"Corrupted or invalid PDF file ({os.path.basename(self.pdf_path)}): {pdf_err}"
                logger.warning(f"Failed to open PDF for OCR ({self.pdf_path}): {pdf_err}")
                return pd.DataFrame(columns=[
                    'warehouse_name', 'item_name', 'normalized_name', 'dosage',
                    'unit_size', 'base_price', 'discount_rate', 'stock_status'
                ])

            num_pages = len(doc)
            if num_pages == 0:
                self.last_error = f"PDF file contains 0 pages ({os.path.basename(self.pdf_path)})"
                return pd.DataFrame(columns=[
                    'warehouse_name', 'item_name', 'normalized_name', 'dosage',
                    'unit_size', 'base_price', 'discount_rate', 'stock_status'
                ])

            ocr_engine = None
            table_engine = None
            try:
                ocr_engine = get_ocr_engine()
            except Exception as ocr_init_err:
                self.last_error = f"RapidOCR engine unavailable: {ocr_init_err}"
                logger.warning(f"RapidOCR engine initialization failed: {ocr_init_err}")
                ocr_engine = None

            if ocr_engine is not None:
                try:
                    table_engine = get_table_engine()
                except Exception as tbl_init_err:
                    logger.warning(f"RapidTable unavailable ({tbl_init_err}); falling back to RapidOCR line clustering.")
                    table_engine = None
            else:
                if not self.last_error:
                    self.last_error = "RapidOCR engine unavailable; falling back to digital parsing."
                logger.info("RapidOCR engine unavailable; proceeding with digital parsing fallback.")

            for page_idx, page in enumerate(doc):
                pct = page_idx / max(num_pages, 1)
                if progress_callback:
                    try:
                        progress_callback(pct, f"مسح صفحة ({page_idx + 1}/{num_pages}) بـ OCR...")
                    except Exception:
                        pass

                page_items = []
                ocr_res = None

                if ocr_engine is not None:
                    # Step 1: PyMuPDF 300 DPI rasterization directly into memory
                    try:
                        pix = page.get_pixmap(dpi=300)
                        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                        if pix.n == 4:
                            img_np = img_np[:, :, :3]
                        elif pix.n == 1:
                            img_np = np.stack([img_np.squeeze(-1)] * 3, axis=-1)
                        del pix
                    except Exception as pix_err:
                        logger.warning(f"Rasterization error on page {page_idx}: {pix_err}")
                        img_np = None

                    # Step 2: RapidOCR ONNX extraction
                    if img_np is not None:
                        try:
                            ocr_res, _ = ocr_engine(img_np)
                        except Exception as ocr_err:
                            logger.warning(f"RapidOCR error on page {page_idx}: {ocr_err}")

                        # Tier 1: RapidTable HTML Table Reconstruction
                        if table_engine is not None and ocr_res and len(ocr_res) > 0:
                            try:
                                dt_boxes = np.array([x[0] for x in ocr_res])
                                rec_res = [str(x[1]) for x in ocr_res]
                                scores = [float(x[2]) for x in ocr_res]
                                batch_ocr = [(dt_boxes, rec_res, scores)]

                                table_out = table_engine(img_np, ocr_results=batch_ocr)
                                html_str = ""
                                if hasattr(table_out, "pred_htmls") and table_out.pred_htmls:
                                    html_str = table_out.pred_htmls[0]
                                elif hasattr(table_out, "pred_html") and table_out.pred_html:
                                    html_str = table_out.pred_html
                                elif isinstance(table_out, str):
                                    html_str = table_out

                                if html_str:
                                    table_rows = html_table_to_rows(html_str)
                                    if table_rows and len(table_rows) > 1:
                                        page_items = self._process_table(table_rows)
                            except Exception as tbl_err:
                                logger.debug(f"RapidTable error on page {page_idx}: {tbl_err}")

                        # Tier 2 Fallback: RapidOCR Line Clustering
                        if not page_items and ocr_res and len(ocr_res) > 0:
                            try:
                                page_items = self._process_ocr_lines(ocr_res)
                            except Exception as line_err:
                                logger.debug(f"OCR line clustering error on page {page_idx}: {line_err}")

                # Tier 3 Fallback: PyMuPDF Digital Parsing
                if not page_items:
                    try:
                        tables = page.find_tables()
                        if tables and len(tables.tables) > 0:
                            for t in tables:
                                t_data = t.extract()
                                if t_data and len(t_data) > 1:
                                    page_items.extend(self._process_table(t_data))
                        if not page_items:
                            page_items = self._process_page_blocks(page)
                    except Exception as dig_err:
                        logger.debug(f"Digital fallback error on page {page_idx}: {dig_err}")

                items.extend(page_items)

            if progress_callback:
                try:
                    progress_callback(1.0, f"اكتمل المسح بـ OCR: تم العثور على {len(items)} صنف.")
                except Exception:
                    pass

        except Exception as e:
            self.last_error = f"Error parsing PDF with OCR: {e}"
            logger.warning(f"Error parsing PDF with OCR {self.warehouse_name} ({self.pdf_path}): {e}")

        if not items:
            if not self.last_error:
                self.last_error = f"No catalog items found in PDF ({os.path.basename(self.pdf_path)})."
            return pd.DataFrame(columns=[
                'warehouse_name', 'item_name', 'normalized_name', 'dosage',
                'unit_size', 'base_price', 'discount_rate', 'stock_status'
            ])

        df = pd.DataFrame(items)
        df = df.sort_values(by='discount_rate', ascending=False).drop_duplicates(
            subset=['normalized_name', 'dosage', 'unit_size'], keep='first'
        )
        return df

    @classmethod
    def parse_catalog_ocr(cls, pdf_path: str, warehouse_name: str = None) -> list:
        """
        Public classmethod interface for Milestone 1 OCR parsing.
        Extracts items from PDF using RapidOCR and RapidTable, returning a list of dicts
        with canonical fields and compatibility aliases ('name', 'price', 'vendor', 'category').
        """
        parser = cls(pdf_path, warehouse_name=warehouse_name)
        df = parser.parse_ocr()
        records = df.to_dict(orient="records")
        for rec in records:
            rec["name"] = rec.get("item_name", "")
            rec["price"] = rec.get("base_price", 0.0)
            rec["vendor"] = rec.get("warehouse_name", "")
            rec["category"] = "Catalog"
        return records


