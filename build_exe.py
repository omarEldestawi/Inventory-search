# -*- coding: utf-8 -*-
"""
PyInstaller Bundler for Egyptian Pharma Procurement Optimizer (v2.7).
Bundles CustomTkinter, PyMuPDF, RapidFuzz, SQLite Medication DB, Arabic OCR ONNX models, and assets.
"""
import os
import sys
import subprocess
import site
import shutil
import stat

def safe_rmtree(path):
    if not os.path.exists(path):
        return
    def on_rm_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    try:
        shutil.rmtree(path, onerror=on_rm_error)
    except Exception:
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Remove-Item -Recurse -Force '{path}'"], capture_output=True)

def build():
    dist_dir = os.path.join("dist", "EgyptianPharmaOptimizer")
    safe_rmtree(dist_dir)
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

    # 2. Source code, input templates, application assets, test fixtures, and medication knowledge base
    add_data_item("src", "src")
    add_data_item("input", "input")
    add_data_item("assets", "assets")
    add_data_item("data", "data")
    add_data_item("tests/fixtures", "tests/fixtures")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "EgyptianPharmaOptimizer",
        "--icon", "assets/app.ico" if os.path.exists("assets/app.ico") else "NONE",
        "--collect-all", "customtkinter",
        "--collect-all", "onnxruntime",
        "--collect-all", "cv2",
        "--collect-all", "rapidfuzz",
        "--collect-all", "pymupdf",
        "--collect-all", "openpyxl",
        "--collect-all", "numpy",
        "--collect-all", "PIL",
        "--collect-all", "rapidocr_onnxruntime",
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "openpyxl",
        "--hidden-import", "pandas",
        "--hidden-import", "fitz",
        "--hidden-import", "pymupdf",
        "--hidden-import", "rapidfuzz",
        "--hidden-import", "google",
        "--hidden-import", "sqlite3",
        "--hidden-import", "onnxruntime",
        "--hidden-import", "cv2",
        "--hidden-import", "src.ocr_engine",
        "--hidden-import", "src.image_table_detector",
        "--hidden-import", "src.catalog_recovery",
        "--hidden-import", "src.pdf_font_decoder",
        "--hidden-import", "src.catalog_diagnostics",
        "--hidden-import", "src.catalog_corrections",
        "--hidden-import", "src.catalog_service",
        "--hidden-import", "src.controller",
        "--hidden-import", "src.pipeline",
        "--hidden-import", "src.allocator",
        "--hidden-import", "src.medication_db",
        "--hidden-import", "src.catalog_reader",
        "--hidden-import", "src.average_discounts",
        "--hidden-import", "src.updater",
        "--hidden-import", "src.pharma_matcher",
        "--hidden-import", "src.report_generator",
        "--hidden-import", "src.normalizer",
        "--hidden-import", "src.pdf_parser",
        "--hidden-import", "src.excel_parser",
        "--hidden-import", "src.order_parser",
        "--hidden-import", "src.gemini_matcher",
        "--hidden-import", "src.manual_search_window",
        "--hidden-import", "src.manual_search_adapter",
    ]

    for d in datas:
        cmd.extend(["--add-data", d])

    cmd.append("app_gui.py")

    print("Running PyInstaller...")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print("PyInstaller build failed.")
        sys.exit(res.returncode)

    # Ensure assets/, data/, and tests/fixtures/ are bundled directly in dist root and _internal
    dist_root = os.path.join("dist", "EgyptianPharmaOptimizer")
    dist_internal = os.path.join(dist_root, "_internal")

    # 1. Assets (including assets/models/rec.onnx and dict.txt)
    if os.path.exists("assets"):
        shutil.copytree("assets", os.path.join(dist_root, "assets"), dirs_exist_ok=True)
        if os.path.isdir(dist_internal):
            shutil.copytree("assets", os.path.join(dist_internal, "assets"), dirs_exist_ok=True)

    # 2. Data
    if os.path.exists("data"):
        shutil.copytree("data", os.path.join(dist_root, "data"), dirs_exist_ok=True)
        if os.path.isdir(dist_internal):
            shutil.copytree("data", os.path.join(dist_internal, "data"), dirs_exist_ok=True)

    # 3. Tests / Fixtures
    if os.path.exists(os.path.join("tests", "fixtures")):
        shutil.copytree(os.path.join("tests", "fixtures"), os.path.join(dist_root, "tests", "fixtures"), dirs_exist_ok=True)
        if os.path.isdir(dist_internal):
            shutil.copytree(os.path.join("tests", "fixtures"), os.path.join(dist_internal, "tests", "fixtures"), dirs_exist_ok=True)

    # 4. Source code directory
    if os.path.exists("src"):
        shutil.copytree("src", os.path.join(dist_root, "src"), dirs_exist_ok=True)
        if os.path.isdir(dist_internal):
            shutil.copytree("src", os.path.join(dist_internal, "src"), dirs_exist_ok=True)

    print("PyInstaller build succeeded. Output located at dist/EgyptianPharmaOptimizer/")

if __name__ == "__main__":
    build()
