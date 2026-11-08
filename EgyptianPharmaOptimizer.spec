# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('src', 'src'), ('assets', 'assets'), ('data/medications.db', 'data'), ('data/average_discounts.xlsx', 'data'), ('tests/fixtures', 'tests/fixtures')]
binaries = []
hiddenimports = ['customtkinter', 'PIL._tkinter_finder', 'openpyxl', 'pandas', 'fitz', 'pymupdf', 'rapidfuzz', 'google', 'sqlite3', 'onnxruntime', 'cv2', 'src.ocr_engine', 'src.image_table_detector', 'src.catalog_recovery', 'src.pdf_font_decoder', 'src.catalog_diagnostics', 'src.catalog_corrections', 'src.catalog_service', 'src.controller', 'src.pipeline', 'src.allocator', 'src.medication_db', 'src.catalog_reader', 'src.average_discounts', 'src.updater', 'src.pharma_matcher', 'src.report_generator', 'src.normalizer', 'src.pdf_parser', 'src.excel_parser', 'src.order_parser', 'src.gemini_matcher', 'src.manual_search_window', 'src.manual_search_adapter']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rapidfuzz')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pymupdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('openpyxl')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('numpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EgyptianPharmaOptimizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EgyptianPharmaOptimizer',
)
