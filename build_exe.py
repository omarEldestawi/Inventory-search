# -*- coding: utf-8 -*-
"""
PyInstaller Bundler for Egyptian Pharma Procurement Optimizer.
Bundles CustomTkinter, RapidOCR, RapidTable, ONNX runtimes, models, and assets.
"""
import os
import sys
import subprocess
import site

def build():
    datas = []

    def add_data_item(src: str, dst: str):
        """Helper to add items to PyInstaller datas using cross-platform os.pathsep."""
        if os.path.exists(src):
            datas.append(f"{src}{os.pathsep}{dst}")

    # 1. CustomTkinter assets
    try:
        import customtkinter
        ctk_path = os.path.dirname(customtkinter.__file__)
        add_data_item(ctk_path, "customtkinter")
    except Exception as e:
        print(f"Warning: Could not resolve customtkinter path: {e}")

    # 2. Source code, input templates, and application assets
    add_data_item("src", "src")
    add_data_item("input", "input")
    add_data_item("assets", "assets")

    # 3. Models directory and standalone ONNX model files
    add_data_item("models", "models")
    for model_name in ["slanet-plus.onnx", "slanet.onnx", "table_rec.onnx", "ch_PP-OCRv4_det_infer.onnx", "ch_PP-OCRv4_rec_infer.onnx", "ch_ppocr_mobile_v2.0_cls_infer.onnx"]:
        if os.path.isfile(model_name):
            add_data_item(model_name, "models")
        if os.path.isfile(os.path.join("src", "models", model_name)):
            add_data_item(os.path.join("src", "models", model_name), "models")

    # 4. RapidOCR package and bundled config/models
    try:
        import rapidocr_onnxruntime
        rapidocr_path = os.path.dirname(rapidocr_onnxruntime.__file__)
        add_data_item(rapidocr_path, "rapidocr_onnxruntime")
        ro_models = os.path.join(rapidocr_path, "models")
        if os.path.exists(ro_models):
            add_data_item(ro_models, os.path.join("rapidocr_onnxruntime", "models"))
    except Exception as e:
        print(f"Note: rapidocr_onnxruntime not imported directly: {e}")

    # 5. RapidTable package and bundled models
    try:
        import rapid_table
        rapid_table_path = os.path.dirname(rapid_table.__file__)
        add_data_item(rapid_table_path, "rapid_table")
        rt_models = os.path.join(rapid_table_path, "models")
        if os.path.exists(rt_models):
            add_data_item(rt_models, os.path.join("rapid_table", "models"))
    except Exception as e:
        print(f"Note: rapid_table not imported directly: {e}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "EgyptianPharmaOptimizer",
        "--icon", "assets/app.ico" if os.path.exists("assets/app.ico") else "NONE",
        "--collect-all", "customtkinter",
        "--collect-all", "rapidocr_onnxruntime",
        "--collect-all", "rapid_table",
        "--collect-all", "onnxruntime",
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "openpyxl",
        "--hidden-import", "pandas",
        "--hidden-import", "fitz",
        "--hidden-import", "pymupdf",
        "--hidden-import", "rapidocr_onnxruntime",
        "--hidden-import", "rapid_table",
        "--hidden-import", "onnxruntime",
    ]

    for d in datas:
        cmd.extend(["--add-data", d])

    cmd.append("app_gui.py")

    print("Running PyInstaller...")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print("PyInstaller build failed.")
        sys.exit(res.returncode)
    print("PyInstaller build succeeded. Output located at dist/EgyptianPharmaOptimizer/")

if __name__ == "__main__":
    build()
