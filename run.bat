@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 remux_gui.py
    goto :end
)

where python >nul 2>&1
if %errorlevel%==0 (
    python remux_gui.py
    goto :end
)

echo.
echo Python no esta instalado o no esta en PATH.
echo Podes usar Remux.exe desde GitHub Actions sin instalar Python.
echo.
pause

:end
endlocal
