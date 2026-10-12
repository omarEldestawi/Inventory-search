# -*- coding: utf-8 -*-
"""
Automated Google Drive & Local Directory Watcher.
Monitors the daily procurement folder, detects new catalogs or order files,
triggers the hybrid matching pipeline, and uploads the optimized Excel report.
"""
import os
import sys
import time
import glob
import logging
import argparse
import subprocess
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Watcher")

def get_drive_state(drive_dir: str) -> dict:
    """Returns a signature of files and modification times in the Drive folder."""
    state = {}
    try:
        files = [
            os.path.join(drive_dir, f) for f in os.listdir(drive_dir)
            if not f.startswith('~$') and not f.startswith('أفضل_اسعار') and not f.startswith('Procurement_Order_') and not f.endswith('.ini')
            and f.endswith(('.pdf', '.xlsx', '.xls', '.csv'))
        ]
        for f in files:
            try:
                state[f] = os.path.getmtime(f)
            except OSError:
                pass
    except Exception as e:
        logger.warning(f"Error accessing drive folder: {e}")
    return state

def run_procurement_pipeline(drive_dir: str = None, catalogs_dir: str = None, orders_dir: str = None, output_dir: str = None):
    """Executes main.py with the configured parameters."""
    cmd = [sys.executable, "main.py"]
    if drive_dir and os.path.exists(drive_dir):
        cmd += ["--drive-dir", drive_dir]
    else:
        if catalogs_dir: cmd += ["--catalogs-dir", catalogs_dir]
        if orders_dir: cmd += ["--orders-dir", orders_dir]
        if output_dir: cmd += ["--output-dir", output_dir]

    logger.info("Executing procurement pipeline...")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode == 0:
        logger.info("[✓] Pipeline execution finished successfully!")
    else:
        logger.error(f"[!] Pipeline exited with error code {result.returncode}")

def main():
    parser = argparse.ArgumentParser(description="Pharmacy Daily Drive Watcher & Automated Optimizer")
    parser.add_argument("--drive-dir", default=os.getenv("DRIVE_DIR", r"G:\My Drive\Pharama Daily orders"), help="Google Drive folder path")
    parser.add_argument("--catalogs-dir", default="input/catalogs", help="Directory for warehouse catalogs")
    parser.add_argument("--orders-dir", default="input/orders", help="Directory for purchase orders")
    parser.add_argument("--output-dir", default="output", help="Directory for output Excel reports")
    parser.add_argument("--watch", action="store_true", help="Run continuously in watcher mode (poll every N seconds)")
    parser.add_argument("--interval", type=int, default=15, help="Poll interval in seconds (default: 15s)")
    args = parser.parse_args()

    using_drive = bool(args.drive_dir and os.path.exists(args.drive_dir))

    if not args.watch:
        logger.info("One-shot run mode triggered.")
        if using_drive:
            run_procurement_pipeline(drive_dir=args.drive_dir)
        else:
            run_procurement_pipeline(catalogs_dir=args.catalogs_dir, orders_dir=args.orders_dir, output_dir=args.output_dir)
        return

    watch_path = args.drive_dir if using_drive else f"{args.catalogs_dir} & {args.orders_dir}"
    logger.info(f"Starting continuous directory watcher (Polling every {args.interval}s)...")
    logger.info(f"Monitoring folder: '{watch_path}'")
    logger.info("Press Ctrl+C to stop.")

    last_state = get_drive_state(args.drive_dir) if using_drive else {}
    if last_state:
        logger.info(f"Initial scan: Found {len(last_state)} file(s). Running initial execution...")
        run_procurement_pipeline(drive_dir=args.drive_dir)

    try:
        while True:
            time.sleep(args.interval)
            current_state = get_drive_state(args.drive_dir) if using_drive else {}
            if current_state != last_state:
                logger.info("New or modified files detected! Triggering pipeline...")
                if using_drive:
                    run_procurement_pipeline(drive_dir=args.drive_dir)
                else:
                    run_procurement_pipeline(catalogs_dir=args.catalogs_dir, orders_dir=args.orders_dir, output_dir=args.output_dir)
                last_state = current_state
    except KeyboardInterrupt:
        logger.info("Watcher stopped by user.")

if __name__ == "__main__":
    main()
