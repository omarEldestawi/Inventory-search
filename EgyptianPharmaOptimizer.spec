# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:/Users/omart/AppData/Local/Programs/Python/Python312/Lib/site-packages/customtkinter', 'customtkinter'), ('src', 'src'), ('input', 'input'), ('assets', 'assets'), ('data', 'data'), ('C:/Users/omart/AppData/Local/Programs/Python/Python312/Lib/site-packages/rapidocr_onnxruntime', 'rapidocr_onnxruntime'), ('C:/Users/omart/AppData/Local/Programs/Python/Python312/Lib/site-packages/rapidocr_onnxruntime/models', 'rapidocr_onnxruntime/models'), ('C:/Users/omart/AppData/Local/Programs/Python/Python312/Lib/site-packages/rapid_table', 'rapid_table'), ('C:/Users/omart/AppData/Local/Programs/Python/Python312/Lib/site-packages/rapid_table/models', 'rapid_table/models')]
binaries = []
hiddenimports = ['customtkinter', 'PIL._tkinter_finder', 'openpyxl', 'pandas', 'fitz', 'pymupdf', 'rapidocr_onnxruntime', 'rapid_table', 'onnxruntime', 'rapidfuzz', 'google', 'sqlite3', 'src.medication_db', 'src.average_discounts', 'src.updater']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rapid_table')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
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
