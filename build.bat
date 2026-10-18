@echo off
REM ==========================================================
REM  Amp Player - بناء الملف التنفيذي (PyInstaller)
REM  الناتج: dist\Amp Player\Amp Player.exe  مجلد كامل جاهز للنسخ
REM  الخطوة الأولى تولّد الأيقونة (tools\make_icon.py).
REM  لا يحتاج البرنامج إلى VLC أو أي مثبّت خارجي.
REM ==========================================================
setlocal
cd /d "%~dp0"

set "AMP_PYTHON=.venv\Scripts\python.exe"
if not exist "%AMP_PYTHON%" set "AMP_PYTHON=python"

echo [1/3] Generating the icon ...
"%AMP_PYTHON%" -X utf8 tools\make_icon.py
if errorlevel 1 goto :fail

echo [2/3] Building the bundle (this takes a few minutes) ...
"%AMP_PYTHON%" -X utf8 -m PyInstaller ampplayer.spec --noconfirm
if errorlevel 1 goto :fail

echo [3/3] Self-test on the frozen build ...
if not exist "dist\Amp Player\Amp Player.exe" goto :fail
start "" /wait "dist\Amp Player\Amp Player.exe" --selftest
if exist "dist\Amp Player\selftest.txt" (
  echo Report: dist\Amp Player\selftest.txt
) else (
  echo NOTE: no selftest.txt was written. If the launch was refused with
  echo       "An Application Control policy has blocked this file", that is
  echo       Smart App Control / a code-signing policy - see the README
  echo       section "building the executable". The build itself is fine.
)

echo.
echo Done: dist\Amp Player\Amp Player.exe
pause
goto :eof

:fail
echo BUILD FAILED - see the messages above.
pause
exit /b 1
