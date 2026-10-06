@echo off
rem ================================================================
rem  SignOffAI Workbench -- double-click to launch
rem
rem  Usage:  run_gui.bat                 launch with default manifest
rem          run_gui.bat -m flow.task    launch and focus a module
rem          run_gui.bat --reset-layout  ignore the saved layout
rem
rem  NOTE: keep this file ASCII-only. cmd.exe reads .bat with the
rem  system codepage (GBK on zh-CN Windows); UTF-8 Chinese in here
rem  gets split mid-character and breaks parsing.
rem
rem  Why not pythonw.exe: it has no console, so a failed start shows
rem  NOTHING -- the hardest kind of failure to diagnose. With the
rem  console build the window sits alongside the GUI and any error
rem  stays on screen behind a pause.
rem ================================================================

setlocal
cd /d "%~dp0"

set PY=%~dp0venv\Scripts\python.exe
if not exist "%PY%" (
    echo.
    echo [FAIL] python not found in the venv:
    echo     %PY%
    echo.
    echo   This project must use its own venv. To create one:
    echo     python -m venv venv
    echo     venv\Scripts\python.exe -m pip install ^
    echo         -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
    echo.
    pause
    exit /b 2
)

"%PY%" -m src.workbench config\workbench.yaml %*

if errorlevel 1 (
    echo.
    echo [FAIL] exit code %errorlevel% -- the error is above.
    echo   Two usual causes:
    echo     * ModuleNotFoundError: PySide6  -^> venv\Scripts\python.exe -m pip install PySide6
    echo     * window off-screen              -^> retry with --reset-layout
    echo.
    pause
)
endlocal
