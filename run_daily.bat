@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

:: ============================================================================
:: DON OF VICE CITY - Daily Autopilot Launcher (Windows Batch)
:: Runs master_autopilot.py with proper environment, logging, and health checks
:: ============================================================================

:: Configuration
set PROJECT_DIR=%~dp0
if "%PROJECT_DIR:~-1%"=="\" set PROJECT_DIR=%PROJECT_DIR:~0,-1%
set PYTHON_EXE=C:\Users\Awesh\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PYTHON_EXE%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Install Python 3.12+ or update PYTHON_EXE.
        exit /b 1
    )
    set PYTHON_EXE=python
)
set SCRIPT=master_autopilot.py
:: Python writes autopilot.log itself through its rotating logger.  Capture
:: stdout/stderr separately to avoid two processes writing the same file.
set CONSOLE_LOG=%PROJECT_DIR%\autopilot_console.log
set ERROR_LOG=%PROJECT_DIR%\autopilot_errors.log
set HEALTH_CHECK_FILE=%PROJECT_DIR%\last_run_health.txt
set PYTHONPATH=%PROJECT_DIR%

:: Channel to run (empty = default from config.yaml)
set CHANNEL=

:: ============================================================================
:: Pre-flight checks
:: ============================================================================
cd /d "%PROJECT_DIR%"

:: Check Python is runnable
"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not runnable: %PYTHON_EXE%
    echo [ERROR] Update PYTHON_EXE in this script or install Python 3.12+
    exit /b 1
)

:: Check script exists
if not exist "%SCRIPT%" (
    echo [ERROR] %SCRIPT% not found in %PROJECT_DIR%
    exit /b 1
)

:: Check client_secret.json exists
if not exist "client_secret.json" (
    echo [WARN] client_secret.json not found - run setup_auth.py first
)

:: Check token.pickle exists (or will be created after first auth)
if not exist "token.pickle" (
    echo [INFO] token.pickle not found - first run will need authentication
)

:: ============================================================================
:: Health check - prevent duplicate runs within short interval
:: ============================================================================
set CURRENT_TIME=%DATE% %TIME%
if exist "%HEALTH_CHECK_FILE%" (
    for /f "usebackq tokens=*" %%a in ("%HEALTH_CHECK_FILE%") do set LAST_RUN=%%a
    echo [INFO] Last run: %LAST_RUN%

    :: Could add time comparison here if needed
) else (
    echo [INFO] First run or health file missing
)

:: Write current run timestamp
echo %CURRENT_TIME% > "%HEALTH_CHECK_FILE%"

:: ============================================================================
:: Run the autopilot
:: ============================================================================
echo [INFO] Starting DON OF VICE CITY Autopilot at %CURRENT_TIME%
echo [INFO] Project: %PROJECT_DIR%
echo [INFO] Python: %PYTHON_EXE%
echo [INFO] Python log: %PROJECT_DIR%\autopilot.log
echo [INFO] Console log: %CONSOLE_LOG%

:: Build command
set CMD="%PYTHON_EXE%" "%PROJECT_DIR%\%SCRIPT%"
if not "%CHANNEL%"=="" set CMD=%CMD% --channel "%CHANNEL%"

:: Capture stdout/stderr separately; Python owns autopilot.log.
%CMD% >> "%CONSOLE_LOG%" 2>&1

:: Capture exit code
set EXIT_CODE=%ERRORLEVEL%

:: ============================================================================
:: Post-run handling
:: ============================================================================
set END_TIME=%DATE% %TIME%

if %EXIT_CODE% equ 0 (
    echo [SUCCESS] Autopilot completed successfully at %END_TIME%
    echo SUCCESS %END_TIME% >> "%HEALTH_CHECK_FILE%"
) else (
    echo [ERROR] Autopilot failed with exit code %EXIT_CODE% at %END_TIME%
    echo ERROR %EXIT_CODE% %END_TIME% >> "%HEALTH_CHECK_FILE%"

    :: Log error to separate error log for easy debugging
    echo. >> "%ERROR_LOG%"
    echo ========================================= >> "%ERROR_LOG%"
    echo FAILED RUN: %END_TIME% (Exit: %EXIT_CODE%) >> "%ERROR_LOG%"
    echo ========================================= >> "%ERROR_LOG%"
    tail -n 50 "%CONSOLE_LOG%" >> "%ERROR_LOG%" 2>nul || (
        :: Fallback if tail not available
        powershell -Command "Get-Content '%CONSOLE_LOG%' -Tail 50" >> "%ERROR_LOG%" 2>nul
    )
)

echo [INFO] Run completed. Check %PROJECT_DIR%\autopilot.log for details.
exit /b %EXIT_CODE%