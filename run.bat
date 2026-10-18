@echo off
REM ==========================================================
REM  Amp Player - تشغيل البرنامج
REM  استخدم البيئة الافتراضية .venv إن وُجدت،
REM  وإلا فاستخدم بايثون من المسار.
REM  لا يحتاج البرنامج إلى VLC أو أي مثبّت خارجي.
REM ==========================================================
setlocal
cd /d "%~dp0"

set "AMP_PYTHON=.venv\Scripts\pythonw.exe"
if not exist "%AMP_PYTHON%" set "AMP_PYTHON=.venv\Scripts\python.exe"
if not exist "%AMP_PYTHON%" set "AMP_PYTHON=python"

REM -X utf8 حتى لا يخطئ إخراج النصوص العربية على الطرفية
start "Amp Player" /min "%AMP_PYTHON%" -X utf8 main.py %*

endlocal
