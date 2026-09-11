import numpy as np
from PIL import Image, ImageDraw
from rapidocr_onnxruntime import RapidOCR
from rapid_table import RapidTable

ocr = RapidOCR()
table_engine = RapidTable()

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
    # RapidOCR returns list of [box, text, score]
    dt_boxes = np.array([x[0] for x in ocr_result])  # shape (N, 4, 2)
    rec_res = [x[1] for x in ocr_result]
    scores = [float(x[2]) for x in ocr_result]

    # RapidTable expects ocr_results to be a LIST (one element per image)
    # where each element is a tuple/list: (dt_boxes, rec_res, scores)
    per_image_ocr = (dt_boxes, rec_res, scores)
    batch_ocr = [per_image_ocr]

    table_out = table_engine(img_np, ocr_results=batch_ocr)
    print("Table recognition succeeded!")
    print("table_out type:", type(table_out))
    print("table_out:", table_out)
    if hasattr(table_out, "pred_html"):
        print("\n--- HTML output ---")
        print(table_out.pred_html)
    if hasattr(table_out, "pred_str"):
        print("\n--- Pred str ---")
        print(table_out.pred_str)
    if hasattr(table_out, "cell_bboxes"):
        print("\n--- Cell bboxes count ---:", len(table_out.cell_bboxes))
