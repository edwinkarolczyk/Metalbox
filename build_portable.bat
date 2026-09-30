@echo off
setlocal

py -m pip install --upgrade pip
py -m pip install -r requirements.txt

if exist dist rmdir /S /Q dist
if exist build rmdir /S /Q build

py -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name Metalbox ^
  --collect-all PySide6 ^
  app.py

if errorlevel 1 (
  echo.
  echo BLAD: budowanie Metalbox nie powiodlo sie.
  exit /b 1
)

echo.
echo GOTOWE: dist\Metalbox\Metalbox.exe
echo Caly katalog dist\Metalbox jest wersja portable.
endlocal
