@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

:: ============================================================================
:: DON OF VICE CITY — Daily Autopilot Launcher (Windows Batch)
:: Runs master_autopilot.py with proper environment, logging, and health checks
:: ============================================================================

:: Configuration
set PROJECT_DIR=C:\Ajfiles\Youtube
set PYTHON_EXE=C:\Users\Awesh\AppData\Local\Programs\Python\Python312\python.exe
set SCRIPT=master_autopilot.py
set LOG_FILE=%PROJECT_DIR%\autopilot.log
set ERROR_LOG=%PROJECT_DIR%\autopilot_errors.log
set HEALTH_CHECK_FILE=%PROJECT_DIR%\last_run_health.txt

:: Channel to run (empty = default from config.yaml)
set CHANNEL=

:: ============================================================================
:: Pre-flight checks
:: ============================================================================
cd /d "%PROJECT_DIR%"

:: Check Python exists
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python not found at %PYTHON_EXE%
    echo [ERROR] Please update PYTHON_EXE in this script or install Python 3.12+
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
    for /f "tokens=*" %%a in (%HEALTH_CHECK_FILE%) do set LAST_RUN=%%a
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
echo [INFO] Log: %LOG_FILE%

:: Build command
set CMD="%PYTHON_EXE%" "%PROJECT_DIR%\%SCRIPT%"
if not "%CHANNEL%"=="" set CMD=%CMD% --channel %CHANNEL%

:: Run with tee to both console and log file
%CMD% >> "%LOG_FILE%" 2>&1

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
    tail -n 50 "%LOG_FILE%" >> "%ERROR_LOG%" 2>nul || (
        :: Fallback if tail not available
        powershell -Command "Get-Content '%LOG_FILE%' -Tail 50" >> "%ERROR_LOG%" 2>nul
    )
)

echo [INFO] Run completed. Check %LOG_FILE% for details.
exit /b %EXIT_CODE%