@echo off
REM ==========================================================
REM  Amp Player - بناء ملف التثبيت (Inno Setup 6)
REM  الناتج: dist\AmpPlayer-1.1.0.exe
REM  يتطلب: مجلد dist\Amp Player مبنياً أولاً (شغّل build.bat)
REM ==========================================================
setlocal
cd /d "%~dp0"

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo INSTALLER BUILD FAILED - Inno Setup 6 not found.
  echo Install it with:  winget install --id JRSoftware.InnoSetup
  pause
  exit /b 1
)

if not exist "dist\Amp Player\Amp Player.exe" (
  echo No application build found. Run build.bat first.
  pause
  exit /b 1
)

echo [1/1] Building the installer ...
"%ISCC%" installer.iss
if errorlevel 1 (
  echo INSTALLER BUILD FAILED - see the messages above.
  pause
  exit /b 1
)

echo.
echo Done: dist\AmpPlayer-1.1.0.exe
pause
