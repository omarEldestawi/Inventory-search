"""
Computer Vision Table and Row Detector (v2.6) for Image-Only and Scanned Arabic Catalogs.

Implements OpenCV-based table boundary detection, vertical column slicing,
horizontal row band slicing, cell-level OCR aggregation, and canonical validation
for Egyptian pharmaceutical catalogs.

Key Responsibilities:
- Detect table boundaries using OpenCV morphological operations (K_h, K_v).
- Vertical projection profiling and X-clustering for column boundary detection.
- Horizontal projection profiling and Y-clustering for row band segmentation.
- Header analysis for deterministic column role classification (item_name, price, discount, code).
- Cell-level OCR text assembly preserving raw_ocr_text, search_normalized_text,
  source bounding box [x0, y0, x1, y1], and source identity p{page}_t{table}_r{row}.
- Canonical validation gate via validate_catalog_item, routing unverified/uncertain rows
  to diagnostic issues and strictly excluding them from procurement.
"""
from __future__ import annotations

import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    from .catalog_diagnostics import ReviewIssue, RowDiagnostic, SourceIdentity
    from .catalog_reader import (
        ALL_EASTERN_DIGITS,
        is_catalog_noise,
        is_explicit_zero_discount,
        is_genuine_header_cell,
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        validate_catalog_item,
    )
    from .ocr_engine import ArabicOCREngine
except ImportError:
    from catalog_diagnostics import ReviewIssue, RowDiagnostic, SourceIdentity
    from catalog_reader import (
        ALL_EASTERN_DIGITS,
        is_catalog_noise,
        is_explicit_zero_discount,
        is_genuine_header_cell,
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        validate_catalog_item,
    )
    from ocr_engine import ArabicOCREngine

logger = logging.getLogger("ImageTableDetector")


@dataclass
class ColumnInfo:
    index: int
    x_center: float
    x_min: float
    x_max: float
    role: str  # 'name', 'price', 'discount', 'code', 'other'
    header_text: str = ""


@dataclass
class OCRRowCandidate:
    row_idx: int
    y_center: float
    y_min: float
    y_max: float
    boxes: List[Dict[str, Any]]
    cells_by_role: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ImageTableDetector:
    """
    Detects table structure and extracts structured catalog items from raster / scanned images.
    """

    def __init__(self, ocr_engine: Optional[ArabicOCREngine] = None):
        self._ocr_engine = ocr_engine or ArabicOCREngine()

    def detect_table_boundaries(self, img_np: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detects outer table boundaries (x, y, w, h) using morphological operations.
        Falls back to page dimensions if no explicit borders are detected.
        """
        if img_np is None or img_np.size == 0:
            return []

        h, w = img_np.shape[:2]
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY) if len(img_np.shape) == 3 else img_np

        # Adaptive thresholding to isolate grid lines
        thresh = cv2.adaptiveThreshold(
            ~gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, -2
        )

        # Scale structuring elements relative to image dimensions
        scale_w = max(10, int(w / 30))
        scale_h = max(10, int(h / 30))

        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (scale_w, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, scale_h))

        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)
        v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)

        table_mask = cv2.add(h_lines, v_lines)
        cnts, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        tables: List[Tuple[int, int, int, int]] = []
        min_area = (w * h) * 0.10  # Must be at least 10% of page area

        for c in cnts:
            bx, by, bw, bh = cv2.boundingRect(c)
            if (bw * bh) >= min_area:
                tables.append((bx, by, bw, bh))

        # Sort top-to-bottom
        tables.sort(key=lambda t: t[1])

        if not tables:
            # Fallback to entire image with a small border margin
            margin_x = int(w * 0.02)
            margin_y = int(h * 0.02)
            tables = [(margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y)]

        return tables

    def cluster_boxes_into_rows(
        self, boxes: List[Dict[str, Any]], y_thresh: float = 35.0
    ) -> List[List[Dict[str, Any]]]:
        """
        Clusters OCR text boxes into horizontal rows based on Y-center proximity.
        """
        if not boxes:
            return []

        # Augment boxes with center coordinates
        prepared = []
        for b in boxes:
            bbox = b["bbox"]
            y_center = (bbox[1] + bbox[3]) / 2.0
            x_center = (bbox[0] + bbox[2]) / 2.0
            prepared.append(
                {
                    **b,
                    "x_center": x_center,
                    "y_center": y_center,
                }
            )

        prepared.sort(key=lambda it: it["y_center"])

        rows: List[List[Dict[str, Any]]] = []
        curr_row: List[Dict[str, Any]] = []
        curr_y: Optional[float] = None

        for b in prepared:
            if curr_y is None:
                curr_y = b["y_center"]
                curr_row.append(b)
            elif abs(b["y_center"] - curr_y) <= y_thresh:
                curr_row.append(b)
                curr_y = float(np.mean([x["y_center"] for x in curr_row]))
            else:
                curr_row.sort(key=lambda x: x["bbox"][0])
                rows.append(curr_row)
                curr_row = [b]
                curr_y = b["y_center"]

        if curr_row:
            curr_row.sort(key=lambda x: x["bbox"][0])
            rows.append(curr_row)

        return rows

    def classify_column_roles(
        self, rows: List[List[Dict[str, Any]]], table_w: float
    ) -> Dict[str, float]:
        """
        Identifies the header row and maps each column role (name, price, discount, code)
        to its approximate X-center coordinate.
        """
        col_roles: Dict[str, float] = {}
        header_row_idx: Optional[int] = None

        header_keywords = {
            "name": ["صنف", "الصنف", "الاسم", "اسم", "بيان", "name", "item", "product", "description"],
            "discount": ["خصم", "الخصم", "نسبة", "نسبه", "disc", "discount", "%"],
            "code": ["كود", "الكود", "code", "رقم", "مسلسل"],
            "price": ["سعر", "السعر", "جمهور", "رسمي", "price", "base"],
        }

        # Inspect top 6 rows for header row
        for idx, r in enumerate(rows[:6]):
            row_text = " ".join(c["text"] for c in r)
            found_roles = 0
            for role, kws in header_keywords.items():
                if any(kw in row_text for kw in kws):
                    found_roles += 1

            if found_roles >= 2:
                header_row_idx = idx
                for c in r:
                    txt = c["text"]
                    xc = c["x_center"]
                    for role, kws in header_keywords.items():
                        if any(kw in txt for kw in kws) and role not in col_roles:
                            col_roles[role] = xc
                break

        # If numeric roles (price, discount) were not explicitly found in header,
        # perform spatial numeric clustering across data rows
        if "price" not in col_roles or "discount" not in col_roles:
            data_rows = rows[header_row_idx + 1 if header_row_idx is not None else 0 :]
            num_cells: List[Tuple[float, float]] = []
            for r in data_rows:
                for c in r:
                    txt = c["text"].replace(",", ".").replace("%", "").strip()
                    try:
                        v = float(txt)
                        num_cells.append((float(c["x_center"]), v))
                    except ValueError:
                        pass

            num_clusters: List[Dict[str, Any]] = []
            for x, v in sorted(num_cells, key=lambda item: item[0]):
                matched = False
                for cl in num_clusters:
                    if abs(cl["center"] - x) < 60:
                        cl["xs"].append(x)
                        cl["center"] = float(np.mean(cl["xs"]))
                        cl["vals"].append(v)
                        matched = True
                        break
                if not matched:
                    num_clusters.append({"center": x, "xs": [x], "vals": [v]})

            code_clusters = [cl for cl in num_clusters if np.median(cl["vals"]) >= 10000.0]
            if code_clusters and "code" not in col_roles:
                col_roles["code"] = code_clusters[0]["center"]

            valid_num_clusters = [cl for cl in num_clusters if np.median(cl["vals"]) < 10000.0]

            if len(valid_num_clusters) >= 2:
                price_cand = None
                disc_cand = None
                for cl in valid_num_clusters:
                    if any(val > 85.0 for val in cl["vals"]):
                        if price_cand is None or max(cl["vals"]) > max(price_cand["vals"]):
                            price_cand = cl
                    elif all(0.0 <= val <= 85.0 for val in cl["vals"]):
                        if disc_cand is None or len(cl["vals"]) > len(disc_cand["vals"]):
                            disc_cand = cl

                if price_cand and "price" not in col_roles:
                    col_roles["price"] = price_cand["center"]
                if disc_cand and "discount" not in col_roles:
                    col_roles["discount"] = disc_cand["center"]
            elif len(valid_num_clusters) == 1:
                cl = valid_num_clusters[0]
                if any(v > 85.0 for v in cl["vals"]):
                    if "price" not in col_roles:
                        col_roles["price"] = cl["center"]
                else:
                    if "discount" not in col_roles:
                        col_roles["discount"] = cl["center"]

        # Fallback defaults if still unresolved
        if "price" not in col_roles:
            col_roles["price"] = table_w * 0.90
        if "discount" not in col_roles:
            col_roles["discount"] = table_w * 0.25

        # If name not found, find column with longest text spans
        if "name" not in col_roles:
            name_xs = []
            for r in rows[header_row_idx + 1 if header_row_idx is not None else 0 :]:
                for c in r:
                    if len(c["text"]) >= 5 and abs(c["x_center"] - col_roles.get("price", -999)) > 200:
                        name_xs.append(c["x_center"])
            if name_xs:
                col_roles["name"] = float(np.median(name_xs))
            else:
                col_roles["name"] = table_w * 0.55

        return col_roles

    def extract_table_records(
        self,
        img_np: np.ndarray,
        page_idx: int = 0,
        warehouse_name: str = "",
        table_idx: int = 0,
        scale_to_pt: float = 72.0 / 150.0,
        ocr_engine_preference: str = "primary",
        pdf_page: Any = None,
    ) -> Tuple[List[Dict[str, Any]], List[RowDiagnostic], List[ReviewIssue]]:
        """
        Performs full table and row extraction from a raster page image.

        Args:
            img_np: RGB or grayscale image array.
            page_idx: 0-based page index.
            warehouse_name: Wholesaler name to stamp on extracted records.
            table_idx: Table index within page.
            scale_to_pt: Scaling factor from image pixels to PDF points.
            ocr_engine_preference: 'primary' or 'secondary'.
            pdf_page: Optional PyMuPDF page handle for high-res targeted re-renders.

        Returns:
            Tuple: (accepted_items, diagnostic_rows, review_issues)
        """
        accepted_items: List[Dict[str, Any]] = []
        diagnostic_rows: List[RowDiagnostic] = []
        review_issues: List[ReviewIssue] = []

        if img_np is None or img_np.size == 0:
            return accepted_items, diagnostic_rows, review_issues

        # 1. OCR Extraction across the image
        boxes = self._ocr_engine.extract_text_boxes(img_np, engine=ocr_engine_preference)
        if not boxes:
            logger.warning("No OCR text boxes detected on page %d", page_idx + 1)
            # Create a region-level issue
            h, w = img_np.shape[:2]
            bbox_pt = [0.0, 0.0, float(w * scale_to_pt), float(h * scale_to_pt)]
            src_id = f"p{page_idx + 1}_t{table_idx}_region"
            ident = SourceIdentity(page=page_idx + 1, table=table_idx, row=None, bbox=bbox_pt)
            reg_diag = RowDiagnostic(
                page=page_idx + 1,
                table=table_idx,
                group=0,
                row=None,
                outcome="rejected",
                reason="ocr_produced_zero_boxes",
                bbox=bbox_pt,
                raw_cells=["[ocr_empty_page]"],
                is_region_issue=True,
                source_id=src_id,
            )
            diagnostic_rows.append(reg_diag)
            review_issues.append(
                ReviewIssue(
                    source_id=src_id,
                    identity=ident,
                    raw_cells=["[ocr_empty_page]"],
                    bbox=bbox_pt,
                    rejection_reason="ocr_produced_zero_boxes",
                    is_region_level=True,
                )
            )
            return accepted_items, diagnostic_rows, review_issues

        # 2. Group boxes into horizontal row bands
        rows = self.cluster_boxes_into_rows(boxes, y_thresh=35.0)
        img_w = float(img_np.shape[1])
        col_roles = self.classify_column_roles(rows, img_w)

        # 3. Identify header row index
        header_idx = None
        for idx, r in enumerate(rows[:5]):
            row_txt = " ".join(c["text"] for c in r)
            if any(k in row_txt for k in ("الصنف", "الخصم", "الكود", "اسم", "سعر")):
                header_idx = idx
                break

        data_rows = rows[header_idx + 1 :] if header_idx is not None else rows

        column_bounds_pt: Dict[str, Tuple[float, float]] = {}
        if col_roles:
            sorted_roles = sorted(col_roles.items(), key=lambda item: item[1])
            for s_i, (role, xc) in enumerate(sorted_roles):
                left_px = 0.0 if s_i == 0 else (sorted_roles[s_i - 1][1] + xc) / 2.0
                right_px = img_w if s_i == len(sorted_roles) - 1 else (xc + sorted_roles[s_i + 1][1]) / 2.0
                column_bounds_pt[role] = (float(left_px * scale_to_pt), float(right_px * scale_to_pt))

        for r_i, r in enumerate(data_rows):
            # Calculate row bounding box in image pixels and scale to points.
            # Expand row width across classified column boundaries to prevent truncating price/discount columns.
            r_x0 = min(c["bbox"][0] for c in r)
            r_y0 = min(c["bbox"][1] for c in r)
            r_x1 = max(c["bbox"][2] for c in r)
            r_y1 = max(c["bbox"][3] for c in r)

            if col_roles:
                table_x0 = min(col_roles.values()) - 50.0
                table_x1 = max(col_roles.values()) + 50.0
                row_x0 = max(0.0, min(r_x0, table_x0))
                row_x1 = min(img_w, max(r_x1, table_x1))
            else:
                row_x0, row_x1 = r_x0, r_x1

            bbox_pt = [
                float(row_x0 * scale_to_pt),
                float(r_y0 * scale_to_pt),
                float(row_x1 * scale_to_pt),
                float(r_y1 * scale_to_pt),
            ]
            src_id = f"p{page_idx + 1}_t{table_idx}_r{r_i}"
            ident = SourceIdentity(page=page_idx + 1, table=table_idx, row=r_i, bbox=bbox_pt)

            # Assign each box in this row to its nearest classified role
            assigned_cells: Dict[str, List[Dict[str, Any]]] = {}
            for c in r:
                txt = c["text"].strip()
                # Check if text is numeric or represents OCR-confused digits (e.g. IOO -> 100, IO -> 10)
                clean_num = (
                    txt.translate(ALL_EASTERN_DIGITS)
                    .replace(",", ".")
                    .replace("%", "")
                    .replace("l", "1")
                    .replace("I", "1")
                    .replace("|", "1")
                    .replace("O", "0")
                    .replace("o", "0")
                    .strip()
                )
                is_numeric = False
                try:
                    float(clean_num)
                    is_numeric = True
                except ValueError:
                    is_numeric = False

                has_arabic = any('\u0600' <= ch <= '\u06ff' for ch in txt)
                closest_role = min(
                    col_roles.keys(), key=lambda k: abs(c["x_center"] - col_roles[k])
                )
                # Pure non-numeric Arabic text (e.g. storage instructions 'ثلاجة', pharmaceutical forms, or trade names)
                # cannot be a price or discount number; route to name even if spatially closer to discount.
                if not is_numeric and has_arabic and txt not in ('صافي', 'Net', 'NET', 'net'):
                    if closest_role in ('discount', 'price', 'code'):
                        closest_role = "name"

                assigned_cells.setdefault(closest_role, []).append(c)

            # Compose text per role
            name_boxes = assigned_cells.get("name", [])
            has_arabic_name = any(
                any("\u0600" <= c <= "\u06ff" or "\ufb50" <= c <= "\ufeff" for c in b.get("text", ""))
                for b in name_boxes
            )
            if has_arabic_name and len(name_boxes) > 1:
                sorted_name_boxes = sorted(name_boxes, key=lambda b: b["bbox"][0], reverse=True)
            else:
                sorted_name_boxes = sorted(name_boxes, key=lambda b: b["bbox"][0])

            raw_name = " ".join(b["text"] for b in sorted_name_boxes).strip()
            raw_ocr_name = " ".join(b["raw_text"] for b in sorted_name_boxes).strip()

            price_boxes = assigned_cells.get("price", [])
            raw_price_str = " ".join(b["text"] for b in price_boxes).strip()

            disc_boxes = assigned_cells.get("discount", [])
            raw_disc_str = " ".join(b["text"] for b in disc_boxes).strip()

            raw_cells_list = [raw_name, raw_price_str, raw_disc_str]

            # Parse numeric price
            p_val: Optional[float] = None
            if raw_price_str:
                p_tokens = raw_price_str.split()
                # If multiple tokens, prefer token in (0, 10000)
                for tok in p_tokens:
                    clean_p = (
                        tok.translate(ALL_EASTERN_DIGITS)
                        .replace(",", ".")
                        .replace("l", "1")
                        .replace("I", "1")
                        .replace("|", "1")
                        .replace("O", "0")
                        .replace("o", "0")
                        .strip()
                    )
                    try:
                        cand_p = float(clean_p)
                        if 0.0 < cand_p < 10000.0:
                            p_val = cand_p
                            # If we found a plausible price < 10000, use it
                            if len(p_tokens) == 1 or cand_p < 5000.0:
                                break
                    except ValueError:
                        pass

            # Parse numeric discount
            d_val: Optional[float] = None
            if raw_disc_str:
                clean_d_str = (
                    raw_disc_str.translate(ALL_EASTERN_DIGITS)
                    .replace("l", "1")
                    .replace("I", "1")
                    .replace("|", "1")
                    .replace("O", "0")
                    .replace("o", "0")
                )
                d_val = parse_discount(clean_d_str)
                if d_val == 0.0 and not is_explicit_zero_discount(clean_d_str):
                    # Try raw float if percentage wasn't matched
                    clean_d = clean_d_str.replace("%", "").strip()
                    try:
                        f_raw = float(clean_d)
                        if f_raw > 1.0 and f_raw <= 85.0:
                            d_val = round(f_raw / 100.0, 4)
                        elif 0.0 <= f_raw <= 0.85:
                            d_val = f_raw
                    except ValueError:
                        d_val = None

            # OCR alternatives are evidence for review, not permission to rewrite
            # a strength. Numeric plausibility and repeated OCR cannot prove order.
            strength_verified = False
            ratio_match = re.search(r'(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)+)', raw_name)
            if ratio_match:
                raw_name, strength_verified = self._recover_multi_component_strength(
                    raw_name, name_boxes, scale_to_pt, pdf_page, img_np,
                    cell_bounds_pt=column_bounds_pt.get("name"),
                )

            storage_cond = "ثلاجة" if any(k in raw_name or k in raw_ocr_name for k in ("ثلاجة", "ثلاجه")) else None

            dosage, unit_size = parse_dosage_and_pack(raw_name) if raw_name else ("", "")
            norm_name = normalize_arabic_text(raw_name) if raw_name else ""

            engine_used = r[0].get("engine", "rapidocr") if r else "rapidocr"

            candidate = {
                "warehouse_name": warehouse_name,
                "item_name": raw_name,
                "normalized_name": norm_name,
                "dosage": dosage,
                "unit_size": unit_size,
                "base_price": p_val,
                "discount_rate": d_val,
                "stock_status": True,
                "storage_condition": storage_cond,
                "_source_id": src_id,
                "_bbox": bbox_pt,
                "_raw_ocr_text": raw_ocr_name,
                "_ocr_strength_verified": strength_verified,
                "_ocr_strength_attempts": list(self._last_strength_attempts) if ratio_match else [],
                "_search_normalized_text": norm_name,
                "_extraction_method": f"arabic_ocr_{engine_used}",
                "_ocr_engine_used": engine_used,
            }

            valid, err = validate_catalog_item(candidate)
            if valid:
                accepted_items.append(candidate)
                diagnostic_rows.append(
                    RowDiagnostic(
                        page=page_idx + 1,
                        table=table_idx,
                        group=0,
                        row=r_i,
                        outcome="accepted",
                        bbox=bbox_pt,
                        raw_cells=raw_cells_list,
                        item_name=raw_name,
                        source_id=src_id,
                        item=candidate,
                    )
                )
            else:
                # Row is unverified / uncertain -> strictly exclude from procurement
                reason_code = err or "ocr_validation_failure"
                target_cell_bbox = None
                if p_val is None and col_roles.get("price") is not None:
                    col_p = col_roles["price"]
                    target_cell_bbox = [
                        float(max(0.0, col_p - 60.0) * scale_to_pt),
                        float(r_y0 * scale_to_pt),
                        float(min(img_w, col_p + 60.0) * scale_to_pt),
                        float(r_y1 * scale_to_pt),
                    ]
                elif not raw_name and col_roles.get("name") is not None:
                    col_n = col_roles["name"]
                    target_cell_bbox = [
                        float(max(0.0, col_n - 100.0) * scale_to_pt),
                        float(r_y0 * scale_to_pt),
                        float(min(img_w, col_n + 100.0) * scale_to_pt),
                        float(r_y1 * scale_to_pt),
                    ]

                diag_row = RowDiagnostic(
                    page=page_idx + 1,
                    table=table_idx,
                    group=0,
                    row=r_i,
                    outcome="rejected",
                    reason=reason_code,
                    bbox=bbox_pt,
                    raw_cells=raw_cells_list,
                    item_name=raw_name,
                    source_id=src_id,
                    item=candidate,
                )
                diagnostic_rows.append(diag_row)
                review_issues.append(
                    ReviewIssue(
                        source_id=src_id,
                        identity=ident,
                        raw_cells=raw_cells_list,
                        bbox=bbox_pt,
                        region_bbox=target_cell_bbox,
                        column_bounds=column_bounds_pt,
                        rejection_reason=reason_code,
                        item=candidate,
                    )
                )

        return accepted_items, diagnostic_rows, review_issues

    def _recover_multi_component_strength(
        self, raw_name, name_boxes, scale_to_pt, pdf_page=None, img_np=None,
        cell_bounds_pt=None,
    ):
        """Collect bounded name-cell readings without guessing values or order.

        Line-level OCR does not expose enough evidence to certify component order.
        Keep the original text and alternatives for review. A matching digital
        source cell can corroborate the *unchanged* text; OCR consensus cannot.
        """
        self._last_strength_attempts = []
        if not raw_name or not name_boxes or not cell_bounds_pt:
            return raw_name, False
        import pymupdf
        x0, x1 = cell_bounds_pt
        y0 = min(b["bbox"][1] for b in name_boxes) * scale_to_pt
        y1 = max(b["bbox"][3] for b in name_boxes) * scale_to_pt
        rect = pymupdf.Rect(x0, y0, x1, y1)
        if rect.is_empty:
            return raw_name, False
        canonical = lambda text: "".join(text.translate(ALL_EASTERN_DIGITS).split())
        if pdf_page is not None:
            rect = rect & pdf_page.rect
            source = pdf_page.get_text("text", clip=rect).strip()
            if source and canonical(source) == canonical(raw_name):
                return raw_name, True
        # Never expand horizontally into price/code/discount columns. Keep the
        # same cell at two resolutions; do not delete suffixes or reverse runs.
        for dpi in (216, 300):
            try:
                if pdf_page is not None:
                    pix = pdf_page.get_pixmap(dpi=dpi, clip=rect)
                    crop = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    if pix.n == 4:
                        crop = cv2.cvtColor(crop, cv2.COLOR_RGBA2RGB)
                elif img_np is not None:
                    px0, py0 = max(0, int(x0 / scale_to_pt)), max(0, int(y0 / scale_to_pt))
                    px1, py1 = min(img_np.shape[1], int(x1 / scale_to_pt)), min(img_np.shape[0], int(y1 / scale_to_pt))
                    crop = img_np[py0:py1, px0:px1]
                    if not crop.size:
                        continue
                    factor = dpi * scale_to_pt / 72.0
                    crop = cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
                else:
                    break
                boxes = self._ocr_engine.extract_text_boxes(crop, engine="windows")
                self._last_strength_attempts.append({
                    "dpi": dpi, "bbox_pt": list(rect),
                    "readings": [{"text": b.get("text", ""), "bbox": b.get("bbox"),
                                  "engine": b.get("engine")} for b in boxes],
                })
            except Exception as exc:
                logger.debug("Targeted strength reading failed: %s", exc)
        return raw_name, False
