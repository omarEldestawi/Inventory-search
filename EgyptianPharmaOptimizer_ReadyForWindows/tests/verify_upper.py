# -*- coding: utf-8 -*-
"""
Test specifically checking uppercase extensions behavior.
"""
import os
import sys
import tempfile
import pandas as pd
import openpyxl

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.controller import classify_files
from src.pipeline import parse_excel_catalog, run_procurement_pipeline, PipelineExecutionError
from src.excel_parser import load_purchase_order

def run_check():
    with tempfile.TemporaryDirectory() as tmp:
        # Create an xlsx file and rename it to .XLSX
        p_lower = os.path.join(tmp, "order_sample.xlsx")
        pd.DataFrame([{"الصنف": "Panadol", "الكمية": 5}]).to_excel(p_lower, index=False)
        p_upper = os.path.join(tmp, "ambiguous_order.XLSX")
        os.rename(p_lower, p_upper)
        
        print("Testing classify_files with uppercase .XLSX...")
        res = classify_files([p_upper])
        print("classify_files result:", res)

        print("Testing load_purchase_order with uppercase .XLSX...")
        try:
            df = load_purchase_order(p_upper)
            print("load_purchase_order succeeded:", len(df))
        except Exception as e:
            print("load_purchase_order FAILED with:", type(e), e)

        print("Testing parse_excel_catalog with uppercase .XLSX...")
        cat_lower = os.path.join(tmp, "catalog_sample.xlsx")
        pd.DataFrame([{"اسم الصنف": "Panadol", "نسبة الخصم": "20%", "سعر الجمهور": 50}]).to_excel(cat_lower, index=False)
        cat_upper = os.path.join(tmp, "catalog_sample.XLSX")
        os.rename(cat_lower, cat_upper)
        try:
            df_cat = parse_excel_catalog(cat_upper, "wh_test")
            print("parse_excel_catalog succeeded, rows:", len(df_cat))
        except Exception as e:
            print("parse_excel_catalog FAILED with:", type(e), e)

if __name__ == "__main__":
    run_check()
