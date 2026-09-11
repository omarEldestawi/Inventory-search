# DISPATCH — Worker R2 (PyInstaller Standalone Executable)

## Mission
Build and verify the PyInstaller standalone executable for the Egyptian Pharmaceutical Procurement Engine:
1. Review `build_exe.py`. Ensure all required hidden imports and datas are bundled:
   - `customtkinter`
   - `rapidocr_onnxruntime`
   - `rapid_table`
   - `onnxruntime`
   - `cv2`
   - `PIL`
   - `openpyxl`
   - `pandas`
   - `fitz`
   - `models/` (including `slanet-plus.onnx` if present)
   - `assets/`
   - `input/` if present
2. Execute `python build_exe.py` (or PyInstaller directly).
3. Verify that the build succeeds and outputs to `dist/EgyptianPharmaOptimizer/` containing `EgyptianPharmaOptimizer.exe`.
4. Test the generated executable by running `dist\EgyptianPharmaOptimizer\EgyptianPharmaOptimizer.exe --self-test` to ensure it launches headless and passes with exit code 0.
5. Create `handoff.md` in your working directory with build logs, verification output, and file sizes.

## Working Directory
`c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_r2`

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT fabricate build logs or verification outputs.
