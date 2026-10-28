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
        is_arabic_text_reversed,
        FORWARD_PHARMA_TOKENS,
        normalize_vendor_name,
        fix_arwasoft_arabic_numbers,
        decode_greek_arwasoft,
        decode_custom_catalog_glyphs,
        AL_HADABA_FONT_MAP,
        CUSTOM_CATALOG_GLYPH_MAP,
        normalize_ocr_split_medication_names,
        EASTERN_ARABIC_DIGITS,
        is_catalog_noise
    )
except ImportError:
    from normalizer import (
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        unreverse_arabic_text,
        is_arabic_text_reversed,
        FORWARD_PHARMA_TOKENS,
        normalize_vendor_name,
        fix_arwasoft_arabic_numbers,
        decode_greek_arwasoft,
        decode_custom_catalog_glyphs,
        AL_HADABA_FONT_MAP,
        CUSTOM_CATALOG_GLYPH_MAP,
        normalize_ocr_split_medication_names,
        EASTERN_ARABIC_DIGITS,
        is_catalog_noise
    )

try:
    from .catalog_reader import (
        TableGeometry,
        ProductGroup,
        analyze_table_geometry,
        detect_product_groups,
        resolve_group_arabic_direction,
        extract_item_from_group_row,
        parse_structural_table,
        CatalogImportMetadata,
        is_genuine_header_cell,
    )
    from .catalog_diagnostics import (
        FileFingerprint,
        RowDiagnostic,
        GroupDiagnostics,
        PageDiagnostics,
        ImportDiagnostics,
        CatalogResult,
        METADATA_KEY,
    )
except ImportError:
    from catalog_reader import (
        TableGeometry,
        ProductGroup,
        analyze_table_geometry,
        detect_product_groups,
        resolve_group_arabic_direction,
        extract_item_from_group_row,
        parse_structural_table,
        CatalogImportMetadata,
        is_genuine_header_cell,
    )
    from catalog_diagnostics import (
        FileFingerprint,
        RowDiagnostic,
        GroupDiagnostics,
        PageDiagnostics,
        ImportDiagnostics,
        CatalogResult,
        METADATA_KEY,
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
    """
    [ARCHIVED / FAILED FEATURE - 2026-10-25]
    RapidOCR has been archived and disabled because its bundled Chinese/English
    PaddleOCR model (`ch_PP-OCRv4_rec_infer.onnx`) does not support Arabic script
    and always produced 0 valid Arabic items before falling back to digital parsing.
    See `archive/failed_ocr_feature/README_FAILED_OCR.md`.
    """
    logger.info(
        "OCR feature is ARCHIVED (marked as FAILED for Arabic catalogs). "
        "Using pure PyMuPDF digital vector & coordinate extraction."
    )
    return None


def get_table_engine():
    """
    [ARCHIVED / FAILED FEATURE - 2026-10-25]
    RapidTable OCR table reconstruction has been archived alongside RapidOCR.
    See `archive/failed_ocr_feature/README_FAILED_OCR.md`.
    """
    return None


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


def fix_arabic_bidi_if_needed(text: str, force_reverse: Optional[bool] = None) -> str:
    """Detects reversed Arabic characters and returns normalized natural text."""
    if not text or not isinstance(text, str):
        return ""
    return unreverse_arabic_text(text, force_reverse=force_reverse).strip()


ALL_EASTERN_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def is_explicit_zero_discount(val: Any) -> bool:
    """Checks whether a cell explicitly represents a 0% / net pricing discount."""
    if val is None:
        return False
    s = str(val).strip().lower().translate(ALL_EASTERN_DIGITS)
    if not s:
        return False
    if re.fullmatch(r'0+(?:\.0+)?\s*%?', s):
        return True
    if any(w in s for w in ['صافي', 'صافى', 'net', 'zero']):
        return True
    return False


def extract_inline_price_hint(text: str) -> Optional[float]:
    """
    Extracts an explicit official public price mention embedded inside an item name
    (e.g. 'سعر 76', 'سعر /24امون', 'سعر جديد 177', '41.5ج', 'س 81 س ج').
    Used by column-level and row-level sanity checks to prevent Price and Discount swaps.
    """
    if not text or not isinstance(text, str):
        return None
    s = text.translate(ALL_EASTERN_DIGITS).replace('٫', '.')
    non_price_unit = (
        r'(?!\s*(?:قرص|اقراص|كبسول|شريط|امبول|فيال|مل|ملل|مللي|مجم|مج|جم|جرام|'
        r'علب|باكو|كرتون|كيس|قطعه|قطعة|لتر|وحدة|iu|mg|gm|ml|%))'
    )
    # 1. Explicit 'سعر' or 'س.ج' followed by price
    m1 = re.search(rf'(?:سعر|س\.ج)\s*(?:جديد|قديم|جدديد)?\s*[/:\-]?\s*(\d+(?:\.\d+)?){non_price_unit}', s)
    if m1:
        try:
            val = float(m1.group(1))
            if 5.0 <= val < 10000.0:
                return val
        except ValueError:
            pass
    # 2. 'س 96 ج' or 'س 81 س ج'
    m2 = re.search(r'\bس\s*(\d+(?:\.\d+)?)\s*(?:ج|جنيه|س\s*ج)\b', s)
    if m2:
        try:
            val = float(m2.group(1))
            if 5.0 <= val < 10000.0:
                return val
        except ValueError:
            pass
    # 3. Number followed by 'ج' or 'جنيه' (not 'جم', 'جرام', 'جل', 'جيل', 'جديد')
    m3 = re.search(r'(?<!\d)(\d+(?:\.\d+)?)\s*(?:جنيه|جنية|ج\.م|ج)(?![\u0600-\u06ff])', s)
    if m3:
        try:
            val = float(m3.group(1))
            if 5.0 <= val < 10000.0:
                return val
        except ValueError:
            pass
    return None


class PDFCatalogParser:
    AL_HADABA_FONT_MAP = AL_HADABA_FONT_MAP
    GLYPH_TRANSLATION_MAP = AL_HADABA_FONT_MAP
    CUSTOM_CATALOG_GLYPH_MAP = CUSTOM_CATALOG_GLYPH_MAP

    @classmethod
    def translate_glyphs(cls, text: str) -> str:
        """Translates custom font glyphs (ArwaSoft Greek, Al-Hadhaba Runic/Aboriginal) to standard Arabic."""
        return decode_custom_catalog_glyphs(text)

    def __init__(self, pdf_path: Optional[str] = None, warehouse_name: Optional[str] = None):
        self.pdf_path = pdf_path
        if pdf_path:
            raw_name = warehouse_name or os.path.splitext(os.path.basename(pdf_path))[0]
            self.warehouse_name = normalize_vendor_name(raw_name)
        else:
            self.warehouse_name = normalize_vendor_name(warehouse_name) if warehouse_name else ""
        self.last_error: Optional[str] = None
        self._doc_first_num_is_price: Optional[bool] = None
        self._established_geometry: Optional[TableGeometry] = None
        self._established_groups: Optional[List[ProductGroup]] = None
        self._page_diagnostics: List[PageDiagnostics] = []
        self._import_diagnostics: Optional[ImportDiagnostics] = None

    @staticmethod
    def _extract_raw_float(val: Any) -> float:
        """Extracts raw positive float from cell/token string without clamping at 85%."""
        if val is None:
            return 0.0
        s = str(val).strip().replace(',', '.').replace('٫', '.').translate(ALL_EASTERN_DIGITS)
        m = re.search(r'[-+]?\d*\.?\d+', s)
        if not m:
            return 0.0
        try:
            v = float(m.group())
            return v if v > 0.0 else 0.0
        except ValueError:
            return 0.0

    def _detect_page_header_price_first(self, page) -> Optional[bool]:
        """
        Inspects header words at the top of a page (Y < 120, X < 300) to determine
        whether 'السعر' (Price) is positioned to the left of 'الخصم' (Discount).
        Returns True if Price is first (leftmost), False if Discount is first, or None if not found.
        """
        try:
            words = page.get_text("words")
            price_x = None
            disc_x = None
            for w in words:
                if w[1] < 120 and w[0] < 300:
                    nw = unicodedata.normalize('NFKD', str(w[4]))
                    if any(k in nw for k in ('السعر', 'رعسلا')) and price_x is None:
                        price_x = float(w[0])
                    elif any(k in nw for k in ('الخصم', 'مصخلا')) and disc_x is None:
                        disc_x = float(w[0])
            if price_x is not None and disc_x is not None and abs(price_x - disc_x) > 5.0:
                return price_x < disc_x
        except Exception:
            pass
        return None

    @staticmethod
    def _detect_table_header_price_first(rows: list) -> Optional[bool]:
        """
        Inspects merged header strings in table rows (e.g. 'رعسلا مصخلا فنصلا مسإ' vs 'مصخلا رعسلا فنصلا مسإ')
        to determine whether Price appears before Discount.
        """
        for r in rows[:4]:
            if not r:
                continue
            row_str = ' '.join(str(c).strip() for c in r if c and str(c).strip())
            if not row_str:
                continue
            norm_r = unicodedata.normalize('NFKD', row_str).lower()
            p_positions = [norm_r.find(k) for k in ('رعسلا', 'السعر', 'رعس', 'سعر', 'price') if norm_r.find(k) != -1]
            d_positions = [norm_r.find(k) for k in ('مصخلا', 'الخصم', 'مصخ', 'خصم', 'disc') if norm_r.find(k) != -1]
            if p_positions and d_positions:
                p_pos = min(p_positions)
                d_pos = min(d_positions)
                if p_pos != d_pos:
                    return p_pos < d_pos
        return None

    def _should_swap_price_and_discount(
        self,
        records: List[Tuple[float, float, str]],
        header_first_is_price: Optional[bool] = None
    ) -> bool:
        """
        Batch/Column-level sanity check that evaluates candidate (disc_raw, price_raw, item_name)
        tuples across a table or column to detect if Discount and Price positions are switched.
        Returns True if the first numeric slot (cand_disc_raw) is actually Price and the second
        numeric slot (cand_price_raw) is actually Discount.
        """
        votes_swap_bound = 0
        votes_keep_bound = 0
        votes_swap_hint = 0
        votes_keep_hint = 0

        for cand_disc, cand_price, name in records:
            if cand_disc <= 0.0 or cand_price <= 0.0:
                continue
            # Signal 1: Pharmaceutical discount upper bound (discounts never exceed 85%, prices go up to 10,000 EGP)
            if 85.0 < cand_disc < 10000.0 and 0.0 < cand_price <= 85.0:
                votes_swap_bound += 1
            elif 85.0 < cand_price < 10000.0 and 0.0 < cand_disc <= 85.0:
                votes_keep_bound += 1

            # Signal 2: Inline public price mention inside the item name (e.g. 'سعر 76', '41.5ج')
            hint = extract_inline_price_hint(name)
            if hint is not None:
                if abs(cand_disc - hint) <= 0.15 and abs(cand_price - hint) > 0.5 and 0.0 < cand_price <= 85.0:
                    votes_swap_hint += 1
                elif abs(cand_price - hint) <= 0.15 and abs(cand_disc - hint) > 0.5 and 0.0 < cand_disc <= 85.0:
                    votes_keep_hint += 1

        swap_score = votes_swap_bound * 2 + votes_swap_hint * 3
        keep_score = votes_keep_bound * 2 + votes_keep_hint * 3

        if swap_score > keep_score and swap_score >= 2:
            return True
        if keep_score > swap_score and keep_score >= 2:
            return False

        if header_first_is_price is not None:
            if swap_score > keep_score:
                return True
            if keep_score > swap_score:
                return False
            return bool(header_first_is_price)

        if swap_score > keep_score:
            return True
        if keep_score > swap_score:
            return False

        # Fallback distribution check when all values in a small table are <= 85 and no header/hints exist
        valid_pairs = [(d, p) for d, p, _ in records if 0.0 < d <= 85.0 and 0.0 < p <= 85.0]
        if len(valid_pairs) >= 3:
            d_over_50 = sum(1 for d, p in valid_pairs if d > 50.0 and 5.0 <= p <= 45.0)
            p_over_50 = sum(1 for d, p in valid_pairs if p > 50.0 and 5.0 <= d <= 45.0)
            if d_over_50 >= 2 and p_over_50 == 0 and (d_over_50 / len(valid_pairs)) >= 0.5:
                return True

        return False

    def _sanity_check_item_price_and_discount(
        self,
        item_name: str,
        price_val: float,
        discount_val: float,
        raw_price_num: float = 0.0,
        raw_disc_num: float = 0.0
    ) -> Tuple[float, float]:
        """
        Per-item row-level sanity check ensuring price_val and discount_val are not inverted.
        1. Recovers rows where raw_disc_num > 85 (up to 10,000 EGP) and price_val is in [1, 85].
        2. Verifies against any explicit inline price mention in item_name (e.g. 'سعر 79', '41.5ج').
        """
        # 1. Out-of-bounds raw discount that is actually a price (> 85 EGP)
        if (discount_val <= 0.0 or discount_val > 0.85) and 85.0 < raw_disc_num < 10000.0 and 0.0 < price_val <= 85.0:
            return raw_disc_num, round(price_val / 100.0, 4)

        # 2. Inline price hint verification
        hint = extract_inline_price_hint(item_name)
        if hint is not None and 0.0 < discount_val <= 0.85:
            disc_pct = round(discount_val * 100.0, 2)
            if abs(disc_pct - hint) <= 0.15 and abs(price_val - hint) > 0.5 and 0.0 < price_val <= 85.0:
                return disc_pct, round(price_val / 100.0, 4)

        return price_val, discount_val

    def parse(self, file_path: Optional[str] = None) -> pd.DataFrame:
        """Extract catalog items from PDF into a structured DataFrame."""
        if file_path is not None:
            self.pdf_path = file_path
            raw_name = os.path.splitext(os.path.basename(file_path))[0]
            self.warehouse_name = normalize_vendor_name(raw_name)
        if not self.pdf_path:
            raise ValueError("pdf_path must be provided either in __init__ or parse().")
        items = []
        self.last_error = None
        self._doc_first_num_is_price = None
        self._established_geometry = None
        self._established_groups = None
        self._page_diagnostics = []
        self._import_diagnostics = None
        raw_accepted_count = 0
        doc = None
        try:
            doc = pymupdf.open(self.pdf_path)

            if len(doc) > 0:
                p0_text = unicodedata.normalize('NFKD', doc[0].get_text("text")[:400])
                if 'الدولية الحديثة' in p0_text or 'الدوليه الحديثه' in p0_text:
                    if not re.search(r'[\u0600-\u06ff]', self.warehouse_name) or self.warehouse_name == 'الدولية فارما':
                        self.warehouse_name = 'مخزن الدولية الحديثة'
                elif 'زهرة فارم' in p0_text or 'زهره فارم' in p0_text:
                    if not re.search(r'[\u0600-\u06ff]', self.warehouse_name) or 'زهر' in self.warehouse_name:
                        self.warehouse_name = 'زهرة فارم'
                self._doc_first_num_is_price = self._detect_page_header_price_first(doc[0])
            
            # Check if this catalog uses whitespace block layout (e.g. Mega Farm)
            is_block_layout = 'ميجا' in self.warehouse_name or 'ميجـا' in self.warehouse_name
            is_cure = 'كيور' in self.warehouse_name
            is_makramy = 'المكرومي' in self.warehouse_name
            base_fname = os.path.basename(self.pdf_path)
            is_sina = 'سينا' in self.warehouse_name or 'سينا' in base_fname
            is_dar_fouad = 'دار الفؤاد' in self.warehouse_name or 'دار الفؤاد' in base_fname
            is_arwasoft_2col = (
                any(k in base_fname for k in ['ادم جمله', 'بيرفكت فارم', 'رواد الدوا', 'الدولية الحديثة', 'الدوليه الحديثه']) or
                any(k in self.warehouse_name for k in ['ادم', 'بيرفكت فارم', 'رواد الدواء', 'الدولية الحديثة'])
            )
            
            if is_block_layout:
                for page_idx, page in enumerate(doc):
                    block_items = self._process_page_blocks(page)
                    items.extend(block_items)
                    raw_accepted_count += len(block_items)
                    self._page_diagnostics.append(
                        PageDiagnostics(
                            page=page_idx + 1,
                            strategy="blocks",
                            accepted_rows=len(block_items),
                            groups=[GroupDiagnostics(group=0, strategy="blocks", candidate_rows=len(block_items), accepted_rows=len(block_items))]
                        )
                    )
            else:
                for page_idx, page in enumerate(doc):
                    page_items = []
                    page_hdr_order = self._detect_page_header_price_first(page)
                    if page_hdr_order is not None:
                        self._doc_first_num_is_price = page_hdr_order
                    
                    # 1. 3-Column Coordinate Whitespace Extractor (Sina Trade)
                    page_top_text = page.get_text("text")[:350]
                    if is_sina or ('سينا تريد' in page_top_text):
                        sina_items = self._extract_sina_columns(page)
                        if sina_items:
                            page_items.extend(sina_items)
                            raw_accepted_count += len(sina_items)
                    
                    if not page_items:
                        tables = page.find_tables()
                        covered_bboxes = []
                        if tables and len(tables.tables) > 0:
                            all_tables = tables.tables
                            if len(all_tables) > 1:
                                filtered_tables = []
                                for i, t1 in enumerate(all_tables):
                                    is_enclosed = False
                                    for j, t2 in enumerate(all_tables):
                                        if i != j:
                                            b1, b2 = t1.bbox, t2.bbox
                                            # If t2 geometrically encloses t1, t1 is an inner sub-table -> discard t1
                                            if b2[0] <= b1[0] + 1 and b2[1] <= b1[1] + 1 and b2[2] >= b1[2] - 1 and b2[3] >= b1[3] - 1:
                                                if abs(b1[0]-b2[0]) < 2 and abs(b1[1]-b2[1]) < 2 and abs(b1[2]-b2[2]) < 2 and abs(b1[3]-b2[3]) < 2:
                                                    if i > j:
                                                        is_enclosed = True
                                                        break
                                                else:
                                                    is_enclosed = True
                                                    break
                                    if not is_enclosed:
                                        filtered_tables.append(t1)
                            else:
                                filtered_tables = all_tables

                            # Process all detected tables on the page (structural and legacy)
                            structural_tables = set()
                            table_groups: List[GroupDiagnostics] = []
                            table_items: List[Dict[str, Any]] = []
                            table_errors: List[str] = []
                            table_expected_known = True

                            for t_idx, t in enumerate(filtered_tables):
                                if hasattr(t, "rows") and len(t.rows) >= 1:
                                    t_extract = t.extract()
                                    geom = analyze_table_geometry(t, established_layout=self._established_geometry)
                                    groups = detect_product_groups(geom, t_extract, established_groups=self._established_groups) if geom else []
                                    has_multi_groups = bool(groups and len(groups) >= 2 and any(g.is_valid for g in groups))
                                    t_num_cols = len(t_extract[0]) if (t_extract and t_extract[0]) else (len(t.rows[0].cells) if t.rows else 0)
                                    t_headers = [str(c).strip() if c is not None else "" for c in t_extract[0]] if t_extract else None
                                    sample_rows = t_extract[1:10] if (t_extract and len(t_extract) > 1) else t_extract
                                    is_layout_compat = bool(
                                        self._established_geometry and self._established_geometry.is_compatible(
                                            t_num_cols,
                                            other_headers=t_headers,
                                            other_col_bboxes=getattr(geom, 'col_bboxes', None),
                                            sample_rows=sample_rows,
                                        )
                                    )
                                    has_est_multi_groups = bool(
                                        self._established_groups and len(self._established_groups) >= 2
                                        and geom and is_layout_compat
                                    )
                                    is_single_row_structural = bool(len(t.rows) == 1 and groups and any(g.is_valid for g in groups))

                                    if has_multi_groups or has_est_multi_groups or is_single_row_structural:
                                        est_geom_to_pass = self._established_geometry if is_layout_compat else None
                                        est_groups_to_pass = self._established_groups if (est_geom_to_pass is not None) else None

                                        p_items, new_geom, new_groups, t_diag = parse_structural_table(
                                            t, page_idx, self.warehouse_name, est_geom_to_pass, est_groups_to_pass, self
                                        )

                                        if has_multi_groups or (new_groups and any(g.is_valid for g in new_groups)):
                                            self._established_geometry = new_geom
                                            self._established_groups = new_groups

                                        structural_tables.add(t)
                                        if hasattr(t, 'bbox') and t.bbox:
                                            covered_bboxes.append(t.bbox)
                                        table_items.extend(p_items)
                                        raw_accepted_count += len(p_items)

                                        # Incorporate group diagnostics with unambiguous table-indexed provenance
                                        for g_diag in t_diag.groups:
                                            grp_idx_on_page = len(table_groups)
                                            g_diag.group = grp_idx_on_page
                                            g_diag.strategy = f"structural_table_t{t_idx}"
                                            for r_diag in g_diag.rows:
                                                r_diag.group = grp_idx_on_page
                                            table_groups.append(g_diag)

                                        if not t_diag.expected_count_known:
                                            table_expected_known = False
                                        if t_diag.errors:
                                            table_errors.extend(t_diag.errors)

                            # Legacy extraction for remaining tables not handled structurally
                            remaining_tables = [t for t in filtered_tables if t not in structural_tables]
                            if remaining_tables:
                                stitched_tables = self._stitch_contiguous_tables(remaining_tables)
                                for rem_idx, table_data in enumerate(stitched_tables):
                                    if table_data and len(table_data) >= 1:
                                        t_items = self._process_table(table_data)
                                        # Skip non-product banner/footer tables that yield no items and lack product catalog indicators
                                        if not t_items and not self._is_likely_catalog_table(table_data):
                                            continue
                                        table_items.extend(t_items)
                                        raw_accepted_count += len(t_items)

                                        grp_idx_on_page = len(table_groups)
                                        legacy_accepted = len(t_items)
                                        header_offset = 1 if (len(table_data) > 1 and any(is_genuine_header_cell(c) for c in table_data[0] if c)) else 0
                                        legacy_candidates = max(legacy_accepted, len(table_data) - header_offset)
                                        legacy_rejected = max(0, legacy_candidates - legacy_accepted)

                                        rem_bbox = None
                                        if rem_idx < len(remaining_tables) and hasattr(remaining_tables[rem_idx], 'bbox'):
                                            rem_bbox = list(remaining_tables[rem_idx].bbox)

                                        legacy_grp = GroupDiagnostics(
                                            group=grp_idx_on_page,
                                            strategy=f"legacy_table_t{rem_idx}",
                                            candidate_rows=legacy_candidates,
                                            accepted_rows=legacy_accepted,
                                            rejected_rows=legacy_rejected,
                                            unprocessed_rows=0,
                                            bbox=rem_bbox,
                                        )
                                        table_groups.append(legacy_grp)

                                for t in remaining_tables:
                                    if hasattr(t, 'bbox') and t.bbox:
                                        covered_bboxes.append(t.bbox)

                            # Aggregate all table and group results into one page-level diagnostic record
                            page_items.extend(table_items)
                            if table_groups:
                                page_accepted = sum(g.accepted_rows for g in table_groups)
                                self._page_diagnostics.append(
                                    PageDiagnostics(
                                        page=page_idx + 1,
                                        strategy="structural_table" if structural_tables else "legacy_table",
                                        expected_count_known=table_expected_known,
                                        accepted_rows=page_accepted,
                                        groups=table_groups,
                                        errors=table_errors,
                                    )
                                )
                        
                        # Dynamically detect 2-column ArwaSoft pages where PyMuPDF only found the left table (Xmax <= 315)
                        is_page_arwasoft_2col = is_arwasoft_2col or (
                            not is_cure and not is_makramy and not is_sina and not is_dar_fouad and
                            tables is not None and len(tables.tables) > 0 and
                            all(t.bbox[2] <= 315 for t in tables.tables) and
                            ('اروى سوفت' in page.get_text("text") or 'أصناف المخزن' in page_top_text)
                        )

                        # Fallback for 3-column ArwaSoft row-rectangle pages (e.g. Zahra Pharm / تحديث زهره.pdf),
                        # 2-column borderless pages (e.g. Dar Al-Fouad), or block extraction when no tables found
                        if not tables or len(tables.tables) == 0:
                            fb_items = []
                            if not is_dar_fouad:
                                rect_3col_items = self._extract_arwasoft_3col_rects(page)
                                if rect_3col_items:
                                    fb_items.extend(rect_3col_items)
                            if len(fb_items) < 2 and (is_dar_fouad or (tables and len(tables.tables) == 0)):
                                fouad_items = self._extract_dar_fouad_columns(page)
                                if fouad_items:
                                    fb_items.extend(fouad_items)
                            if len(fb_items) < 2:
                                block_items = self._process_page_blocks(page)
                                fb_items.extend(block_items)
                            page_items.extend(fb_items)
                            raw_accepted_count += len(fb_items)
                            if len(self._page_diagnostics) <= page_idx:
                                self._page_diagnostics.append(
                                    PageDiagnostics(
                                        page=page_idx + 1,
                                        strategy="fallback",
                                        accepted_rows=len(fb_items),
                                        groups=[GroupDiagnostics(group=0, strategy="fallback", candidate_rows=len(fb_items), accepted_rows=len(fb_items))]
                                    )
                                )
                            
                        # Multi-column accounting layout recovery (ArwaSoft PDFs)
                        if is_cure:
                            right_items = self._extract_cure_right_column(page)
                            if right_items:
                                page_items.extend(right_items)
                                raw_accepted_count += len(right_items)
                                covered_bboxes.append((300.0, 80.0, 600.0, 790.0))
                                if len(self._page_diagnostics) > page_idx:
                                    grp_idx = len(self._page_diagnostics[page_idx].groups)
                                    self._page_diagnostics[page_idx].groups.append(
                                        GroupDiagnostics(
                                            group=grp_idx,
                                            strategy="cure_right_column",
                                            candidate_rows=len(right_items),
                                            accepted_rows=len(right_items),
                                            rejected_rows=0,
                                            unprocessed_rows=0,
                                        )
                                    )
                                    self._page_diagnostics[page_idx].accepted_rows += len(right_items)
                        elif is_page_arwasoft_2col:
                            right_items = self._extract_arwasoft_right_column(page)
                            if right_items:
                                page_items.extend(right_items)
                                raw_accepted_count += len(right_items)
                                covered_bboxes.append((315.0, 80.0, 600.0, 790.0))
                                if len(self._page_diagnostics) > page_idx:
                                    self._page_diagnostics[page_idx].groups.append(
                                        GroupDiagnostics(
                                            group=1,
                                            strategy="arwasoft_right_column",
                                            candidate_rows=len(right_items),
                                            accepted_rows=len(right_items),
                                            rejected_rows=0,
                                            unprocessed_rows=0,
                                        )
                                    )
                                    self._page_diagnostics[page_idx].accepted_rows += len(right_items)
                        elif is_makramy:
                            extra_cols = self._extract_makramy_columns(page)
                            if extra_cols:
                                page_items.extend(extra_cols)
                                raw_accepted_count += len(extra_cols)
                                covered_bboxes.append((200.0, 80.0, 600.0, 790.0))
                                if len(self._page_diagnostics) > page_idx:
                                    grp_idx = len(self._page_diagnostics[page_idx].groups)
                                    self._page_diagnostics[page_idx].groups.append(
                                        GroupDiagnostics(
                                            group=grp_idx,
                                            strategy="makramy_columns",
                                            candidate_rows=len(extra_cols),
                                            accepted_rows=len(extra_cols),
                                            rejected_rows=0,
                                            unprocessed_rows=0,
                                        )
                                    )
                                    self._page_diagnostics[page_idx].accepted_rows += len(extra_cols)

                        # Coordinate-based uncovered-region recovery (Feature F12)
                        # Replaces legacy '< 2 items' check by scanning text blocks outside table bboxes
                        if covered_bboxes and not is_cure and not is_makramy and not is_sina and not is_page_arwasoft_2col:
                            uncovered = self._find_uncovered_blocks(page, covered_bboxes)
                            if uncovered:
                                coord_items = self._extract_items_from_blocks(uncovered)
                                if coord_items:
                                    for ci in coord_items:
                                        ci['_strategy'] = "coordinate_recovery"
                                    page_items.extend(coord_items)
                                    raw_accepted_count += len(coord_items)
                                    if len(self._page_diagnostics) > page_idx:
                                        grp_idx = len(self._page_diagnostics[page_idx].groups)
                                        self._page_diagnostics[page_idx].groups.append(
                                            GroupDiagnostics(
                                                group=grp_idx,
                                                strategy="coordinate_recovery",
                                                candidate_rows=len(coord_items),
                                                accepted_rows=len(coord_items),
                                                rejected_rows=0,
                                                unprocessed_rows=0,
                                            )
                                        )
                                        self._page_diagnostics[page_idx].accepted_rows += len(coord_items)
                                    else:
                                        self._page_diagnostics.append(
                                            PageDiagnostics(
                                                page=page_idx + 1,
                                                strategy="coordinate_recovery",
                                                accepted_rows=len(coord_items),
                                                groups=[
                                                    GroupDiagnostics(
                                                        group=0,
                                                        strategy="coordinate_recovery",
                                                        candidate_rows=len(coord_items),
                                                        accepted_rows=len(coord_items),
                                                        rejected_rows=0,
                                                        unprocessed_rows=0,
                                                    )
                                                ]
                                            )
                                        )

                    for it in page_items:
                        if '_page' not in it:
                            it['_page'] = page_idx
                    items.extend(page_items)
                    if len(self._page_diagnostics) <= page_idx:
                        self._page_diagnostics.append(
                            PageDiagnostics(
                                page=page_idx + 1,
                                strategy="page",
                                accepted_rows=len(page_items),
                                groups=[GroupDiagnostics(group=0, strategy="page", candidate_rows=len(page_items), accepted_rows=len(page_items))]
                            )
                        )
                    else:
                        self._page_diagnostics[page_idx].accepted_rows = sum(
                            g.accepted_rows for g in self._page_diagnostics[page_idx].groups
                        )
        except Exception as e:
            self.last_error = f"Corrupted or invalid PDF file ({os.path.basename(self.pdf_path)}): {e}"
            logger.warning(f"Error parsing PDF {self.warehouse_name}: {e}")
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


        if not items:
            df = pd.DataFrame(columns=[
                'warehouse_name', 'item_name', 'normalized_name', 'dosage',
                'unit_size', 'base_price', 'discount_rate', 'stock_status'
            ])
            import_diag = ImportDiagnostics(
                pages=self._page_diagnostics,
                accepted_rows=0,
                unique_records=0,
                duplicate_records=0,
                errors=[self.last_error] if self.last_error else [],
            )
            self._import_diagnostics = import_diag
            fp = FileFingerprint.from_path(self.pdf_path) if self.pdf_path and os.path.exists(self.pdf_path) else None
            res = CatalogResult(dataframe=df, diagnostics=import_diag, fingerprint=fp)
            df.attrs[METADATA_KEY] = CatalogImportMetadata(
                diagnostics=import_diag,
                fingerprint=fp,
                acknowledgment_token=res.acknowledgment_token
            )
            df.diagnostics = import_diag
            df.fingerprint = fp
            df.acknowledgment_token = res.acknowledgment_token
            return df
            
        # Sort items by document position before deduplication (Feature F12)
        items.sort(key=lambda it: (it.get('_page', 0), it.get('_y', 0.0)))
        for it in items:
            it.pop('_page', None)
            it.pop('_y', None)
            it.pop('_strategy', None)

        df = pd.DataFrame(items)
        df = df[(df['base_price'] > 0.0) & (df['base_price'] < 10000.0)]

        unique_records = len(df)
        accepted_rows = raw_accepted_count
        duplicate_records = max(0, accepted_rows - unique_records)

        import_diag = ImportDiagnostics(
            pages=self._page_diagnostics,
            accepted_rows=accepted_rows,
            unique_records=unique_records,
            duplicate_records=duplicate_records,
            errors=[self.last_error] if self.last_error else [],
        )
        self._import_diagnostics = import_diag
        fp = FileFingerprint.from_path(self.pdf_path) if self.pdf_path and os.path.exists(self.pdf_path) else None
        res = CatalogResult(dataframe=df, diagnostics=import_diag, fingerprint=fp)
        df.attrs[METADATA_KEY] = CatalogImportMetadata(
            diagnostics=import_diag,
            fingerprint=fp,
            acknowledgment_token=res.acknowledgment_token
        )
        df.diagnostics = import_diag
        df.fingerprint = fp
        df.acknowledgment_token = res.acknowledgment_token
        return df



    def _is_likely_catalog_table(self, table_data: list) -> bool:
        """
        Determines whether a raw table is likely an actual product catalog table
        rather than a page banner, header logo, or footer metadata table.
        """
        if not table_data or len(table_data) < 1:
            return False

        # 1. Check for genuine product catalog column headers (in first 3 rows)
        for row in table_data[:3]:
            for cell in row:
                if cell and is_genuine_header_cell(cell):
                    return True

        # 2. For headerless tables: must have at least 2 rows and at least 2 columns
        if len(table_data) < 2 or len(table_data[0]) < 2:
            return False

        # 3. Look for combinations of price-like numbers and product-like text across rows
        has_price = False
        has_product_text = False
        for row in table_data:
            for cell in row:
                if not cell:
                    continue
                s = str(cell).strip()
                s_num = re.sub(r'[^\d.]', '', s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")))
                try:
                    val = float(s_num)
                    if 0.5 <= val <= 50000.0:
                        has_price = True
                except ValueError:
                    pass
                letters = re.findall(r'[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeffa-zA-Z]', s)
                if len(letters) >= 3 and not any(kw in s for kw in ['تاريخ', 'صفحة', 'الوقت', 'طبع', 'مساهمة']):
                    has_product_text = True
            if has_price and has_product_text:
                return True

        return False

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

        # 0. Pattern: 10-12 Column ERP Purchase Invoice (e.g. Al-Arabia Pharma)
        if len(table) >= 2 and len(table[0]) >= 10:
            row0_str = ' '.join(str(c) for c in table[0] if c)
            is_invoice_banner = any(kw in row0_str for kw in ['فاتورة مشتريات', 'فﺎﺗورة ﻣﺷﺗرﯾﺎت', 'دروﻣﻟا', 'تﺎﯾرﺗﺷﻣ', 'المورد', 'اﻟﻣورد'])
            is_arabia_wh = 'العربيه' in self.warehouse_name or 'العربية' in self.warehouse_name
            if is_invoice_banner or is_arabia_wh:
                start_row = 1
                for r_idx in range(min(4, len(table))):
                    r_text = ' '.join(str(c) for c in table[r_idx] if c)
                    if any(kw in r_text for kw in ['مﺻﺧ', 'خصم', 'روﮭﻣﺟ', 'جمهور', 'فﻧﺻﻟا', 'الصنف']):
                        start_row = r_idx + 1
                        break
                
                invoice_results = []
                for row in table[start_row:]:
                    if not row or len(row) < 9:
                        continue
                    # Col 8 (or 9) = Item Name, Col 5 = Public Price, Col 3 = Discount %
                    raw_name = str(row[8]).strip() if row[8] else ''
                    if not raw_name and len(row) > 9 and row[9]:
                        raw_name = str(row[9]).strip()
                    if not raw_name:
                        continue
                    # Strip leading price prefixes like ـ(٤٥) or (45)
                    raw_name = re.sub(r'^ـ?\s*\(\s*[\d\.\u0660-\u0669]+\s*\)\s*', '', raw_name).strip()
                    if not raw_name or len(raw_name) < 2:
                        continue
                    if any(kw in raw_name for kw in ['اسم الصنف', 'فﻧﺻﻟا مﺳا', 'دروﻣﻟا', 'بﺗﺎﻛﻟا']):
                        continue
                    
                    price_val = self._parse_price(row[5] if len(row) > 5 else '')
                    disc_val = parse_discount(row[3] if len(row) > 3 else '')
                    
                    if 0 < disc_val <= 0.85 and 0 < price_val <= 10000.0:
                        raw_name = decode_greek_arwasoft(raw_name)
                        if is_catalog_noise(raw_name):
                            continue
                        latin_chars = len(re.findall(r'[a-zA-Z]', raw_name))
                        arabic_chars = len(re.findall(r'[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]', raw_name))
                        if latin_chars > arabic_chars:
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=False)
                        else:
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=True)
                        norm_name = normalize_arabic_text(item_name)
                        dosage, unit_size = parse_dosage_and_pack(item_name)
                        if len(norm_name) >= 2:
                            invoice_results.append({
                                'warehouse_name': self.warehouse_name,
                                'item_name': item_name,
                                'normalized_name': norm_name,
                                'dosage': dosage,
                                'unit_size': unit_size,
                                'base_price': price_val,
                                'discount_rate': disc_val,
                                'stock_status': True
                            })
                if invoice_results:
                    return invoice_results

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
                            raw_p_num = self._extract_raw_float(c0)
                            raw_d_num = self._extract_raw_float(c1)
                            raw_name = c2
                        elif is_c2_num and not is_c0_num:
                            p_val = self._parse_price(c2)
                            d_val = parse_discount(c1)
                            raw_p_num = self._extract_raw_float(c2)
                            raw_d_num = self._extract_raw_float(c1)
                            raw_name = c0
                        else:
                            text_in_c0 = len(re.findall(r'[a-zA-Z\u0600-\u06ff\u0380-\u03ff]', c0))
                            text_in_c2 = len(re.findall(r'[a-zA-Z\u0600-\u06ff\u0380-\u03ff]', c2))
                            if text_in_c2 >= text_in_c0:
                                p_val = self._parse_price(c0)
                                d_val = parse_discount(c1)
                                raw_p_num = self._extract_raw_float(c0)
                                raw_d_num = self._extract_raw_float(c1)
                                raw_name = c2
                            else:
                                p_val = self._parse_price(c2)
                                d_val = parse_discount(c1)
                                raw_p_num = self._extract_raw_float(c2)
                                raw_d_num = self._extract_raw_float(c1)
                                raw_name = c0

                        raw_name = decode_greek_arwasoft(raw_name)
                        if is_catalog_noise(raw_name):
                            continue
                        latin_chars = len(re.findall(r'[a-zA-Z]', raw_name))
                        arabic_chars = len(re.findall(r'[\u0600-\u06ff]', raw_name))
                        if latin_chars > arabic_chars:
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=False)
                        elif is_arabic_text_reversed(raw_name):
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=True)
                        else:
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=False)

                        p_val, d_val = self._sanity_check_item_price_and_discount(
                            item_name, p_val, d_val, raw_price_num=raw_p_num, raw_disc_num=raw_d_num
                        )
                        is_valid_d = (0 < d_val <= 0.85) or (d_val == 0.0 and is_explicit_zero_discount(c1))
                        if is_valid_d and 0 < p_val <= 10000.0:
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

        # 2. Pattern: 4-element rows with item code in col 0 or col 2 and item name in col 1 (Al-Hadhaba vs Special Pharma)
        rows_4 = [r for r in filtered_rows if len(r) == 4]
        r1_word_rows = sum(
            1 for r in rows_4[:20]
            if re.search(r'[a-zA-Z\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufeff\u1800-\u18af]', str(r[1]))
        ) if rows_4 else 0
        if len(rows_4) >= 2 and (len(rows_4) / len(filtered_rows)) >= 0.4 and r1_word_rows >= len(rows_4[:20]) * 0.5:
            # Dynamic 4-column layout detection:
            # Al-Hadhaba catalog [Code, Name, Price, Discount] vs Special Pharma [Discount, Name, Code, Price]
            sample_candidates = []
            for r in rows_4[:20]:
                r1_clean = normalize_arabic_text(decode_custom_catalog_glyphs(str(r[1])))
                r0_clean = normalize_arabic_text(decode_custom_catalog_glyphs(str(r[0])))
                if any(h in r1_clean for h in ['صنف', 'اسم', 'فنص', 'مسا', 'name', 'item']) or any(h in r0_clean for h in ['صنف', 'اسم', 'كود', 'code', 'مقر', 'رقم']):
                    continue
                sample_candidates.append(r)
            
            c0_disc_count = sum(1 for r in sample_candidates if 0.01 <= parse_discount(r[0]) <= 0.85)
            c3_disc_count = sum(1 for r in sample_candidates if 0.01 <= parse_discount(r[3]) <= 0.85)
            is_hadhaba = c3_disc_count > c0_disc_count or ('هضبة' in self.warehouse_name or 'الهضبة' in self.warehouse_name or 'الهضبه' in self.warehouse_name)

            for r in filtered_rows:
                if len(r) == 4:
                    r1_raw = str(r[1]).strip()
                    r0_raw = str(r[0]).strip()
                    r1_norm = normalize_arabic_text(decode_custom_catalog_glyphs(r1_raw))
                    r0_norm = normalize_arabic_text(decode_custom_catalog_glyphs(r0_raw))
                    if any(h in r1_norm for h in ['صنف', 'اسم', 'فنص', 'مسا', 'name', 'item', 'product', 'description', 'البيان']):
                        continue
                    if any(h in r0_norm for h in ['رقم', 'كود', 'مقر', 'دوك', 'code', 'barcode', 'خصم', 'مصخ', 'disc', 'discount']):
                        continue

                    raw_name = r[1]
                    if is_hadhaba:
                        d_val = parse_discount(r[3])
                        disc_cell = r[3]
                        p_val = self._parse_price(r[2])
                        raw_d_num = self._extract_raw_float(r[3])
                        raw_p_num = self._extract_raw_float(r[2])
                    else:
                        d_val = parse_discount(r[0])
                        disc_cell = r[0]
                        raw_d_num = self._extract_raw_float(r[0])
                        v2 = self._parse_price(r[2])
                        v3 = self._parse_price(r[3])
                        if v2 >= 10000 and 0 < v3 < 10000:
                            p_val = v3
                        elif v3 >= 10000 and 0 < v2 < 10000:
                            p_val = v2
                        else:
                            p_val = v3 if v3 > 0 else v2
                        raw_p_num = p_val

                    cleaned_raw_name = re.sub(r'^\s*[\u1800-\u18af\s]+\n', '', raw_name)
                    decoded_name = decode_custom_catalog_glyphs(cleaned_raw_name)
                    latin_chars = len(re.findall(r'[a-zA-Z]', decoded_name))
                    arabic_chars = len(re.findall(r'[\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufeff]', decoded_name))
                    if latin_chars > arabic_chars:
                        item_name = fix_arabic_bidi_if_needed(decoded_name, force_reverse=False)
                    elif is_arabic_text_reversed(decoded_name):
                        item_name = fix_arabic_bidi_if_needed(decoded_name, force_reverse=True)
                    else:
                        item_name = fix_arabic_bidi_if_needed(decoded_name, force_reverse=False)

                    p_val, d_val = self._sanity_check_item_price_and_discount(
                        item_name, p_val, d_val, raw_price_num=raw_p_num, raw_disc_num=raw_d_num
                    )
                    is_valid_d = (0 < d_val <= 0.85) or (d_val == 0.0 and is_explicit_zero_discount(disc_cell))
                    if is_valid_d and 0 < p_val <= 10000.0:
                        norm_name = normalize_arabic_text(item_name)
                        if is_catalog_noise(norm_name) or is_catalog_noise(item_name):
                            continue
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
            raw_row0 = [str(col).strip() if col else '' for col in sub_t[0]]
            row0_joined = ' '.join(c for c in raw_row0 if c).lower()
            has_explicit_header_kw = any(
                kw in row0_joined
                for kw in ['اسم الصنف', 'إسم الصنف', 'فنصلا', 'السعر', 'رعسلا', 'الخصم', 'مصخلا', 'البيان', 'item', 'product', 'price', 'discount']
            )
            pure_num_cells_row0 = sum(
                1 for c in raw_row0
                if c and re.fullmatch(r'[-+]?\d+(?:[.,٫]\d+)?\s*%?', c.translate(ALL_EASTERN_DIGITS))
            )
            non_empty_r0 = [c for c in raw_row0 if c]
            is_merged_data_r0 = (
                len(non_empty_r0) == 1 and
                bool(re.match(r'^\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s+', non_empty_r0[0].translate(ALL_EASTERN_DIGITS)))
            )
            if not has_explicit_header_kw and (pure_num_cells_row0 >= 2 or is_merged_data_r0):
                sub_headers = ['' for _ in raw_row0]
                data_rows = sub_t
            else:
                sub_headers = raw_row0
                data_rows = sub_t[1:]

            name_idx, price_idx, discount_idx, stock_idx = self._find_column_indices(sub_headers, data_rows)

            # Pre-scan Case A (merged single-cell rows) across sub_t for batch Price/Discount sanity check
            # and table-level Arabic reversal consistency
            case_a_records = []
            rev_votes = 0
            fwd_votes = 0
            for r_scan in data_rows:
                if not r_scan:
                    continue
                ne_scan = [str(c).strip() for c in r_scan if c and str(c).strip()]
                if len(ne_scan) == 1 and (' ' in ne_scan[0]):
                    for ln_scan in ne_scan[0].split('\n'):
                        ln_s = ln_scan.strip().translate(EASTERN_ARABIC_DIGITS)
                        pts = ln_s.split()
                        if len(pts) >= 3 and re.match(r'^\d+(?:\.\d+)?$', pts[0]) and re.match(r'^\d+(?:\.\d+)?$', pts[1]):
                            v0 = self._extract_raw_float(pts[0])
                            v1 = self._extract_raw_float(pts[1])
                            rn = ' '.join(pts[2:])
                            if is_arabic_text_reversed(rn):
                                rev_votes += 1
                                prev_n = fix_arabic_bidi_if_needed(rn, force_reverse=True)
                            else:
                                if any(w in rn for w in FORWARD_PHARMA_TOKENS):
                                    fwd_votes += 1
                                prev_n = fix_arabic_bidi_if_needed(rn, force_reverse=False)
                            case_a_records.append((v0, v1, prev_n))

            tbl_hdr_price_first = self._detect_table_header_price_first(sub_t)
            if tbl_hdr_price_first is None:
                tbl_hdr_price_first = self._doc_first_num_is_price
            case_a_first_is_price = (
                self._should_swap_price_and_discount(case_a_records, header_first_is_price=tbl_hdr_price_first)
                if case_a_records else bool(tbl_hdr_price_first)
            )
            is_table_reversed = (rev_votes >= 2 and rev_votes > fwd_votes * 2)
            
            for row in data_rows:
                if not row or all(not cell for cell in row):
                    continue

                # Case A: Row has merged single string with multiple columns
                non_empty_cells = [str(c).strip() for c in row if c and str(c).strip()]
                if len(non_empty_cells) == 1 and (' ' in non_empty_cells[0]):
                    lines = [ln.strip() for ln in non_empty_cells[0].split('\n') if ln.strip()]
                    for ln in lines:
                        cell_text = ln.translate(EASTERN_ARABIC_DIGITS)
                        parts = cell_text.split()
                        if len(parts) >= 3:
                            m0 = re.match(r'^\d+(?:\.\d+)?$', parts[0])
                            m1 = re.match(r'^\d+(?:\.\d+)?$', parts[1])
                            if m0 and m1:
                                if case_a_first_is_price:
                                    price_val = self._parse_price(parts[0])
                                    discount_val = parse_discount(parts[1])
                                    raw_p_num = self._extract_raw_float(parts[0])
                                    raw_d_num = self._extract_raw_float(parts[1])
                                else:
                                    discount_val = parse_discount(parts[0])
                                    price_val = self._parse_price(parts[1])
                                    raw_d_num = self._extract_raw_float(parts[0])
                                    raw_p_num = self._extract_raw_float(parts[1])
                                raw_name = ' '.join(parts[2:])
                                if is_catalog_noise(raw_name):
                                    continue
                                latin_chars = len(re.findall(r'[a-zA-Z]', raw_name))
                                arabic_chars = len(re.findall(r'[\u0600-\u06ff]', raw_name))
                                if latin_chars > arabic_chars:
                                    item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=False)
                                elif is_arabic_text_reversed(raw_name) or (is_table_reversed and not any(w in raw_name for w in FORWARD_PHARMA_TOKENS)):
                                    item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=True)
                                else:
                                    item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=False)
                                price_val, discount_val = self._sanity_check_item_price_and_discount(
                                    item_name, price_val, discount_val, raw_price_num=raw_p_num, raw_disc_num=raw_d_num
                                )
                                if is_catalog_noise(item_name) or discount_val <= 0.0 or discount_val > 0.85 or price_val <= 0.0 or price_val >= 10000.0:
                                    continue
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
                raw_name_cell = str(row[name_idx]).strip() if name_idx is not None and name_idx < len(row) and row[name_idx] else ''
                if not raw_name_cell:
                    continue
                    
                if any(h in raw_name_cell for h in ['اسم الصنف', 'الصنف', 'Item Name', 'Product', 'البيان', 'فنصلا', 'مسإ', 'مساف']):
                    continue

                raw_discount_cell = str(row[discount_idx]).strip() if discount_idx is not None and discount_idx < len(row) and row[discount_idx] else ''
                raw_price_cell = str(row[price_idx]).strip() if price_idx is not None and price_idx < len(row) and row[price_idx] else ''

                # Split multiline lines if present
                name_lines = [ln.strip() for ln in raw_name_cell.split('\n') if ln.strip()]
                price_lines = [ln.strip() for ln in raw_price_cell.split('\n') if ln.strip()]
                disc_lines = [ln.strip() for ln in raw_discount_cell.split('\n') if ln.strip()]

                # Check for shifted discount column placed on a separate line inside name_cell (e.g. Al-Forsan page 6: "سيدرال فورت ق \n 27")
                if len(name_lines) > 1 and (not raw_discount_cell or (not is_explicit_zero_discount(raw_discount_cell) and parse_discount(raw_discount_cell) == 0.0)):
                    m_last = re.fullmatch(r'(\d{1,2}(?:\.\d+)?)\s*%?', name_lines[-1].strip().translate(ALL_EASTERN_DIGITS))
                    if m_last:
                        try:
                            val_cand = float(m_last.group(1))
                            if 1.0 <= val_cand <= 85.0:
                                raw_discount_cell = m_last.group(1)
                                disc_lines = [raw_discount_cell]
                                name_lines.pop()
                        except ValueError:
                            pass

                # Determine whether this is a multi-line merged row (e.g. Al-Forsan) or single medicine
                sub_items = []
                is_cell_reversed = is_arabic_text_reversed(raw_name_cell)
                if len(name_lines) > 1 and (len(price_lines) > 1 or len(disc_lines) > 1):
                    # Aligned multi-item row:
                    # Detect and rejoin wrapped medicine names if name_lines > price_lines
                    reconciled_names = []
                    wrap_continuation = re.compile(
                        r'^(?:\d+\s*(?:ق|قرص|اقراص|كبسول|شريط|امبول|فيال|نقط|مل|مجم|باكت|علبة|tab|cap|amp|vial|strip|ml|mg|gm)|سعر\s*جديد|سعر\s*قديم|\d+\s*%)',
                        re.IGNORECASE
                    )
                    for n_idx, ln in enumerate(name_lines):
                        unrev_ln = fix_arabic_bidi_if_needed(ln, force_reverse=True if is_cell_reversed and not any(w in ln for w in FORWARD_PHARMA_TOKENS) else None)
                        if (
                            n_idx > 0
                            and len(reconciled_names) > 0
                            and (len(reconciled_names) + len(name_lines) - n_idx - 1 >= len(price_lines))
                            and (wrap_continuation.match(unrev_ln) or wrap_continuation.match(ln) or len(ln) < 6)
                        ):
                            reconciled_names[-1] += " " + ln
                        else:
                            reconciled_names.append(ln)

                    num_sub = min(len(reconciled_names), len(price_lines)) if price_lines else len(reconciled_names)
                    for k in range(num_sub):
                        n_k = reconciled_names[k]
                        p_k = price_lines[k] if k < len(price_lines) else (price_lines[0] if len(price_lines) == 1 else '')
                        d_k = disc_lines[k] if k < len(disc_lines) else (disc_lines[0] if len(disc_lines) == 1 else '')
                        sub_items.append((n_k, p_k, d_k))
                else:
                    sub_items = [(' '.join(name_lines) if name_lines else raw_name_cell, raw_price_cell, raw_discount_cell)]

                stock_status = True
                if stock_idx is not None and stock_idx < len(row) and row[stock_idx]:
                    stock_text = str(row[stock_idx]).strip().lower()
                    if any(kw in stock_text for kw in ['غير متوفر', 'نفذ', 'out', '0', 'لا يوجد']):
                        stock_status = False

                for sub_name, sub_price_str, sub_disc_str in sub_items:
                    if not sub_name or sub_name.isdigit() or len(sub_name) < 2:
                        continue
                    if any(h in sub_name for h in ['اسم الصنف', 'الصنف', 'Item Name', 'Product', 'البيان', 'فنصلا', 'مسإ', 'مساف']):
                        continue

                    # Inline discount recovery (e.g. shifted column: "سيدرال اكتف \n 27" or "27%")
                    # Must be preceded by newline or explicitly suffixed with % to avoid capturing pack numbers (e.g. باكت 10)
                    m_inline = re.search(r'(?:\n\s*(\d{1,2}(?:\.\d+)?)\s*%?\s*$|\s+(\d{1,2}(?:\.\d+)?)\s*%\s*$)', sub_name)
                    if m_inline and (not sub_disc_str or (not is_explicit_zero_discount(sub_disc_str) and parse_discount(sub_disc_str) == 0.0)):
                        try:
                            val_str = m_inline.group(1) or m_inline.group(2)
                            val_cand = float(val_str)
                            if 1.0 <= val_cand <= 85.0:
                                sub_disc_str = val_str
                                sub_name = sub_name[:m_inline.start()].strip()
                        except ValueError:
                            pass

                    cleaned_sub_name = re.sub(r'^\s*[\u1800-\u18af\s]+\n', '', sub_name)
                    decoded_sub_name = decode_custom_catalog_glyphs(cleaned_sub_name)

                    price_val = self._parse_price(sub_price_str)
                    discount_val = parse_discount(sub_disc_str)

                    # Recover glued price/discount if single item and either was merged or missed
                    if len(sub_items) == 1 and (discount_val <= 0.0 or price_val <= 0.0):
                        for c_idx, cell in enumerate(row):
                            if c_idx == name_idx or not cell:
                                continue
                            c_str = str(cell).strip().translate(EASTERN_ARABIC_DIGITS)
                            m_both = re.search(r'(\d+(?:\.\d+)?)\s*%\s*(\d+(?:\.\d+)?)', c_str)
                            if m_both:
                                if discount_val <= 0.0:
                                    discount_val = parse_discount(m_both.group(1))
                                    sub_disc_str = m_both.group(1)
                                if price_val <= 0.0:
                                    price_val = self._parse_price(m_both.group(2))
                                break
                            m_both2 = re.search(r'(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*%', c_str)
                            if m_both2:
                                if price_val <= 0.0:
                                    price_val = self._parse_price(m_both2.group(1))
                                if discount_val <= 0.0:
                                    discount_val = parse_discount(m_both2.group(2))
                                    sub_disc_str = m_both2.group(2)
                                break
                            m_both3 = re.search(r'(\d+(?:\.\d+)?)\s*%\s*$', c_str)
                            if m_both3 and discount_val <= 0.0:
                                discount_val = parse_discount(m_both3.group(1))
                                sub_disc_str = m_both3.group(1)

                    latin_chars = len(re.findall(r'[a-zA-Z]', decoded_sub_name))
                    arabic_chars = len(re.findall(r'[\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufeff]', decoded_sub_name))
                    if latin_chars > arabic_chars:
                        item_name = fix_arabic_bidi_if_needed(decoded_sub_name, force_reverse=False)
                    elif is_cell_reversed and not any(w in decoded_sub_name for w in FORWARD_PHARMA_TOKENS):
                        item_name = fix_arabic_bidi_if_needed(decoded_sub_name, force_reverse=True)
                    elif is_arabic_text_reversed(decoded_sub_name):
                        item_name = fix_arabic_bidi_if_needed(decoded_sub_name, force_reverse=True)
                    else:
                        item_name = fix_arabic_bidi_if_needed(decoded_sub_name, force_reverse=False)
                    norm_name = normalize_arabic_text(item_name)
                    if is_catalog_noise(norm_name) or is_catalog_noise(item_name):
                        continue

                    raw_p_num = self._extract_raw_float(sub_price_str)
                    raw_d_num = self._extract_raw_float(sub_disc_str)
                    price_val, discount_val = self._sanity_check_item_price_and_discount(
                        item_name, price_val, discount_val, raw_price_num=raw_p_num, raw_disc_num=raw_d_num
                    )
                    dosage, unit_size = parse_dosage_and_pack(item_name)

                    # Support explicit zero discount ("صافي" / net pricing)
                    is_valid_zero = (discount_val == 0.0 and is_explicit_zero_discount(sub_disc_str))
                    valid_discount = (0.0 < discount_val <= 0.85) or is_valid_zero

                    if len(norm_name) >= 2 and valid_discount and 0.0 < price_val <= 10000.0:
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
        discount_keywords = ['خصم', 'نسبة', 'disc', 'discount', 'مصخلا', 'مصخ', 'ةلمج', 'جملة', 'ممم']
        stock_keywords = ['رصيد', 'كمية', 'حالة', 'توفر', 'متاح', 'stock', 'qty', 'status', 'avail']
        code_keywords = ['كود', 'code', 'باركود', 'barcode', 'رمز', 'دوك', 'دوكلا']
        code_idx = None
        
        for idx, h in enumerate(headers):
            h_clean = h.lower().strip()
            if any(k in h_clean for k in code_keywords) and code_idx is None:
                code_idx = idx
            elif any(k in h_clean for k in name_keywords) and name_idx is None:
                name_idx = idx
            elif (any(k in h_clean for k in discount_keywords) or ('%' in h_clean and len(h_clean) <= 15)) and discount_idx is None:
                discount_idx = idx
            elif any(k in h_clean for k in price_keywords) and price_idx is None:
                price_idx = idx
            elif any(k in h_clean for k in stock_keywords) and stock_idx is None:
                stock_idx = idx

        explicit_hdr_both = (discount_idx is not None and price_idx is not None)

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

        # Sanity check: detect and correct switched Price and Discount columns
        if discount_idx is not None and price_idx is not None and discount_idx != price_idx and sample_rows:
            col_records = []
            for row in sample_rows[:30]:
                if discount_idx < len(row) and price_idx < len(row):
                    d_raw = self._extract_raw_float(row[discount_idx])
                    p_raw = self._extract_raw_float(row[price_idx])
                    n_raw = str(row[name_idx]).strip() if (name_idx is not None and name_idx < len(row) and row[name_idx]) else ''
                    if n_raw:
                        n_dec = decode_custom_catalog_glyphs(n_raw)
                        n_prev = fix_arabic_bidi_if_needed(n_dec, force_reverse=True if is_arabic_text_reversed(n_dec) else False)
                    else:
                        n_prev = ''
                    if d_raw > 0.0 and p_raw > 0.0:
                        col_records.append((d_raw, p_raw, n_prev))
            if col_records and self._should_swap_price_and_discount(
                col_records,
                header_first_is_price=False if explicit_hdr_both else None
            ):
                price_idx, discount_idx = discount_idx, price_idx

        return name_idx, price_idx, discount_idx, stock_idx

    def _parse_price(self, val) -> float:
        if val is None:
            return 0.0
        val_str = str(val).strip().replace(',', '.')
        # Translate Eastern Arabic digits
        val_str = val_str.translate(EASTERN_ARABIC_DIGITS)

        # 1. Handle space-separated duplicates: "540 540", "136.5 136.5", "55 55"
        parts = val_str.split()
        if len(parts) >= 2 and parts[0] == parts[1]:
            val_str = parts[0]

        # 2. Decouple repeated decimal prices before number matching: e.g. "12.512.5" -> "12.5"
        m_dec = re.search(r'(\d+\.\d+)\1', val_str)
        if m_dec:
            val_str = m_dec.group(1)

        if re.search(r'[eE]', val_str):
            return 0.0

        match = re.search(r'[-+]?\d*\.?\d+', val_str)
        if not match:
            return 0.0

        s = match.group()

        # 3. Decouple repeated integer prices: e.g. "7575" -> "75", "210210" -> "210", "288288" -> "288", "120120" -> "120"
        m_int_rep = re.match(r'^(\d{2,4})\1$', s)
        if m_int_rep:
            s = m_int_rep.group(1)

        # 4. Decouple triple-repeated prices: e.g. "757575" -> "75"
        m_tri_rep = re.match(r'^(\d{2,3})\1\1$', s)
        if m_tri_rep:
            s = m_tri_rep.group(1)

        try:
            p = float(s)
        except ValueError:
            return 0.0

        # Reject explicitly formatted extreme floats ending with .0 (e.g. 2027172.0, 210210.0)
        if p >= 10000.0 and val_str.endswith(('.0', '.00')):
            return 0.0

        # 5. Decouple glued expiry date + price (e.g. 2027172 -> year 2027 + price 172, 2035120.5 -> 120.5)
        if p > 10000.0:
            m_date = re.match(r'^(?:202[4-9]|203[0-5])(\d{2,4}(?:\.\d+)?)$', s)
            if m_date:
                cand_p = float(m_date.group(1))
                if 0.0 < cand_p <= 10000.0:
                    p = cand_p

        # 6. Decouple glued common dosage/pack + price (e.g. 160118 -> 160mg + 118, 30265 -> 30 + 265, 10218 -> 10 + 218)
        if p > 10000.0:
            m_dosage = re.match(r'^(?:10|20|25|30|40|42|50|60|100|160|200|400|500)(\d{2,4}(?:\.\d+)?)$', s)
            if m_dosage:
                cand_p = float(m_dosage.group(1))
                if 0.0 < cand_p <= 10000.0:
                    p = cand_p

        # 7. Strict upper and lower cap (< 10,000 EGP)
        if p <= 0.0 or p >= 10000.0:
            return 0.0

        return p

    def _find_uncovered_blocks(self, page, covered_bboxes: list) -> list:
        """
        Scan text blocks outside covered table bounding boxes (Feature F12).
        Filters out header/footer noise (y < 80, y > 790) and catalog noise.
        """
        uncovered = []
        try:
            blocks = page.get_text("blocks")
        except Exception:
            return []

        for b in blocks:
            # b: (x0, y0, x1, y1, text, block_no, block_type)
            if len(b) > 6 and b[6] != 0:
                continue
            bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
            # Filter margin noise (y < 80, y > 790)
            if by0 < 80.0 or by1 > 790.0:
                continue
            text = b[4].strip() if len(b) > 4 else ""
            if not text or is_catalog_noise(text):
                continue
            # Filter repeated column header noise
            if any(h in text for h in ['الخصم', 'السعر', 'الصنف', 'المخزن', 'أصناف', 'شركة اروى', 'لتجارة وتوزيع']):
                if not re.search(r'\d+', text):
                    continue

            # Check overlap with covered bounding boxes
            is_covered = False
            b_area = max(1.0, (bx1 - bx0) * (by1 - by0))
            for cbox in covered_bboxes:
                cx0, cy0, cx1, cy1 = cbox[0], cbox[1], cbox[2], cbox[3]
                ix0 = max(bx0, cx0)
                iy0 = max(by0, cy0)
                ix1 = min(bx1, cx1)
                iy1 = min(by1, cy1)
                if ix1 > ix0 and iy1 > iy0:
                    inter_area = (ix1 - ix0) * (iy1 - iy0)
                    if inter_area / b_area > 0.2:
                        is_covered = True
                        break
            if not is_covered:
                uncovered.append(b)

        return uncovered

    def _extract_items_from_blocks(self, blocks: list) -> list:
        """Extract medication items from a list of PyMuPDF text blocks."""
        items = []
        for b in blocks:
            if len(b) > 1 and (b[1] < 80.0 or b[3] > 790.0):
                continue
            text = b[4].strip() if len(b) > 4 else ""
            if not text or is_catalog_noise(text):
                continue
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
                                    'stock_status': True,
                                    '_y': b[1] if len(b) > 1 else 0.0,
                                })

        # Multi-line ArwaSoft block fallback (when item name, price, and discount are split by \n inside each block)
        if len(items) < 2:
            for b in blocks:
                if len(b) > 1 and (b[1] < 80.0 or b[3] > 790.0):
                    continue
                raw_text = b[4].strip() if len(b) > 4 else ""
                if not raw_text or any(h in raw_text for h in ['الخصم', 'السعر', 'الصنف', 'المخزن', 'أصناف', 'شركة اروى', 'لتجارة وتوزيع']):
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
                price_val = self._parse_price(m_price.group(1))
                raw_name = prefix[:m_price.start()].strip()
                raw_name = re.sub(r'\b(?:ج|جنيه|س\.ج|س\.ق|سعر|جديد|قديم)\b', ' ', raw_name)
                raw_name = re.sub(r'[\s/]+$', '', raw_name).strip()
                if len(raw_name) >= 2 and not is_catalog_noise(raw_name) and 0 < disc_val <= 0.85 and 0 < price_val < 10000.0:
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
                            'discount_rate': disc_val,
                            'stock_status': True,
                            '_y': b[1] if len(b) > 1 else 0.0,
                        })
        return items

    def _process_page_blocks(self, page) -> list:
        """Extract lines using PyMuPDF text blocks for whitespace-layout PDFs."""
        try:
            blocks = page.get_text("blocks")
        except Exception:
            return []
        return self._extract_items_from_blocks(blocks)

    def _extract_arwasoft_3col_rects(self, page) -> list:
        """
        Extracts items from 3-column ArwaSoft accounting catalogs (e.g. Zahra Pharm / تحديث زهره.pdf)
        where each item row is enclosed in a drawn vector rectangle (width ~181.6 pt, height ~14.2 pt)
        without internal vertical cell lines (causing PyMuPDF find_tables() to return 0 tables).
        """
        try:
            drawings = page.get_drawings()
        except Exception:
            return []
        if not drawings:
            return []

        raw_rects = []
        for d in drawings:
            r = d.get("rect")
            if r is not None:
                rw = r.x1 - r.x0
                rh = r.y1 - r.y0
                if 150.0 <= rw <= 200.0 and 10.0 <= rh <= 30.0 and 85.0 <= r.y0 <= 800.0:
                    raw_rects.append(r)

        if not raw_rects:
            return []

        # Deduplicate rectangles by rounded coordinates
        seen_rects = set()
        unique_rects = []
        for r in raw_rects:
            key = (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
            if key not in seen_rects:
                seen_rects.add(key)
                unique_rects.append(r)

        if len(unique_rects) < 3:
            return []

        # Sort in natural RTL column reading order: Right column (x0~401), Middle (x0~216), Left (x0~31), then top-to-bottom
        unique_rects.sort(key=lambda r: (-round(r.x0 / 50.0), round(r.y0, 1)))

        words = page.get_text("words")
        if not words:
            return []

        candidate_rows = []
        batch_records = []

        for r in unique_rects:
            cell_words = [
                w for w in words
                if (r.x0 - 1.0) <= ((w[0] + w[2]) / 2.0) <= (r.x1 + 1.0)
                and (r.y0 - 0.5) <= ((w[1] + w[3]) / 2.0) <= (r.y1 + 0.5)
            ]
            if not cell_words:
                continue

            # Inside each 181.6pt ArwaSoft row box:
            # - Discount is at offset [0, 32) from r.x0 (typically ~10pt)
            # - Public Price is at offset [32, 67) from r.x0 (typically ~36..61pt)
            # - Item Name starts at offset >= 67 from r.x0 (leftmost word in wide names starts at ~69pt)
            c0_words = [w for w in cell_words if (w[0] - r.x0) < 32.0 and re.search(r'[\d\u0660-\u0669]', w[4])]
            c1_words = [w for w in cell_words if 32.0 <= (w[0] - r.x0) < 67.0 and re.search(r'[\d\u0660-\u0669]', w[4])]
            name_words = [
                w for w in cell_words
                if (w[0] - r.x0) >= 67.0
                or (32.0 <= (w[0] - r.x0) < 67.0 and not re.search(r'[\d\u0660-\u0669]', w[4]))
            ]

            if not c0_words or not c1_words or not name_words:
                continue

            c0_str = "".join(w[4] for w in sorted(c0_words, key=lambda x: x[0]))
            c1_str = "".join(w[4] for w in sorted(c1_words, key=lambda x: x[0]))

            # Group name_words into horizontal lines (supports 2-line wrapped item names inside a row box)
            y_lines = []
            for nw in sorted(name_words, key=lambda x: x[1]):
                placed = False
                for line_grp in y_lines:
                    if abs(line_grp[0][1] - nw[1]) <= 5.0:
                        line_grp.append(nw)
                        placed = True
                        break
                if not placed:
                    y_lines.append([nw])

            line_strs = []
            for line_grp in y_lines:
                rtl_words = sorted(line_grp, key=lambda x: x[0], reverse=True)
                parts = []
                for idx, nw in enumerate(rtl_words):
                    if (
                        idx > 0
                        and (rtl_words[idx - 1][0] - nw[2]) <= 1.5
                        and not re.search(r'[\d\u0660-\u0669]', nw[4])
                        and not re.search(r'[\d\u0660-\u0669]', rtl_words[idx - 1][4])
                    ):
                        parts[-1] += nw[4]
                    else:
                        parts.append(nw[4])
                line_strs.append(" ".join(parts))

            raw_name = unicodedata.normalize('NFKD', " ".join(line_strs).strip())
            raw_name = decode_custom_catalog_glyphs(raw_name)
            raw_name = fix_arwasoft_arabic_numbers(raw_name)
            if is_catalog_noise(raw_name) or len(raw_name) < 2:
                continue

            item_name = fix_arabic_bidi_if_needed(raw_name)
            v0 = self._extract_raw_float(c0_str)
            v1 = self._extract_raw_float(c1_str)
            candidate_rows.append((c0_str, c1_str, v0, v1, item_name))
            if v0 > 0.0 and v1 > 0.0:
                batch_records.append((v0, v1, item_name))

        if not candidate_rows:
            return []

        first_is_price = self._should_swap_price_and_discount(
            batch_records,
            header_first_is_price=self._doc_first_num_is_price
        )

        items = []
        for c0_str, c1_str, v0, v1, item_name in candidate_rows:
            if first_is_price:
                p_val = self._parse_price(c0_str)
                disc_val = parse_discount(c1_str)
                raw_p_num, raw_d_num = v0, v1
            else:
                disc_val = parse_discount(c0_str)
                p_val = self._parse_price(c1_str)
                raw_d_num, raw_p_num = v0, v1

            p_val, disc_val = self._sanity_check_item_price_and_discount(
                item_name, p_val, disc_val, raw_price_num=raw_p_num, raw_disc_num=raw_d_num
            )
            if 0 < disc_val <= 0.85 and 0 < p_val < 10000.0:
                norm_name = normalize_arabic_text(item_name)
                dosage, unit_size = parse_dosage_and_pack(item_name)
                if len(norm_name) >= 2:
                    items.append({
                        'warehouse_name': self.warehouse_name,
                        'item_name': item_name,
                        'normalized_name': norm_name,
                        'dosage': dosage,
                        'unit_size': unit_size,
                        'base_price': p_val,
                        'discount_rate': disc_val,
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
                price_val = self._parse_price(prices[0][4])
                        
            name_words_sorted = sorted(names, key=lambda w: w[0], reverse=True)
            raw_name = ' '.join(w[4] for w in name_words_sorted).strip()
            raw_name = unicodedata.normalize('NFKD', raw_name)
            raw_name = fix_arwasoft_arabic_numbers(raw_name)
            
            if raw_name and 0 < disc_val <= 0.85 and 0 < price_val < 10000.0:
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

    def _extract_arwasoft_right_column(self, page) -> list:
        """
        Extracts right-column items from ArwaSoft 2-column accounting layouts
        (e.g. Adam Farm, Perfect Farm, Rowad Al-Dawaa, Al-Dawlia Al-Haditha) where
        PyMuPDF table detection only picks up the left column.
        Groups words by vertical Y proximity (threshold <= 6.0 pt) for X >= 300,
        applies batch + per-item Price/Discount sanity checks, and routes through _parse_price.
        """
        words = page.get_text("words")
        # Right column bounds: X from 300 to 585, Y from 88 to 795
        col_words = [w for w in words if w[0] >= 300 and 88 < w[1] < 795]
        if not col_words:
            return []

        y_groups = []
        for w in sorted(col_words, key=lambda x: x[1]):
            matched = False
            for grp in y_groups:
                if abs(grp[0][1] - w[1]) <= 6.0:
                    grp.append(w)
                    matched = True
                    break
            if not matched:
                y_groups.append([w])

        # First pass: collect candidate rows (c0_str, c1_str, raw_name) for column-level sanity check
        candidate_rows = []
        batch_records = []
        for grp in y_groups:
            sorted_x = sorted(grp, key=lambda x: x[0])
            c0_words = [w for w in sorted_x if 300 <= w[0] < 345]
            c1_words = [w for w in sorted_x if 345 <= w[0] < 395]
            name_words = [w for w in sorted_x if w[0] >= 395]

            if not c0_words or not c1_words or not name_words:
                continue

            c0_str = c0_words[0][4]
            c1_str = c1_words[0][4]

            # Reconstruct RTL word order and stitch adjacent sub-word glyph fragments
            name_words_rtl = sorted(name_words, key=lambda x: x[0], reverse=True)
            name_parts = []
            for idx, nw in enumerate(name_words_rtl):
                if idx > 0 and (name_words_rtl[idx - 1][0] - nw[2]) <= 1.5:
                    name_parts[-1] += nw[4]
                else:
                    name_parts.append(nw[4])
            raw_name = unicodedata.normalize('NFKD', " ".join(name_parts).strip())
            raw_name = fix_arwasoft_arabic_numbers(raw_name)
            if is_catalog_noise(raw_name) or len(raw_name) < 2:
                continue

            item_name = fix_arabic_bidi_if_needed(raw_name)
            v0 = self._extract_raw_float(c0_str)
            v1 = self._extract_raw_float(c1_str)
            candidate_rows.append((c0_str, c1_str, v0, v1, item_name))
            if v0 > 0.0 and v1 > 0.0:
                batch_records.append((v0, v1, item_name))

        if not candidate_rows:
            return []

        first_is_price = self._should_swap_price_and_discount(
            batch_records,
            header_first_is_price=self._doc_first_num_is_price
        )

        items = []
        for c0_str, c1_str, v0, v1, item_name in candidate_rows:
            if first_is_price:
                p_val = self._parse_price(c0_str)
                disc_val = parse_discount(c1_str)
                raw_p_num, raw_d_num = v0, v1
            else:
                disc_val = parse_discount(c0_str)
                p_val = self._parse_price(c1_str)
                raw_d_num, raw_p_num = v0, v1

            p_val, disc_val = self._sanity_check_item_price_and_discount(
                item_name, p_val, disc_val, raw_price_num=raw_p_num, raw_disc_num=raw_d_num
            )
            if 0 < disc_val <= 0.85 and 0 < p_val < 10000.0:
                norm_name = normalize_arabic_text(item_name)
                dosage, unit_size = parse_dosage_and_pack(item_name)
                if len(norm_name) >= 2:
                    items.append({
                        'warehouse_name': self.warehouse_name,
                        'item_name': item_name,
                        'normalized_name': norm_name,
                        'dosage': dosage,
                        'unit_size': unit_size,
                        'base_price': p_val,
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
            price_val = self._parse_price(m_price.group(1))
            raw_name = prefix[:m_price.start()].strip()
            raw_name = re.sub(r'\b(?:ج|جنيه|س\.ج|س\.ق|سعر|جديد|قديم)\b', ' ', raw_name)
            raw_name = re.sub(r'[\s/]+$', '', raw_name).strip()
            
            if len(raw_name) >= 2 and 0 < disc_val <= 0.85 and 0 < price_val < 10000.0:
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

    def _stitch_contiguous_tables(self, tables_list: list) -> list:
        """
        Detects when a page produces multiple contiguous table objects where len(table_data) == 1
        and bounding box X-bounds match (e.g. El-Qemma Xmin ~ 61, Xmax ~ 534).
        Stitches these single rows into coherent multi-row tables.
        """
        if not tables_list:
            return []
        
        extracted_tables = []
        i = 0
        while i < len(tables_list):
            t_curr = tables_list[i]
            d_curr = t_curr.extract() if hasattr(t_curr, 'extract') else t_curr
            if d_curr and len(d_curr) == 1:
                col_cnt = len(d_curr[0])
                b_curr = getattr(t_curr, 'bbox', None)
                stitched_rows = list(d_curr)
                j = i + 1
                while j < len(tables_list):
                    t_next = tables_list[j]
                    d_next = t_next.extract() if hasattr(t_next, 'extract') else t_next
                    b_next = getattr(t_next, 'bbox', None)
                    if (d_next and len(d_next) == 1 and len(d_next[0]) == col_cnt):
                        if b_curr and b_next:
                            if abs(b_next[0] - b_curr[0]) < 10.0 and abs(b_next[2] - b_curr[2]) < 10.0:
                                stitched_rows.extend(d_next)
                                j += 1
                            else:
                                break
                        else:
                            stitched_rows.extend(d_next)
                            j += 1
                    else:
                        break
                if len(stitched_rows) > 1:
                    extracted_tables.append(stitched_rows)
                    i = j
                    continue
            if d_curr and len(d_curr) > 0:
                extracted_tables.append(d_curr)
            i += 1
            
        return extracted_tables

    def _extract_sina_columns(self, page) -> list:
        """
        3-column coordinate whitespace extractor for Sina Trade catalogs (سينا.pdf).
        Divides width into 3 vertical column bands: [20, 210], [211, 395], [396, 585].
        Inside each band, groups words by Y proximity (threshold <= 4 pt), extracting:
        Public Price (الجمهور), Discount % (الخصم), and Item Name.
        """
        words = page.get_text("words")
        if not words:
            return []
        
        bands = [
            (20, 210, (20, 60), (61, 105), (106, 210)),
            (211, 395, (211, 245), (246, 290), (291, 395)),
            (396, 585, (396, 435), (436, 480), (481, 585))
        ]
        
        items = []
        for b_min, b_max, p_rng, d_rng, n_rng in bands:
            b_words = [w for w in words if b_min <= w[0] < b_max and w[1] > 100]
            y_groups = []
            for w in sorted(b_words, key=lambda x: x[1]):
                matched = False
                for grp in y_groups:
                    if abs(grp[0][1] - w[1]) <= 4.0:
                        grp.append(w)
                        matched = True
                        break
                if not matched:
                    y_groups.append([w])
                    
            for grp in y_groups:
                p_words = [w[4] for w in grp if p_rng[0] <= w[0] <= p_rng[1]]
                d_words = [w[4] for w in grp if d_rng[0] <= w[0] <= d_rng[1]]
                n_words = [w[4] for w in grp if w[0] >= n_rng[0] - 10]
                
                if p_words and d_words and n_words:
                    raw_name = ' '.join(n_words).strip()
                    if is_catalog_noise(raw_name) or len(raw_name) < 2:
                        continue
                    price_val = self._parse_price(p_words[0])
                    disc_val = parse_discount(d_words[0])
                    
                    if 0 < disc_val <= 0.85 and 0 < price_val <= 10000.0:
                        raw_name = decode_greek_arwasoft(raw_name)
                        if is_arabic_text_reversed(raw_name):
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=True)
                        else:
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=False)
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
                                'discount_rate': disc_val,
                                'stock_status': True
                            })
        return items

    def _extract_dar_fouad_columns(self, page) -> list:
        """
        2-column coordinate extractor for borderless accounting pages (e.g. Dar Al-Fouad).
        Left column: disc [30, 80], price [85, 140], name [140, W/2]
        Right column: disc [300, 355], price [355, 410], name [410, W]
        """
        words = page.get_text("words")
        if not words:
            return []

        # Guard against 3-column layouts (e.g. ArwaSoft 3-col catalogs where Column 2 spans X=[216..398])
        if 'دار الفؤاد' not in self.warehouse_name:
            hdr_words = [wd for wd in words if 50 <= wd[1] <= 110 and any(k in wd[4] for k in ['السعر', 'الخصم', 'الصنف'])]
            if hdr_words:
                has_mid_hdr = any(210 <= wd[0] <= 295 for wd in hdr_words)
                if has_mid_hdr:
                    return []
        
        w = page.rect.width
        cols = [
            ((30, 80), (85, 140), (140, int(w / 2))),
            ((300, 355), (355, 410), (410, int(w)))
        ]
        
        items = []
        for d_rng, p_rng, n_rng in cols:
            col_words = [wd for wd in words if d_rng[0] <= wd[0] < n_rng[1] and wd[1] > 60]
            y_groups = []
            for wd in sorted(col_words, key=lambda x: x[1]):
                matched = False
                for grp in y_groups:
                    if abs(grp[0][1] - wd[1]) <= 4.0:
                        grp.append(wd)
                        matched = True
                        break
                if not matched:
                    y_groups.append([wd])
                    
            for grp in y_groups:
                d_words = [wd[4] for wd in grp if d_rng[0] <= wd[0] <= d_rng[1]]
                p_words = [wd[4] for wd in grp if p_rng[0] <= wd[0] <= p_rng[1]]
                n_words = [wd[4] for wd in grp if wd[0] >= n_rng[0] - 15]
                
                if d_words and p_words and n_words:
                    raw_name = ' '.join(n_words).strip()
                    if is_catalog_noise(raw_name) or len(raw_name) < 2:
                        continue
                    price_val = self._parse_price(p_words[0])
                    disc_val = parse_discount(d_words[0])
                    
                    if 0 < disc_val <= 0.85 and 0 < price_val <= 10000.0:
                        raw_name = fix_arwasoft_arabic_numbers(raw_name)
                        if is_arabic_text_reversed(raw_name):
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=True)
                        else:
                            item_name = fix_arabic_bidi_if_needed(raw_name, force_reverse=False)
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
            price_val = self._parse_price(m1.group(1))
            disc_val = parse_discount(m1.group(2))
            raw_name = clean_line[:m1.start()].strip()
            if not is_catalog_noise(raw_name) and 0.0 < disc_val <= 0.85 and 0.0 < price_val < 10000.0:
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
            price_val = self._parse_price(m2.group(2))
            raw_name = clean_line[:m2.start()].strip()
            if not is_catalog_noise(raw_name) and 0.0 < disc_val <= 0.85 and 0.0 < price_val < 10000.0:
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
                price_val = self._parse_price(m_pr.group(1))
                raw_name = prefix[:m_pr.start()].strip()
                if not is_catalog_noise(raw_name) and 0.0 < disc_val <= 0.85 and 0.0 < price_val < 10000.0:
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

        # Group words by Y proximity (threshold ~14px for 150 DPI)
        y_groups = []
        for w in sorted(word_items, key=lambda i: i['y']):
            matched_group = None
            for group in y_groups:
                if abs(group['y'] - w['y']) <= 14.0:
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
        [ARCHIVED / DEPRECATED - FAILED OCR FEATURE (2026-10-25)]
        The RapidOCR + RapidTable pipeline has been archived (see `archive/failed_ocr_feature/README_FAILED_OCR.md`)
        because its Chinese/English ONNX recognition model lacks Arabic character support and never worked on
        Arabic pharmaceutical catalogs.
        Delegates directly to the digital vector & coordinate parser (`self.parse()`).
        """
        self.last_error = None
        if progress_callback:
            try:
                progress_callback(0.1, "جاري قراءة الكتالوج رقمياً...")
            except Exception:
                pass
        df = self.parse()
        if df.empty and not self.last_error:
            self.last_error = f"No catalog items found in PDF ({os.path.basename(self.pdf_path or '')})."
        if progress_callback:
            try:
                progress_callback(1.0, f"اكتملت القراءة: تم العثور على {len(df)} صنف.")
            except Exception:
                pass
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


