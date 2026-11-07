"""
Deterministic Automatic Recovery Engine (v2.5) for Egyptian Pharma Wholesaler Catalogs.

Implements the 3-stage deterministic recovery engine executing strategies strictly in order:
1. Coordinate Re-extraction: re-extract text by cell/row coordinates from the PDF vector text stream.
2. Wrapped Text Reconstruction: reconstruct multi-line wrapped Arabic and mixed Arabic/Latin medication names.
3. Column Role Resolution: resolve swapped price/discount columns and headerless continuation layout.

Strictly deterministic:
- Maximum one attempt per strategy per issue.
- Accept only a single unambiguous interpretation supported by source evidence.
- Conflicting interpretations remain unresolved for human review without guessed values.
- Never borrow values across neighboring products or other catalogs.
- Preserves existing valid records and ensures operations are idempotent.
- Routes all candidates through canonical validate_catalog_item.
"""
from __future__ import annotations

import logging
import math
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pandas as pd
import pymupdf

try:
    from .catalog_diagnostics import CatalogResult, ReviewIssue
    from .catalog_reader import (
        ALL_EASTERN_DIGITS,
        decode_custom_catalog_glyphs,
        extract_raw_float_value,
        is_arabic_text_reversed,
        is_catalog_noise,
        is_explicit_zero_discount,
        is_genuine_header_cell,
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        unreverse_arabic_text,
        validate_catalog_item,
    )
    from .image_table_detector import ImageTableDetector
    from .ocr_engine import ArabicOCREngine
except ImportError:
    from catalog_diagnostics import CatalogResult, ReviewIssue
    from catalog_reader import (
        ALL_EASTERN_DIGITS,
        decode_custom_catalog_glyphs,
        extract_raw_float_value,
        is_arabic_text_reversed,
        is_catalog_noise,
        is_explicit_zero_discount,
        is_genuine_header_cell,
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        unreverse_arabic_text,
        validate_catalog_item,
    )
    from image_table_detector import ImageTableDetector
    from ocr_engine import ArabicOCREngine

logger = logging.getLogger("CatalogRecovery")

STANDARD_COLUMNS = [
    "warehouse_name",
    "item_name",
    "normalized_name",
    "dosage",
    "unit_size",
    "base_price",
    "discount_rate",
    "stock_status",
]


def reconstruct_wrapped_name(raw_name: str) -> str:
    """
    Reconstructs wrapped multi-line medication names (Arabic, Latin, or mixed) into
    a single coherent, clinically valid medication identity without reversing Latin strings.
    """
    if not raw_name:
        return ""

    lines = [ln.strip() for ln in str(raw_name).splitlines() if ln.strip()]
    if not lines:
        return ""

    cleaned_lines: List[str] = []
    for line in lines:
        # Skip pure noise lines
        if is_catalog_noise(line) or is_genuine_header_cell(line):
            continue

        latin_count = len(re.findall(r"[a-zA-Z]", line))
        arabic_count = len(re.findall(r"[\u0600-\u06ff]", line))

        if latin_count > arabic_count:
            # Predominantly Latin: preserve forward order without splitting letters/numbers
            cleaned_lines.append(line.strip())
        elif is_arabic_text_reversed(line):
            # Arabic line detected as reversed
            decoded = decode_custom_catalog_glyphs(line)
            line_clean = unreverse_arabic_text(decoded, force_reverse=True)
            cleaned_lines.append(line_clean.strip())
        else:
            decoded = decode_custom_catalog_glyphs(line)
            cleaned_lines.append(decoded.strip())

    if not cleaned_lines:
        return str(raw_name).strip()

    reconstructed = " ".join(cleaned_lines)
    return re.sub(r"\s+", " ", reconstructed).strip()


def _extract_words_from_pdf_bbox(
    pdf_path: str,
    page_number: int,
    bbox: List[float],
    open_doc: Optional[Any] = None,
) -> List[Tuple[float, float, float, float, str, int, int, int]]:
    """Safely extracts words from a PDF page at the specified bounding box."""
    if not bbox or len(bbox) < 4:
        return []
    if open_doc is None and (not pdf_path or not os.path.isfile(pdf_path)):
        return []
    if any(not isinstance(c, (int, float)) or math.isnan(c) or math.isinf(c) for c in bbox):
        return []

    doc = open_doc
    should_close = False
    try:
        if doc is None:
            doc = pymupdf.open(pdf_path)
            should_close = True
        page_idx = page_number - 1
        if not (0 <= page_idx < len(doc)):
            return []

        page = doc[page_idx]
        clip_rect = pymupdf.Rect(bbox) + (-2.0, -2.0, 2.0, 2.0)
        words = page.get_text("words", clip=clip_rect)
        # Sort words in reading order: top-to-bottom, left-to-right
        words.sort(key=lambda w: (round(w[1], 1), w[0]))
        return words
    except Exception as e:
        logger.debug(f"Failed to extract words from PDF {pdf_path}: {e}")
        return []
    finally:
        if should_close and doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def recover_by_coordinates(
    issue: ReviewIssue,
    pdf_path: Optional[str],
    default_wh: str = "",
    open_doc: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    Strategy 1: Re-extract text by cell/row coordinates from the PDF vector text stream.
    Resolves missing extracted cells when physical text exists in the underlying stream.
    """
    if (not pdf_path and open_doc is None) or not issue.bbox or not issue.identity:
        return None

    words = _extract_words_from_pdf_bbox(pdf_path or "", issue.identity.page, issue.bbox, open_doc=open_doc)
    if not words:
        return None

    raw_tokens = [w[4].strip() for w in words if w[4].strip()]
    if not raw_tokens:
        return None

    # Check existing raw_cells for available clues
    existing_name = ""
    existing_price = None
    existing_discount = None
    existing_stock = True

    if issue.raw_cells:
        for cell in issue.raw_cells:
            if cell is None:
                continue
            s_cell = str(cell).strip()
            if not s_cell:
                continue
            # Check if discount
            if "%" in s_cell or is_explicit_zero_discount(s_cell):
                if existing_discount is None:
                    d = parse_discount(s_cell)
                    if 0.0 < d <= 0.85 or is_explicit_zero_discount(s_cell):
                        existing_discount = d
            elif re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s_cell.translate(ALL_EASTERN_DIGITS).replace(",", ".")):
                num = float(s_cell.translate(ALL_EASTERN_DIGITS).replace(",", "."))
                if 0.0 < num < 10000.0 and existing_price is None:
                    existing_price = num
            elif len(s_cell) >= 2 and not is_genuine_header_cell(s_cell) and not is_catalog_noise(s_cell):
                if not existing_name:
                    existing_name = s_cell

    # Extract tokens and coordinates from the PDF text stream using source column bounds
    column_bounds = getattr(issue, "column_bounds", None)
    bbox = issue.bbox or [0.0, 0.0, 1000.0, 1000.0]
    bbox_w = (bbox[2] - bbox[0]) if (len(bbox) >= 4 and bbox[2] > bbox[0]) else 1000.0
    if not column_bounds:
        column_bounds = {
            "discount": (bbox[0], bbox[0] + 0.28 * bbox_w),
            "name": (bbox[0] + 0.28 * bbox_w, bbox[0] + 0.70 * bbox_w),
            "code": (bbox[0] + 0.70 * bbox_w, bbox[0] + 0.86 * bbox_w),
            "price": (bbox[0] + 0.86 * bbox_w, bbox[0] + bbox_w),
        }

    stream_prices: List[Tuple[float, float]] = []  # (x_mid, val)
    stream_discounts: List[Tuple[float, float]] = []  # (x_mid, val)
    stream_name_tokens: List[str] = []

    for w in words:
        tok = w[4].strip()
        if not tok or is_genuine_header_cell(tok) or is_catalog_noise(tok):
            continue

        w_mid_x = (w[0] + w[2]) / 2.0
        role = None
        for r_name, (c_x0, c_x1) in column_bounds.items():
            if c_x0 <= w_mid_x <= c_x1:
                role = r_name
                break
        if role is None:
            role = min(
                column_bounds.keys(),
                key=lambda r_name: abs(w_mid_x - (column_bounds[r_name][0] + column_bounds[r_name][1]) / 2.0)
            )

        if role == "price":
            tok_clean = tok.translate(ALL_EASTERN_DIGITS).replace(",", ".").replace("%", "").strip()
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", tok_clean):
                try:
                    num = float(tok_clean)
                    if 0.0 < num < 10000.0:
                        stream_prices.append((w_mid_x, num))
                except ValueError:
                    pass
        elif role == "discount":
            if is_explicit_zero_discount(tok):
                stream_discounts.append((w_mid_x, 0.0))
            else:
                d = parse_discount(tok)
                if 0.0 <= d <= 0.85:
                    stream_discounts.append((w_mid_x, d))
                else:
                    tok_clean = tok.translate(ALL_EASTERN_DIGITS).replace(",", ".").replace("%", "").strip()
                    if re.fullmatch(r"\d+(?:\.\d+)?", tok_clean):
                        try:
                            v = float(tok_clean)
                            if 0.0 <= v <= 85.0:
                                stream_discounts.append((w_mid_x, v / 100.0 if v > 1.0 else v))
                        except ValueError:
                            pass
        elif role == "name":
            stream_name_tokens.append(tok)
        elif role == "code":
            # Product code column ignored for price/discount
            pass

    # Determine final price by coordinate bounds
    final_price = existing_price
    if stream_prices:
        p_center = (column_bounds["price"][0] + column_bounds["price"][1]) / 2.0
        stream_prices.sort(key=lambda t: abs(t[0] - p_center))
        final_price = stream_prices[0][1]

    # Determine final discount by coordinate bounds
    final_discount = existing_discount
    if stream_discounts:
        d_center = (column_bounds["discount"][0] + column_bounds["discount"][1]) / 2.0
        stream_discounts.sort(key=lambda t: abs(t[0] - d_center))
        final_discount = stream_discounts[0][1]

    # Determine final name
    final_name = existing_name
    if not final_name and stream_name_tokens:
        cand_name = " ".join(stream_name_tokens).strip()
        if len(cand_name) >= 2:
            final_name = cand_name

    if not final_name or final_price is None or final_discount is None:
        return None

    cleaned_name = reconstruct_wrapped_name(final_name)
    candidate = {
        "warehouse_name": default_wh or "CatalogWarehouse",
        "item_name": cleaned_name,
        "base_price": final_price,
        "discount_rate": final_discount,
        "stock_status": existing_stock,
    }

    valid, err = validate_catalog_item(candidate)
    if valid:
        return candidate
    return None


def recover_by_wrapped_text(
    issue: ReviewIssue, default_wh: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Strategy 2: Reconstruct wrapped text within the same source row.
    Handles wrapped Arabic and mixed Arabic/Latin medication names.
    """
    raw_cells = issue.raw_cells or []
    has_wrapped = any("\n" in str(c) for c in raw_cells if c)
    if not has_wrapped and issue.item and "\n" in str(issue.item.get("item_name", "")):
        has_wrapped = True

    if not has_wrapped:
        return None

    # Find wrapped name cell and numeric cells
    wrapped_name = ""
    prices: List[float] = []
    discounts: List[float] = []

    for cell in raw_cells:
        if cell is None:
            continue
        s_cell = str(cell).strip()
        if not s_cell:
            continue
        if "%" in s_cell or is_explicit_zero_discount(s_cell):
            d = parse_discount(s_cell)
            if 0.0 < d <= 0.85 or is_explicit_zero_discount(s_cell):
                discounts.append(d)
        elif re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s_cell.translate(ALL_EASTERN_DIGITS).replace(",", ".")):
            num = float(s_cell.translate(ALL_EASTERN_DIGITS).replace(",", "."))
            if 0.0 < num < 10000.0:
                prices.append(num)
        else:
            if not is_genuine_header_cell(s_cell) and not is_catalog_noise(s_cell):
                wrapped_name = s_cell if not wrapped_name else f"{wrapped_name} {s_cell}"

    if not wrapped_name and issue.item:
        wrapped_name = str(issue.item.get("item_name", "")).strip()

    if not wrapped_name:
        return None

    cleaned_name = reconstruct_wrapped_name(wrapped_name)

    # If prices/discounts in issue.item
    price = prices[0] if prices else (issue.item.get("base_price") if issue.item else None)
    discount = discounts[0] if discounts else (issue.item.get("discount_rate") if issue.item else None)

    if price is None or discount is None:
        return None

    candidate = {
        "warehouse_name": default_wh or (issue.item.get("warehouse_name") if issue.item else "CatalogWarehouse"),
        "item_name": cleaned_name,
        "base_price": price,
        "discount_rate": discount,
        "stock_status": True,
    }

    valid, err = validate_catalog_item(candidate)
    if valid:
        return candidate
    return None


def recover_by_column_roles(
    issue: ReviewIssue, default_wh: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Strategy 3: Resolve column roles using explicit cues, swapped price/discount,
    or established geometrically compatible layout.
    Strictly deterministic: ambiguous interpretations remain unresolved.
    """
    raw_cells = issue.raw_cells or []
    if not raw_cells or len(raw_cells) < 2:
        return None

    # Separate text and numeric candidates
    text_candidates: List[str] = []
    num_candidates: List[Tuple[float, str]] = []  # (value, raw_str)

    for c in raw_cells:
        if c is None:
            continue
        s_c = str(c).strip()
        if not s_c:
            continue
        s_num = s_c.translate(ALL_EASTERN_DIGITS).replace("%", "").replace(",", ".").strip()
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s_num):
            try:
                val = float(s_num)
                num_candidates.append((val, s_c))
            except ValueError:
                pass
        elif len(s_c) >= 2 and not is_genuine_header_cell(s_c) and not is_catalog_noise(s_c):
            text_candidates.append(s_c)

    if len(text_candidates) != 1 or len(num_candidates) != 2:
        return None

    med_name = reconstruct_wrapped_name(text_candidates[0])

    cand_a_val, cand_a_raw = num_candidates[0]
    cand_b_val, cand_b_raw = num_candidates[1]

    # Check for disambiguating cues:
    # A has %, B does not -> A is discount, B is price
    # B has %, A does not -> B is discount, A is price
    # One is > 0.85 and other <= 0.85 (and not ambiguous)
    price_val: Optional[float] = None
    disc_val: Optional[float] = None

    if "%" in cand_a_raw and "%" not in cand_b_raw:
        disc_val = parse_discount(cand_a_raw)
        if disc_val == 0.0 and not is_explicit_zero_discount(cand_a_raw):
            return None
        price_val = cand_b_val
    elif "%" in cand_b_raw and "%" not in cand_a_raw:
        disc_val = parse_discount(cand_b_raw)
        if disc_val == 0.0 and not is_explicit_zero_discount(cand_b_raw):
            return None
        price_val = cand_a_val
    elif is_explicit_zero_discount(cand_a_raw) and "%" not in cand_b_raw and not is_explicit_zero_discount(cand_b_raw):
        disc_val = 0.0
        price_val = cand_b_val
    elif is_explicit_zero_discount(cand_b_raw) and "%" not in cand_a_raw and not is_explicit_zero_discount(cand_a_raw):
        disc_val = 0.0
        price_val = cand_a_val
    elif "%" not in cand_a_raw and "%" not in cand_b_raw and cand_a_val > 0.85 and cand_b_val <= 0.85 and cand_b_val >= 0.0:
        # cand_a must be price, cand_b is discount
        price_val = cand_a_val
        disc_val = cand_b_val
    elif "%" not in cand_a_raw and "%" not in cand_b_raw and cand_b_val > 0.85 and cand_a_val <= 0.85 and cand_a_val >= 0.0:
        # cand_b must be price, cand_a is discount
        price_val = cand_b_val
        disc_val = cand_a_val
    else:
        # Both values are ambiguous (e.g. 50.0 and 60.0 without % sign)
        # Must remain unresolved for human review without guessed values
        return None

    if price_val is not None and disc_val is not None:
        if 0.0 < price_val < 10000.0 and (0.0 <= disc_val <= 0.85):
            candidate = {
                "warehouse_name": default_wh or "CatalogWarehouse",
                "item_name": med_name,
                "base_price": price_val,
                "discount_rate": disc_val,
                "stock_status": True,
            }
            valid, _ = validate_catalog_item(candidate)
            if valid:
                return candidate

    return None


def deskew_and_enhance_image(img_np: np.ndarray, apply_clahe: bool = True) -> np.ndarray:
    """
    Applies bounded affine deskewing for |θ| > 0.5° and CLAHE adaptive contrast.
    Strictly bans global Otsu binarization and enforces bounded resolution.
    """
    if img_np is None or img_np.size == 0:
        return img_np

    res = img_np.copy()
    gray = cv2.cvtColor(res, cv2.COLOR_RGB2GRAY) if len(res.shape) == 3 else res

    # Affine deskewing for |θ| > 0.5°
    pts = np.column_stack(np.where(gray < 220))
    if len(pts) > 50:
        rect = cv2.minAreaRect(pts[:, ::-1])
        angle = rect[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if 0.5 < abs(angle) < 45.0:
            h, w = res.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            res = cv2.warpAffine(res, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    if apply_clahe:
        if len(res.shape) == 3:
            lab = cv2.cvtColor(res, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            res = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2RGB)
        else:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            res = clahe.apply(res)

    return res


def _evaluate_ocr_candidate_on_crop(
    img_np: np.ndarray,
    ocr_engine: ArabicOCREngine,
    default_wh: str,
    issue: ReviewIssue,
    engine_pref: str = "primary",
) -> Optional[Dict[str, Any]]:
    """Runs OCR on cropped cell/row image and evaluates candidate item."""
    if img_np is None or img_np.size == 0:
        return None

    # Establish whether target crop is physically blank using source ink evidence
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY) if len(img_np.shape) == 3 else img_np
    ink_pixels = np.count_nonzero(gray < 190)
    total_pixels = gray.size
    ink_ratio = ink_pixels / float(total_pixels) if total_pixels > 0 else 0.0
    if ink_ratio < 0.005:
        # Source evidence confirms cell has no visible ink
        return None

    boxes = ocr_engine.extract_text_boxes(img_np, engine=engine_pref)
    if not boxes:
        return None

    boxes.sort(key=lambda b: b["bbox"][0])
    raw_texts = [b["text"].strip() for b in boxes if b["text"].strip()]
    if not raw_texts:
        return None

    existing_name = ""
    existing_price = None
    existing_discount = None
    if issue.raw_cells:
        if len(issue.raw_cells) == 3 and not (issue.raw_cells[0] == "[ocr_empty_page]"):
            # Position-aware raw_cells from image table detector: [name, price, discount]
            name_c, price_c, disc_c = issue.raw_cells[0], issue.raw_cells[1], issue.raw_cells[2]
            if name_c and len(str(name_c).strip()) >= 2 and not is_genuine_header_cell(str(name_c)) and not is_catalog_noise(str(name_c)):
                existing_name = str(name_c).strip()
            if price_c:
                sp = str(price_c).strip().translate(ALL_EASTERN_DIGITS).replace(",", ".")
                if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", sp):
                    try:
                        v = float(sp)
                        if 0.0 < v < 10000.0:
                            existing_price = v
                    except ValueError:
                        pass
            if disc_c:
                sd = str(disc_c).strip()
                if "%" in sd or is_explicit_zero_discount(sd):
                    d = parse_discount(sd)
                    if 0.0 <= d <= 0.85:
                        existing_discount = d
                else:
                    sd_num = sd.translate(ALL_EASTERN_DIGITS).replace(",", ".")
                    if re.fullmatch(r"\d+(?:\.\d+)?", sd_num):
                        try:
                            vd = float(sd_num)
                            if 0.0 <= vd <= 85.0:
                                existing_discount = vd / 100.0 if vd > 1.0 else vd
                        except ValueError:
                            pass
        else:
            for c in issue.raw_cells:
                if not c:
                    continue
                sc = str(c).strip()
                if "%" in sc or is_explicit_zero_discount(sc):
                    d = parse_discount(sc)
                    if 0.0 <= d <= 0.85:
                        existing_discount = d
                elif re.fullmatch(r"[-+]?\d+(?:\.\d+)?", sc.translate(ALL_EASTERN_DIGITS).replace(",", ".")):
                    v = float(sc.translate(ALL_EASTERN_DIGITS).replace(",", "."))
                    if 0.0 < v < 10000.0 and existing_price is None:
                        existing_price = v
                elif len(sc) >= 2 and not is_genuine_header_cell(sc) and not is_catalog_noise(sc):
                    existing_name = sc

    found_price = existing_price
    found_disc = existing_discount
    name_tokens: List[str] = []

    is_name_issue = issue.rejection_reason in ("blank_name", "empty_name_cell", "name_too_short")
    is_price_issue = issue.rejection_reason in ("missing_price", "invalid_price", "zero_price")
    is_disc_issue = issue.rejection_reason in ("missing_discount", "invalid_discount")

    # Establish physical coordinates of the cropped region
    crop_w = float(img_np.shape[1])
    crop_bbox = issue.region_bbox or issue.bbox or [0.0, 0.0, crop_w, float(img_np.shape[0])]
    crop_w_pt = (crop_bbox[2] - crop_bbox[0]) if (crop_bbox and len(crop_bbox) >= 4) else crop_w
    if crop_w_pt <= 0.0:
        crop_w_pt = crop_w

    # Determine whether crop is a targeted single-cell crop vs a full multi-column row band
    is_targeted_single_cell = bool(
        issue.region_bbox
        and issue.bbox
        and len(issue.region_bbox) >= 4
        and len(issue.bbox) >= 4
        and (issue.region_bbox[2] - issue.region_bbox[0]) < 0.65 * (issue.bbox[2] - issue.bbox[0])
    )

    column_bounds = getattr(issue, "column_bounds", None)
    if not is_targeted_single_cell and not column_bounds:
        # Default Egyptian wholesaler RTL column bounds in PDF points
        column_bounds = {
            "discount": (crop_bbox[0], crop_bbox[0] + 0.28 * crop_w_pt),
            "name": (crop_bbox[0] + 0.28 * crop_w_pt, crop_bbox[0] + 0.70 * crop_w_pt),
            "code": (crop_bbox[0] + 0.70 * crop_w_pt, crop_bbox[0] + 0.86 * crop_w_pt),
            "price": (crop_bbox[0] + 0.86 * crop_w_pt, crop_bbox[0] + crop_w_pt),
        }

    price_tokens: List[Tuple[float, float]] = []  # (x_center_pt, val)
    disc_tokens: List[Tuple[float, float]] = []   # (x_center_pt, val)

    for b in boxes:
        txt = b["text"].strip()
        if not txt or is_genuine_header_cell(txt):
            continue

        # Physical horizontal center of box in PDF points
        bx_mid_px = (b["bbox"][0] + b["bbox"][2]) / 2.0
        bx_mid_pt = crop_bbox[0] + (bx_mid_px / crop_w) * crop_w_pt

        # Determine cell role by actual coordinates
        role: Optional[str] = None
        if is_targeted_single_cell:
            if is_price_issue:
                role = "price"
            elif is_disc_issue:
                role = "discount"
            elif is_name_issue:
                role = "name"
        elif column_bounds:
            # Map box to designated column bounds
            for r_name, (c_x0, c_x1) in column_bounds.items():
                if c_x0 <= bx_mid_pt <= c_x1:
                    role = r_name
                    break
            if role is None:
                # Closest column interval if slight edge margin
                role = min(
                    column_bounds.keys(),
                    key=lambda r_name: abs(bx_mid_pt - (column_bounds[r_name][0] + column_bounds[r_name][1]) / 2.0)
                )

        if role == "price":
            clean_num = txt.translate(ALL_EASTERN_DIGITS).replace(",", ".").replace("%", "").strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", clean_num):
                try:
                    val = float(clean_num)
                    if 0.0 < val < 10000.0:
                        price_tokens.append((bx_mid_pt, val))
                except ValueError:
                    pass
        elif role == "discount":
            if is_explicit_zero_discount(txt):
                disc_tokens.append((bx_mid_pt, 0.0))
            else:
                clean_num = txt.translate(ALL_EASTERN_DIGITS).replace(",", ".").replace("%", "").strip()
                if re.fullmatch(r"\d+(?:\.\d+)?", clean_num):
                    try:
                        val = float(clean_num)
                        if 0.0 <= val <= 85.0:
                            d_rate = val / 100.0 if val > 1.0 else val
                            disc_tokens.append((bx_mid_pt, d_rate))
                    except ValueError:
                        pass
        elif role == "name":
            if not is_name_issue or not ("%" in txt or re.fullmatch(r"[%0-9I\.\s]+", txt)):
                if not is_catalog_noise(txt):
                    name_tokens.append(txt)
        elif role == "code":
            # Product code column: ignored for price/discount to prevent overwriting
            pass

    if price_tokens:
        if column_bounds and "price" in column_bounds:
            p_center = (column_bounds["price"][0] + column_bounds["price"][1]) / 2.0
            price_tokens.sort(key=lambda t: abs(t[0] - p_center))
        found_price = price_tokens[0][1]

    if disc_tokens:
        if column_bounds and "discount" in column_bounds:
            d_center = (column_bounds["discount"][0] + column_bounds["discount"][1]) / 2.0
            disc_tokens.sort(key=lambda t: abs(t[0] - d_center))
        found_disc = disc_tokens[0][1]

    final_name = " ".join(name_tokens).strip() or existing_name
    if not final_name or found_price is None:
        return None

    wh_name = ""
    if issue.item and isinstance(issue.item, dict):
        wh_name = issue.item.get("warehouse_name", "")
    if not wh_name:
        wh_name = default_wh or "CatalogWarehouse"

    dosage, unit_size = parse_dosage_and_pack(final_name)
    engine_used = boxes[0].get("engine", "windows_media_ocr" if ocr_engine.is_windows_ocr_available() else "rapidocr") if boxes else "primary"
    candidate = {
        "warehouse_name": wh_name,
        "item_name": final_name,
        "base_price": found_price,
        "discount_rate": found_disc,  # Preserved as None if missing/unreadable, distinct from 0.0
        "dosage": dosage,
        "unit_size": unit_size,
        "stock_status": True,
        "_source_id": issue.source_id,
        "_bbox": issue.bbox,
        "_raw_ocr_text": " ".join(raw_texts),
        "_extraction_method": f"ocr_recovery_{engine_pref}",
        "_ocr_engine_used": engine_used,
    }
    return candidate


def recover_by_ocr_ladder(
    issue: ReviewIssue,
    pdf_path: Optional[str],
    default_wh: str = "",
    open_doc: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    Strategy 4: Bounded OCR recovery ladder executing strictly in order:
      - Tier 0: 150 DPI native RGB, auto-orientation, primary Arabic OCR engine.
      - Tier 1: 200 DPI (capped at 200 DPI; ban 300+) + CLAHE + affine deskewing for |θ| > 0.5°
                (strict ban on global Otsu).
      - Tier 2: Secondary engine (Windows Media OCR fast-path).
    Monotonic quality retention: returns first unambiguously valid candidate passing validate_catalog_item.
    """
    if not pdf_path and open_doc is None:
        return None
    
    # Target specific cell region if available, otherwise row bbox
    bbox = issue.region_bbox or issue.bbox
    if not bbox or not issue.identity or len(bbox) < 4:
        return None

    page_num = issue.identity.page

    doc = open_doc
    should_close = False
    try:
        if doc is None:
            if not pdf_path or not os.path.isfile(pdf_path):
                return None
            doc = pymupdf.open(pdf_path)
            should_close = True

        page_idx = page_num - 1
        if not (0 <= page_idx < len(doc)):
            return None

        page = doc[page_idx]
        clip_rect = pymupdf.Rect(bbox) + (-4.0, -4.0, 4.0, 4.0)
        clip_rect = clip_rect & page.rect
        if clip_rect.is_empty or clip_rect.width < 5 or clip_rect.height < 5:
            return None

        ocr_engine = ArabicOCREngine()
        if not ocr_engine.is_available():
            return None

        # TIER 0: 150 DPI native RGB, Primary Engine
        pix0 = page.get_pixmap(dpi=150, clip=clip_rect)
        img0 = np.frombuffer(pix0.samples, dtype=np.uint8).reshape(pix0.height, pix0.width, pix0.n)
        if pix0.n == 4:
            img0 = cv2.cvtColor(img0, cv2.COLOR_RGBA2RGB)

        cand0 = _evaluate_ocr_candidate_on_crop(img0, ocr_engine, default_wh, issue, engine_pref="primary")
        if cand0:
            valid, _ = validate_catalog_item(cand0)
            if valid:
                return cand0

        # TIER 1: 200 DPI + CLAHE + Affine Deskewing (|θ| > 0.5°), Primary Engine
        pix1 = page.get_pixmap(dpi=200, clip=clip_rect)
        img1 = np.frombuffer(pix1.samples, dtype=np.uint8).reshape(pix1.height, pix1.width, pix1.n)
        if pix1.n == 4:
            img1 = cv2.cvtColor(img1, cv2.COLOR_RGBA2RGB)

        enhanced1 = deskew_and_enhance_image(img1, apply_clahe=True)
        cand1 = _evaluate_ocr_candidate_on_crop(enhanced1, ocr_engine, default_wh, issue, engine_pref="primary")
        if cand1:
            valid, _ = validate_catalog_item(cand1)
            if valid:
                return cand1

        # TIER 2: Secondary Engine (Windows Media OCR fast-path)
        if ocr_engine.is_windows_ocr_available():
            cand2 = _evaluate_ocr_candidate_on_crop(img0, ocr_engine, default_wh, issue, engine_pref="secondary")
            if cand2:
                valid, _ = validate_catalog_item(cand2)
                if valid:
                    return cand2

        return None
    except Exception as exc:
        logger.debug(f"OCR ladder recovery failed for issue {issue.source_id}: {exc}")
        return None
    finally:
        if should_close and doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def recover_region_by_ocr(
    issue: ReviewIssue,
    pdf_path: Optional[str],
    default_wh: str = "",
    open_doc: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Executes bounded OCR table recovery on an unmapped or image-only region.
    Tiers: Tier 0 (150 DPI RGB) -> Tier 1 (200 DPI + CLAHE deskew) -> Tier 2 (Secondary engine).
    """
    if not pdf_path and open_doc is None:
        return []
    if not issue.identity:
        return []

    page_num = issue.identity.page
    bbox = issue.bbox

    doc = open_doc
    should_close = False
    try:
        if doc is None:
            if not pdf_path or not os.path.isfile(pdf_path):
                return []
            doc = pymupdf.open(pdf_path)
            should_close = True

        page_idx = page_num - 1
        if not (0 <= page_idx < len(doc)):
            return []

        page = doc[page_idx]
        clip_rect = pymupdf.Rect(bbox) if (bbox and len(bbox) == 4) else page.rect
        clip_rect = clip_rect & page.rect
        if clip_rect.is_empty:
            return []

        detector = ImageTableDetector()
        scale_to_pt_150 = 72.0 / 150.0

        # Tier 0: 150 DPI native RGB
        pix0 = page.get_pixmap(dpi=150, clip=clip_rect)
        img0 = np.frombuffer(pix0.samples, dtype=np.uint8).reshape(pix0.height, pix0.width, pix0.n)
        if pix0.n == 4:
            img0 = cv2.cvtColor(img0, cv2.COLOR_RGBA2RGB)

        accepted0, _, _ = detector.extract_table_records(
            img0, page_idx=page_idx, warehouse_name=default_wh, scale_to_pt=scale_to_pt_150, ocr_engine_preference="primary"
        )
        if len(accepted0) >= 1:
            return accepted0

        # Tier 1: 200 DPI + CLAHE + deskew
        scale_to_pt_200 = 72.0 / 200.0
        pix1 = page.get_pixmap(dpi=200, clip=clip_rect)
        img1 = np.frombuffer(pix1.samples, dtype=np.uint8).reshape(pix1.height, pix1.width, pix1.n)
        if pix1.n == 4:
            img1 = cv2.cvtColor(img1, cv2.COLOR_RGBA2RGB)

        enhanced1 = deskew_and_enhance_image(img1, apply_clahe=True)
        accepted1, _, _ = detector.extract_table_records(
            enhanced1, page_idx=page_idx, warehouse_name=default_wh, scale_to_pt=scale_to_pt_200, ocr_engine_preference="primary"
        )
        if len(accepted1) >= 1:
            return accepted1

        # Tier 2: Secondary engine
        accepted2, _, _ = detector.extract_table_records(
            img0, page_idx=page_idx, warehouse_name=default_wh, scale_to_pt=scale_to_pt_150, ocr_engine_preference="secondary"
        )
        if len(accepted2) >= 1:
            return accepted2

        return []
    except Exception as exc:
        logger.debug(f"Region OCR recovery failed for issue {issue.source_id}: {exc}")
        return []
    finally:
        if should_close and doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def run_automatic_recovery(
    catalog_result: CatalogResult, pdf_path: Optional[str] = None
) -> CatalogResult:
    """
    Executes the 4-stage bounded deterministic recovery engine over all unresolved review issues:
    1. Coordinate Re-extraction -> 2. Wrapped Text Reconstruction -> 3. Column Role Resolution -> 4. OCR Recovery Ladder.
    Preserves all existing valid records and ensures idempotent execution.
    """
    if catalog_result is None:
        return catalog_result

    # Determine PDF source path if not provided
    if pdf_path is None and catalog_result.fingerprint is not None:
        pdf_path = catalog_result.fingerprint.path

    default_wh = ""
    if len(catalog_result.dataframe) > 0 and "warehouse_name" in catalog_result.dataframe.columns:
        default_wh = str(catalog_result.dataframe["warehouse_name"].iloc[0])

    updated_df = catalog_result.dataframe.copy(deep=True)
    existing_source_ids = set()
    if "_source_id" in updated_df.columns:
        existing_source_ids = set(updated_df["_source_id"].dropna())

    attempted_count = 0
    recovered_count = 0

    strategies = [
        ("coordinate_reextraction", recover_by_coordinates),
        ("wrapped_text_reconstruction", recover_by_wrapped_text),
        ("column_role_resolution", recover_by_column_roles),
        ("ocr_recovery_ladder", recover_by_ocr_ladder),
    ]

    open_doc = None
    if pdf_path and os.path.isfile(pdf_path):
        try:
            open_doc = pymupdf.open(pdf_path)
        except Exception:
            open_doc = None

    try:
        for issue in catalog_result.review_issues:
            # Generic row recovery must not erase unresolved strength evidence
            # and then approve a differently transcribed numeric sequence.
            if issue.rejection_reason in ("unverified_ocr_strength_sequence", "ambiguous_ocr_decimal"):
                continue
            if issue.resolved:
                continue

            # Check if this is a region-level issue (image_only or unmapped table region)
            is_region = bool(
                getattr(issue, "is_region_level", False)
                or getattr(issue.identity, "is_region_issue", False)
                or issue.source_id.endswith("_region")
            )
            if is_region:
                if "ocr_recovery_ladder" not in issue.attempted_strategies:
                    issue.attempted_strategies.append("ocr_recovery_ladder")
                    attempted_count += 1

                reg_items = recover_region_by_ocr(issue, pdf_path, default_wh, open_doc=open_doc)
                if reg_items:
                    issue.resolved = True
                    issue.provenance = "ocr_recovery_ladder"
                    issue.strategy_outcomes["ocr_recovery_ladder"] = f"recovered_{len(reg_items)}_items"
                    recovered_count += len(reg_items)

                    for it in reg_items:
                        src_id = it.get("_source_id", f"p{issue.identity.page if issue.identity else 1}_t0_rec_{len(updated_df)}")
                        if src_id not in existing_source_ids:
                            dosage, unit_size = parse_dosage_and_pack(it["item_name"])
                            cand_norm = it.get("normalized_name") or normalize_arabic_text(it["item_name"])
                            row_dict = {
                                "warehouse_name": it.get("warehouse_name") or default_wh or "CatalogWarehouse",
                                "item_name": it["item_name"],
                                "normalized_name": cand_norm,
                                "dosage": it.get("dosage", dosage),
                                "unit_size": it.get("unit_size", unit_size),
                                "base_price": float(it["base_price"]),
                                "discount_rate": float(it["discount_rate"]) if it.get("discount_rate") is not None else None,
                                "stock_status": bool(it.get("stock_status", True)),
                                "_source_id": src_id,
                                "_bbox": it.get("_bbox", issue.bbox),
                                "_raw_ocr_text": it.get("_raw_ocr_text", ""),
                                "_search_normalized_text": cand_norm,
                                "_extraction_method": it.get("_extraction_method", "ocr_recovery_ladder"),
                                "_ocr_engine_used": it.get("_ocr_engine_used", "windows_media_ocr"),
                            }
                            updated_df = pd.concat([updated_df, pd.DataFrame([row_dict])], ignore_index=True)
                            existing_source_ids.add(src_id)
                    continue
                else:
                    issue.strategy_outcomes["ocr_recovery_ladder"] = "failed"
                    continue

            resolved_for_issue = False

            for strat_name, strat_func in strategies:
                if resolved_for_issue:
                    break

                if strat_name not in issue.attempted_strategies:
                    issue.attempted_strategies.append(strat_name)
                    attempted_count += 1

                if strat_name in ("coordinate_reextraction", "ocr_recovery_ladder"):
                    candidate = strat_func(issue, pdf_path, default_wh, open_doc=open_doc)
                else:
                    candidate = strat_func(issue, default_wh)

                if candidate:
                    valid, err = validate_catalog_item(candidate)
                    if valid:
                        issue.resolved = True
                        issue.provenance = "automatic_recovery"
                        issue.item = candidate
                        issue.strategy_outcomes[strat_name] = "recovered"
                        recovered_count += 1
                        resolved_for_issue = True

                        # Add row to DataFrame if not already present
                        cand_norm = candidate.get("normalized_name") or normalize_arabic_text(candidate["item_name"])
                        cand_price = float(candidate["base_price"])

                        already_in_df = False
                        if len(updated_df) > 0 and "normalized_name" in updated_df.columns and "base_price" in updated_df.columns:
                            already_in_df = any(
                                (row_n == cand_norm and abs(row_p - cand_price) < 0.01)
                                for row_n, row_p in zip(updated_df["normalized_name"], updated_df["base_price"])
                            )

                        src_id = issue.source_id
                        if src_id not in existing_source_ids and not already_in_df:
                            dosage, unit_size = parse_dosage_and_pack(candidate["item_name"])
                            raw_disc = candidate.get("discount_rate")
                            disc_val = float(raw_disc) if raw_disc is not None else None
                            row_dict = {
                                "warehouse_name": candidate.get("warehouse_name") or default_wh or "CatalogWarehouse",
                                "item_name": candidate["item_name"],
                                "normalized_name": cand_norm,
                                "dosage": candidate.get("dosage", dosage),
                                "unit_size": candidate.get("unit_size", unit_size),
                                "base_price": cand_price,
                                "discount_rate": disc_val,
                                "stock_status": bool(candidate.get("stock_status", True)),
                                "_source_id": candidate.get("_source_id", src_id),
                                "_bbox": candidate.get("_bbox", issue.bbox),
                                "_raw_ocr_text": candidate.get("_raw_ocr_text", ""),
                                "_search_normalized_text": candidate.get("_search_normalized_text", cand_norm),
                                "_extraction_method": candidate.get("_extraction_method", "ocr_recovery_ladder"),
                                "_ocr_engine_used": candidate.get("_ocr_engine_used", "windows_media_ocr"),
                            }
                            updated_df = pd.concat([updated_df, pd.DataFrame([row_dict])], ignore_index=True)
                            existing_source_ids.add(src_id)
                    else:
                        issue.strategy_outcomes[strat_name] = f"validation_error: {err}"
                else:
                    issue.strategy_outcomes[strat_name] = (
                        "unresolved_ambiguity" if strat_name == "column_role_resolution" else "failed"
                    )
    finally:
        if open_doc is not None:
            try:
                open_doc.close()
            except Exception:
                pass

    # Update diagnostics accounting
    if catalog_result.diagnostics is not None:
        catalog_result.diagnostics.attempted_recovery_count += attempted_count
        catalog_result.diagnostics.successful_recovery_count += recovered_count
        catalog_result.diagnostics.accepted_rows = len(updated_df)
        catalog_result.diagnostics.unique_records = len(updated_df)

        # Update matching RowDiagnostic in diagnostics pages/groups
        for page in catalog_result.diagnostics.pages:
            for grp in page.groups:
                for r_diag in grp.rows:
                    if r_diag.source_id in catalog_result.issues_by_source_id:
                        iss = catalog_result.issues_by_source_id[r_diag.source_id]
                        if iss.resolved:
                            r_diag.outcome = "recovered"
                            r_diag.attempted_strategies = list(iss.attempted_strategies)
                            r_diag.provenance = iss.provenance
                            if iss.item and iss.item.get("item_name"):
                                r_diag.item_name = iss.item["item_name"]

    if "base_price" in updated_df.columns:
        updated_df["base_price"] = pd.to_numeric(updated_df["base_price"], errors="coerce").astype(float)
    if "discount_rate" in updated_df.columns:
        updated_df["discount_rate"] = pd.to_numeric(updated_df["discount_rate"], errors="coerce").astype(float)

    catalog_result.dataframe = updated_df
    return catalog_result
