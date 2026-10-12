@echo off
chcp 65001 > nul
echo ======================================================================
echo  🏥 تشغيل مقارنة أسعار الأدوية اليومية وتوزيع الطلبيات
echo ======================================================================

python --version > nul 2>&1
if errorlevel 1 (
    echo [!] خطأ: لم يتم العثور على Python في هذا الجهاز.
    echo برجاء تثبيت بايثون من: https://www.python.org/downloads/
    echo وتأكد من تفعيل "Add Python to PATH"
    pause
    exit /b 1
)

:: Check if core packages are installed
python -c "import pymupdf, pandas, openpyxl, rapidfuzz" > nul 2>&1
if errorlevel 1 (
    echo [!] تم اكتشاف نقص في بعض المكتبات المطلوبة.
    echo [+] جاري تثبيتها تلقائياً الآن...
    python -m pip install -r requirements.txt
)

python main.py
echo.
pause

