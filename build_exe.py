# -*- coding: utf-8 -*-
"""
PyInstaller Bundler for Egyptian Pharma Procurement Optimizer.
Bundles CustomTkinter, RapidOCR, RapidTable, ONNX runtimes, models, and assets.
"""
import os
import sys
import subprocess
import site
import customtkinter

def build():
    ctk_path = os.path.dirname(customtkinter.__file__)
    
    # Locate RapidOCR / RapidTable assets if present
    datas = [
        f"{ctk_path};customtkinter",
        "src;src",
    ]

    if os.path.exists("input"):
        datas.append("input;input")

    # Include ONNX models if in a local models directory
    if os.path.exists("models"):
        datas.append("models;models")
    if os.path.exists("assets"):
        datas.append("assets;assets")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "EgyptianPharmaOptimizer",
        "--icon", "assets/app.ico" if os.path.exists("assets/app.ico") else "NONE",
        "--collect-all", "customtkinter",
        "--collect-all", "rapidocr_onnxruntime",
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "openpyxl",
        "--hidden-import", "pandas",
        "--hidden-import", "fitz",
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
