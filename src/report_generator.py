# -*- coding: utf-8 -*-
"""
Arabic Excel Report Generator with 100% Structural & Visual Parity to Procurement_Order_Optimized benchmark.
Generates Right-to-Left (RTL) multi-sheet workbooks with identical typography, KPI summary cards,
exact formulas, financial totals, and side-by-side catalog comparison.
"""
import os
import re
import datetime
from typing import Optional, Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import pandas as pd

# XML 1.0 illegal characters regex for openpyxl safety
# Prohibits ASCII control characters (0-8, 11-12, 14-31) and surrogate/non-character code points
ILLEGAL_CHARACTERS_RE = re.compile(
    r'[\000-\010]|[\013-\014]|[\016-\037]|[\ud800-\udfff]|[\ufffe-\uffff]'
)


def clean_excel_str(val: Any) -> str:
    """
    Sanitizes string values by removing illegal XML characters to avoid
    openpyxl.utils.exceptions.IllegalCharacterError. Converts None / NaN to empty string.
    """
    if val is None:
        return ""
    if isinstance(val, float) and (val != val):  # Fast NaN check
        return ""
    val_str = str(val)
    if val_str.strip().lower() == 'nan':
        return ""
    return ILLEGAL_CHARACTERS_RE.sub("", val_str)


def clean_sheet_title(title: str) -> str:
    r"""
    Sanitizes sheet tab title for openpyxl:
    - Removes invalid characters: \ / ? * : [ ]
    - Removes XML illegal characters
    - Truncates to max 31 characters
    """
    if not title:
        return "Sheet"
    cleaned = re.sub(r'[\\*?:/\[\]]', '_', str(title))
    cleaned = ILLEGAL_CHARACTERS_RE.sub("", cleaned).strip()
    return cleaned[:31] or "Sheet"


def _parse_discount_value(val: Any) -> Optional[float]:
    """Safely parses discount rate value handling floats, ints, percentage strings, and dashes."""
    if val is None or pd.isna(val) or val == '-':
        return None
    try:
        v_str = str(val).strip()
        is_pct = '%' in v_str
        v_clean = v_str.replace('%', '').strip()
        v_float = float(v_clean)
        if is_pct or v_float > 1.0:
            v_float = v_float / 100.0
        return max(0.0, min(1.0, v_float))
    except (ValueError, TypeError):
        return None


def _parse_currency_value(val: Any) -> Optional[float]:
    """Safely parses currency amounts handling comma separators, EGP symbols, and strings."""
    if val is None or pd.isna(val) or val == '-':
        return None
    try:
        v_str = str(val).replace(',', '').replace('ج.م', '').replace('EGP', '').replace('LE', '').strip()
        return float(v_str)
    except (ValueError, TypeError):
        return None


class ArabicExcelReportGenerator:
    def __init__(self, allocation_result: dict, output_dir: Optional[str] = None):
        self.result = allocation_result
        try:
            from .pipeline import resolve_safe_output_dir, validate_directory_writable
        except ImportError:
            from pipeline import resolve_safe_output_dir, validate_directory_writable
        self.output_dir = resolve_safe_output_dir(output_dir)
        validate_directory_writable(self.output_dir)
        
    def generate(self, custom_date_str: str = None) -> str:
        """
        Generate the Excel workbook matching the exact Procurement_Order_Optimized template format.
        Saves both Procurement_Order_Optimized_YYYY-MM-DD.xlsx and أفضل_اسعار_YYYY-MM-DD.xlsx.
        """
        today_date = datetime.date.today()
        today_str = custom_date_str or today_date.strftime("%Y-%m-%d")
        
        # Arabic date text e.g. "10 سبتمبر 2026"
        months_ar = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
        try:
            d_obj = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()
            arabic_date_text = f"{d_obj.day:02d} {months_ar[d_obj.month - 1]} {d_obj.year}"
        except Exception:
            arabic_date_text = today_str

        filename = f"Procurement_Order_Optimized_{today_str}.xlsx"
        filepath = os.path.join(self.output_dir, filename)

        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # Remove default blank sheet

        # -------------------------------------------------------------
        # EXACT STYLES FROM Procurement_Order_Optimized.xlsx
        # -------------------------------------------------------------
        font_main_title = Font(name="Calibri", size=16, bold=True, color="1F4E79")
        font_subtitle = Font(name="Calibri", size=11, bold=False, color="595959")
        
        font_kpi_lbl = Font(name="Calibri", size=10, bold=True, color="595959")
        font_kpi_val = Font(name="Calibri", size=14, bold=True, color="1F4E79")
        
        font_tbl_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_cell = Font(name="Calibri", size=11, bold=False, color="000000")
        font_cell_bold = Font(name="Calibri", size=11, bold=True, color="000000")
        
        fill_navy_header = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        fill_kpi = PatternFill(start_color="F2F4F8", end_color="F2F4F8", fill_type="solid")
        fill_zebra = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")
        fill_total_row = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
        fill_oos_row = PatternFill(start_color="FFF5F5", end_color="FFF5F5", fill_type="solid")
        fill_soft_green = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
        font_soft_green = Font(name="Calibri", size=11, bold=True, color="375623")
        fill_soft_yellow = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
        font_soft_yellow = Font(name="Calibri", size=11, bold=True, color="7F6000")

        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        align_right = Alignment(horizontal="right", vertical="center", wrap_text=True)
        
        thin_border = Border(
            left=Side(style='thin', color='D9D9D9'),
            right=Side(style='thin', color='D9D9D9'),
            top=Side(style='thin', color='D9D9D9'),
            bottom=Side(style='thin', color='D9D9D9')
        )
        total_border = Border(
            left=Side(style='thin', color='A6B9D0'),
            right=Side(style='thin', color='A6B9D0'),
            top=Side(style='thin', color='1F4E79'),
            bottom=Side(style='double', color='1F4E79')
        )

        kpis = self.result.get('kpis', {})
        master_df = self.result.get('master_comparison')
        if isinstance(master_df, list):
            master_df = pd.DataFrame(master_df)
        elif master_df is not None:
            master_df = master_df.copy()

        if master_df is not None and not master_df.empty:
            if 'اسم الصنف في أمر الشراء' in master_df.columns and 'اسم الصنف المطلوب (في طلب الشراء)' in master_df.columns:
                master_df = master_df.drop(columns=['اسم الصنف في أمر الشراء'])

            first_11_cols = [c for c in master_df.columns if c not in ('الخصم المرجح %', 'فرق الخصم %')][:11]
            remaining_cols = [c for c in master_df.columns if c not in ('الخصم المرجح %', 'فرق الخصم %')][11:]

            if 'الخصم المرجح %' not in master_df.columns:
                master_df['الخصم المرجح %'] = '-'
            if 'فرق الخصم %' not in master_df.columns:
                master_df['فرق الخصم %'] = '-'

            master_df = master_df[first_11_cols + ['الخصم المرجح %', 'فرق الخصم %'] + remaining_cols]

        allocated = self.result.get('allocated_orders', {})
        oos_df = self.result.get('out_of_stock')
        rec_df = self.result.get('recommendations')

        # -------------------------------------------------------------
        # SHEET 1: Master Comparison (المقارنة الشاملة وتوزيع الأصناف)
        # -------------------------------------------------------------
        ws_master = wb.create_sheet(title="المقارنة الشاملة وتوزيع الأصناف")
        ws_master.views.sheetView[0].rightToLeft = True

        max_cols = max(len(master_df.columns) if master_df is not None and not master_df.empty else 14, 14)
        end_col_letter = get_column_letter(max_cols)

        # Row 1: Title
        ws_master.merge_cells(f"A1:{end_col_letter}1")
        c_title = ws_master["A1"]
        c_title.value = clean_excel_str("تقرير مقارنة أسعار الأدوية وخطة الشراء المحسنة")
        c_title.font = font_main_title
        c_title.alignment = align_center

        # Row 2: Subtitle
        ws_master.merge_cells(f"A2:{end_col_letter}2")
        c_sub = ws_master["A2"]
        num_wh = kpis.get('num_warehouses', len(allocated))
        c_sub.value = clean_excel_str(f"تحليل عروض {num_wh} مخازن أدوية وتوزيع الأصناف حسب أعلى نسبة خصم مع مطابقة تامة بدون بدائل | {arabic_date_text}")
        c_sub.font = font_subtitle
        c_sub.alignment = align_center

        # Rows 4-5: 7 KPI Cards (Merged pairs A-B, C-D, E-F, G-H, I-J, K-L, M-N)
        kpi_defs = [
            ("إجمالي الأصناف المطلوبة", f"{kpis.get('total_items', 0)} صنف", "A4:B4", "A5:B5"),
            ("الأصناف المتوفرة والموزعة", f"{kpis.get('matched_items', 0)} صنف", "C4:D4", "C5:D5"),
            ("الأصناف غير المتوفرة (نواقص)", f"{kpis.get('out_of_stock', 0)} صنف", "E4:F4", "E5:F5"),
            ("إجمالي الكمية المطلوبة", f"{kpis.get('total_quantity', 0):,} عبوة", "G4:H4", "G5:H5"),
            ("إجمالي القيمة بسعر الجمهور", f"{kpis.get('total_public_value', 0.0):,.2f} ج.م", "I4:J4", "I5:J5"),
            ("إجمالي تكلفة الشراء المحسنة", f"{kpis.get('total_purchase_cost', 0.0):,.2f} ج.م", "K4:L4", "K5:L5"),
            ("إجمالي الوفر المحقق", f"{kpis.get('total_savings', 0.0):,.2f} ج.م ({kpis.get('savings_pct', 0.0)}%)", "M4:N4", "M5:N5")
        ]

        for lbl, val, r_top, r_val in kpi_defs:
            ws_master.merge_cells(r_top)
            ws_master.merge_cells(r_val)
            c_top = ws_master[r_top.split(":")[0]]
            c_val = ws_master[r_val.split(":")[0]]
            
            c_top.value = clean_excel_str(lbl)
            c_top.font = font_kpi_lbl
            c_top.alignment = align_center
            c_top.fill = fill_kpi
            
            c_val.value = clean_excel_str(val)
            c_val.font = font_kpi_val
            c_val.alignment = align_center
            c_val.fill = fill_kpi

        for row in ws_master["A4:N5"]:
            for cell in row:
                cell.border = thin_border

        # Row 8: Table Headers
        start_row = 8
        if master_df is not None and not master_df.empty:
            headers = [clean_excel_str(h) for h in master_df.columns]
            for col_idx, h in enumerate(headers, 1):
                c = ws_master.cell(row=start_row, column=col_idx)
                c.value = clean_excel_str(h)
                c.font = font_tbl_header
                c.fill = fill_navy_header
                c.alignment = align_center
                c.border = thin_border
            
            # Row 9+: Data Rows
            current_row = start_row + 1
            for r_i, row_data in enumerate(master_df.values, current_row):
                is_even = (r_i % 2 == 0)
                for c_i, val in enumerate(row_data, 1):
                    c = ws_master.cell(row=r_i, column=c_i)
                    c.font = font_cell
                    c.border = thin_border
                    
                    # Col 1: Serial No
                    if c_i == 1:
                        try:
                            c.value = int(val) if val is not None and not (isinstance(val, float) and val != val) else r_i - start_row
                        except (ValueError, TypeError):
                            c.value = r_i - start_row
                        c.alignment = align_center
                    # Col 2, 3: Item Names
                    elif c_i in (2, 3):
                        c.value = clean_excel_str(val)
                        c.alignment = align_right
                    # Col 4: Qty
                    elif c_i == 4:
                        try:
                            c.value = int(val) if val is not None and not (isinstance(val, float) and val != val) else 1
                        except (ValueError, TypeError):
                            c.value = 1
                        c.alignment = align_center
                    # Col 5: Winning Warehouse
                    elif c_i == 5:
                        c.value = clean_excel_str(val)
                        c.alignment = align_center
                    # Col 6: Highest Discount %
                    elif c_i == 6:
                        try:
                            if val is not None and not (isinstance(val, float) and val != val):
                                c.value = float(val)
                                c.number_format = '0.0%'
                            else:
                                c.value = ""
                        except (ValueError, TypeError):
                            c.value = clean_excel_str(val)
                        c.alignment = align_center
                    # Col 7..11: Currency amounts
                    elif c_i in (7, 8, 9, 10, 11):
                        try:
                            if val is not None and not (isinstance(val, float) and val != val):
                                c.value = float(val)
                                c.number_format = '#,##0.00'
                            else:
                                c.value = ""
                        except (ValueError, TypeError):
                            c.value = clean_excel_str(val)
                        c.alignment = align_center
                    # Col 12: Reference Weighted Average Discount %
                    elif c_i == 12:
                        try:
                            if val is not None and not (isinstance(val, float) and val != val) and val != '-':
                                c.value = float(val)
                                c.number_format = '0.0%'
                            else:
                                c.value = '-'
                        except (ValueError, TypeError):
                            c.value = '-'
                        c.alignment = align_center
                    # Col 13: Difference %
                    elif c_i == 13:
                        try:
                            if val is not None and not (isinstance(val, float) and val != val) and val != '-':
                                c.value = float(val)
                                c.number_format = '0.0%'
                            else:
                                c.value = '-'
                        except (ValueError, TypeError):
                            c.value = '-'
                        c.alignment = align_center
                    # Warehouse discount columns (Col 14+)
                    else:
                        if isinstance(val, (int, float)) and not (isinstance(val, float) and val != val):
                            c.value = float(val)
                            c.number_format = '0.0%'
                        else:
                            c.value = clean_excel_str(val)
                        c.alignment = align_center

                    if is_even:
                        c.fill = fill_zebra
                current_row = r_i

            # Row Last: Summary Row
            sum_row = current_row + 1
            ws_master.cell(row=sum_row, column=2, value="الإجمالي العام").font = font_cell_bold
            ws_master.cell(row=sum_row, column=2).alignment = align_right
            
            # Qty sum
            c_qty_sum = ws_master.cell(row=sum_row, column=4, value=f"=SUM(D9:D{current_row})")
            c_qty_sum.font = font_cell_bold
            c_qty_sum.alignment = align_center
            
            # Currency sums
            for c_i in (9, 10, 11):
                col_let = get_column_letter(c_i)
                c_sum = ws_master.cell(row=sum_row, column=c_i, value=f"=SUM({col_let}9:{col_let}{current_row})")
                c_sum.font = font_cell_bold
                c_sum.number_format = '#,##0.00'
                c_sum.alignment = align_center

            for c_i in range(1, len(headers) + 1):
                cell = ws_master.cell(row=sum_row, column=c_i)
                cell.fill = fill_total_row
                cell.border = total_border
        else:
            ws_master.cell(row=start_row, column=1, value="لا توجد أصناف مطابقة للتخصيص حالياً.").font = font_cell

        self._autofit_columns(ws_master)

        # -------------------------------------------------------------
        # Winning Supplier PO Sheets (طلب شراء - [اسم المخزن])
        # -------------------------------------------------------------
        existing_sheet_titles = set(wb.sheetnames)
        for w_name, po_df in allocated.items():
            w_name_clean = clean_excel_str(w_name)
            clean_tab_name = w_name_clean.replace("مخزن ", "").replace(".pdf", "").strip()[:20]
            base_sheet_title = clean_sheet_title(f"طلب شراء - {clean_tab_name}")
            sheet_title = base_sheet_title
            suffix = 1
            while sheet_title in existing_sheet_titles:
                tag = f"_{suffix}"
                sheet_title = f"{base_sheet_title[:31-len(tag)]}{tag}"
                suffix += 1
            existing_sheet_titles.add(sheet_title)

            ws_po = wb.create_sheet(title=sheet_title)
            ws_po.views.sheetView[0].rightToLeft = True

            # Row 1: Title
            ws_po.merge_cells("A1:F1")
            po_title = ws_po["A1"]
            po_title.value = clean_excel_str(f"أمر توريد أدوية - {w_name}")
            po_title.font = font_main_title
            po_title.alignment = align_center

            # Row 2: Subtitle
            ws_po.merge_cells("A2:F2")
            po_sub = ws_po["A2"]
            po_sub.value = clean_excel_str(f"تاريخ الطلب: {arabic_date_text} | عدد الأصناف المتاحة: {len(po_df)} صنف")
            po_sub.font = font_subtitle
            po_sub.alignment = align_center

            # Row 4: Header
            po_headers = [
                'م',
                'اسم الصنف في فارما',
                'اسم الصنف في كتالوج المخزن',
                'نسبة الخصم %',
                'سعر الجمهور للوحدة',
                'المخزن صاحب أعلى خصم'
            ]
            for c_i, h in enumerate(po_headers, 1):
                c = ws_po.cell(row=4, column=c_i)
                c.value = clean_excel_str(h)
                c.font = font_tbl_header
                c.fill = fill_navy_header
                c.alignment = align_center
                c.border = thin_border

            # Row 5+: Data Rows
            current_po_row = 4
            if po_df is not None and not po_df.empty:
                for r_idx, (_, r_data) in enumerate(po_df.iterrows(), 5):
                    is_even = (r_idx % 2 == 0)

                    # Col 1: Serial No
                    ser_val = r_data.get('م', r_idx - 4)
                    try:
                        ser_val = int(ser_val)
                    except (ValueError, TypeError):
                        ser_val = r_idx - 4

                    # Col 2: Requested item name in Pharma
                    pharma_name = (
                        r_data.get('اسم الصنف في فارما')
                        or r_data.get('اسم الصنف في أمر الشراء')
                        or r_data.get('اسم الصنف المطلوب (في طلب الشراء)')
                        or r_data.get('اسم الصنف')
                        or ''
                    )

                    # Col 3: Catalog item name in warehouse
                    cat_name = (
                        r_data.get('اسم الصنف في كتالوج المخزن')
                        or r_data.get('اسم الصنف في كشف المخزن الفائز')
                        or r_data.get('اسم الصنف في الكتالوج')
                        or r_data.get('item_name')
                        or ''
                    )

                    # Col 4: Discount of this warehouse
                    disc_val = _parse_discount_value(
                        r_data.get('نسبة الخصم %')
                        if 'نسبة الخصم %' in r_data
                        else r_data.get('أعلى خصم %')
                    )

                    # Col 5: Unit public price
                    bp_val = _parse_currency_value(
                        r_data.get('سعر الجمهور للوحدة')
                        if 'سعر الجمهور للوحدة' in r_data
                        else r_data.get('سعر الجمهور')
                    )

                    # Col 6: Winning Warehouse status and competitive discount
                    is_winner_flag = r_data.get('_is_winner')
                    max_disc_val = _parse_discount_value(r_data.get('أعلى خصم متاح %'))
                    if max_disc_val is None:
                        max_disc_val = disc_val or 0.0

                    w_disc_val = disc_val or 0.0
                    if is_winner_flag is not None and not pd.isna(is_winner_flag):
                        is_winner = bool(is_winner_flag)
                    else:
                        is_winner = (w_disc_val >= max_disc_val - 1e-6)

                    win_wh_status = r_data.get('المخزن صاحب أعلى خصم')
                    if is_winner:
                        status_text = w_name
                    else:
                        if win_wh_status and win_wh_status not in ('-', w_name):
                            status_text = str(win_wh_status).strip()
                            if "%" not in status_text and max_disc_val > 0:
                                status_text = f"{status_text} ({max_disc_val * 100:.1f}%)"
                        else:
                            cand_win = str(r_data.get('_winning_wh', '')).strip()
                            if not cand_win or cand_win in (w_name, clean_excel_str(w_name)):
                                cand_win = "مخزن منافس"
                            status_text = f"{cand_win} ({max_disc_val * 100:.1f}%)"

                    c1 = ws_po.cell(row=r_idx, column=1, value=ser_val)
                    c1.font = font_cell
                    c1.alignment = align_center
                    c1.border = thin_border

                    c2 = ws_po.cell(row=r_idx, column=2, value=clean_excel_str(pharma_name))
                    c2.font = font_cell
                    c2.alignment = align_right
                    c2.border = thin_border

                    c3 = ws_po.cell(row=r_idx, column=3, value=clean_excel_str(cat_name))
                    c3.font = font_cell
                    c3.alignment = align_right
                    c3.border = thin_border

                    c4 = ws_po.cell(row=r_idx, column=4)
                    if disc_val is not None:
                        c4.value = float(disc_val)
                        c4.number_format = '0.0%'
                    else:
                        c4.value = clean_excel_str(r_data.get('نسبة الخصم %', ''))
                    c4.font = font_cell
                    c4.alignment = align_center
                    c4.border = thin_border

                    c5 = ws_po.cell(row=r_idx, column=5)
                    if bp_val is not None:
                        c5.value = float(bp_val)
                        c5.number_format = '#,##0.00'
                    else:
                        c5.value = clean_excel_str(r_data.get('سعر الجمهور للوحدة', ''))
                    c5.font = font_cell
                    c5.alignment = align_center
                    c5.border = thin_border

                    c6 = ws_po.cell(row=r_idx, column=6, value=clean_excel_str(status_text))
                    c6.alignment = align_center
                    c6.border = thin_border
                    if is_winner:
                        c6.fill = fill_soft_green
                        c6.font = font_soft_green
                    else:
                        c6.fill = fill_soft_yellow
                        c6.font = font_soft_yellow

                    if is_even:
                        for col_k in (c1, c2, c3, c4, c5):
                            col_k.fill = fill_zebra

                    current_po_row = r_idx

            # Summary Row for Supplier
            po_sum_row = current_po_row + 1
            ws_po.cell(row=po_sum_row, column=2, value=f"إجمالي الأصناف: {len(po_df)} صنف").font = font_cell_bold
            ws_po.cell(row=po_sum_row, column=2).alignment = align_right

            for c_i in range(1, len(po_headers) + 1):
                cell = ws_po.cell(row=po_sum_row, column=c_i)
                cell.fill = fill_total_row
                cell.border = total_border

            # ---------------------------------------------------------
            # Secondary Table: Per-Warehouse Above-Average Discounts (Saving >= 4.00 EGP)
            # ---------------------------------------------------------
            sec_df = self._get_warehouse_above_average_discounts(w_name)

            sec_title_row = po_sum_row + 2
            sec_sub_row = sec_title_row + 1
            sec_header_row = sec_sub_row + 2

            # Section Title Banner
            ws_po.merge_cells(f"A{sec_title_row}:I{sec_title_row}")
            c_sec_title = ws_po[f"A{sec_title_row}"]
            c_sec_title.value = clean_excel_str("أصناف إضافية متاحة بالمخزن بخصم أعلى من المتوسط المرجح (بفارق 4% فأكثر)")
            c_sec_title.font = Font(name="Calibri", size=13, bold=True, color="1F4E79")
            c_sec_title.alignment = align_center

            # Section Subtitle Banner
            ws_po.merge_cells(f"A{sec_sub_row}:I{sec_sub_row}")
            c_sec_sub = ws_po[f"A{sec_sub_row}"]
            c_sec_sub.value = clean_excel_str(
                f"الأصناف التي يتجاوز خصمها الخصم المرجح بـ 4% فأكثر | الأخضر: أفضل سعر متاح لدى هذا المخزن | الأصفر: متاح بنسبة أعلى لدى مخزن آخر | عدد الأصناف: {len(sec_df)} صنف"
            )
            c_sec_sub.font = font_subtitle
            c_sec_sub.alignment = align_center

            # Secondary Table Headers (Columns 1-9)
            sec_headers = [
                'م',
                'اسم الصنف في أرصدة المخازن',
                'اسم الصنف في الكتالوج',
                'سعر الجمهور للوحدة',
                'الخصم المرجح %',
                'خصم هذا المخزن %',
                'أعلى خصم متاح %',
                'المخزن صاحب أعلى خصم',
                'فرق السعر (الوفر بالجنيه)'
            ]

            for c_i, h in enumerate(sec_headers, 1):
                c = ws_po.cell(row=sec_header_row, column=c_i)
                c.value = clean_excel_str(h)
                c.font = font_tbl_header
                c.fill = fill_navy_header
                c.alignment = align_center
                c.border = thin_border

            # Data Rows or Clean Notice Row
            if sec_df is not None and not sec_df.empty:
                start_sec_data = sec_header_row + 1
                current_sec_row = sec_header_row
                for r_idx, (_, r_data) in enumerate(sec_df.iterrows(), start_sec_data):
                    is_even = (r_idx % 2 == 0)

                    # Determine Winner status for Column 8
                    w_disc_f = _parse_discount_value(r_data.get('خصم هذا المخزن %', 0.0)) or 0.0
                    max_disc_f = _parse_discount_value(r_data.get('أعلى خصم متاح %', 0.0)) or 0.0

                    is_winner_flag = r_data.get('_is_winner')
                    if is_winner_flag is not None and not pd.isna(is_winner_flag):
                        is_winner = bool(is_winner_flag) and (w_disc_f >= max_disc_f - 1e-6)
                    else:
                        is_winner = (w_disc_f >= max_disc_f - 1e-6)

                    winning_wh_status = str(r_data.get('المخزن صاحب أعلى خصم', '')).strip()
                    if is_winner:
                        winning_wh_status = w_name
                    else:
                        w_clean = str(w_name).replace(".pdf", "").strip()
                        w_short = w_clean.replace("مخزن ", "").strip()
                        is_self_ref = (
                            not winning_wh_status
                            or winning_wh_status in (w_name, clean_excel_str(w_name), w_clean, '-')
                            or (w_short and (winning_wh_status == w_short or winning_wh_status == f"مخزن {w_short}"))
                        )
                        if is_self_ref:
                            cand_win = str(r_data.get('_winning_wh', '')).strip()
                            if not cand_win or cand_win in (w_name, clean_excel_str(w_name), w_clean) or (w_short and cand_win == w_short):
                                cand_win = "مخزن منافس"
                            winning_wh_status = f"{cand_win} ({max_disc_f * 100:.1f}%)"
                        elif "%" not in winning_wh_status and max_disc_f > 0:
                            winning_wh_status = f"{winning_wh_status} ({max_disc_f * 100:.1f}%)"

                    for c_i in range(1, 10):
                        c = ws_po.cell(row=r_idx, column=c_i)
                        c.font = font_cell
                        c.border = thin_border

                        if c_i == 1:
                            c.value = r_idx - sec_header_row
                            c.alignment = align_center
                        elif c_i == 2:
                            ref_drug_name = (
                                r_data.get('اسم الصنف في أرصدة المخازن')
                                or r_data.get('اسم الصنف في أرصده المخازن')
                                or r_data.get('اسم الصنف المطلوب (في طلب الشراء)')
                                or r_data.get('clean_name')
                                or r_data.get('اسم الصنف')
                                or ''
                            )
                            c.value = clean_excel_str(ref_drug_name)
                            c.alignment = align_right
                        elif c_i == 3:
                            cat_drug_name = (
                                r_data.get('اسم الصنف في الكتالوج')
                                or r_data.get('اسم الصنف في كشف المخزن الفائز')
                                or r_data.get('اسم الصنف في كتالوج المخزن')
                                or r_data.get('item_name')
                                or ''
                            )
                            c.value = clean_excel_str(cat_drug_name)
                            c.alignment = align_right
                        elif c_i == 4:
                            bp_val = _parse_currency_value(r_data.get('سعر الجمهور للوحدة', 0.0))
                            if bp_val is not None:
                                c.value = bp_val
                                c.number_format = '#,##0.00'
                            else:
                                c.value = '-'
                            c.alignment = align_center
                        elif c_i in (5, 6, 7):
                            col_keys = {5: 'الخصم المرجح %', 6: 'خصم هذا المخزن %', 7: 'أعلى خصم متاح %'}
                            val = _parse_discount_value(r_data.get(col_keys[c_i]))
                            if val is not None:
                                c.value = float(val)
                                c.number_format = '0.0%'
                            else:
                                c.value = '-'
                            c.alignment = align_center
                        elif c_i == 8:
                            c.value = clean_excel_str(winning_wh_status)
                            c.alignment = align_center
                            if is_winner:
                                c.fill = fill_soft_green
                                c.font = font_soft_green
                            else:
                                c.fill = fill_soft_yellow
                                c.font = font_soft_yellow
                        elif c_i == 9:
                            diff_egp = _parse_currency_value(r_data.get('فرق السعر (الوفر بالجنيه)', 0.0))
                            if diff_egp is not None:
                                c.value = diff_egp
                                c.number_format = '#,##0.00'
                            else:
                                c.value = '-'
                            c.font = font_cell_bold
                            c.alignment = align_center

                        if is_even and c_i != 8:
                            c.fill = fill_zebra

                    current_sec_row = r_idx

                # Secondary Table Summary Row
                sec_sum_row = current_sec_row + 1
                ws_po.cell(row=sec_sum_row, column=2, value=f"إجمالي الأصناف: {len(sec_df)} صنف").font = font_cell_bold
                ws_po.cell(row=sec_sum_row, column=2).alignment = align_right

                c_sec_saving_sum = ws_po.cell(row=sec_sum_row, column=9, value=f"=SUM(I{start_sec_data}:I{current_sec_row})")
                c_sec_saving_sum.font = font_cell_bold
                c_sec_saving_sum.number_format = '#,##0.00'
                c_sec_saving_sum.alignment = align_center

                for c_i in range(1, len(sec_headers) + 1):
                    cell = ws_po.cell(row=sec_sum_row, column=c_i)
                    cell.fill = fill_total_row
                    cell.border = total_border
            else:
                sec_empty_row = sec_header_row + 1
                ws_po.merge_cells(f"A{sec_empty_row}:I{sec_empty_row}")
                c_empty = ws_po.cell(
                    row=sec_empty_row,
                    column=1,
                    value="لا توجد أصناف إضافية بخصم يتجاوز الخصم المرجح بـ 4% فأكثر لدى هذا المخزن حالياً."
                )
                c_empty.font = font_cell
                c_empty.alignment = align_center
                for c_i in range(1, len(sec_headers) + 1):
                    ws_po.cell(row=sec_empty_row, column=c_i).border = thin_border

                sec_sum_row = sec_empty_row + 1
                ws_po.cell(row=sec_sum_row, column=2, value="إجمالي الأصناف: 0 صنف").font = font_cell_bold
                ws_po.cell(row=sec_sum_row, column=2).alignment = align_right

                for c_i in range(1, len(sec_headers) + 1):
                    cell = ws_po.cell(row=sec_sum_row, column=c_i)
                    cell.fill = fill_total_row
                    cell.border = total_border

            self._autofit_columns(ws_po)

        # -------------------------------------------------------------
        # SHEET LAST: Out of Stock - نواقص غير متوفرة
        # -------------------------------------------------------------
        oos_sheet_title = clean_sheet_title("نواقص غير متوفرة")
        if oos_sheet_title in existing_sheet_titles:
            oos_sheet_title = f"{oos_sheet_title[:28]}_1"
        existing_sheet_titles.add(oos_sheet_title)
        ws_oos = wb.create_sheet(title=oos_sheet_title)
        ws_oos.views.sheetView[0].rightToLeft = True

        # Row 1: Title
        ws_oos.merge_cells("A1:E1")
        oos_title = ws_oos["A1"]
        oos_title.value = clean_excel_str("بيان الأصناف غير المتوفرة في المخازن (نواقص الشراء)")
        oos_title.font = font_main_title
        oos_title.alignment = align_center

        # Row 2: Subtitle
        ws_oos.merge_cells("A2:E2")
        oos_sub = ws_oos["A2"]
        oos_count = len(oos_df) if oos_df is not None else 0
        oos_sub.value = clean_excel_str(f"إجمالي النواقص: {oos_count} صنف | يتطلب المتابعة مع الموردين أو البحث عن بدائل معتمدة")
        oos_sub.font = font_subtitle
        oos_sub.alignment = align_center

        # Row 4: Headers
        oos_headers = ['م', 'اسم الصنف المطلوب', 'الكمية المطلوبة', 'حالة التوفر', 'ملاحظات المتابعة والبحث']
        for c_i, h in enumerate(oos_headers, 1):
            c = ws_oos.cell(row=4, column=c_i)
            c.value = clean_excel_str(h)
            c.font = font_tbl_header
            c.fill = PatternFill(start_color="595959", end_color="595959", fill_type="solid")
            c.alignment = align_center
            c.border = thin_border

        # Row 5+: Data Rows
        if oos_df is not None and not oos_df.empty:
            for r_i, row_data in enumerate(oos_df.values, 5):
                is_even = (r_i % 2 == 0)
                for c_i, val in enumerate(row_data, 1):
                    c = ws_oos.cell(row=r_i, column=c_i)
                    c.font = font_cell
                    c.border = thin_border
                    
                    if c_i == 1:
                        try:
                            c.value = int(val) if val is not None and not (isinstance(val, float) and val != val) else r_i - 4
                        except (ValueError, TypeError):
                            c.value = r_i - 4
                        c.alignment = align_center
                    elif c_i == 2:
                        c.value = clean_excel_str(val)
                        c.alignment = align_right
                    elif c_i == 3:
                        try:
                            c.value = int(val) if val is not None and not (isinstance(val, float) and val != val) else 1
                        except (ValueError, TypeError):
                            c.value = 1
                        c.alignment = align_center
                    else:
                        c.value = clean_excel_str(val)
                        c.alignment = align_center
                        
                    if is_even:
                        c.fill = fill_oos_row

        self._autofit_columns(ws_oos)

        # -------------------------------------------------------------
        # SHEET FINAL: Recommendations & Alternatives - توصيات وبدائل النواقص
        # -------------------------------------------------------------
        rec_sheet_title = clean_sheet_title("توصيات وبدائل النواقص")
        if rec_sheet_title in existing_sheet_titles:
            rec_sheet_title = f"{rec_sheet_title[:28]}_1"
        existing_sheet_titles.add(rec_sheet_title)
        ws_rec = wb.create_sheet(title=rec_sheet_title)
        ws_rec.views.sheetView[0].rightToLeft = True

        # Build fallback rec_df if not provided
        if rec_df is None or (isinstance(rec_df, pd.DataFrame) and rec_df.empty):
            rec_rows = []
            if oos_df is not None and not oos_df.empty:
                for idx, r in enumerate(oos_df.values, 1):
                    rec_rows.append({
                        'م': idx,
                        'الصنف الأصلي المطلوب (الناقص)': r[1] if len(r) > 1 else '',
                        'الكمية المطلوبة': r[2] if len(r) > 2 else 1,
                        'البديل التجاري المقترح': 'لا يوجد بديل تجاري متوفر حالياً بالمخازن',
                        'المخزن المتاح لديه': '-',
                        'سعر الجمهور': '-',
                        'نسبة الخصم %': '-',
                        'السعر بعد الخصم': '-',
                        'ملاحظات الصيدلي والتوصيات': 'يتطلب المتابعة مع الوكلاء أو توفير صنف بديل معتمد'
                    })
            rec_df_render = pd.DataFrame(rec_rows) if rec_rows else pd.DataFrame(columns=[
                'م', 'الصنف الأصلي المطلوب (الناقص)', 'الكمية المطلوبة',
                'البديل التجاري المقترح', 'المخزن المتاح لديه', 'سعر الجمهور',
                'نسبة الخصم %', 'السعر بعد الخصم', 'ملاحظات الصيدلي والتوصيات'
            ])
        else:
            rec_df_render = rec_df

        # Row 1: Title
        ws_rec.merge_cells("A1:I1")
        rec_title = ws_rec["A1"]
        rec_title.value = clean_excel_str("توصيات وبدائل النواقص التجارية للأصناف غير المتوفرة (مراجعة الصيدلي)")
        rec_title.font = font_main_title
        rec_title.alignment = align_center

        # Row 2: Subtitle / Pharmacist Guidance
        ws_rec.merge_cells("A2:I2")
        rec_sub = ws_rec["A2"]
        rec_sub.value = clean_excel_str("تنبيه مهني للصيدلي: هذه البدائل التجارية مقترحة كخيارات اختيارية للمراجعة المهنية ولا تضاف تلقائياً لطلبيات التوريد حفاظاً على سلامة التوريد")
        rec_sub.font = font_subtitle
        rec_sub.alignment = align_center

        # Row 4: Headers
        rec_headers = [
            'م', 'الصنف الأصلي المطلوب (الناقص)', 'الكمية المطلوبة',
            'البديل التجاري المقترح', 'المخزن المتاح لديه', 'سعر الجمهور',
            'نسبة الخصم %', 'السعر بعد الخصم', 'ملاحظات الصيدلي والتوصيات'
        ]
        fill_rec_header = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
        for c_i, h in enumerate(rec_headers, 1):
            c = ws_rec.cell(row=4, column=c_i)
            c.value = clean_excel_str(h)
            c.font = font_tbl_header
            c.fill = fill_rec_header
            c.alignment = align_center
            c.border = thin_border

        # Row 5+: Data Rows
        if not rec_df_render.empty:
            for r_i, row_data in enumerate(rec_df_render.values, 5):
                is_even = (r_i % 2 == 0)
                for c_i, val in enumerate(row_data, 1):
                    c = ws_rec.cell(row=r_i, column=c_i)
                    c.font = font_cell
                    c.border = thin_border

                    if c_i == 1:
                        try:
                            c.value = int(val) if val is not None and not (isinstance(val, float) and val != val) else r_i - 4
                        except (ValueError, TypeError):
                            c.value = r_i - 4
                        c.alignment = align_center
                    elif c_i in [2, 4]:
                        c.value = clean_excel_str(val)
                        c.alignment = align_right
                    elif c_i == 3:
                        try:
                            c.value = int(val) if val is not None and not (isinstance(val, float) and val != val) else 1
                        except (ValueError, TypeError):
                            c.value = 1
                        c.alignment = align_center
                    elif c_i in [6, 7, 8]:
                        try:
                            c.value = float(val) if val is not None and str(val).strip() != '-' else str(val)
                        except (ValueError, TypeError):
                            c.value = str(val)
                        c.alignment = align_center
                    else:
                        c.value = clean_excel_str(val)
                        c.alignment = align_center

                    if is_even:
                        c.fill = fill_zebra

        self._autofit_columns(ws_rec)

        # Save primary benchmark name: Procurement_Order_Optimized_YYYY-MM-DD.xlsx
        try:
            wb.save(filepath)
        except (PermissionError, OSError):
            ts = datetime.datetime.now().strftime("%H%M%S")
            filename = f"Procurement_Order_Optimized_{today_str}_{ts}.xlsx"
            filepath = os.path.join(self.output_dir, filename)
            try:
                wb.save(filepath)
            except (PermissionError, OSError):
                try:
                    from .pipeline import get_default_output_dir
                except ImportError:
                    from pipeline import get_default_output_dir
                fallback_dir = get_default_output_dir()
                self.output_dir = fallback_dir
                filepath = os.path.join(fallback_dir, filename)
                wb.save(filepath)

        # Also save Arabic name: أفضل_اسعار_YYYY-MM-DD.xlsx
        arabic_filename = f"أفضل_اسعار_{today_str}.xlsx"
        arabic_filepath = os.path.join(self.output_dir, arabic_filename)
        try:
            wb.save(arabic_filepath)
        except (PermissionError, OSError):
            pass
            
        return filepath

    def _get_warehouse_above_average_discounts(self, warehouse_name: str) -> pd.DataFrame:
        """
        Extracts above-average discount items for a specific warehouse where:
        Difference = (Warehouse Discount - Reference Weighted Average Discount) >= 4.0% (0.04).
        Returns a DataFrame with columns:
        ['م', 'اسم الصنف في أرصدة المخازن', 'اسم الصنف في الكتالوج', 'سعر الجمهور للوحدة',
         'الخصم المرجح %', 'خصم هذا المخزن %', 'أعلى خصم متاح %', 'المخزن صاحب أعلى خصم',
         'فرق السعر (الوفر بالجنيه)', '_is_winner', '_winning_wh', '_winning_disc']
        """
        w_clean = str(warehouse_name).replace(".pdf", "").strip()
        w_short = w_clean.replace("مخزن ", "").strip()

        # 1. Check per_warehouse_above_average_discounts in result
        per_wh_dict = self.result.get('per_warehouse_above_average_discounts')
        if isinstance(per_wh_dict, dict):
            for k, df_cand in per_wh_dict.items():
                k_clean = str(k).replace(".pdf", "").strip()
                k_short = k_clean.replace("مخزن ", "").strip()
                if warehouse_name == k or w_clean == k_clean or (w_short and w_short == k_short):
                    if isinstance(df_cand, pd.DataFrame) and not df_cand.empty:
                        res_rows = []
                        for _, r in df_cand.iterrows():
                            bp = _parse_currency_value(r.get('سعر الجمهور للوحدة') or r.get('سعر الجمهور') or r.get('base_price') or 0.0) or 0.0
                            wd = _parse_discount_value(r.get('خصم هذا المخزن %') or r.get('خصم هذا المخزن') or r.get('نسبة الخصم %') or 0.0) or 0.0
                            rd = _parse_discount_value(r.get('الخصم المرجح %') or r.get('خصم مرجح') or r.get('ref_discount') or 0.0) or 0.0
                            saving = r.get('فرق السعر (الوفر بالجنيه)') or r.get('فرق السعر') or r.get('الوفر بالجنيه') or r.get('unit_saving')
                            saving_val = _parse_currency_value(saving)
                            diff_disc = round(wd - rd, 4)
                            if saving_val is None:
                                saving_val = round(bp * diff_disc, 2)
                            if diff_disc >= 0.04 - 1e-6:
                                r_dict = dict(r)
                                r_dict['سعر الجمهور للوحدة'] = bp
                                r_dict['خصم هذا المخزن %'] = wd
                                r_dict['الخصم المرجح %'] = rd
                                r_dict['فرق السعر (الوفر بالجنيه)'] = saving_val
                                md = _parse_discount_value(r.get('أعلى خصم متاح %') or r.get('أعلى خصم %') or 0.0)
                                if md is not None and md > 0:
                                    r_dict['أعلى خصم متاح %'] = md
                                else:
                                    r_dict['أعلى خصم متاح %'] = wd
                                res_rows.append(r_dict)
                        if res_rows:
                            filtered_df = pd.DataFrame(res_rows)
                            filtered_df = filtered_df.sort_values(
                                by=['فرق الخصم %', 'خصم هذا المخزن %'] if 'فرق الخصم %' in filtered_df.columns else ['فرق السعر (الوفر بالجنيه)', 'خصم هذا المخزن %'],
                                ascending=[False, False]
                            ).reset_index(drop=True)
                            filtered_df['م'] = range(1, len(filtered_df) + 1)
                            return filtered_df
                        return pd.DataFrame(columns=[
                            'م', 'اسم الصنف في أرصدة المخازن', 'اسم الصنف في الكتالوج',
                            'سعر الجمهور للوحدة', 'الخصم المرجح %', 'خصم هذا المخزن %',
                            'أعلى خصم متاح %', 'المخزن صاحب أعلى خصم', 'فرق السعر (الوفر بالجنيه)'
                        ])

        # 2. Check above_average_discounts
        above_avg_df = self.result.get('above_average_discounts')
        if isinstance(above_avg_df, list):
            above_avg_df = pd.DataFrame(above_avg_df)

        if above_avg_df is not None and isinstance(above_avg_df, pd.DataFrame) and not above_avg_df.empty:
            # Check attrs['per_warehouse']
            attrs_dict = getattr(above_avg_df, 'attrs', {}).get('per_warehouse', {})
            if isinstance(attrs_dict, dict):
                for k, df_cand in attrs_dict.items():
                    k_clean = str(k).replace(".pdf", "").strip()
                    k_short = k_clean.replace("مخزن ", "").strip()
                    if warehouse_name == k or w_clean == k_clean or (w_short and w_short == k_short):
                        if isinstance(df_cand, pd.DataFrame) and not df_cand.empty:
                            res_rows = []
                            for _, r in df_cand.iterrows():
                                bp = _parse_currency_value(r.get('سعر الجمهور للوحدة') or r.get('سعر الجمهور') or r.get('base_price') or 0.0) or 0.0
                                wd = _parse_discount_value(r.get('خصم هذا المخزن %') or r.get('خصم هذا المخزن') or r.get('نسبة الخصم %') or 0.0) or 0.0
                                rd = _parse_discount_value(r.get('الخصم المرجح %') or r.get('خصم مرجح') or r.get('ref_discount') or 0.0) or 0.0
                                saving = r.get('فرق السعر (الوفر بالجنيه)') or r.get('فرق السعر') or r.get('الوفر بالجنيه') or r.get('unit_saving')
                                saving_val = _parse_currency_value(saving)
                                diff_disc = round(wd - rd, 4)
                                if saving_val is None:
                                    saving_val = round(bp * diff_disc, 2)
                                if diff_disc >= 0.04 - 1e-6:
                                    r_dict = dict(r)
                                    r_dict['سعر الجمهور للوحدة'] = bp
                                    r_dict['خصم هذا المخزن %'] = wd
                                    r_dict['الخصم المرجح %'] = rd
                                    r_dict['فرق السعر (الوفر بالجنيه)'] = saving_val
                                    md = _parse_discount_value(r.get('أعلى خصم متاح %') or r.get('أعلى خصم %') or 0.0)
                                    if md is not None and md > 0:
                                        r_dict['أعلى خصم متاح %'] = md
                                    else:
                                        r_dict['أعلى خصم متاح %'] = wd
                                    res_rows.append(r_dict)
                            if res_rows:
                                filtered_df = pd.DataFrame(res_rows)
                                filtered_df = filtered_df.sort_values(
                                    by=['فرق الخصم %', 'خصم هذا المخزن %'] if 'فرق الخصم %' in filtered_df.columns else ['فرق السعر (الوفر بالجنيه)', 'خصم هذا المخزن %'],
                                    ascending=[False, False]
                                ).reset_index(drop=True)
                                filtered_df['م'] = range(1, len(filtered_df) + 1)
                                return filtered_df
                            return pd.DataFrame(columns=[
                                'م', 'اسم الصنف في أرصدة المخازن', 'اسم الصنف في الكتالوج',
                                'سعر الجمهور للوحدة', 'الخصم المرجح %', 'خصم هذا المخزن %',
                                'أعلى خصم متاح %', 'المخزن صاحب أعلى خصم', 'فرق السعر (الوفر بالجنيه)'
                            ])

            # Fallback: Extract from above_avg_df columns
            target_disc_col = None
            for c in above_avg_df.columns:
                c_str = str(c).strip()
                c_norm = c_str.replace(".pdf", "").strip()
                c_short = c_norm.replace("خصم ", "").replace("مخزن ", "").strip()
                if c_str == f"خصم {warehouse_name}" or c_norm == f"خصم {w_clean}":
                    target_disc_col = c
                    break
                if c_short == w_short or c_norm == w_clean:
                    target_disc_col = c
                    break
                if c_str.startswith("خصم ") and (w_short in c_str or w_clean in c_str):
                    target_disc_col = c
                    break

            records = []
            for _, r in above_avg_df.iterrows():
                ref_name = r.get('اسم الصنف في أرصدة المخازن') or r.get('اسم الصنف في أرصده المخازن') or r.get('clean_name') or r.get('اسم الصنف المطلوب (في طلب الشراء)') or ''
                if not ref_name:
                    continue

                bp = _parse_currency_value(r.get('سعر الجمهور للوحدة') or r.get('سعر الجمهور') or r.get('base_price') or 0.0) or 0.0
                if bp <= 0:
                    continue

                rd = _parse_discount_value(r.get('الخصم المرجح %') or r.get('خصم مرجح') or r.get('ref_discount') or 0.0) or 0.0
                md = _parse_discount_value(r.get('أعلى خصم متاح %') or r.get('أعلى خصم %') or 0.0) or 0.0

                winning_wh = str(r.get('المخزن الفائز') or r.get('المخزن صاحب أعلى خصم') or '').strip()

                wd = None
                if target_disc_col and target_disc_col in r:
                    wd = _parse_discount_value(r[target_disc_col])

                if wd is None and (winning_wh == warehouse_name or winning_wh == w_clean or (w_short and w_short in winning_wh)):
                    wd = md

                if wd is None or wd <= 0.0:
                    continue

                diff_disc = round(wd - rd, 4)
                if diff_disc < 0.04 - 1e-6:
                    continue
                unit_saving = round(bp * diff_disc, 2)

                is_winner = (wd >= md - 1e-6)
                if is_winner:
                    wh_status = warehouse_name
                else:
                    cand_win = winning_wh
                    if not cand_win or cand_win == warehouse_name or cand_win == w_clean or (w_short and w_short == cand_win.replace("مخزن ", "").replace(".pdf", "").strip()):
                        for col_k in r.index:
                            if str(col_k).startswith('خصم ') and col_k != target_disc_col:
                                try:
                                    c_val = _parse_discount_value(r[col_k])
                                    if c_val is not None and abs(c_val - md) < 1e-6:
                                        cand_win = str(col_k).replace('خصم ', '').strip()
                                        break
                                except (ValueError, TypeError):
                                    pass
                    if not cand_win:
                        cand_win = "مخزن منافس"
                    wh_status = f"{cand_win} ({md * 100:.1f}%)"

                cat_name = r.get(f'اسم الصنف في كتالوج {warehouse_name}') or r.get('اسم الصنف في كشف المخزن الفائز') or r.get('اسم الصنف في كتالوج المخزن') or ref_name

                records.append({
                    'اسم الصنف في أرصدة المخازن': ref_name,
                    'اسم الصنف في الكتالوج': cat_name,
                    'سعر الجمهور للوحدة': bp,
                    'الخصم المرجح %': rd,
                    'خصم هذا المخزن %': wd,
                    'أعلى خصم متاح %': md if md > 0 else wd,
                    'المخزن صاحب أعلى خصم': wh_status,
                    'فرق السعر (الوفر بالجنيه)': unit_saving,
                    '_is_winner': is_winner,
                    '_winning_wh': cand_win if not is_winner else warehouse_name,
                    '_winning_disc': md,
                })

            if records:
                records.sort(key=lambda x: (x.get('فرق الخصم %', 0.0), x.get('خصم هذا المخزن %', 0.0)), reverse=True)
                for idx, item in enumerate(records, 1):
                    item['م'] = idx
                return pd.DataFrame(records)

        return pd.DataFrame(columns=[
            'م', 'اسم الصنف في أرصدة المخازن', 'اسم الصنف في الكتالوج',
            'سعر الجمهور للوحدة', 'الخصم المرجح %', 'خصم هذا المخزن %',
            'أعلى خصم متاح %', 'المخزن صاحب أعلى خصم', 'فرق السعر (الوفر بالجنيه)'
        ])

    def _autofit_columns(self, ws):
        """Adjust column widths dynamically for professional visual presentation."""
        multi_col_merged_rows = set()
        for rng in ws.merged_cells.ranges:
            if rng.min_col != rng.max_col:
                for r in range(rng.min_row, rng.max_row + 1):
                    multi_col_merged_rows.add(r)

        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.value is not None:
                    # Ignore rows that span multiple columns (titles/banners) or KPI cards
                    if cell.row in multi_col_merged_rows or cell.row in [1, 2] or (ws.title == "المقارنة الشاملة وتوزيع الأصناف" and cell.row in [4, 5]):
                        continue
                    val_str = str(cell.value)
                    # Ignore notice/placeholder rows spanning long text
                    if "لا توجد أصناف" in val_str:
                        continue
                    max_len = max(max_len, len(val_str))
            ws.column_dimensions[col_letter].width = max(max_len + 5, 14)

    @classmethod
    def generate_report(cls, allocation_result: dict, output_dir: Optional[str] = None, custom_date_str: Optional[str] = None) -> str:
        """Convenience class method matching ReportGenerator.generate_report()."""
        generator = cls(allocation_result, output_dir=output_dir)
        return generator.generate(custom_date_str=custom_date_str)


# Alias for domain benchmark compliance
ReportGenerator = ArabicExcelReportGenerator

