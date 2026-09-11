import os
import rapidocr_onnxruntime

pkg_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
print("rapidocr dir:", pkg_dir)
for root, dirs, files in os.walk(pkg_dir):
    for f in files:
        if f.endswith(".onnx"):
            print("  onnx:", os.path.relpath(os.path.join(root, f), pkg_dir))

import rapid_table
table_dir = os.path.dirname(rapid_table.__file__)
print("rapid_table dir:", table_dir)
for root, dirs, files in os.walk(table_dir):
    for f in files:
        if f.endswith(".onnx"):
            print("  onnx:", os.path.relpath(os.path.join(root, f), table_dir))
