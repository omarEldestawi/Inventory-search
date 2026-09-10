# -*- coding: utf-8 -*-
"""
Arabic Excel Report Generator with 100% Structural & Visual Parity to Procurement_Order_Optimized benchmark.
Generates Right-to-Left (RTL) multi-sheet workbooks with identical typography, KPI summary cards,
exact formulas, financial totals, and side-by-side catalog comparison.
"""
import os
import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class ArabicExcelReportGenerator:
    def __init__(self, allocation_result: dict, output_dir: str = "output"):
        self.result = allocation_result
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
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
        allocated = self.result.get('allocated_orders', {})
        oos_df = self.result.get('out_of_stock')

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
        c_title.value = "تقرير مقارنة أسعار الأدوية وخطة الشراء المحسنة"
        c_title.font = font_main_title
        c_title.alignment = align_center

        # Row 2: Subtitle
        ws_master.merge_cells(f"A2:{end_col_letter}2")
        c_sub = ws_master["A2"]
        num_wh = kpis.get('num_warehouses', len(allocated))
        c_sub.value = f"تحليل عروض {num_wh} مخازن أدوية وتوزيع الأصناف حسب أعلى نسبة خصم مع مطابقة تامة بدون بدائل | {arabic_date_text}"
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
            
            c_top.value = lbl
            c_top.font = font_kpi_lbl
            c_top.alignment = align_center
            c_top.fill = fill_kpi
            
            c_val.value = val
            c_val.font = font_kpi_val
            c_val.alignment = align_center
            c_val.fill = fill_kpi

        for row in ws_master["A4:N5"]:
            for cell in row:
                cell.border = thin_border

        # Row 8: Table Headers
        start_row = 8
        if master_df is not None and not master_df.empty:
            headers = list(master_df.columns)
            for col_idx, h in enumerate(headers, 1):
                c = ws_master.cell(row=start_row, column=col_idx)
                c.value = h
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
                        c.value = int(val) if val is not None else r_i - start_row
                        c.alignment = align_center
                    # Col 2, 3: Item Names
                    elif c_i in (2, 3):
                        c.value = str(val) if val is not None else ""
                        c.alignment = align_right
                    # Col 4: Qty
                    elif c_i == 4:
                        c.value = int(val) if val is not None else 1
                        c.alignment = align_center
                    # Col 5: Winning Warehouse
                    elif c_i == 5:
                        c.value = str(val) if val is not None else ""
                        c.alignment = align_center
                    # Col 6: Highest Discount %
                    elif c_i == 6:
                        try:
                            c.value = float(val)
                            c.number_format = '0.0%'
                        except (ValueError, TypeError):
                            c.value = val
                        c.alignment = align_center
                    # Col 7..11: Currency amounts
                    elif c_i in (7, 8, 9, 10, 11):
                        try:
                            c.value = float(val)
                            c.number_format = '#,##0.00'
                        except (ValueError, TypeError):
                            c.value = val
                        c.alignment = align_center
                    # Warehouse discount columns
                    else:
                        if isinstance(val, (int, float)):
                            c.value = float(val)
                            c.number_format = '0.0%'
                        else:
                            c.value = val
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
        # SHEETS 2+: Winning Supplier PO Sheets (طلب شراء - [اسم المخزن])
        # -------------------------------------------------------------
        for w_name, po_df in allocated.items():
            clean_tab_name = w_name.replace("مخزن ", "").replace(".pdf", "").strip()[:20]
            sheet_title = f"طلب شراء - {clean_tab_name}"[:31]
            ws_po = wb.create_sheet(title=sheet_title)
            ws_po.views.sheetView[0].rightToLeft = True

            # Row 1: Title
            ws_po.merge_cells("A1:J1")
            po_title = ws_po["A1"]
            po_title.value = f"أمر توريد أدوية - {w_name}"
            po_title.font = font_main_title
            po_title.alignment = align_center

            # Row 2: Subtitle
            ws_po.merge_cells("A2:J2")
            po_sub = ws_po["A2"]
            po_sub.value = f"تاريخ الطلب: {arabic_date_text} | عدد الأصناف المعتمدة: {len(po_df)} صنف"
            po_sub.font = font_subtitle
            po_sub.alignment = align_center

            # Row 4: Header
            po_headers = [
                'م', 'اسم الصنف في أمر الشراء', 'اسم الصنف في كتالوج المخزن',
                'الكمية المطلوبة', 'نسبة الخصم %', 'سعر الجمهور للوحدة',
                'سعر التوريد الصافي', 'إجمالي القيمة بسعر الجمهور',
                'إجمالي القيمة الصافية', 'ملاحظات التوريد'
            ]
            for c_i, h in enumerate(po_headers, 1):
                c = ws_po.cell(row=4, column=c_i)
                c.value = h
                c.font = font_tbl_header
                c.fill = fill_navy_header
                c.alignment = align_center
                c.border = thin_border

            # Row 5+: Data Rows
            current_po_row = 4
            for r_i, row_data in enumerate(po_df.values, 5):
                is_even = (r_i % 2 == 0)
                for c_i, val in enumerate(row_data, 1):
                    c = ws_po.cell(row=r_i, column=c_i)
                    c.font = font_cell
                    c.border = thin_border
                    
                    if c_i == 1:
                        c.value = int(val) if val is not None else r_i - 4
                        c.alignment = align_center
                    elif c_i in (2, 3):
                        c.value = str(val) if val is not None else ""
                        c.alignment = align_right
                    elif c_i == 4:
                        c.value = int(val) if val is not None else 1
                        c.alignment = align_center
                    elif c_i == 5:
                        try:
                            c.value = float(val)
                            c.number_format = '0.0%'
                        except (ValueError, TypeError):
                            c.value = val
                        c.alignment = align_center
                    elif c_i in (6, 7, 8, 9):
                        try:
                            c.value = float(val)
                            c.number_format = '#,##0.00'
                        except (ValueError, TypeError):
                            c.value = val
                        c.alignment = align_center
                    else:
                        c.value = str(val) if val is not None else ""
                        c.alignment = align_center

                    if is_even:
                        c.fill = fill_zebra
                current_po_row = r_i

            # Summary Row for Supplier
            po_sum_row = current_po_row + 1
            ws_po.cell(row=po_sum_row, column=2, value="الإجمالي").font = font_cell_bold
            ws_po.cell(row=po_sum_row, column=2).alignment = align_right
            
            c_qty = ws_po.cell(row=po_sum_row, column=4, value=f"=SUM(D5:D{current_po_row})")
            c_qty.font = font_cell_bold
            c_qty.alignment = align_center
            
            c_pub = ws_po.cell(row=po_sum_row, column=8, value=f"=SUM(H5:H{current_po_row})")
            c_pub.font = font_cell_bold
            c_pub.number_format = '#,##0.00'
            c_pub.alignment = align_center
            
            c_net = ws_po.cell(row=po_sum_row, column=9, value=f"=SUM(I5:I{current_po_row})")
            c_net.font = font_cell_bold
            c_net.number_format = '#,##0.00'
            c_net.alignment = align_center

            for c_i in range(1, len(po_headers) + 1):
                cell = ws_po.cell(row=po_sum_row, column=c_i)
                cell.fill = fill_total_row
                cell.border = total_border

            self._autofit_columns(ws_po)

        # -------------------------------------------------------------
        # SHEET LAST: Out of Stock - نواقص غير متوفرة
        # -------------------------------------------------------------
        ws_oos = wb.create_sheet(title="نواقص غير متوفرة")
        ws_oos.views.sheetView[0].rightToLeft = True

        # Row 1: Title
        ws_oos.merge_cells("A1:E1")
        oos_title = ws_oos["A1"]
        oos_title.value = "بيان الأصناف غير المتوفرة في المخازن (نواقص الشراء)"
        oos_title.font = font_main_title
        oos_title.alignment = align_center

        # Row 2: Subtitle
        ws_oos.merge_cells("A2:E2")
        oos_sub = ws_oos["A2"]
        oos_count = len(oos_df) if oos_df is not None else 0
        oos_sub.value = f"إجمالي النواقص: {oos_count} صنف | يتطلب المتابعة مع الموردين أو البحث عن بدائل معتمدة"
        oos_sub.font = font_subtitle
        oos_sub.alignment = align_center

        # Row 4: Headers
        oos_headers = ['م', 'اسم الصنف المطلوب', 'الكمية المطلوبة', 'حالة التوفر', 'ملاحظات المتابعة والبحث']
        for c_i, h in enumerate(oos_headers, 1):
            c = ws_oos.cell(row=4, column=c_i)
            c.value = h
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
                        c.value = int(val) if val is not None else r_i - 4
                        c.alignment = align_center
                    elif c_i == 2:
                        c.value = str(val) if val is not None else ""
                        c.alignment = align_right
                    elif c_i == 3:
                        c.value = int(val) if val is not None else 1
                        c.alignment = align_center
                    else:
                        c.value = str(val) if val is not None else ""
                        c.alignment = align_center
                        
                    if is_even:
                        c.fill = fill_oos_row

        self._autofit_columns(ws_oos)

        # Save primary benchmark name: Procurement_Order_Optimized_YYYY-MM-DD.xlsx
        try:
            wb.save(filepath)
        except PermissionError:
            ts = datetime.datetime.now().strftime("%H%M%S")
            filename = f"Procurement_Order_Optimized_{today_str}_{ts}.xlsx"
            filepath = os.path.join(self.output_dir, filename)
            wb.save(filepath)

        # Also save Arabic name: أفضل_اسعار_YYYY-MM-DD.xlsx
        arabic_filename = f"أفضل_اسعار_{today_str}.xlsx"
        arabic_filepath = os.path.join(self.output_dir, arabic_filename)
        try:
            wb.save(arabic_filepath)
        except PermissionError:
            pass
            
        return filepath

    def _autofit_columns(self, ws):
        """Adjust column widths dynamically for professional visual presentation."""
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.value is not None:
                    val_str = str(cell.value)
                    # Ignore title and KPI rows when calculating widths
                    if cell.row in [1, 2, 4, 5]:
                        continue
                    max_len = max(max_len, len(val_str))
            ws.column_dimensions[col_letter].width = max(max_len + 5, 14)
