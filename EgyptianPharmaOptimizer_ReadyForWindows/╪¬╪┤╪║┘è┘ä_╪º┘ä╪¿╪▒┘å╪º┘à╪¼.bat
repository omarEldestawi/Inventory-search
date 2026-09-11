@echo off
chcp 65001 > nul
title نظام المشتريات الصيدلانية - Egyptian Pharma Procurement Optimizer
echo ========================================================
echo جاري تشغيل نظام المشتريات الصيدلانية v1.1.0...
echo Starting Egyptian Pharma Procurement Optimizer v1.1.0...
echo ========================================================
python app_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo حدث خطأ أثناء تشغيل البرنامج. يرجى التأكد من تثبيت بايثون.
    echo An error occurred. Press any key to exit...
    pause > nul
)
