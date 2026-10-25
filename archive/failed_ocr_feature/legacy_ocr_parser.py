# -*- coding: utf-8 -*-
"""
ARCHIVED / FAILED FEATURE (2026-10-25):
Legacy RapidOCR + RapidTable PDF Catalog OCR Engine.

Status: FAILED — Archived for historical reference only.
Reason: RapidOCR's bundled PaddleOCR models (`ch_PP-OCRv4_rec_infer.onnx`) do not support
Arabic script or RTL ligatures, resulting in 0 extracted Arabic items on Egyptian pharmaceutical
catalogs before falling back to digital parsing. Replaced by pure PyMuPDF vector coordinate
and drawing-rectangle extraction (`_extract_arwasoft_3col_rects`, etc.) in `src/pdf_parser.py`.
"""
import os
import sys
import re
import logging
import unicodedata
from typing import Optional, Tuple, Dict
import pymupdf
import pandas as pd
import numpy as np

logger = logging.getLogger("ArchivedOCRParser")

_ocr_engine = None
_table_engine = None


def find_rapid_table_model() -> Optional[str]:
    """
    [ARCHIVED - FAILED OCR FEATURE]
    Locates the slanet-plus.onnx / table recognition model for RapidTable across
    frozen PyInstaller bundles (sys._MEIPASS), local models directories, and site-packages.
    """
    env_path = os.environ.get("RAPID_TABLE_MODEL_PATH")
    if env_path and os.path.isfile(env_path):
        return os.path.normpath(os.path.abspath(env_path))

    candidates = []
    model_names = ["slanet-plus.onnx", "slanet.onnx", "table_rec.onnx", "table_structure.onnx"]

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for name in model_names:
            candidates.extend([
                os.path.join(meipass, "rapid_table", "models", name),
                os.path.join(meipass, "models", name),
                os.path.join(meipass, "rapid_table", name),
                os.path.join(meipass, name),
                os.path.join(meipass, "_internal", "rapid_table", "models", name),
                os.path.join(meipass, "_internal", "models", name),
                os.path.join(meipass, "_internal", "rapid_table", name),
                os.path.join(meipass, "_internal", name),
            ])

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        for name in model_names:
            candidates.extend([
                os.path.join(exe_dir, "_internal", "rapid_table", "models", name),
                os.path.join(exe_dir, "_internal", "models", name),
                os.path.join(exe_dir, "_internal", "rapid_table", name),
                os.path.join(exe_dir, "_internal", name),
                os.path.join(exe_dir, "models", name),
                os.path.join(exe_dir, "rapid_table", "models", name),
                os.path.join(exe_dir, "rapid_table", name),
                os.path.join(exe_dir, name),
            ])

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for name in model_names:
        candidates.extend([
            os.path.join(project_root, "models", name),
            os.path.join(project_root, name),
            os.path.join(project_root, "assets", name),
            os.path.join(project_root, "src", "models", name),
        ])

    try:
        import rapid_table
        pkg_dir = os.path.dirname(rapid_table.__file__)
        for name in model_names:
            candidates.extend([
                os.path.join(pkg_dir, "models", name),
                os.path.join(pkg_dir, name),
            ])
    except Exception:
        pass

    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.normpath(os.path.abspath(path))

    return None


def find_rapid_ocr_assets() -> Tuple[Optional[str], Dict[str, Optional[str]]]:
    """
    [ARCHIVED - FAILED OCR FEATURE]
    Locates bundled config.yaml and ONNX models (det, rec, cls) for RapidOCR.
    """
    config_candidates = []
    env_cfg = os.environ.get("RAPID_OCR_CONFIG_PATH")
    if env_cfg:
        config_candidates.append(env_cfg)

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        config_candidates.extend([
            os.path.join(meipass, "rapidocr_onnxruntime", "config.yaml"),
            os.path.join(meipass, "config.yaml"),
            os.path.join(meipass, "models", "config.yaml"),
            os.path.join(meipass, "_internal", "rapidocr_onnxruntime", "config.yaml"),
            os.path.join(meipass, "_internal", "config.yaml"),
        ])

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        config_candidates.extend([
            os.path.join(exe_dir, "_internal", "rapidocr_onnxruntime", "config.yaml"),
            os.path.join(exe_dir, "rapidocr_onnxruntime", "config.yaml"),
            os.path.join(exe_dir, "config.yaml"),
            os.path.join(exe_dir, "models", "config.yaml"),
        ])

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_candidates.extend([
        os.path.join(project_root, "config.yaml"),
        os.path.join(project_root, "models", "config.yaml"),
        os.path.join(project_root, "assets", "config.yaml"),
    ])

    try:
        import rapidocr_onnxruntime
        pkg_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
        config_candidates.extend([
            os.path.join(pkg_dir, "config.yaml"),
            os.path.join(pkg_dir, "models", "config.yaml"),
        ])
    except Exception:
        pass

    resolved_config = None
    for cp in config_candidates:
        if cp and os.path.isfile(cp):
            resolved_config = os.path.normpath(os.path.abspath(cp))
            break

    model_keys = {
        "det_model_path": [
            "ch_PP-OCRv4_det_infer.onnx",
            "ch_PP-OCRv3_det_infer.onnx",
            "det.onnx",
            "ch_ppocr_server_v2.0_det_infer.onnx",
        ],
        "rec_model_path": [
            "ch_PP-OCRv4_rec_infer.onnx",
            "ch_PP-OCRv3_rec_infer.onnx",
            "rec.onnx",
            "ch_ppocr_server_v2.0_rec_infer.onnx",
        ],
        "cls_model_path": [
            "ch_ppocr_mobile_v2.0_cls_infer.onnx",
            "cls.onnx",
        ],
    }

    env_keys = {
        "det_model_path": "RAPID_OCR_DET_MODEL_PATH",
        "rec_model_path": "RAPID_OCR_REC_MODEL_PATH",
        "cls_model_path": "RAPID_OCR_CLS_MODEL_PATH",
    }

    search_dirs = [project_root, os.path.join(project_root, "models"), os.path.join(project_root, "assets")]
    try:
        import rapidocr_onnxruntime
        pkg_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
        search_dirs.extend([pkg_dir, os.path.join(pkg_dir, "models")])
    except Exception:
        pass

    resolved_models = {}
    for param_name, filenames in model_keys.items():
        env_var = env_keys.get(param_name)
        if env_var and os.environ.get(env_var) and os.path.isfile(os.environ[env_var]):
            resolved_models[param_name] = os.path.normpath(os.path.abspath(os.environ[env_var]))
            continue

        found_path = None
        for sdir in search_dirs:
            for fname in filenames:
                candidate = os.path.join(sdir, fname)
                if os.path.isfile(candidate):
                    found_path = os.path.normpath(os.path.abspath(candidate))
                    break
            if found_path:
                break
        if found_path:
            resolved_models[param_name] = found_path

    return resolved_config, resolved_models


def get_legacy_ocr_engine():
    """[ARCHIVED - FAILED OCR FEATURE] Lazy singleton initializer for RapidOCR."""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            config_path, model_paths = find_rapid_ocr_assets()
            ocr_kwargs = {}
            if config_path and os.path.isfile(config_path):
                ocr_kwargs["config_path"] = config_path
            for param_name, model_path in model_paths.items():
                if model_path and os.path.isfile(model_path):
                    ocr_kwargs[param_name] = model_path
            _ocr_engine = RapidOCR(**ocr_kwargs) if ocr_kwargs else RapidOCR()
        except Exception as exc:
            logger.warning(f"Archived RapidOCR initialization failed: {exc}")
            return None
    return _ocr_engine


def get_legacy_table_engine():
    """[ARCHIVED - FAILED OCR FEATURE] Lazy singleton initializer for RapidTable."""
    global _table_engine
    if _table_engine is None:
        try:
            from rapid_table import RapidTable, RapidTableInput
            model_path = find_rapid_table_model()
            if model_path and os.path.isfile(model_path):
                cfg = RapidTableInput(model_dir_or_path=model_path)
                _table_engine = RapidTable(cfg=cfg)
            else:
                _table_engine = RapidTable()
        except Exception as exc:
            logger.warning(f"Archived RapidTable initialization failed: {exc}")
            return None
    return _table_engine
