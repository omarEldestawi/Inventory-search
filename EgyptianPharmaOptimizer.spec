# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:/Users/omart/AppData/Local/Programs/Python/Python312/Lib/site-packages/customtkinter', 'customtkinter'), ('src', 'src'), ('input', 'input'), ('assets', 'assets'), ('data', 'data'), ('tests/fixtures', 'tests/fixtures')]
binaries = []
hiddenimports = ['customtkinter', 'PIL._tkinter_finder', 'openpyxl', 'pandas', 'fitz', 'pymupdf', 'rapidfuzz', 'google', 'sqlite3', 'src.medication_db', 'src.average_discounts', 'src.updater', 'src.catalog_diagnostics', 'src.catalog_reader', 'src.catalog_recovery', 'src.catalog_corrections', 'src.catalog_service']
tmp_ret = collect_all('customtkinter')
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
