# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

datas = [('src', 'src')]

if os.path.exists('input'):
    datas.append(('input', 'input'))
if os.path.exists('assets'):
    datas.append(('assets', 'assets'))
if os.path.exists('models'):
    datas.append(('models', 'models'))

# Include standalone ONNX models if present
for model_name in [
    'slanet-plus.onnx', 'slanet.onnx', 'table_rec.onnx',
    'ch_PP-OCRv4_det_infer.onnx', 'ch_PP-OCRv4_rec_infer.onnx', 'ch_ppocr_mobile_v2.0_cls_infer.onnx'
]:
    if os.path.isfile(model_name):
        datas.append((model_name, 'models'))
    if os.path.isfile(os.path.join('src', 'models', model_name)):
        datas.append((os.path.join('src', 'models', model_name), 'models'))

# Include rapidocr_onnxruntime package and models
try:
    import rapidocr_onnxruntime
    ro_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
    datas.append((ro_dir, 'rapidocr_onnxruntime'))
except Exception:
    pass

# Include rapid_table package and models
try:
    import rapid_table
    rt_dir = os.path.dirname(rapid_table.__file__)
    datas.append((rt_dir, 'rapid_table'))
except Exception:
    pass

binaries = []
hiddenimports = [
    'customtkinter',
    'PIL._tkinter_finder',
    'openpyxl',
    'pandas',
    'fitz',
    'pymupdf',
    'rapidocr_onnxruntime',
    'rapid_table',
    'onnxruntime',
]

for pkg_name in ['customtkinter', 'rapidocr_onnxruntime', 'rapid_table', 'onnxruntime']:
    try:
        tmp_ret = collect_all(pkg_name)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass


def _dedup(seq):
    seen = set()
    res = []
    for item in seq:
        k = item if not isinstance(item, (list, tuple)) else tuple(item)
        if k not in seen:
            seen.add(k)
            res.append(item)
    return res


datas = _dedup(datas)
binaries = _dedup(binaries)
hiddenimports = _dedup(hiddenimports)

icon_path = 'assets/app.ico' if os.path.exists('assets/app.ico') else None

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
    icon=[icon_path] if icon_path else None,
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
