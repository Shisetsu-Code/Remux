@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 goto :error

%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name Remux remux_gui.py
if errorlevel 1 goto :error

echo.
echo Listo: dist\Remux.exe
echo.
pause
exit /b 0

:error
echo.
echo No se pudo compilar Remux.exe.
pause
exit /b 1
