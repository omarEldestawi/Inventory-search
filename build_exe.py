# -*- coding: utf-8 -*-
"""
PyInstaller Bundler for Egyptian Pharma Procurement Optimizer (v2.7.2).
Bundles CustomTkinter, PyMuPDF, RapidFuzz, SQLite Medication DB, Arabic OCR ONNX models, and assets.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
APP_NAME = "EgyptianPharmaOptimizer"
MAX_BUNDLE_BYTES = 480 * 1024 * 1024
MAX_INSTALLER_BYTES = 150 * 1024 * 1024
WORKER = Path("src/native_ocr/PowerToysOcrWorker.exe")
RUNTIME_RESOURCES = (
    Path("assets/app.ico"), Path("assets/models/dict.txt"), Path("assets/models/rec.onnx"),
    Path("data/medications.db"), Path("data/average_discounts.xlsx"),
    Path("tests/fixtures/hayah_shibin.pdf"),
)


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ensure_native_ocr_worker():
    """Compile the native worker when its source or compiler inputs change."""
    worker = ROOT / WORKER
    source = worker.with_suffix(".cs")
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    framework = windows / "Microsoft.NET" / "Framework64" / "v4.0.30319"
    compiler = framework / "csc.exe"
    references = [
        *(framework / name for name in (
            "System.Runtime.WindowsRuntime.dll", "System.Runtime.dll",
            "System.Threading.Tasks.dll", "System.Web.Extensions.dll")),
        *(windows / "System32" / "WinMetadata" / f"Windows.{name}.winmd" for name in (
            "Foundation", "Globalization", "Graphics", "Media", "Security", "Storage")),
    ]
    inputs = {str(path): _sha256(path) for path in (source, compiler, *references)}
    flags = ["/nologo", "/optimize+", "/target:exe"]
    stamp = ROOT / "build" / "native_ocr.json"
    stamp.parent.mkdir(exist_ok=True)
    try:
        previous = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    rebuild = (previous.get("inputs") != inputs or previous.get("flags") != flags
               or not worker.is_file() or previous.get("worker_sha256") != _sha256(worker))
    if rebuild:
        staged = stamp.parent / "PowerToysOcrWorker.exe"
        command = [str(compiler), *flags, f"/out:{staged}",
                   *(f"/r:{reference}" for reference in references), str(source)]
        subprocess.run(command, cwd=ROOT, check=True, timeout=60)
    else:
        staged = worker
    request = '{"request_id":"smoke","image_base64":"invalid"}\n{"command":"exit"}\n'
    smoke = subprocess.run([str(staged)], input=request, text=True, encoding="utf-8",
                           capture_output=True, timeout=7, check=True)
    lines = smoke.stdout.splitlines()
    if len(lines) != 2 or lines[0] != "__READY__":
        raise RuntimeError(f"Invalid native worker smoke response: {smoke.stderr}")
    response = json.loads(lines[1])
    if response.get("request_id") != "smoke" or response.get("status") != "error":
        raise RuntimeError("Native worker did not echo its smoke request ID")
    if rebuild:
        staged.replace(worker)
    stamp.write_text(json.dumps(dict(inputs=inputs, flags=flags, worker_sha256=_sha256(worker)), indent=2),
                     encoding="utf-8")


def verify_bundle(bundle):
    if not bundle.is_dir():
        raise FileNotFoundError(f"Expected distribution at {bundle}")
    required = {Path("_internal") / path for path in (*RUNTIME_RESOURCES, WORKER)}
    files = []
    worker_paths = []
    resource_hashes = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or path.name == "bundle_manifest.json":
            continue
        relative = path.relative_to(bundle)
        lowered = relative.name.lower()
        if lowered.endswith((".bak", "-journal", "-wal", "-shm", ".log")):
            raise ValueError(f"Unexpected runtime file: {relative}")
        app_resource = (relative.parts[0] in {"src", "tests", "data", "assets", "input"}
                        or (len(relative.parts) > 1 and relative.parts[0] == "_internal"
                            and relative.parts[1] in {"src", "tests", "data", "assets", "input"}))
        if app_resource and relative not in required:
            raise ValueError(f"Unexpected bundled app resource: {relative}")
        if lowered == WORKER.name.lower():
            worker_paths.append(relative)
        digest = _sha256(path)
        if relative in required:
            resource_hashes[relative] = digest
        files.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": digest})
    if required - resource_hashes.keys() or worker_paths != [Path("_internal") / WORKER]:
        raise ValueError(f"Missing resources or invalid worker paths: {required - resource_hashes.keys()}, {worker_paths}")
    counts = {}
    for entry in files:
        counts[entry["sha256"]] = counts.get(entry["sha256"], 0) + 1
    for relative, digest in resource_hashes.items():
        if counts[digest] != 1:
            raise ValueError(f"Duplicate bundled resource content: {relative}")
    total = sum(entry["bytes"] for entry in files)
    manifest = bundle / "bundle_manifest.json"
    manifest.write_text(json.dumps({"bundle_bytes": total, "files": files}, indent=2), encoding="utf-8")
    total += manifest.stat().st_size
    if total > MAX_BUNDLE_BYTES:
        raise ValueError(f"Bundle exceeds 480 MiB: {total / 1024**2:.1f} MiB")
    return total


def build():
    ensure_native_ocr_worker()
    work = ROOT / "build" / f"v272-{time.time_ns()}"
    staged_dist = work / "dist"
    work.mkdir(parents=True)
    datas = []
    for resource in RUNTIME_RESOURCES:
        if not (ROOT / resource).is_file():
            raise FileNotFoundError(resource)
        datas.append(f"{resource}{os.pathsep}{resource.parent.as_posix()}")
    binaries = [f"{WORKER}{os.pathsep}{WORKER.parent.as_posix()}"]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", APP_NAME,
        "--distpath", str(staged_dist),
        "--workpath", str(work / "work"),
        "--icon", "assets/app.ico" if os.path.exists("assets/app.ico") else "NONE",
        "--collect-all", "customtkinter",
        "--collect-all", "onnxruntime",
        "--collect-all", "cv2",
        "--collect-all", "rapidfuzz",
        "--collect-all", "pymupdf",
        "--collect-all", "openpyxl",
        "--collect-all", "numpy",
        "--collect-all", "PIL",
        "--collect-all", "rapidocr_onnxruntime",
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "openpyxl",
        "--hidden-import", "pandas",
        "--hidden-import", "fitz",
        "--hidden-import", "pymupdf",
        "--hidden-import", "rapidfuzz",
        "--hidden-import", "google",
        "--hidden-import", "sqlite3",
        "--hidden-import", "onnxruntime",
        "--hidden-import", "cv2",
        "--hidden-import", "src.ocr_engine",
        "--hidden-import", "src.image_table_detector",
        "--hidden-import", "src.catalog_recovery",
        "--hidden-import", "src.pdf_font_decoder",
        "--hidden-import", "src.catalog_diagnostics",
        "--hidden-import", "src.catalog_corrections",
        "--hidden-import", "src.catalog_service",
        "--hidden-import", "src.controller",
        "--hidden-import", "src.pipeline",
        "--hidden-import", "src.allocator",
        "--hidden-import", "src.medication_db",
        "--hidden-import", "src.catalog_reader",
        "--hidden-import", "src.average_discounts",
        "--hidden-import", "src.updater",
        "--hidden-import", "src.pharma_matcher",
        "--hidden-import", "src.report_generator",
        "--hidden-import", "src.normalizer",
        "--hidden-import", "src.pdf_parser",
        "--hidden-import", "src.excel_parser",
        "--hidden-import", "src.order_parser",
        "--hidden-import", "src.gemini_matcher",
        "--hidden-import", "src.manual_search_window",
        "--hidden-import", "src.manual_search_adapter",
        "--hidden-import", "src.box_ocr_service",
    ]

    for d in datas:
        cmd.extend(["--add-data", d])

    for b in binaries:
        cmd.extend(["--add-binary", b])

    cmd.append("app_gui.py")

    print("Running PyInstaller...")
    subprocess.run(cmd, cwd=ROOT, check=True, timeout=600)
    staged_bundle = staged_dist / APP_NAME
    total = verify_bundle(staged_bundle)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    bundle = dist / APP_NAME
    archive = dist / f"{APP_NAME}_old_{time.time_ns()}"
    if not all(path.resolve().is_relative_to(ROOT) for path in (dist, bundle, archive, staged_bundle)):
        raise ValueError("Distribution paths must remain inside the workspace")
    if bundle.exists():
        bundle.rename(archive)
    try:
        staged_bundle.rename(bundle)
    except OSError:
        if archive.exists() and not bundle.exists():
            archive.rename(bundle)
        raise
    print(f"Verified bundle: {bundle} ({total / 1024**2:.1f} MiB)")
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", type=Path, help="Compile and validate the installer after building")
    args = parser.parse_args()
    build()
    if args.iscc:
        subprocess.run([str(args.iscc.resolve()), "installer.iss"], cwd=ROOT, check=True, timeout=600)
        installer = ROOT / "dist_installer" / f"{APP_NAME}_Setup_v2.7.2.exe"
        if installer.stat().st_size > MAX_INSTALLER_BYTES:
            raise ValueError("Installer exceeds 150 MiB")
        print(f"Installer SHA-256: {_sha256(installer)}")


if __name__ == "__main__":
    main()
