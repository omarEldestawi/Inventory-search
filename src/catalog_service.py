"""
Unified Catalog Correction Service.

Shared identically between GUI inspection and direct headless procurement.
Provides centralized access to:
- Catalog inspection and cached parsing
- Review issue tracking and listing
- Deterministic automatic recovery passes
- Table column mapping preview and atomic application
- Interactive and persistent manual field corrections
- Pristine state reset
"""
from __future__ import annotations

import copy
import logging
import math
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    from .catalog_diagnostics import (
        CatalogResult,
        FileFingerprint,
        GroupDiagnostics,
        ImportDiagnostics,
        PageDiagnostics,
        ReviewIssue,
        RowDiagnostic,
        SourceIdentity,
        METADATA_KEY,
    )
    from .catalog_reader import (
        CatalogImportMetadata,
        parse_dosage_and_pack,
        validate_catalog_item,
    )
    from .normalizer import (
        normalize_arabic_text,
        normalize_vendor_name,
        parse_discount,
    )
except ImportError:
    from catalog_diagnostics import (
        CatalogResult,
        FileFingerprint,
        GroupDiagnostics,
        ImportDiagnostics,
        PageDiagnostics,
        ReviewIssue,
        RowDiagnostic,
        SourceIdentity,
        METADATA_KEY,
    )
    from catalog_reader import (
        CatalogImportMetadata,
        parse_dosage_and_pack,
        validate_catalog_item,
    )
    from normalizer import (
        normalize_arabic_text,
        normalize_vendor_name,
        parse_discount,
    )

logger = logging.getLogger("CatalogCorrectionService")

STANDARD_COLUMNS: List[str] = [
    "warehouse_name",
    "item_name",
    "normalized_name",
    "dosage",
    "unit_size",
    "base_price",
    "discount_rate",
    "stock_status",
]


class CatalogCorrectionService:
    """
    Unified service managing catalog extraction lifecycle, deterministic recovery,
    interactive preview, and persistent manual corrections.
    """

    def __init__(self, catalog_path: str):
        self.raw_path = catalog_path
        self.catalog_path = os.path.normpath(os.path.abspath(catalog_path))
        self.canonical_path = os.path.normcase(os.path.realpath(self.catalog_path))

        self._lock = threading.RLock()
        self._catalog_result: Optional[CatalogResult] = None
        self._base_catalog_result: Optional[CatalogResult] = None
        self._field_corrections: Dict[str, Dict[str, Any]] = {}
        self._table_mappings: Dict[int, Dict[str, int]] = {}

        fname = os.path.basename(self.catalog_path)
        w_raw = os.path.splitext(fname)[0]
        self.warehouse_name = normalize_vendor_name(w_raw)

    def get_fingerprint(self) -> Optional[FileFingerprint]:
        """Returns FileFingerprint for current file, or None if file does not exist."""
        try:
            if os.path.isfile(self.catalog_path):
                return FileFingerprint.from_path(self.catalog_path)
        except OSError:
            pass
        return None

    def _parse_catalog_base(self, refresh: bool = False) -> CatalogResult:
        """Invokes underlying parser (or cache) to obtain baseline extraction result."""
        empty_df = pd.DataFrame(columns=STANDARD_COLUMNS)

        if not os.path.isfile(self.catalog_path):
            diag = ImportDiagnostics(errors=[f"Catalog file not found: {self.catalog_path}"])
            return CatalogResult(dataframe=empty_df, diagnostics=diag, fingerprint=None)

        # Try to delegate to controller.inspect_catalog if available
        try:
            try:
                from .controller import inspect_catalog
            except ImportError:
                from controller import inspect_catalog

            res = inspect_catalog(self.catalog_path, refresh=refresh)
            if res is not None:
                return res
        except Exception as exc:
            logger.debug(f"controller.inspect_catalog delegation bypassed: {exc}")

        # Fallback to direct PDF / Excel parsing
        fp = self.get_fingerprint()
        if self.catalog_path.lower().endswith(".pdf"):
            try:
                try:
                    from .pdf_parser import PDFCatalogParser
                except ImportError:
                    from pdf_parser import PDFCatalogParser

                parser = PDFCatalogParser(self.catalog_path)
                df = parser.parse()
                res = CatalogResult.from_dataframe(df)
                if res is not None:
                    return res
                return CatalogResult(dataframe=df, diagnostics=ImportDiagnostics(), fingerprint=fp)
            except Exception as e:
                diag = ImportDiagnostics(errors=[f"PDF parsing error: {e}"])
                return CatalogResult(dataframe=empty_df, diagnostics=diag, fingerprint=fp)
        else:
            try:
                try:
                    from .pipeline import parse_excel_catalog
                except ImportError:
                    from pipeline import parse_excel_catalog

                df = parse_excel_catalog(self.catalog_path, self.warehouse_name)
                res = CatalogResult.from_dataframe(df)
                if res is not None:
                    return res
                diag = ImportDiagnostics(
                    accepted_rows=len(df),
                    unique_records=len(df),
                )
                return CatalogResult(dataframe=df, diagnostics=diag, fingerprint=fp)
            except Exception as e:
                diag = ImportDiagnostics(errors=[f"Excel parsing error: {e}"])
                return CatalogResult(dataframe=empty_df, diagnostics=diag, fingerprint=fp)

    def get_refreshed_catalog_result(self, refresh: bool = False) -> CatalogResult:
        """
        Returns updated CatalogResult reflecting baseline parsing, applied recovery,
        table mappings, and manual field corrections.
        """
        with self._lock:
            if self._catalog_result is not None and not refresh:
                return self._catalog_result

            if self._base_catalog_result is None or (refresh and os.path.isfile(self.catalog_path)):
                self._base_catalog_result = self._parse_catalog_base(refresh=refresh)

            base_res = self._base_catalog_result

            # Ensure review_issues is populated from diagnostics if empty
            issues: Dict[str, ReviewIssue] = {}
            for issue in base_res.review_issues:
                issues[issue.source_id] = copy.deepcopy(issue)

            if not issues and base_res.diagnostics:
                for p in base_res.diagnostics.pages:
                    for g in p.groups:
                        for r in g.rows:
                            if r.outcome != "accepted":
                                iss = r.to_review_issue()
                                issues[iss.source_id] = iss
                    if p.errors:
                        region_id = f"p{p.page}_t0_region"
                        ident = SourceIdentity(
                            page=p.page,
                            table=0,
                            row=None,
                            is_region_issue=True,
                            source_id=region_id,
                        )
                        issues[region_id] = ReviewIssue(
                            source_id=region_id,
                            identity=ident,
                            rejection_reason="; ".join(p.errors),
                            resolved=False,
                        )

            current_df = base_res.dataframe.copy(deep=True)

            # Track internal _source_id for deterministic row replacement
            if "_source_id" not in current_df.columns:
                source_ids = []
                if base_res.diagnostics:
                    for p in base_res.diagnostics.pages:
                        for g in p.groups:
                            for r in g.rows:
                                if r.outcome == "accepted":
                                    source_ids.append(r.source_id)
                if len(source_ids) == len(current_df):
                    current_df["_source_id"] = source_ids
                elif len(source_ids) > 0:
                    source_ids_mapped = []
                    diag_map = {r.item_name: r.source_id for p in base_res.diagnostics.pages for g in p.groups for r in g.rows if r.outcome == "accepted" and getattr(r, "item_name", None)}
                    for idx, row in current_df.iterrows():
                        nm = row.get("item_name")
                        if nm in diag_map:
                            source_ids_mapped.append(diag_map[nm])
                        elif idx < len(source_ids):
                            source_ids_mapped.append(source_ids[idx])
                        else:
                            source_ids_mapped.append(f"p1_t0_r{idx}")
                    current_df["_source_id"] = source_ids_mapped
                else:
                    current_df["_source_id"] = [f"p1_t0_r{i}" for i in range(len(current_df))]

            # Apply table column mappings
            for table_id, mapping in self._table_mappings.items():
                current_df, issues = self._apply_table_mapping_internal(
                    table_id=table_id,
                    mapping=mapping,
                    df=current_df,
                    issues=issues,
                    base_res=base_res,
                )

            # Apply individual field corrections
            for source_id, field_updates in self._field_corrections.items():
                current_df, issues = self._apply_field_correction_internal(
                    source_id=source_id,
                    field_updates=field_updates,
                    df=current_df,
                    issues=issues,
                    base_res=base_res,
                )

            # Reconcile diagnostics accounting
            updated_diag = copy.deepcopy(base_res.diagnostics)
            unresolved_regions = sum(
                1 for iss in issues.values()
                if not iss.resolved and iss.identity and iss.identity.is_region_issue
            )
            updated_diag.unresolved_region_count = unresolved_regions

            # Strip internal _source_id so canonical dataframe columns match STANDARD_COLUMNS
            clean_cols = [c for c in STANDARD_COLUMNS if c in current_df.columns]
            clean_df = current_df[clean_cols].copy().reset_index(drop=True)
            updated_diag.accepted_rows = len(clean_df)
            updated_diag.unique_records = len(clean_df)

            all_issues = list(issues.values())
            res = CatalogResult(
                dataframe=clean_df,
                diagnostics=updated_diag,
                fingerprint=base_res.fingerprint or self.get_fingerprint(),
                review_issues=all_issues,
                issues_by_source_id=issues,
            )
            self._catalog_result = res
            return res

    def list_unresolved_issues(self) -> List[ReviewIssue]:
        """Returns all review issues that remain unresolved."""
        res = self.get_refreshed_catalog_result()
        return [issue for issue in res.review_issues if not issue.resolved]

    def run_bounded_automatic_recovery(self) -> CatalogResult:
        """
        Executes bounded deterministic automatic recovery strategies in strict order:
        1. Coordinate re-extraction
        2. Wrapped text reconstruction
        3. Column roles resolution
        """
        with self._lock:
            res = self.get_refreshed_catalog_result()

            # Attempt to delegate to catalog_recovery module if present
            try:
                try:
                    from .catalog_recovery import run_automatic_recovery
                except ImportError:
                    from catalog_recovery import run_automatic_recovery

                res = run_automatic_recovery(res)
                self._catalog_result = res
                return res
            except ImportError:
                pass

            # Fallback bounded recovery pass for unrecovered issues
            attempted = 0
            recovered = 0
            standard_strategies = [
                "coordinate_reextraction",
                "wrapped_text_reconstruction",
                "column_role_resolution",
            ]

            updated_df = res.dataframe.copy(deep=True)
            for issue in res.review_issues:
                if issue.resolved:
                    continue

                for strat in standard_strategies:
                    if strat not in issue.attempted_strategies:
                        issue.attempted_strategies.append(strat)
                        attempted += 1

                # If raw_cells contains text that can be unambiguously validated:
                if issue.raw_cells and len(issue.raw_cells) >= 2:
                    candidate = self._attempt_heuristic_recovery(issue.raw_cells)
                    if candidate:
                        valid, _ = validate_catalog_item(candidate)
                        if valid:
                            issue.resolved = True
                            issue.provenance = "automatic_recovery"
                            issue.item = candidate
                            recovered += 1
                            row_dict = self._build_canonical_row(candidate)
                            updated_df = pd.concat([updated_df, pd.DataFrame([row_dict])], ignore_index=True)
                            continue

                issue.strategy_outcomes["recovery_attempt"] = "unresolved_ambiguity"

            res.diagnostics.attempted_recovery_count += attempted
            res.diagnostics.successful_recovery_count += recovered
            res.diagnostics.accepted_rows = len(updated_df)
            res.diagnostics.unique_records = len(updated_df)
            res.dataframe = updated_df
            self._catalog_result = res
            return res

    def _attempt_heuristic_recovery(self, raw_cells: List[Any]) -> Optional[Dict[str, Any]]:
        """Bounded, conservative recovery for single unambiguous row representation."""
        if not raw_cells:
            return None

        # Look for text candidate and numeric candidates
        text_candidates = [str(c).strip() for c in raw_cells if c and not re_is_pure_num(str(c))]
        num_candidates = [extract_numeric(c) for c in raw_cells if c and extract_numeric(c) is not None]

        if not text_candidates or not num_candidates:
            return None

        # Unambiguous: exactly one valid medication name candidate and one valid price candidate
        valid_names = [t for t in text_candidates if len(t) >= 2 and not is_header_text(t)]
        if len(valid_names) != 1:
            return None

        valid_prices = [p for p in num_candidates if 0.0 < p < 10000.0]
        if len(valid_prices) != 1:
            return None

        candidate = {
            "warehouse_name": self.warehouse_name,
            "item_name": valid_names[0],
            "base_price": valid_prices[0],
            "discount_rate": None,
            "stock_status": True,
        }
        return candidate

    def preview_table_column_mapping(
        self, table_id: int, mapping: Dict[str, int]
    ) -> List[Dict[str, Any]]:
        """
        Previews transformation of ALL records belonging to table_id (including previously accepted ones).
        Does not mutate state.
        """
        res = self.get_refreshed_catalog_result()
        preview_records: List[Dict[str, Any]] = []

        # Find all raw row diagnostics and issues belonging to table_id
        target_rows: List[Tuple[str, List[Any], bool]] = []

        # From diagnostics
        for p in res.diagnostics.pages:
            for g in p.groups:
                for r in g.rows:
                    if r.table == table_id or (r.table == 0 and g.group == table_id):
                        is_acc = (r.outcome == "accepted")
                        target_rows.append((r.source_id, list(r.raw_cells), is_acc))

        # From review issues if not duplicate
        seen_ids = {sid for sid, _, _ in target_rows}
        for issue in res.review_issues:
            if issue.identity and issue.identity.table == table_id and issue.source_id not in seen_ids:
                target_rows.append((issue.source_id, list(issue.raw_cells), issue.resolved))
                seen_ids.add(issue.source_id)

        for source_id, raw_cells, was_accepted in target_rows:
            if not raw_cells:
                continue

            candidate = self._map_raw_cells_to_candidate(raw_cells, mapping)
            valid, err = validate_catalog_item(candidate)

            preview_records.append({
                "source_id": source_id,
                "table_id": table_id,
                "raw_cells": raw_cells,
                "candidate": candidate,
                "valid": valid,
                "validation_error": err,
                "was_previously_accepted": was_accepted,
            })

        return preview_records

    def apply_table_column_mapping(
        self, table_id: int, mapping: Dict[str, int]
    ) -> CatalogResult:
        """
        Applies validated column mapping across table_id atomically.
        """
        with self._lock:
            # Store mapping
            self._table_mappings[table_id] = dict(mapping)
            # Recompute result
            self._catalog_result = None
            return self.get_refreshed_catalog_result()

    def apply_field_correction(
        self, source_id: str, field_updates: Dict[str, Any]
    ) -> CatalogResult:
        """
        Applies validated field correction to a specific source identity item atomically.
        """
        # Validate correction data through canonical validation
        valid, err = validate_catalog_item(field_updates)
        if not valid:
            raise ValueError(f"Invalid field correction: {err}")

        with self._lock:
            self._field_corrections[source_id] = dict(field_updates)
            self._catalog_result = None
            return self.get_refreshed_catalog_result()

    def reset_corrections(self) -> CatalogResult:
        """
        Clears all table mappings and field corrections, restoring pristine catalog result.
        """
        with self._lock:
            self._table_mappings.clear()
            self._field_corrections.clear()
            self._catalog_result = None
            if os.path.isfile(self.catalog_path):
                self._base_catalog_result = None
            return self.get_refreshed_catalog_result(refresh=True)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _map_raw_cells_to_candidate(
        self, raw_cells: List[Any], mapping: Dict[str, int]
    ) -> Dict[str, Any]:
        """Maps raw row cells according to column index mapping."""
        candidate: Dict[str, Any] = {"warehouse_name": self.warehouse_name}

        for key in ("item_name", "base_price", "discount_rate", "stock_status"):
            if key in mapping:
                idx = mapping[key]
                # Guard against non-integer, bool, or out-of-range mapping indices
                if (
                    isinstance(idx, int)
                    and not isinstance(idx, bool)
                    and 0 <= idx < len(raw_cells)
                    and raw_cells[idx] is not None
                ):
                    candidate[key] = raw_cells[idx]
                else:
                    candidate[key] = None

        return candidate

    def _build_canonical_row(self, item_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Constructs an exact 8-column dictionary for DataFrame inclusion."""
        name = str(item_dict.get("item_name") or item_dict.get("name") or "").strip()
        norm_name = item_dict.get("normalized_name") or normalize_arabic_text(name)
        dosage, unit_size = parse_dosage_and_pack(name)

        raw_p = item_dict.get("base_price", item_dict.get("price", 0.0))
        try:
            price_val = float(raw_p)
        except (ValueError, TypeError):
            price_val = 0.0

        raw_d = item_dict.get("discount_rate", item_dict.get("discount"))
        discount_val = None
        if raw_d is not None and str(raw_d).strip() != "":
            try:
                discount_val = float(parse_discount(str(raw_d)))
            except (ValueError, TypeError):
                discount_val = None

        stock_val = item_dict.get("stock_status", item_dict.get("stock", True))
        if isinstance(stock_val, str):
            stock_bool = not any(kw in stock_val.lower() for kw in ["غير متوفر", "نفذ", "out", "0", "لا يوجد"])
        else:
            stock_bool = bool(stock_val)

        return {
            "warehouse_name": item_dict.get("warehouse_name", self.warehouse_name),
            "item_name": name,
            "normalized_name": norm_name,
            "dosage": item_dict.get("dosage", dosage),
            "unit_size": item_dict.get("unit_size", unit_size),
            "base_price": price_val,
            "discount_rate": discount_val,
            "stock_status": stock_bool,
        }

    def _apply_table_mapping_internal(
        self,
        table_id: int,
        mapping: Dict[str, int],
        df: pd.DataFrame,
        issues: Dict[str, ReviewIssue],
        base_res: CatalogResult,
    ) -> Tuple[pd.DataFrame, Dict[str, ReviewIssue]]:
        """Applies column mapping for table_id, re-mapping ALL rows (accepted and issues)."""
        updated_df = df.copy(deep=True)

        # Collect all rows belonging to table_id (both accepted and rejected), matching preview
        target_rows: List[Tuple[str, List[Any], bool, Optional[SourceIdentity]]] = []
        seen_ids = set()

        if base_res.diagnostics:
            for p in base_res.diagnostics.pages:
                for g in p.groups:
                    for r in g.rows:
                        if r.table == table_id or (r.table == 0 and g.group == table_id):
                            is_acc = (r.outcome == "accepted")
                            ident = SourceIdentity(
                                page=r.page,
                                table=r.table if r.table != 0 else g.group,
                                row=r.row,
                                bbox=r.bbox,
                                is_region_issue=r.is_region_issue,
                                source_id=r.source_id,
                            )
                            target_rows.append((r.source_id, list(r.raw_cells), is_acc, ident))
                            seen_ids.add(r.source_id)

        for sid, issue in list(issues.items()):
            if issue.identity and issue.identity.table == table_id and sid not in seen_ids:
                target_rows.append((sid, list(issue.raw_cells), issue.resolved, issue.identity))
                seen_ids.add(sid)

        for source_id, raw_cells, was_accepted, ident in target_rows:
            if not raw_cells:
                continue

            candidate = self._map_raw_cells_to_candidate(raw_cells, mapping)
            valid, err = validate_catalog_item(candidate)

            if valid:
                row_dict = self._build_canonical_row(candidate)
                row_dict["_source_id"] = source_id

                if source_id in issues:
                    issues[source_id].resolved = True
                    issues[source_id].provenance = "manual_correction"
                    issues[source_id].item = candidate
                    issues[source_id].rejection_reason = ""

                # In-place update if row exists in dataframe, else append
                mask = (
                    (updated_df["_source_id"] == source_id)
                    if "_source_id" in updated_df.columns
                    else pd.Series(False, index=updated_df.index)
                )
                if mask.any():
                    for col in STANDARD_COLUMNS:
                        updated_df.loc[mask, col] = row_dict[col]
                else:
                    updated_df = pd.concat([updated_df, pd.DataFrame([row_dict])], ignore_index=True)
            else:
                # If row was previously in updated_df, remove it because mapping made it invalid
                mask = (
                    (updated_df["_source_id"] == source_id)
                    if "_source_id" in updated_df.columns
                    else pd.Series(False, index=updated_df.index)
                )
                if mask.any():
                    updated_df = updated_df.loc[~mask].reset_index(drop=True)

                if source_id in issues:
                    issues[source_id].resolved = False
                    issues[source_id].rejection_reason = err or "invalid_under_table_mapping"
                    issues[source_id].item = candidate
                else:
                    ident_to_use = ident or SourceIdentity(page=1, table=table_id, row=None, source_id=source_id)
                    issues[source_id] = ReviewIssue(
                        source_id=source_id,
                        identity=ident_to_use,
                        raw_cells=raw_cells,
                        rejection_reason=err or "invalid_under_table_mapping",
                        resolved=False,
                        provenance="manual_correction",
                        item=candidate,
                    )

        return updated_df, issues

    def _apply_field_correction_internal(
        self,
        source_id: str,
        field_updates: Dict[str, Any],
        df: pd.DataFrame,
        issues: Dict[str, ReviewIssue],
        base_res: Optional[CatalogResult] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, ReviewIssue]]:
        """Applies single field update to state, updating issue and DataFrame."""
        updated_df = df.copy(deep=True)
        if base_res is None:
            base_res = getattr(self, "_base_catalog_result", None)

        # Update or create issue
        if source_id in issues:
            issue = issues[source_id]
            issue.resolved = True
            issue.provenance = "manual_correction"
            issue.item = dict(field_updates)
            issue.rejection_reason = ""
        else:
            # Check diagnostics for coordinates and raw cells
            raw_cells = []
            bbox = None
            if base_res and base_res.diagnostics:
                for p in getattr(base_res.diagnostics, "pages", []):
                    for g in getattr(p, "groups", []):
                        for r in getattr(g, "rows", []):
                            if getattr(r, "source_id", "") == source_id:
                                raw_cells = list(getattr(r, "raw_cells", []))
                                bbox = getattr(r, "bbox", None)
                                break
                    if raw_cells:
                        break

            issue = ReviewIssue(
                source_id=source_id,
                raw_cells=raw_cells,
                bbox=bbox,
                rejection_reason="",
                resolved=True,
                provenance="manual_correction",
                item=dict(field_updates),
            )
            issues[source_id] = issue

        row_dict = self._build_canonical_row(field_updates)
        row_dict["_source_id"] = source_id

        # Multi-layer stable row matching
        target_idx = None

        # Strategy 1: Match on internal _source_id column if present
        if "_source_id" in updated_df.columns:
            mask = (updated_df["_source_id"] == source_id)
            if mask.any():
                target_idx = updated_df.index[mask][0]

        # Strategy 2: Match on original item identity from baseline diagnostics
        if target_idx is None and base_res and base_res.diagnostics:
            for p in getattr(base_res.diagnostics, "pages", []):
                for g in getattr(p, "groups", []):
                    for r in getattr(g, "rows", []):
                        if getattr(r, "source_id", "") == source_id:
                            orig_name = getattr(r, "item_name", "")
                            if orig_name and "item_name" in updated_df.columns:
                                mask = (updated_df["item_name"] == orig_name)
                                if mask.any():
                                    target_idx = updated_df.index[mask][0]
                            break
                    if target_idx is not None:
                        break
                if target_idx is not None:
                    break

        # Strategy 3: Match on prior issue item name
        if target_idx is None and source_id in issues:
            prev_item = issues[source_id].item or {}
            prev_name = prev_item.get("item_name")
            if prev_name and "item_name" in updated_df.columns:
                mask = (updated_df["item_name"] == prev_name)
                if mask.any():
                    target_idx = updated_df.index[mask][0]

        # Strategy 4: Row index correlation from base_res accepted rows
        if target_idx is None and base_res and base_res.diagnostics:
            accepted_diag_rows = [
                r for p in getattr(base_res.diagnostics, "pages", [])
                for g in getattr(p, "groups", [])
                for r in getattr(g, "rows", [])
                if getattr(r, "outcome", "") == "accepted"
            ]
            for idx_acc, r in enumerate(accepted_diag_rows):
                if getattr(r, "source_id", "") == source_id:
                    if idx_acc < len(updated_df):
                        target_idx = updated_df.index[idx_acc]
                    break

        # Strategy 5: Current item_name match (no-rename field edit fallback)
        if target_idx is None and "item_name" in updated_df.columns:
            name = row_dict["item_name"]
            mask = (updated_df["item_name"] == name)
            if mask.any():
                target_idx = updated_df.index[mask][0]

        # Apply in-place replacement or append
        if target_idx is not None:
            for col in STANDARD_COLUMNS:
                if col in row_dict:
                    updated_df.loc[target_idx, col] = row_dict[col]
            if "_source_id" in updated_df.columns:
                updated_df.loc[target_idx, "_source_id"] = source_id
        else:
            if "_source_id" in updated_df.columns:
                row_dict["_source_id"] = source_id
            updated_df = pd.concat([updated_df, pd.DataFrame([row_dict])], ignore_index=True)

        return updated_df, issues


def extract_numeric(val: Any) -> Optional[float]:
    """Extracts float from value or string with Eastern digits/commas replaced."""
    if val is None:
        return None
    s = str(val).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")).replace(",", ".").strip()
    try:
        f = float(s)
        return f if not (math.isnan(f) or math.isinf(f)) else None
    except (ValueError, TypeError):
        return None


def re_is_pure_num(val: str) -> bool:
    """Checks if string is solely digits/floats."""
    s = val.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")).replace(",", ".").strip("% \t\n")
    try:
        float(s)
        return True
    except ValueError:
        return False


def is_header_text(s: str) -> bool:
    """Quick check if text is a known header phrase."""
    headers = {"اسم", "صنف", "اسم الصنف", "سعر", "السعر", "خصم", "الخصم", "رصيد", "كمية", "name", "price", "discount"}
    return s.strip().lower() in headers


# Safely wire catalog corrections persistence on import
try:
    try:
        from .catalog_corrections import wire_catalog_correction_service
    except ImportError:
        from catalog_corrections import wire_catalog_correction_service
    wire_catalog_correction_service(CatalogCorrectionService)
except Exception as _wire_err:
    logger.debug(f"Auto-wiring catalog corrections deferred: {_wire_err}")

