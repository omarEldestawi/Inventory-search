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
import re
import logging
import pandas as pd
from .normalizer import extract_dosage_form, extract_canonical_brand, extract_sorted_brand_tokens
from .pharma_matcher import (
    is_safe_pharmaceutical_match,
    extract_core_brand_root,
    extract_form_category,
    check_strength_compatibility,
    check_modifier_compatibility
)
from .gemini_matcher import GeminiMedicineMatcher

logger = logging.getLogger("MedicineAllocator")

class MedicineAllocator:
    def __init__(self, warehouse_inventory: pd.DataFrame):
        """
        warehouse_inventory DataFrame with columns:
        ['warehouse_name', 'item_name', 'normalized_name', 'dosage', 'unit_size', 'base_price', 'discount_rate', 'stock_status']
        """
        self.inventory = warehouse_inventory
        self.warehouses = sorted(list(self.inventory['warehouse_name'].unique())) if not self.inventory.empty else []
        self.gemini_matcher = GeminiMedicineMatcher()
        
        # Pre-index inventory with canonical brand and brand tokens for ultra-fast matching
        if not self.inventory.empty:
            self.inventory = self.inventory.copy()
            self.inventory['brand_root'] = self.inventory['item_name'].apply(extract_core_brand_root)
            self.inventory['canonical_brand'] = self.inventory['item_name'].apply(extract_canonical_brand)
            self.inventory['sorted_brand'] = self.inventory['item_name'].apply(extract_sorted_brand_tokens)
            self.valid_inv = self.inventory[self.inventory['stock_status'] == True].copy()
            
            # Fast index mappings
            self.canonical_index = {}
            self.sorted_brand_index = {}
            self.brand_root_index = {}
            self.brand_root_ns_index = {}
            for idx, row in self.valid_inv.iterrows():
                cb = row['canonical_brand']
                if cb:
                    self.canonical_index.setdefault(cb, []).append(idx)
                sb = row['sorted_brand']
                if sb:
                    self.sorted_brand_index.setdefault(sb, []).append(idx)
                br = row['brand_root']
                if br:
                    self.brand_root_index.setdefault(br, []).append(idx)
                    br_ns = br.replace(' ', '')
                    if br_ns:
                        self.brand_root_ns_index.setdefault(br_ns, []).append(idx)
        else:
            self.valid_inv = pd.DataFrame()
            self.canonical_index = {}
            self.sorted_brand_index = {}
            self.brand_root_index = {}
            self.brand_root_ns_index = {}

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
                'اسم الصنف في أمر الشراء': req_item,
                'اسم الصنف في كتالوج المخزن الفائز': winning_row['item_name'],
                'الكمية': qty_int,
                'المخزن الفائز': winning_warehouse,
                'أعلى خصم %': max_disc,
                'سعر الجمهور': base_price,
                'سعر الشراء': unit_purchase_price,
                'إجمالي الجمهور': total_public,
                'إجمالي الشراء': total_purchase,
                'الوفر المحقق': savings,
                '_base_price': base_price,
                '_discount_rate_num': max_disc,
                '_remarks': remarks
            }

            for w in self.warehouses:
                w_match = candidates[candidates['warehouse_name'] == w]
                if not w_match.empty:
                    top_w_disc = w_match['discount_rate'].max()
                    master_row[f'خصم {w}'] = top_w_disc
                else:
                    master_row[f'خصم {w}'] = '-'

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
                            'اسم الصنف في أمر الشراء': req_item,
                            'اسم الصنف في كتالوج المخزن الفائز': winning_row['item_name'],
                            'الكمية': qty_int,
                            'المخزن الفائز': winning_warehouse,
                            'أعلى خصم %': max_disc,
                            'سعر الجمهور': base_price,
                            'سعر الشراء': unit_purchase_price,
                            'إجمالي الجمهور': total_public,
                            'إجمالي الشراء': total_purchase,
                            'الوفر المحقق': savings,
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
        # Build Out of Stock Records
        # =====================================================================
        out_of_stock_records = []
        for req_item, qty_int, dosage_form in unmatched_items:
            out_of_stock_records.append({
                'م': len(out_of_stock_records) + 1,
                'اسم الصنف المطلوب': req_item,
                'الكمية المطلوبة': qty_int,
                'حالة التوفر': 'غير متوفر بجميع المخازن (نواقص)',
                'ملاحظات المتابعة والبحث': 'لم يتم العثور على الصنف في أي من عروض أسعار المخازن'
            })

        master_df = pd.DataFrame(matched_records)
        oos_df = pd.DataFrame(out_of_stock_records)

        # Step 2: Separate allocations per winning warehouse
        allocated_orders = {}
        if not master_df.empty and 'المخزن الفائز' in master_df.columns:
            for w in self.warehouses:
                w_items = master_df[master_df['المخزن الفائز'] == w].copy()
                if not w_items.empty:
                    po_df = pd.DataFrame({
                        'م': range(1, len(w_items) + 1),
                        'اسم الصنف في أمر الشراء': w_items['اسم الصنف في أمر الشراء'],
                        'اسم الصنف في كتالوج المخزن': w_items['اسم الصنف في كتالوج المخزن الفائز'],
                        'الكمية المطلوبة': w_items['الكمية'],
                        'نسبة الخصم %': w_items['أعلى خصم %'],
                        'سعر الجمهور للوحدة': w_items['سعر الجمهور'],
                        'سعر التوريد الصافي': w_items['سعر الشراء'],
                        'إجمالي القيمة بسعر الجمهور': w_items['إجمالي الجمهور'],
                        'إجمالي القيمة الصافية': w_items['إجمالي الشراء'],
                        'ملاحظات التوريد': 'تأكيد التوريد الفوري'
                    })
                    allocated_orders[w] = po_df

        # KPI Summary
        total_items = len(buying_list)
        oos_count = len(oos_df)
        matched_count = len(matched_records)
        avg_discount = 0.0
        total_qty = 0
        total_public_val = 0.0
        total_purchase_val = 0.0
        total_savings_val = 0.0

        if matched_count > 0:
            avg_discount = round(master_df['_discount_rate_num'].mean() * 100, 1)
            total_qty = int(master_df['الكمية'].sum())
            total_public_val = round(float(master_df['إجمالي الجمهور'].sum()), 2)
            total_purchase_val = round(float(master_df['إجمالي الشراء'].sum()), 2)
            total_savings_val = round(float(master_df['الوفر المحقق'].sum()), 2)

        savings_pct = round((total_savings_val / total_public_val * 100), 1) if total_public_val > 0 else 0.0

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
            'allocation_counts': {w: len(df) for w, df in allocated_orders.items()}
        }

        # Drop internal helper columns from master_df
        cols_to_drop = ['_base_price', '_discount_rate_num', '_remarks']
        master_df_clean = master_df.drop(columns=[c for c in cols_to_drop if c in master_df.columns])

        return {
            'master_comparison': master_df_clean,
            'allocated_orders': allocated_orders,
            'out_of_stock': oos_df,
            'kpis': kpis
        }

    def _find_safe_candidates(self, req_item: str) -> pd.DataFrame:
        """Finds all catalog items that pass strict pharmaceutical validation."""
        req_parts = [p.strip() for p in re.split(r'(?<!\d)/(?!\d)', req_item) if p.strip()] if '/' in req_item else [req_item]
        
        matching_indices = []
        
        for r_part in req_parts:
            cand_indices = set()
            
            # 1. Direct canonical brand index lookup (O(1))
            c_brand = extract_canonical_brand(r_part)
            if c_brand and c_brand in self.canonical_index:
                cand_indices.update(self.canonical_index[c_brand])
            
            # 2. Sorted brand token lookup for inverted word-order in catalogs
            s_brand = extract_sorted_brand_tokens(r_part)
            if s_brand and s_brand in self.sorted_brand_index:
                cand_indices.update(self.sorted_brand_index[s_brand])
                
            # 3. Core brand root lookup
            b_root = extract_core_brand_root(r_part)
            if b_root and b_root in self.brand_root_index:
                cand_indices.update(self.brand_root_index[b_root])
            b_root_ns = b_root.replace(' ', '')
            if b_root_ns and b_root_ns in self.brand_root_ns_index:
                cand_indices.update(self.brand_root_ns_index[b_root_ns])
                
            # Validate collected candidates with strict clinical safety gates
            for idx in cand_indices:
                cand_row = self.valid_inv.loc[idx]
                if is_safe_pharmaceutical_match(r_part, cand_row['item_name']):
                    matching_indices.append(idx)
                                
        if not matching_indices:
            return self.valid_inv.iloc[0:0]
            
        unique_indices = list(set(matching_indices))
        return self.valid_inv.loc[unique_indices]
