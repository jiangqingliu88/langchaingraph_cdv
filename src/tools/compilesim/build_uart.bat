@echo off
REM ============================================================
REM  UART UVM 验证环境 —— 一键生成 + 编译
REM  Usage: build_uart.bat           (gen + compile)
REM         build_uart.bat gen       (gen only)
REM         build_uart.bat compile   (compile only)
REM         build_uart.bat clean     (clean)
REM ============================================================
setlocal enabledelayedexpansion

set "PROJ_ROOT=D:\cdv_a"
set "GENDIR=D:\tmp\uart_gen"
set "QUESTA_HOME=f:\questasim64_2024.1\win64"
set "UVM12_SRC=f:\questasim64_2024.1\verilog_src\uvm-1.2\src"
set "PYTHON=%PROJ_ROOT%\venv\Scripts\python.exe"
set "VLIB=%QUESTA_HOME%\vlib.exe"
set "VLOG=%QUESTA_HOME%\vlog.exe"
set "WORK_DIR=build\uart\work"

cd /d "%PROJ_ROOT%"

if "%1"=="clean" (
    echo Cleaning...
    if exist "%GENDIR%" rmdir /s /q "%GENDIR%"
    if exist build rmdir /s /q build
    echo Done.
    goto :eof
)

if "%1"=="compile" goto :compile

:gen
echo ============================================================
echo  Step 1/2: Generating UVM code...
echo  Output: %GENDIR%
echo ============================================================
if exist "%GENDIR%" rmdir /s /q "%GENDIR%"
%PYTHON% -c "exec(open('src/tools/compilesim/_gen_uart.py').read())"
if %ERRORLEVEL% neq 0 (
    echo GEN FAILED
    goto :eof
)
if "%1"=="gen" goto :eof

:compile
echo ============================================================
echo  Step 2/2: Compiling with UVM-1.2...
echo ============================================================
if not exist "%GENDIR%\filelist.f" (
    echo Filelist not found! Run 'build_uart.bat gen' first.
    goto :eof
)
if not exist "%WORK_DIR%" mkdir "%WORK_DIR%"
%VLIB% "%WORK_DIR%"
%VLOG% -work "%WORK_DIR%" -sv +incdir+"%UVM12_SRC%" -timescale=1ns/1ps "%UVM12_SRC%\uvm_pkg.sv" -f "%GENDIR%\filelist.f"
if %ERRORLEVEL% equ 0 (
    echo ============================================================
    echo  COMPILE OK
    echo ============================================================
) else (
    echo COMPILE FAILED
)
goto :eof
