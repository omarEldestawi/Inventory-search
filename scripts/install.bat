@echo off
chcp 65001 > nul
echo ======================================================================
echo  📦 تثبيت المتطلبات لتشغيل برنامج مقارنة أسعار الأدوية (Setup)
echo ======================================================================
python --version > nul 2>&1
if errorlevel 1 (
    echo [!] خطأ: بايثون غير مثبت على هذا الجهاز.
    echo برجاء تحميل وتثبيت Python من الرابط: https://www.python.org/downloads/
    echo وتأكد من تفعيل خيار "Add Python to PATH" أثناء التثبيت.
    echo.
    pause
    exit /b 1
)

echo [+] تم العثور على Python.
echo [+] جاري تثبيت المكتبات المطلوبة من requirements.txt ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [!] حدث خطأ أثناء تثبيت المكتبات. يرجى التأكد من الاتصال بالإنترنت.
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo  [✓] تم تجهيز بيئة التشغيل بنجاح!
echo  👉 لتشغيل البرنامج في أي وقت، اضغط نقرتين على: run_daily.bat
echo ======================================================================
pause
