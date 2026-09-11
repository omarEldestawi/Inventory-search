import sys
sys.stdout.reconfigure(encoding="utf-8")
import fitz
import numpy as np
import time
from rapidocr_onnxruntime import RapidOCR
from rapid_table import RapidTable

pdf_path = r"input\catalogs\الشركة_المتحدة.pdf"
doc = fitz.open(pdf_path)
page = doc[0]
pix = page.get_pixmap(dpi=300)
img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
if pix.n == 4:
    img_np = img_np[:, :, :3]

ocr = RapidOCR()
ocr_result, _ = ocr(img_np)

table_engine = RapidTable()
dt_boxes = np.array([x[0] for x in ocr_result])
rec_res = [x[1] for x in ocr_result]
scores = [float(x[2]) for x in ocr_result]

per_image_ocr = (dt_boxes, rec_res, scores)
batch_ocr = [per_image_ocr]

t0 = time.time()
table_out = table_engine(img_np, ocr_results=batch_ocr)
print(f"RapidTable completed in {time.time() - t0:.2f}s")
if hasattr(table_out, "pred_htmls") and table_out.pred_htmls:
    print("\n--- Extracted HTML ---")
    print(table_out.pred_htmls[0])
