import numpy as np
from PIL import Image, ImageDraw
import time

print("Initializing RapidOCR...")
t0 = time.time()
from rapidocr_onnxruntime import RapidOCR
ocr = RapidOCR()
print(f"RapidOCR initialized in {time.time() - t0:.2f}s")

# Create a small dummy image with text
img = Image.new("RGB", (300, 100), color=(255, 255, 255))
draw = ImageDraw.Draw(img)
draw.text((10, 30), "Panadol 500mg 20 EGP", fill=(0, 0, 0))
img_np = np.array(img)

print("Running RapidOCR...")
t1 = time.time()
ocr_result, elapse_list = ocr(img_np)
print(f"RapidOCR ran in {time.time() - t1:.2f}s")
print("ocr_result type:", type(ocr_result))
print("ocr_result content:", ocr_result)
print("elapse_list:", elapse_list)

print("\nInitializing RapidTable...")
t2 = time.time()
from rapid_table import RapidTable
table_engine = RapidTable()
print(f"RapidTable initialized in {time.time() - t2:.2f}s")

# Let's inspect RapidTable return structure
print("Running RapidTable...")
t3 = time.time()
try:
    table_result = table_engine(img_np, ocr_results=ocr_result)
    print(f"RapidTable ran in {time.time() - t3:.2f}s")
    print("table_result type:", type(table_result))
    print("table_result dir/attrs:", [a for a in dir(table_result) if not a.startswith("_")])
    print("table_result content:", table_result)
except Exception as e:
    import traceback
    traceback.print_exc()
