import inspect
import numpy as np

print("--- RapidOCR ---")
try:
    from rapidocr_onnxruntime import RapidOCR
    print("RapidOCR class:", RapidOCR)
    init_sig = inspect.signature(RapidOCR.__init__)
    print("RapidOCR.__init__ signature:", init_sig)
    call_sig = inspect.signature(RapidOCR.__call__)
    print("RapidOCR.__call__ signature:", call_sig)
except Exception as e:
    print("RapidOCR error:", e)

print("\n--- RapidTable ---")
try:
    from rapid_table import RapidTable
    print("RapidTable class:", RapidTable)
    init_sig = inspect.signature(RapidTable.__init__)
    print("RapidTable.__init__ signature:", init_sig)
    call_sig = inspect.signature(RapidTable.__call__)
    print("RapidTable.__call__ signature:", call_sig)
except Exception as e:
    print("RapidTable error:", e)
