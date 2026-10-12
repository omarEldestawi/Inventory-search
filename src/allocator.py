# -*- coding: utf-8 -*-
"""
High-precision, clinically validated allocation engine.
Maximizes discount rate while enforcing zero cross-drug substitutions,
exact strength validation, and formulation consistency.
Features two-pass hybrid architecture:
  Pass 1: Ultra-fast local deterministic matching with canonical brand indexing (0ms, 0 API calls).
  Pass 2: Gemini Flash semantic assistant for Arabic transliterations & brand aliases,
          strictly guarded by Hard Clinical Safety Gates.
"""
import os
import re
import logging
from typing import Optional, Dict, Any, List, Set
import pandas as pd
from rapidfuzz import fuzz
from .normalizer import extract_dosage_form, extract_canonical_brand, extract_sorted_brand_tokens
from .pharma_matcher import (
    is_safe_pharmaceutical_match,
    extract_core_brand_root,
    extract_form_category,
    check_strength_compatibility,
    check_modifier_compatibility,
    clean_arabic_string
)
from .gemini_matcher import GeminiMedicineMatcher

try:
    from .medication_db import MedicationDB, DEFAULT_DB_PATH
except ImportError:
    try:
        from medication_db import MedicationDB, DEFAULT_DB_PATH
    except ImportError:
        MedicationDB = None
        DEFAULT_DB_PATH = None

logger = logging.getLogger("MedicineAllocator")

NOISE_TOKENS = {
    'مجم', 'قرص', 'كبسول', 'امبول', 'شراب', 'نقط', 'مل', 'جرام', 'جم', 'اكياس',
    'مرهم', 'كريم', 'شريط', 'تابلت', 'فيال', 'لبوس', 'بخاخ', 'غسول', 'دش',
    'سيرم', 'زيت', 'لوشن', 'معجون', 'اقراص', 'كبسولات', 'امبولات', 'شرايط',
    'فيالات', 'لوسيون', 'بودرة', 'محلول', 'جل', 'جيل', 'حبيبات', 'فوار',
    'قمع', 'اقماع', 'جديد', 'قديم', 'سعر', 'خاص', 'كبير', 'صغير', 'باكو', 'علبة',
    'علبه', 'كرتون', 'كرتونه', 'باكت', 'شيط', 'سريعة', 'فوري', 'معلق', 'س.ج', 'س.ق',
    'فورت', 'بلس', 'بلاس', 'اكسترا', 'كومبليكس', 'ادفانس', 'ريتارد', 'اطفال',
    'شريطين', 'كبار', 'مطهر', 'مساج', 'فطريات', 'للفطريات', 'مهبلي', 'حساسية',
    'شركة', 'مخزن', 'فارما', 'فارم', 'جروب', 'الدواء', 'توزيع', 'جملة', 'عرض',
    'ابيكو', 'فاركو', 'سيد', 'امون', 'سانوفي', 'سيديكو', 'ماش', 'ايبيكو', 'دلتا', 'مينا'
}

def _extract_clean_brand_tokens(text: str) -> Set[str]:
    """Extracts distinctive brand tokens (length >= 3) excluding common dosage, unit, and commercial noise."""
    if not text:
        return set()
    cleaned = clean_arabic_string(text)
    toks = set()
    for w in cleaned.split():
        if len(w) >= 3 and w not in NOISE_TOKENS and not w.isdigit():
            toks.add(w)
            if w.startswith('ال') and len(w) > 4:
                toks.add(w[2:])
    br = extract_core_brand_root(text)
    if br:
        for w in br.split():
            if len(w) >= 3 and w not in NOISE_TOKENS and not w.isdigit():
                toks.add(w)
                if w.startswith('ال') and len(w) > 4:
                    toks.add(w[2:])
    return toks

class MedicineAllocator:
    def __init__(self, warehouse_inventory: Optional[pd.DataFrame] = None, enable_ai: Optional[bool] = None, medication_db: Optional[Any] = None):
        """
        warehouse_inventory DataFrame with columns:
        ['warehouse_name', 'item_name', 'normalized_name', 'dosage', 'unit_size', 'base_price', 'discount_rate', 'stock_status']
        """
        if warehouse_inventory is None:
            warehouse_inventory = pd.DataFrame()
        self.inventory = warehouse_inventory
        self.warehouses = sorted(list(self.inventory['warehouse_name'].unique())) if not self.inventory.empty else []
        self.gemini_matcher = GeminiMedicineMatcher()
        if enable_ai is not None:
            self.gemini_matcher.enabled = enable_ai

        if medication_db is not None:
            self.medication_db = medication_db if medication_db is not False else None
        elif MedicationDB is not None:
            try:
                self.medication_db = MedicationDB()
                logger.info(
                    f"MedicationDB initialized successfully from {self.medication_db.db_path} "
                    f"({self.medication_db.count_standards()} standards, {self.medication_db.count_aliases()} aliases, "
                    f"read_only={getattr(self.medication_db, '_is_read_only', False)})"
                )
            except Exception as e:
                logger.error(f"Failed to auto-load MedicationDB: {e}", exc_info=True)
                self.medication_db = None
        else:
            self.medication_db = None

        self.standard_id_index = {}
        
        # Pre-index inventory with canonical brand and brand tokens for ultra-fast matching
        if not self.inventory.empty:
            self.inventory = self.inventory.copy()
            self.inventory['brand_root'] = self.inventory['item_name'].apply(extract_core_brand_root)
            self.inventory['canonical_brand'] = self.inventory['item_name'].apply(extract_canonical_brand)
            self.inventory['sorted_brand'] = self.inventory['item_name'].apply(extract_sorted_brand_tokens)
            self.valid_inv = self.inventory[self.inventory['stock_status'] == True].copy().reset_index(drop=True)
            self.valid_inv_names = self.valid_inv['item_name'].to_dict()
            
            # Fast index mappings - Tier 1
            self.canonical_index = {}
            self.sorted_brand_index = {}
            self.brand_root_index = {}
            self.brand_root_ns_index = {}
            self.brand_root_no_al_index = {}
            self.valid_inv_brand_roots_no_al = {}
            
            # Fast index mappings - Tier 2 (Token-anchored inverted index)
            self.token_index = {}
            
            # Fast index mappings - Tier 3 (Form category and first-char sound index)
            self.form_category_index = {}
            self.first_char_index = {}
            
            c_brands = self.valid_inv['canonical_brand'].tolist()
            s_brands = self.valid_inv['sorted_brand'].tolist()
            b_roots = self.valid_inv['brand_root'].tolist()
            form_cats = self.valid_inv['item_name'].apply(extract_form_category).tolist()
            
            for idx in range(len(self.valid_inv)):
                name = self.valid_inv_names[idx]
                if self.medication_db:
                    std_rec = self.medication_db.resolve(name)
                    if std_rec and "id" in std_rec:
                        self.standard_id_index.setdefault(std_rec["id"], []).append(idx)

                cb = c_brands[idx]
                if cb:
                    self.canonical_index.setdefault(cb, []).append(idx)
                sb = s_brands[idx]
                if sb:
                    self.sorted_brand_index.setdefault(sb, []).append(idx)
                br = b_roots[idx]
                if br:
                    self.brand_root_index.setdefault(br, []).append(idx)
                    br_ns = br.replace(' ', '')
                    if br_ns:
                        self.brand_root_ns_index.setdefault(br_ns, []).append(idx)
                        br_no_al = br_ns[2:] if br_ns.startswith('ال') and len(br_ns) > 4 else br_ns
                        self.valid_inv_brand_roots_no_al[idx] = br_no_al
                        if br_no_al:
                            self.brand_root_no_al_index.setdefault(br_no_al, []).append(idx)
                            self.first_char_index.setdefault(br_no_al[0], []).append(idx)
                
                # Tier 2 Tokens
                for tok in _extract_clean_brand_tokens(name):
                    self.token_index.setdefault(tok, []).append(idx)
                    
                # Tier 3 Form Category
                fc = form_cats[idx]
                self.form_category_index.setdefault(fc, []).append(idx)
                
            # Prune frequent tokens (stop-words) to ensure lightning-fast O(1) lookups
            self.token_index = {tok: idxs for tok, idxs in self.token_index.items() if len(idxs) <= 35}
        else:
            self.valid_inv = pd.DataFrame()
            self.valid_inv_names = {}
            self.canonical_index = {}
            self.sorted_brand_index = {}
            self.brand_root_index = {}
            self.brand_root_ns_index = {}
            self.brand_root_no_al_index = {}
            self.valid_inv_brand_roots_no_al = {}
            self.token_index = {}
            self.form_category_index = {}
            self.first_char_index = {}

    def optimize_procurement(self, order_df: pd.DataFrame, catalog_df: Optional[pd.DataFrame] = None, enable_ai: Optional[bool] = None) -> dict:
        """
        Executes deterministic clinical allocation.
        Supports both MedicineAllocator().optimize_procurement(order_df, catalog_df)
        and MedicineAllocator(catalog_df).optimize_procurement(order_df).
        """
        if catalog_df is not None:
            self.__init__(catalog_df, enable_ai=enable_ai)
        elif enable_ai is not None:
            self.gemini_matcher.enabled = enable_ai
        return self.allocate_order(order_df)

    def allocate_order(self, buying_list: pd.DataFrame) -> dict:
        """
        Allocate each unique item in buying_list to the best warehouse based on max(discount_rate).
        Returns dict containing:
        - 'master_comparison': pd.DataFrame (matched items with side-by-side comparison & financials)
        - 'allocated_orders': dict of {warehouse_name: pd.DataFrame}
        - 'out_of_stock': pd.DataFrame
        - 'kpis': dict
        """
        if self.valid_inv.empty:
            empty_df = pd.DataFrame()
            return {
                'master_comparison': empty_df,
                'allocated_orders': {},
                'out_of_stock': buying_list.copy(),
                'kpis': {
                    'total_items': len(buying_list),
                    'matched_items': 0,
                    'out_of_stock': len(buying_list),
                    'num_warehouses': 0,
                    'total_quantity': 0,
                    'total_public_value': 0.0,
                    'total_purchase_cost': 0.0,
                    'total_savings': 0.0,
                    'savings_pct': 0.0
                }
            }

        matched_records = []
        warehouse_allocation_counts = {w: 0 for w in self.warehouses}
        
        deterministic_matches = 0
        unmatched_items = []

        # =====================================================================
        # PASS 1: Ultra-Fast Local Deterministic Matching
        # =====================================================================
        for idx, row in buying_list.iterrows():
            req_item = str(row['requested_item']).strip()
            qty = row.get('quantity', 1)
            try:
                qty_int = int(qty)
            except (ValueError, TypeError):
                qty_int = 1
            dosage_form = extract_dosage_form(req_item)

            candidates = self._find_safe_candidates(req_item)
            
            if candidates.empty:
                unmatched_items.append((req_item, qty_int, dosage_form))
                continue

            deterministic_matches += 1
            max_disc = candidates['discount_rate'].max()
            best_candidates = candidates[candidates['discount_rate'] == max_disc]

            # Tie-breaking by supplier batch consolidation
            if len(best_candidates) > 1:
                best_candidates = best_candidates.copy()
                best_candidates['w_count'] = best_candidates['warehouse_name'].map(warehouse_allocation_counts)
                winning_row = best_candidates.sort_values(by='w_count', ascending=False).iloc[0]
            else:
                winning_row = best_candidates.iloc[0]

            winning_warehouse = winning_row['warehouse_name']
            warehouse_allocation_counts[winning_warehouse] += 1
            base_price = float(winning_row.get('base_price', 0.0) or 0.0)

            unit_purchase_price = round(base_price * (1.0 - max_disc), 2)
            total_public = round(base_price * qty_int, 2)
            total_purchase = round(unit_purchase_price * qty_int, 2)
            savings = round(total_public - total_purchase, 2)

            remarks = 'أعلى نسبة خصم متاحة' if len(candidates['warehouse_name'].unique()) > 1 else 'المورد الوحيد المتاح'

            master_row = {
                'م': len(matched_records) + 1,
                'اسم الصنف المطلوب (في طلب الشراء)': req_item,
                'اسم الصنف في كشف المخزن الفائز': winning_row['item_name'],
                'الكمية المطلوبة': qty_int,
                'المخزن الفائز': winning_warehouse,
                'أعلى خصم %': max_disc,
                'سعر الجمهور': base_price,
                'سعر الشراء للوحدة': unit_purchase_price,
                'إجمالي سعر الجمهور': total_public,
                'إجمالي تكلفة الشراء': total_purchase,
                'قيمة الوفر': savings,
                '_base_price': base_price,
                '_discount_rate_num': max_disc,
                '_remarks': remarks
            }

            w_disc_dict = candidates.groupby('warehouse_name')['discount_rate'].max().to_dict()
            for w in self.warehouses:
                master_row[f'خصم {w}'] = w_disc_dict.get(w, '-')

            matched_records.append(master_row)

        # =====================================================================
        # PASS 2: Hybrid AI Assistance (Gemini Flash) with Safety Gates
        # =====================================================================
        ai_matches = 0
        if unmatched_items and self.gemini_matcher.enabled:
            print(f"  [AI] Activating Gemini Flash for {len(unmatched_items)} unmatched / transliterated item(s)...")
            unmatched_names = [item[0] for item in unmatched_items]
            ai_resolved = self.gemini_matcher.batch_match(unmatched_names, self.valid_inv)
            
            remaining_unmatched = []
            for req_item, qty_int, dosage_form in unmatched_items:
                if req_item in ai_resolved:
                    match_info = ai_resolved[req_item]
                    cand_name = match_info['matched_candidate']
                    
                    # Look up candidate across all warehouses
                    cand_rows = self.valid_inv[self.valid_inv['item_name'] == cand_name]
                    if not cand_rows.empty:
                        ai_matches += 1
                        max_disc = cand_rows['discount_rate'].max()
                        best_candidates = cand_rows[cand_rows['discount_rate'] == max_disc]
                        
                        if len(best_candidates) > 1:
                            best_candidates = best_candidates.copy()
                            best_candidates['w_count'] = best_candidates['warehouse_name'].map(warehouse_allocation_counts)
                            winning_row = best_candidates.sort_values(by='w_count', ascending=False).iloc[0]
                        else:
                            winning_row = best_candidates.iloc[0]
                            
                        winning_warehouse = winning_row['warehouse_name']
                        warehouse_allocation_counts[winning_warehouse] += 1
                        base_price = float(winning_row.get('base_price', 0.0) or 0.0)
                        
                        unit_purchase_price = round(base_price * (1.0 - max_disc), 2)
                        total_public = round(base_price * qty_int, 2)
                        total_purchase = round(unit_purchase_price * qty_int, 2)
                        savings = round(total_public - total_purchase, 2)
                        
                        reason = match_info.get('reason', 'مطابقة لغوية ذكية')
                        remarks = f"مطابقة ذكية معتمدة ({reason})"
                        
                        print(f"    ✓ AI Resolved: '{req_item}' -> '{cand_name}' (Supplier: {winning_warehouse}, Discount: {round(max_disc*100, 1)}%)")
                        
                        master_row = {
                            'م': len(matched_records) + 1,
                            'اسم الصنف المطلوب (في طلب الشراء)': req_item,
                            'اسم الصنف في كشف المخزن الفائز': winning_row['item_name'],
                            'الكمية المطلوبة': qty_int,
                            'المخزن الفائز': winning_warehouse,
                            'أعلى خصم %': max_disc,
                            'سعر الجمهور': base_price,
                            'سعر الشراء للوحدة': unit_purchase_price,
                            'إجمالي سعر الجمهور': total_public,
                            'إجمالي تكلفة الشراء': total_purchase,
                            'قيمة الوفر': savings,
                            '_base_price': base_price,
                            '_discount_rate_num': max_disc,
                            '_remarks': remarks
                        }
                        
                        for w in self.warehouses:
                            w_match = cand_rows[cand_rows['warehouse_name'] == w]
                            if not w_match.empty:
                                top_w_disc = w_match['discount_rate'].max()
                                master_row[f'خصم {w}'] = top_w_disc
                            else:
                                master_row[f'خصم {w}'] = '-'
                                
                        matched_records.append(master_row)
                        continue
                        
                remaining_unmatched.append((req_item, qty_int, dosage_form))
                
            unmatched_items = remaining_unmatched

        # =====================================================================
        # Build Out of Stock & Procurement Recommendations
        # =====================================================================
        out_of_stock_records = []
        recommendations_records = []

        substitute_candidates = []
        if not self.valid_inv.empty:
            for _, s_row in self.valid_inv.iterrows():
                nm = str(s_row.get('item_name', ''))
                if any(k in nm for k in ['بديل', 'بدائل', 'substitute']):
                    substitute_candidates.append(s_row)
        substitute_df = pd.DataFrame(substitute_candidates) if substitute_candidates else pd.DataFrame()

        for req_item, qty_int, dosage_form in unmatched_items:
            out_of_stock_records.append({
                'م': len(out_of_stock_records) + 1,
                'اسم الصنف المطلوب': req_item,
                'الكمية المطلوبة': qty_int,
                'حالة التوفر': 'غير متوفر بجميع المخازن (نواقص)',
                'ملاحظات المتابعة والبحث': 'لم يتم العثور على الصنف في أي من عروض أسعار المخازن'
            })

            found_recs = []
            req_parts = [p.strip() for p in re.split(r'(?<!\d)/(?!\d)', req_item) if p.strip()] if '/' in req_item else [req_item]
            
            for r_part in req_parts:
                part_c_brand = extract_canonical_brand(r_part)
                part_b_root = extract_core_brand_root(r_part)
                part_form = extract_form_category(r_part)
                if part_form == 'UNKNOWN' and len(req_parts) > 1:
                    part_form = extract_form_category(req_item)

                if not substitute_df.empty:
                    for _, s_row in substitute_df.iterrows():
                        s_name = str(s_row['item_name'])
                        s_clean = re.sub(r'\b(?:بديل|بدائل|substitute)\b', ' ', s_name).strip()
                        if is_safe_pharmaceutical_match(r_part, s_clean):
                            found_recs.append(s_row)
                        elif part_c_brand and extract_canonical_brand(s_clean) == part_c_brand:
                            found_recs.append(s_row)
                        elif part_b_root and len(part_b_root) >= 3 and part_b_root in s_name:
                            found_recs.append(s_row)

                if not self.valid_inv.empty:
                    cand_idxs = []
                    if part_c_brand and part_c_brand in self.canonical_index:
                        cand_idxs.extend(self.canonical_index[part_c_brand])
                    elif part_b_root and part_b_root in self.brand_root_index:
                        cand_idxs.extend(self.brand_root_index[part_b_root])
                    
                    for c_idx in cand_idxs[:5]:
                        row_cand = self.valid_inv.iloc[c_idx]
                        c_name = str(row_cand['item_name'])
                        c_form = extract_form_category(c_name)
                        if part_form != 'UNKNOWN' and c_form != 'UNKNOWN' and part_form != c_form:
                            continue
                        found_recs.append(row_cand)

            if found_recs:
                seen_recs = set()
                for r_row in found_recs:
                    cand_name = str(r_row['item_name'])
                    if cand_name in seen_recs:
                        continue
                    seen_recs.add(cand_name)
                    base_p = float(r_row.get('base_price', 0.0))
                    disc_r = float(r_row.get('discount_rate', 0.0))
                    net_p = round(base_p * (1.0 - disc_r), 2)
                    recommendations_records.append({
                        'م': len(recommendations_records) + 1,
                        'الصنف الأصلي المطلوب (الناقص)': req_item,
                        'الكمية المطلوبة': qty_int,
                        'البديل التجاري المقترح': cand_name,
                        'المخزن المتاح لديه': r_row.get('warehouse_name', '-'),
                        'سعر الجمهور': base_p,
                        'نسبة الخصم %': round(disc_r * 100, 1),
                        'السعر بعد الخصم': net_p,
                        'ملاحظات الصيدلي والتوصيات': 'بديل تجاري معتمد مقترح للمراجعة المهنية'
                    })
            else:
                recommendations_records.append({
                    'م': len(recommendations_records) + 1,
                    'الصنف الأصلي المطلوب (الناقص)': req_item,
                    'الكمية المطلوبة': qty_int,
                    'البديل التجاري المقترح': 'لا يوجد بديل تجاري متوفر حالياً بالمخازن',
                    'المخزن المتاح لديه': '-',
                    'سعر الجمهور': '-',
                    'نسبة الخصم %': '-',
                    'السعر بعد الخصم': '-',
                    'ملاحظات الصيدلي والتوصيات': 'يتطلب المتابعة مع الوكلاء أو توفير صنف بديل معتمد'
                })

        master_df = pd.DataFrame(matched_records)
        oos_df = pd.DataFrame(out_of_stock_records)
        recommendations_df = pd.DataFrame(recommendations_records)

        # Step 2: Separate allocations per winning warehouse
        allocated_orders = {}
        if not master_df.empty and 'المخزن الفائز' in master_df.columns:
            for w in self.warehouses:
                w_items = master_df[master_df['المخزن الفائز'] == w].copy()
                if not w_items.empty:
                    po_df = pd.DataFrame({
                        'م': range(1, len(w_items) + 1),
                        'اسم الصنف في أمر الشراء': w_items['اسم الصنف المطلوب (في طلب الشراء)'],
                        'اسم الصنف في كتالوج المخزن': w_items['اسم الصنف في كشف المخزن الفائز'],
                        'الكمية المطلوبة': w_items['الكمية المطلوبة'],
                        'نسبة الخصم %': w_items['أعلى خصم %'],
                        'سعر الجمهور للوحدة': w_items['سعر الجمهور'],
                        'سعر التوريد الصافي': w_items['سعر الشراء للوحدة'],
                        'إجمالي القيمة بسعر الجمهور': w_items['إجمالي سعر الجمهور'],
                        'إجمالي القيمة الصافية': w_items['إجمالي تكلفة الشراء'],
                        'ملاحظات التوريد': 'تأكيد التوريد الفوري'
                    })
                    allocated_orders[w] = po_df

        # KPI Summary
        total_items = len(buying_list)
        matched_count = len(matched_records)
        oos_count = max(0, total_items - matched_count)
        avg_discount = 0.0
        total_qty = 0
        total_public_val = 0.0
        total_purchase_val = 0.0
        total_savings_val = 0.0

        if matched_count > 0:
            avg_discount = round(master_df['_discount_rate_num'].mean() * 100, 1)
            total_qty = int(master_df['الكمية المطلوبة'].sum())
            total_public_val = round(float(master_df['إجمالي سعر الجمهور'].sum()), 2)
            total_purchase_val = round(float(master_df['إجمالي تكلفة الشراء'].sum()), 2)
            total_savings_val = round(float(master_df['قيمة الوفر'].sum()), 2)

        savings_pct = round((total_savings_val / total_public_val * 100), 1) if total_public_val > 0 else 0.0

        allocation_counts = {w: len(df) for w, df in allocated_orders.items()}
        allocation_values = {
            w: round(float(df['إجمالي القيمة الصافية'].sum()), 2)
            for w, df in allocated_orders.items()
            if 'إجمالي القيمة الصافية' in df.columns
        }

        kpis = {
            'total_items': total_items,
            'matched_items': matched_count,
            'deterministic_matches': deterministic_matches,
            'ai_assisted_matches': ai_matches,
            'out_of_stock': oos_count,
            'avg_discount': avg_discount,
            'total_quantity': total_qty,
            'total_public_value': total_public_val,
            'total_purchase_cost': total_purchase_val,
            'total_savings': total_savings_val,
            'savings_pct': savings_pct,
            'num_warehouses': len(allocated_orders),
            'allocation_counts': allocation_counts,
            'allocation_values': allocation_values
        }

        # Drop internal helper columns from master_df
        cols_to_drop = ['_base_price', '_discount_rate_num', '_remarks']
        master_df_clean = master_df.drop(columns=[c for c in cols_to_drop if c in master_df.columns])
        if 'اسم الصنف المطلوب (في طلب الشراء)' in master_df_clean.columns:
            master_df_clean['اسم الصنف في أمر الشراء'] = master_df_clean['اسم الصنف المطلوب (في طلب الشراء)']

        return {
            'master_comparison': master_df_clean,
            'allocated_orders': allocated_orders,
            'out_of_stock': oos_df,
            'recommendations': recommendations_df,
            'kpis': kpis
        }

    def _find_safe_candidates(self, req_item: str) -> pd.DataFrame:
        """Finds all catalog items that pass strict pharmaceutical validation."""
        req_parts = [p.strip() for p in re.split(r'(?<!\d)/(?!\d)', req_item) if p.strip()] if '/' in req_item else [req_item]
        
        matching_indices = set()
        
        for r_part in req_parts:
            part_matched = False

            # =========================================================
            # Tier 0: Standard ID Lookup via Medication Knowledge Base
            # =========================================================
            if self.medication_db and self.standard_id_index:
                req_std = self.medication_db.resolve(r_part) or self.medication_db.resolve(req_item)
                if req_std and "id" in req_std:
                    s_id = req_std["id"]
                    if s_id in self.standard_id_index:
                        for idx in self.standard_id_index[s_id]:
                            cand_name = self.valid_inv_names.get(idx)
                            if cand_name:
                                if is_safe_pharmaceutical_match(req_item, cand_name):
                                    matching_indices.add(idx)
                                    part_matched = True
                                else:
                                    # Fallback when alias is verified by MedicationDB: enforce strict clinical safety gates
                                    req_form = extract_form_category(req_item)
                                    cand_form = extract_form_category(cand_name)
                                    never_unknown = {
                                        'INJECTABLE', 'DOUCHE', 'INFANT_MILK', 'DROPS', 'ORAL_LIQUID',
                                        'SACHET', 'SUPPOSITORY', 'TOPICAL_GEL', 'TOPICAL_SOLUTION',
                                        'SPRAY', 'COSMETIC', 'TOPICAL_OINTMENT', 'TOPICAL_CREAM'
                                    }
                                    form_compat = (req_form == cand_form) or (
                                        (req_form == 'UNKNOWN' or cand_form == 'UNKNOWN') and
                                        req_form not in never_unknown and cand_form not in never_unknown
                                    )
                                    if form_compat and check_strength_compatibility(req_item, cand_name) and check_modifier_compatibility(req_item, cand_name):
                                        matching_indices.add(idx)
                                        part_matched = True

            if part_matched:
                continue

            # =========================================================
            # Tier 1: Canonical brand root lookup (exact dictionary)
            # =========================================================
            t1_cands = set()
            c_brand = extract_canonical_brand(r_part)
            if c_brand and c_brand in self.canonical_index:
                t1_cands.update(self.canonical_index[c_brand])
            
            s_brand = extract_sorted_brand_tokens(r_part)
            if s_brand and s_brand in self.sorted_brand_index:
                t1_cands.update(self.sorted_brand_index[s_brand])
                
            b_root = extract_core_brand_root(r_part)
            if b_root:
                if b_root in self.brand_root_index:
                    t1_cands.update(self.brand_root_index[b_root])
                b_root_ns = b_root.replace(' ', '')
                if b_root_ns:
                    if b_root_ns in self.brand_root_ns_index:
                        t1_cands.update(self.brand_root_ns_index[b_root_ns])
                    b_root_no_al = b_root_ns[2:] if b_root_ns.startswith('ال') and len(b_root_ns) > 4 else b_root_ns
                    if b_root_no_al in self.brand_root_no_al_index:
                        t1_cands.update(self.brand_root_no_al_index[b_root_no_al])
            
            for idx in t1_cands:
                cand_name = self.valid_inv_names.get(idx)
                if cand_name and is_safe_pharmaceutical_match(req_item, cand_name):
                    matching_indices.add(idx)
                    part_matched = True
                    
            if part_matched:
                continue

            # =========================================================
            # Tier 2: Token-anchored inverted index lookup
            # =========================================================
            r_tokens = _extract_clean_brand_tokens(r_part)
            t2_cands = set()
            for tok in r_tokens:
                if tok in self.token_index:
                    t2_cands.update(self.token_index[tok])
                    
            req_fc = extract_form_category(r_part)
            if req_fc == 'UNKNOWN' and len(req_parts) > 1:
                req_fc = extract_form_category(req_item)
            if req_fc != 'UNKNOWN':
                allowed_forms = {req_fc, 'UNKNOWN'}
                form_cands = set()
                for fc in allowed_forms:
                    form_cands.update(self.form_category_index.get(fc, []))
                t2_cands &= form_cands
                
            for idx in t2_cands:
                cand_name = self.valid_inv_names.get(idx)
                if cand_name and is_safe_pharmaceutical_match(req_item, cand_name):
                    matching_indices.add(idx)
                    part_matched = True
                    
            if part_matched:
                continue

            # =========================================================
            # Tier 3: RapidFuzz / token similarity fallback
            # =========================================================
            if b_root:
                b_root_ns = b_root.replace(' ', '')
                b_root_no_al = b_root_ns[2:] if b_root_ns.startswith('ال') and len(b_root_ns) > 4 else b_root_ns
                first_c = b_root_no_al[0] if b_root_no_al else None
                
                # Pre-filtered candidate pool: strictly requires matching first letter
                if first_c and first_c in self.first_char_index:
                    pool = set(self.first_char_index[first_c])
                    if req_fc != 'UNKNOWN':
                        allowed_forms = {req_fc, 'UNKNOWN'}
                        form_pool = set()
                        for fc in allowed_forms:
                            form_pool.update(self.form_category_index.get(fc, []))
                        pool &= form_pool
                        
                    len_req = len(b_root_no_al)
                    # Evaluate candidates in small pre-filtered pool
                    for idx in pool:
                        cand_br_no_al = self.valid_inv_brand_roots_no_al.get(idx)
                        if not cand_br_no_al:
                            continue
                        if abs(len_req - len(cand_br_no_al)) > 3:
                            continue
                        
                        score = fuzz.token_sort_ratio(b_root_no_al, cand_br_no_al)
                        if score >= 80:
                            cand_name = self.valid_inv_names.get(idx)
                            if cand_name and is_safe_pharmaceutical_match(req_item, cand_name):
                                matching_indices.add(idx)
                                
        if not matching_indices:
            return self.valid_inv.iloc[0:0]
            
        return self.valid_inv.loc[list(matching_indices)]
