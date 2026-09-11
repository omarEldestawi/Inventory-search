import numpy as np
from PIL import Image, ImageDraw
from rapidocr_onnxruntime import RapidOCR
from rapid_table import RapidTable

ocr = RapidOCR()
table_engine = RapidTable()

# Create a sample table image
# Columns: اسم الصنف | السعر | الخصم
img = Image.new("RGB", (600, 200), color=(255, 255, 255))
draw = ImageDraw.Draw(img)
# Draw header
draw.text((20, 20), "Item", fill=(0, 0, 0))
draw.text((200, 20), "Price", fill=(0, 0, 0))
draw.text((400, 20), "Discount", fill=(0, 0, 0))
# Draw row 1
draw.text((20, 70), "Panadol Extra", fill=(0, 0, 0))
draw.text((200, 70), "50.00", fill=(0, 0, 0))
draw.text((400, 70), "20%", fill=(0, 0, 0))
# Draw row 2
draw.text((20, 120), "Cataflam 50mg", fill=(0, 0, 0))
draw.text((200, 120), "35.00", fill=(0, 0, 0))
draw.text((400, 120), "15%", fill=(0, 0, 0))

img_np = np.array(img)
ocr_result, _ = ocr(img_np)
print("OCR items count:", len(ocr_result) if ocr_result else 0)

if ocr_result:
    dt_boxes = [x[0] for x in ocr_result]
    rec_res = [x[1] for x in ocr_result]
    scores = [float(x[2]) for x in ocr_result]
    ocr_tuple = (dt_boxes, rec_res, scores)

    print("Passing formatted ocr_tuple to table_engine...")
    table_out = table_engine(img_np, ocr_results=ocr_tuple)
    print("table_out:", table_out)
    print("table_out type:", type(table_out))
    if hasattr(table_out, "pred_html"):
        print("pred_html:\n", table_out.pred_html)
    if hasattr(table_out, "pred_str"):
        print("pred_str:\n", table_out.pred_str)
