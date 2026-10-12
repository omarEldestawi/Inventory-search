@echo off
setlocal

REM Ensure Git is in PATH
set "PATH=%LOCALAPPDATA%\Programs\Git\cmd;C:\Program Files\Git\cmd;%PATH%"

echo ===================================================
echo   Pharma Procurement - Automatic Git Backup
echo ===================================================
echo.

git --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Git is not installed or not found.
    pause
    exit /b 1
)

REM Ensure remote is set to SSH URL
git remote get-url origin >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    git remote add origin git@github.com:omarEldestawi/Inventory-search.git
)

echo [1/3] Staging all files...
git add -A

echo [2/3] Committing changes...
git diff-index --quiet HEAD --
if %ERRORLEVEL% NEQ 0 (
    git commit -m "Auto backup: %DATE% %TIME%"
) else (
    echo No new changes to commit.
)

echo [3/3] Pushing to GitHub (SSH key auth - zero password required)...
git push -u origin main
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ===================================================
    echo   Backup Successful! Pushed to origin/main.
    echo ===================================================
) else (
    echo.
    echo [NOTE] If you haven't created the repository on GitHub yet:
    echo 1. Go to https://github.com/new
    echo 2. Repository name: Inventory-search
    echo 3. Leave it empty and click "Create repository".
    echo 4. Re-run this file (git_backup.bat), and it will push instantly with NO password needed!
)

echo.
pause
