# -*- coding: utf-8 -*-
"""
PyInstaller Bundler for Egyptian Pharma Procurement Optimizer.
Bundles CustomTkinter, PyMuPDF, RapidFuzz, SQLite Medication DB, and assets.
(Note: Legacy RapidOCR / RapidTable / ONNX runtime bundling removed after OCR feature was archived as FAILED.)
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
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "openpyxl",
        "--hidden-import", "pandas",
        "--hidden-import", "fitz",
        "--hidden-import", "pymupdf",
        "--hidden-import", "rapidfuzz",
        "--hidden-import", "google",
        "--hidden-import", "sqlite3",
        "--hidden-import", "src.medication_db",
        "--hidden-import", "src.average_discounts",
        "--hidden-import", "src.updater",
        "--hidden-import", "src.catalog_diagnostics",
        "--hidden-import", "src.catalog_reader",
    ]

    for d in datas:
        cmd.extend(["--add-data", d])

    cmd.append("app_gui.py")

    print("Running PyInstaller...")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print("PyInstaller build failed.")
        sys.exit(res.returncode)

    # Ensure data/ and tests/fixtures/ are bundled directly for standalone runs
    out_data = os.path.join("dist", "EgyptianPharmaOptimizer", "data")
    if os.path.exists("data"):
        os.makedirs(out_data, exist_ok=True)
        for fname in os.listdir("data"):
            src_f = os.path.join("data", fname)
            dst_f = os.path.join(out_data, fname)
            if os.path.isfile(src_f):
                shutil.copy2(src_f, dst_f)

    out_fixtures = os.path.join("dist", "EgyptianPharmaOptimizer", "tests", "fixtures")
    if os.path.exists(os.path.join("tests", "fixtures")):
        os.makedirs(out_fixtures, exist_ok=True)
        for fname in os.listdir(os.path.join("tests", "fixtures")):
            src_f = os.path.join("tests", "fixtures", fname)
            dst_f = os.path.join(out_fixtures, fname)
            if os.path.isfile(src_f):
                shutil.copy2(src_f, dst_f)

    print("PyInstaller build succeeded. Output located at dist/EgyptianPharmaOptimizer/")

if __name__ == "__main__":
    build()
