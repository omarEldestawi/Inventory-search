# -*- coding: utf-8 -*-
"""
Manual Search Adapter Module.
Provides a thin, non-altering adapter wrapping MedicineAllocator._find_safe_candidates
for interactive manual medication search without changing candidate generation,
scoring, thresholds, ranking, or procurement allocation logic.
"""
from __future__ import annotations

import os
import re
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import pandas as pd

try:
    from .allocator import MedicineAllocator
    from .controller import global_catalog_cache, inspect_catalog
    from .catalog_diagnostics import CatalogResult
    from .normalizer import normalize_vendor_name
    from .average_discounts import load_average_discounts_file, resolve_default_avg_discounts_path
except ImportError:
    from allocator import MedicineAllocator
    from controller import global_catalog_cache, inspect_catalog
    from catalog_diagnostics import CatalogResult
    from normalizer import normalize_vendor_name
    from average_discounts import load_average_discounts_file, resolve_default_avg_discounts_path

logger = logging.getLogger("ManualSearchAdapter")


@dataclass
class SearchResultItem:
    medicine_name: str
    warehouse_name: str
    base_price: float
    discount_pct: float          # 100 * discount_rate
    net_price: Optional[float]
    ref_discount_pct: Optional[float]


@dataclass
class ManualSearchResult:
    job_id: int
    catalog_gen_id: int
    query: str
    warehouse_filter: Optional[str]
    sort_mode: str               # "best_match" or "highest_discount"
    candidates: List[SearchResultItem]
    reference_benchmark: Optional[Dict[str, Any]]
    total_matches: int
    catalog_errors: List[str]


class ManualSearchAdapter:
    """
    Thin adapter wrapping MedicineAllocator._find_safe_candidates.
    Enforces thread-safety, warehouse filtering, 100-row render cap,
    display field contracts, and reference benchmark isolation.
    """

    def __init__(
        self,
        catalog_files: List[str],
        catalog_gen_id: int = 0,
        avg_discounts_path: Optional[str] = None
    ) -> None:
        self.catalog_files = list(dict.fromkeys([os.path.normpath(os.path.abspath(f)) for f in catalog_files if f]))
        self.catalog_gen_id = catalog_gen_id
        self.avg_discounts_path = avg_discounts_path
        self._lock = threading.RLock()
        self.warehouses: List[str] = []
        self.catalog_errors: List[str] = []
        self._allocator: Optional[MedicineAllocator] = None
        self._build_index()

    def _build_index(self) -> None:
        with self._lock:
            eligible_dfs: List[pd.DataFrame] = []
            noise_values = {'nan', 'none', '', 'null', 'صنف', 'الصنف', 'اسم الصنف', 'البيان', 'item', 'name'}

            for path in self.catalog_files:
                if not os.path.isfile(path):
                    self.catalog_errors.append(f"Catalog file not found: {os.path.basename(path)}")
                    continue

                cat_df = global_catalog_cache.get(path)
                if cat_df is None:
                    try:
                        cat_res = inspect_catalog(path, refresh=False)
                        if cat_res is not None and cat_res.dataframe is not None and not cat_res.dataframe.empty:
                            cat_df = cat_res.to_dataframe()
                        else:
                            if cat_res and cat_res.diagnostics and cat_res.diagnostics.errors:
                                self.catalog_errors.extend(cat_res.diagnostics.errors)
                            cat_df = None
                    except Exception as exc:
                        self.catalog_errors.append(f"Failed to inspect {os.path.basename(path)}: {exc}")
                        cat_df = None

                if cat_df is None or cat_df.empty:
                    continue

                clean = cat_df.copy(deep=True)

                # Filter out rejected rows and unresolved review issues per procurement rules
                res = CatalogResult.from_dataframe(cat_df)
                excluded_sids = set()
                if res is not None and res.diagnostics is not None:
                    for p in getattr(res.diagnostics, "pages", []):
                        for g in getattr(p, "groups", []):
                            for r in getattr(g, "rows", []):
                                if getattr(r, "outcome", None) in ("rejected", "unprocessed") and getattr(r, "source_id", None):
                                    excluded_sids.add(r.source_id)
                if res is not None:
                    for iss in getattr(res, "review_issues", []):
                        if not getattr(iss, "resolved", False) and getattr(iss, "source_id", None):
                            excluded_sids.add(iss.source_id)

                if excluded_sids and "source_id" in clean.columns:
                    clean = clean[~clean["source_id"].isin(excluded_sids)]

                # Field validation safeguards
                if "item_name" in clean.columns:
                    clean = clean[clean["item_name"].astype(str).str.strip().str.len() > 1]
                    clean = clean[~clean["item_name"].astype(str).str.strip().str.lower().isin(noise_values)]

                if "base_price" in clean.columns:
                    clean["base_price"] = pd.to_numeric(clean["base_price"], errors="coerce")
                    clean = clean[(clean["base_price"] > 0.0) & (clean["base_price"] <= 10000.0)]

                if "discount_rate" in clean.columns:
                    clean["discount_rate"] = pd.to_numeric(clean["discount_rate"], errors="coerce")
                    clean = clean[clean["discount_rate"].notna() & (clean["discount_rate"] >= 0.0) & (clean["discount_rate"] <= 0.85)]

                if "stock_status" in clean.columns:
                    clean = clean[clean["stock_status"].fillna(True).astype(bool)]

                if not clean.empty:
                    if "warehouse_name" not in clean.columns:
                        raw_wh = os.path.splitext(os.path.basename(path))[0]
                        clean["warehouse_name"] = normalize_vendor_name(raw_wh)
                    eligible_dfs.append(clean)

            if eligible_dfs:
                consolidated = pd.concat(eligible_dfs, ignore_index=True)
            else:
                consolidated = pd.DataFrame(columns=[
                    'warehouse_name', 'item_name', 'base_price', 'discount_rate', 'stock_status'
                ])

            # Isolated reference loading
            avg_df = None
            try:
                target_ref = self.avg_discounts_path or resolve_default_avg_discounts_path()
                if target_ref and os.path.isfile(target_ref):
                    avg_df = load_average_discounts_file(target_ref)
            except Exception as exc:
                logger.warning(f"Manual search: reference discount loading skipped or failed: {exc}")
                avg_df = None

            self._allocator = MedicineAllocator(
                warehouse_inventory=consolidated,
                enable_ai=False,
                avg_discounts_df=avg_df
            )
            self.warehouses = sorted(list(consolidated['warehouse_name'].dropna().unique())) if not consolidated.empty else []

    def search(
        self,
        query: str,
        warehouse_filter: Optional[str] = None,
        sort_mode: str = "best_match",
        job_id: int = 0
    ) -> ManualSearchResult:
        with self._lock:
            clean_q = query.strip() if query else ""
            norm_wh = None if warehouse_filter in [None, "", "All", "الكل", "جميع المخازن", "الكل / All"] else warehouse_filter
            norm_sort = "highest_discount" if sort_mode == "highest_discount" else "best_match"

            if not self._allocator or not hasattr(self._allocator, 'valid_inv') or self._allocator.valid_inv.empty:
                return ManualSearchResult(
                    job_id=job_id,
                    catalog_gen_id=self.catalog_gen_id,
                    query=query,
                    warehouse_filter=warehouse_filter,
                    sort_mode=sort_mode,
                    candidates=[],
                    reference_benchmark=None,
                    total_matches=0,
                    catalog_errors=list(self.catalog_errors),
                )

            # Blank query browsing vs. safe matching
            if not clean_q:
                pool = self._allocator.valid_inv.copy()
                ref_benchmark = None
            else:
                pool = self._allocator._find_safe_candidates(clean_q)
                ref_rate = self._allocator._lookup_ref_discount(clean_q)
                if ref_rate is not None and ref_rate > 0.0:
                    ref_benchmark = {
                        "query": clean_q,
                        "rate": float(ref_rate),
                        "discount_pct": round(float(ref_rate) * 100.0, 2),
                        "formatted_pct": f"{float(ref_rate) * 100.0:.1f}%",
                        "ref_discount_pct": round(float(ref_rate) * 100.0, 1),
                        "ref_discount_str": f"{float(ref_rate) * 100.0:.1f}%",
                    }
                else:
                    ref_benchmark = None

            # Warehouse filter
            if norm_wh and not pool.empty and "warehouse_name" in pool.columns:
                pool = pool[pool['warehouse_name'] == norm_wh]

            # Sorting
            if norm_sort == "highest_discount" and not pool.empty and "discount_rate" in pool.columns:
                pool = pool.sort_values(by='discount_rate', ascending=False, kind='mergesort')
            # "best_match" preserves pool order verbatim

            total_matches = len(pool)
            display_df = pool.iloc[:100]

            result_items: List[SearchResultItem] = []
            for _, row in display_df.iterrows():
                med_name = str(row.get('item_name', ''))
                wh_name = str(row.get('warehouse_name', ''))

                try:
                    bp = float(row.get('base_price', 0.0) or 0.0)
                except (ValueError, TypeError):
                    bp = 0.0

                try:
                    dr = float(row.get('discount_rate', 0.0) or 0.0)
                except (ValueError, TypeError):
                    dr = 0.0

                disc_pct = round(dr * 100.0, 2)
                net_price = round(bp * (1.0 - dr), 2) if (bp > 0.0 and 0.0 <= dr <= 1.0) else None

                ref_item_rate = self._allocator._lookup_ref_discount(clean_q, med_name) if clean_q else None
                ref_disc_pct = round(float(ref_item_rate) * 100.0, 2) if ref_item_rate is not None else (
                    ref_benchmark["discount_pct"] if ref_benchmark else None
                )

                result_items.append(SearchResultItem(
                    medicine_name=med_name,
                    warehouse_name=wh_name,
                    base_price=bp,
                    discount_pct=disc_pct,
                    net_price=net_price,
                    ref_discount_pct=ref_disc_pct,
                ))

            return ManualSearchResult(
                job_id=job_id,
                catalog_gen_id=self.catalog_gen_id,
                query=query,
                warehouse_filter=warehouse_filter,
                sort_mode=sort_mode,
                candidates=result_items,
                reference_benchmark=ref_benchmark,
                total_matches=total_matches,
                catalog_errors=list(self.catalog_errors),
            )
