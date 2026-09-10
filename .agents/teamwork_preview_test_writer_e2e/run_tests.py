# -*- coding: utf-8 -*-
import sys
import pytest

if __name__ == '__main__':
    args = ["-v", "tests/test_pipeline.py", "tests/test_e2e_procurement.py"]
    print(f"Running pytest with args: {args}")
    code = pytest.main(args)
    print(f"\nPytest exited with code: {code}")
    sys.exit(code)
