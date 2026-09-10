# -*- coding: utf-8 -*-
"""
High-performance PyMuPDF Catalog Parser with Multi-Column, Multi-Table, and Whitespace-Layout support.
Extracts items from Arabic PDF pharmaceutical catalogs in seconds.
"""
import os
import re
import unicodedata
import pymupdf
import pandas as pd
from .normalizer import (
    normalize_arabic_text,
    parse_discount,
    parse_dosage_and_pack,
    unreverse_arabic_text,
    normalize_vendor_name,
    fix_arwasoft_arabic_numbers,
    EASTERN_ARABIC_DIGITS
)

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
        
    def parse(self) -> pd.DataFrame:
        """Extract catalog items from PDF into a structured DataFrame."""
        items = []
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
            print(f"[Warning] Error parsing {self.warehouse_name}: {e}")

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
        
        # Check if table has multiple side-by-side table blocks (e.g. 6 cols = 3 + 3, or 9 cols with Nones)
        sub_tables = []
        # Filter rows to non-empty cells
        filtered_rows = [[str(c).strip() for c in r if c is not None and str(c).strip() != ''] for r in table]
        
        # Detect if rows consistently have 6 items (two 3-column tables)
        if len(filtered_rows) > 1 and len(filtered_rows[1]) == 6:
            t1 = [r[:3] for r in filtered_rows if len(r) >= 3]
            t2 = [r[3:6] for r in filtered_rows if len(r) >= 6]
            sub_tables.append(t1)
            sub_tables.append(t2)
        else:
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
        
        for idx, h in enumerate(headers):
            h_clean = h.lower().strip()
            if any(k in h_clean for k in name_keywords) and name_idx is None:
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
                    nums = col_scores[i]['numbers']
                    return len(nums)
                price_idx = max(range(num_cols), key=price_score)

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
            if not lines or any(k in text for k in ['لتجــارة', 'ميجــا', 'اسم الصنف', 'السعر', '0502384138', 'المنصـورة']):
                continue
            
            full_line = ' '.join(lines).translate(EASTERN_ARABIC_DIGITS)
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
                    if len(raw_name) >= 2 and discount_val > 0:
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

