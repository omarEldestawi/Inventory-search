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

import pandas as pd
import pymupdf

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

    # Extract tokens from the PDF text stream
    stream_prices: List[float] = []
    stream_discounts: List[float] = []
    stream_name_tokens: List[str] = []

    for tok in raw_tokens:
        tok_clean = tok.translate(ALL_EASTERN_DIGITS).replace(",", ".")
        if "%" in tok or is_explicit_zero_discount(tok):
            d = parse_discount(tok)
            if 0.0 < d <= 0.85 or is_explicit_zero_discount(tok):
                stream_discounts.append(d)
        elif re.fullmatch(r"[-+]?\d+(?:\.\d+)?", tok_clean):
            try:
                num = float(tok_clean)
                if 0.0 < num < 10000.0:
                    stream_prices.append(num)
            except ValueError:
                pass
        else:
            if not is_genuine_header_cell(tok) and not is_catalog_noise(tok):
                stream_name_tokens.append(tok)

    # Determine final price
    final_price = existing_price
    if final_price is None and stream_prices:
        # If stream has prices, check if there's an unambiguous price
        valid_stream_prices = [p for p in stream_prices if 0.0 < p < 10000.0]
        if len(valid_stream_prices) == 1:
            final_price = valid_stream_prices[0]
        elif len(valid_stream_prices) > 1 and existing_discount is not None:
            # One might be price, one might be something else
            diff_prices = [p for p in valid_stream_prices if abs(p - existing_discount) > 1e-4]
            if len(diff_prices) == 1:
                final_price = diff_prices[0]

    # Determine final discount
    final_discount = existing_discount
    if final_discount is None and stream_discounts:
        valid_stream_discs = [d for d in stream_discounts if (0.0 <= d <= 0.85)]
        if len(valid_stream_discs) == 1:
            final_discount = valid_stream_discs[0]

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
        price_val = cand_b_val
    elif "%" in cand_b_raw and "%" not in cand_a_raw:
        disc_val = parse_discount(cand_b_raw)
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


def run_automatic_recovery(
    catalog_result: CatalogResult, pdf_path: Optional[str] = None
) -> CatalogResult:
    """
    Executes the 3-stage deterministic recovery engine over all unresolved review issues:
    1. Coordinate Re-extraction -> 2. Wrapped Text Reconstruction -> 3. Column Role Resolution.
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
    ]

    open_doc = None
    if pdf_path and os.path.isfile(pdf_path):
        try:
            open_doc = pymupdf.open(pdf_path)
        except Exception:
            open_doc = None

    try:
        for issue in catalog_result.review_issues:
            if issue.resolved:
                continue

            resolved_for_issue = False

            for strat_name, strat_func in strategies:
                if resolved_for_issue:
                    break

                if strat_name not in issue.attempted_strategies:
                    issue.attempted_strategies.append(strat_name)
                    attempted_count += 1

                if strat_name == "coordinate_reextraction":
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
                            disc_float = 0.0 if raw_disc is None else float(raw_disc)
                            row_dict = {
                                "warehouse_name": candidate.get("warehouse_name", default_wh),
                                "item_name": candidate["item_name"],
                                "normalized_name": cand_norm,
                                "dosage": candidate.get("dosage", dosage),
                                "unit_size": candidate.get("unit_size", unit_size),
                                "base_price": cand_price,
                                "discount_rate": disc_float,
                                "stock_status": bool(candidate.get("stock_status", True)),
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
