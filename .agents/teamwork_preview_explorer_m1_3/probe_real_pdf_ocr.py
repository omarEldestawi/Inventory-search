import sys
sys.stdout.reconfigure(encoding="utf-8")
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import io
import time
from rapidocr_onnxruntime import RapidOCR
from rapid_table import RapidTable

pdf_path = r"input\catalogs\الشركة_المتحدة.pdf"
print(f"Opening PDF: {pdf_path}")
doc = fitz.open(pdf_path)
print(f"Page count: {len(doc)}")

page = doc[0]
t0 = time.time()
pix = page.get_pixmap(dpi=300)
print(f"Rendered page 0 at 300 DPI in {time.time() - t0:.2f}s, size: {pix.width}x{pix.height}, format: {pix.colorspace.name}")

# Convert pixmap to numpy array (RGB)
# pix.samples has raw bytes
img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
if pix.n == 4:  # RGBA to RGB
    img_np = img_np[:, :, :3]
print(f"Numpy array shape: {img_np.shape}, dtype: {img_np.dtype}")

# Test RapidOCR on page
print("Running RapidOCR...")
t1 = time.time()
ocr = RapidOCR()
ocr_result, _ = ocr(img_np)
print(f"RapidOCR completed in {time.time() - t1:.2f}s. Detected {len(ocr_result) if ocr_result else 0} text elements.")

if ocr_result:
    print("Sample detected items (first 5):")
    for item in ocr_result[:5]:
        print(" ", item[1], f"(conf: {item[2]})")
