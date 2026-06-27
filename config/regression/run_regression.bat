@echo off
REM =============================================================================
REM QuestaSim 回归测试 - Windows 启动脚本
REM =============================================================================
REM 用法:
REM   run_regression.bat smoke          REM 冒烟测试 (本地)
REM   run_regression.bat alu            REM ALU 全量回归 (本地)
REM   run_regression.bat apb_uart       REM APB+UART 回归 (本地)
REM   run_regression.bat alu_lsf        REM ALU 回归 (LSF 集群)
REM   run_regression.bat smoke_mock     REM 冒烟测试 (模拟)
REM
REM 前提:
REM   - vlog, vsim, vlib 在 PATH 中
REM   - Python 3.8+
REM =============================================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%..\.."

set FRAMEWORK_DIR=src\tools\regression_tools\regression_framwork
set REGRESSION_PY=%FRAMEWORK_DIR%\regression.py
set CONFIG_DIR=config\regression

if not exist "%REGRESSION_PY%" (
    echo [ERROR] regression.py not found: %REGRESSION_PY%
    exit /b 1
)

set CMD=%1
if "%CMD%"=="" set CMD=help

if "%CMD%"=="smoke" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_smoke.yaml" --action all --mode local --tags smoke
) else if "%CMD%"=="alu" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_alu_full.yaml" --action all --mode local
) else if "%CMD%"=="apb_uart" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_apb_uart.yaml" --action all --mode local
) else if "%CMD%"=="smoke_mock" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_smoke.yaml" --action all --mode mock --dry-run
) else if "%CMD%"=="alu_mock" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_alu_full.yaml" --action all --mode mock --dry-run
) else if "%CMD%"=="apb_uart_mock" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_apb_uart.yaml" --action all --mode mock --dry-run
) else if "%CMD%"=="alu_lsf" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_alu_full.yaml" --action all --mode lsf --lsf-queue normal
) else if "%CMD%"=="apb_uart_lsf" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_apb_uart.yaml" --action all --mode lsf --lsf-queue normal
) else if "%CMD%"=="alu_inc" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_alu_full.yaml" --action all --mode local --incremental
) else if "%CMD%"=="smoke_gen" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_smoke.yaml" --action generate
) else if "%CMD%"=="alu_gen" (
    python "%REGRESSION_PY%" --config "%CONFIG_DIR%\questa_alu_full.yaml" --action generate
) else if "%CMD%"=="rerun" (
    if "%2"=="" (
        echo [ERROR] Usage: run_regression.bat rerun ^<dir^>
        exit /b 1
    )
    python "%REGRESSION_PY%" --rerun-failed "%2"
) else (
    echo.
    echo QuestaSim Regression Runner ^(Windows^)
    echo =====================================
    echo.
    echo Usage: run_regression.bat ^<command^> [args]
    echo.
    echo Commands:
    echo   smoke           Run smoke tests locally
    echo   alu             Run full ALU regression locally
    echo   apb_uart        Run APB+UART regression locally
    echo   smoke_mock      Dry-run smoke test ^(print commands^)
    echo   alu_mock        Dry-run ALU regression
    echo   apb_uart_mock   Dry-run APB+UART regression
    echo   alu_lsf         Submit ALU regression to LSF
    echo   apb_uart_lsf    Submit APB+UART regression to LSF
    echo   alu_inc         Incremental ALU regression
    echo   smoke_gen       Generate scripts only
    echo   alu_gen         Generate scripts only
    echo   rerun ^<dir^>     Rerun failed tests
    echo.
)

endlocal
