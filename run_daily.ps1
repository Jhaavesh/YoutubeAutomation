<#
.SYNOPSIS
    DON OF VICE CITY — Daily Autopilot Launcher (PowerShell)
    Modern, robust alternative to batch file with better error handling,
    structured logging, and health monitoring.

.DESCRIPTION
    Runs master_autopilot.py with comprehensive pre-flight checks,
    quota monitoring, structured logging, and Windows Event Log integration.

.EXAMPLE
    .\run_daily.ps1
    .\run_daily.ps1 -Channel "donofvicecity2026"
    .\run_daily.ps1 -AllChannels
#>

param(
    [string]$Channel = "",
    [switch]$AllChannels,
    [switch]$QuotaOnly,
    [switch]$VerifyOnly,
    [switch]$LongOnly,
    [switch]$ShortsOnly
)

# ============================================================================
# CONFIGURATION
# ============================================================================
$ProjectDir = "C:\Ajfiles\Youtube"
$PythonExe = "C:\Users\Awesh\AppData\Local\Programs\Python\Python312\python.exe"
$Script = "master_autopilot.py"
$LogFile = Join-Path $ProjectDir "autopilot.log"
$ErrorLogFile = Join-Path $ProjectDir "autopilot_errors.log"
$HealthFile = Join-Path $ProjectDir "last_run_health.json"
$BootLogFile = Join-Path $ProjectDir "autopilot_boot.log"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
function Write-Log {
    param(
        [string]$Message,
        [string]$Level = "INFO",
        [switch]$BootLog = $false
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $entry = "[$timestamp] [$Level] $Message"

    # Console output
    switch ($Level) {
        "ERROR" { Write-Host $entry -ForegroundColor Red }
        "WARN"  { Write-Host $entry -ForegroundColor Yellow }
        "SUCCESS" { Write-Host $entry -ForegroundColor Green }
        default { Write-Host $entry }
    }

    # File output
    $targetFile = if ($BootLog) { $BootLogFile } else { $LogFile }
    $entry | Out-File -FilePath $targetFile -Encoding utf8 -Append
}

function Write-EventLog {
    param([string]$Message, [string]$Level = "Information")
    try {
        if (-not [System.Diagnostics.EventLog]::SourceExists("DonOfViceCity")) {
            [System.Diagnostics.EventLog]::CreateEventSource("DonOfViceCity", "Application")
        }
        Write-EventLog -Source "DonOfViceCity" -EventId 1000 -EntryType $Level -Message $Message
    } catch {
        # Silently fail if no admin rights
    }
}

function Test-Prerequisites {
    Write-Log "Checking prerequisites..."

    # Python
    if (-not (Test-Path $PythonExe)) {
        Write-Log "Python not found at $PythonExe" "ERROR"
        return $false
    }
    Write-Log "Python: $PythonExe" "DEBUG"

    # Script
    $scriptPath = Join-Path $ProjectDir $Script
    if (-not (Test-Path $scriptPath)) {
        Write-Log "Script not found: $scriptPath" "ERROR"
        return $false
    }

    # Client secret
    $secretPath = Join-Path $ProjectDir "client_secret.json"
    if (-not (Test-Path $secretPath)) {
        Write-Log "client_secret.json not found - run setup_auth.py first" "WARN"
    }

    # Token
    $tokenPath = Join-Path $ProjectDir "token.pickle"
    if (-not (Test-Path $tokenPath)) {
        Write-Log "token.pickle not found - first run needs authentication" "WARN"
    }

    Write-Log "Prerequisites OK" "SUCCESS"
    return $true
}

function Get-LastRunHealth {
    if (Test-Path $HealthFile) {
        $content = Get-Content $HealthFile -Raw
        return $content | ConvertFrom-Json
    }
    return @{}
}

function Save-Health {
    param([Hashtable]$Health)
    $Health | ConvertTo-Json -Depth 5 | Set-Content $HealthFile -Encoding utf8
}

function Invoke-Autopilot {
    param([string]$ChannelArg = "")

    $scriptPath = Join-Path $ProjectDir $Script
    $args = @()

    if ($QuotaOnly) { $args += "--quota" }
    if ($VerifyOnly) { $args += "--verify" }
    if ($LongOnly) { $args += "--long-only" }
    if ($ShortsOnly) { $args += "--shorts-only" }
    if ($AllChannels) { $args += "--all-channels" }
    if ($ChannelArg) { $args += "--channel", $ChannelArg }

    $cmd = & $PythonExe $scriptPath @args

    # Capture output line by line for logging
    $output = @()
    $process = Start-Process -FilePath $PythonExe -ArgumentList ($scriptPath + " " + ($args -join " ")) -WorkingDirectory $ProjectDir -RedirectStandardOutput (Join-Path $ProjectDir "temp_stdout.txt") -RedirectStandardError (Join-Path $ProjectDir "temp_stderr.txt") -Wait -PassThru -NoNewWindow

    # Read output files
    if (Test-Path (Join-Path $ProjectDir "temp_stdout.txt")) {
        $stdout = Get-Content (Join-Path $ProjectDir "temp_stdout.txt") -Raw
        Remove-Item (Join-Path $ProjectDir "temp_stdout.txt") -Force
    }
    if (Test-Path (Join-Path $ProjectDir "temp_stderr.txt")) {
        $stderr = Get-Content (Join-Path $ProjectDir "temp_stderr.txt") -Raw
        Remove-Item (Join-Path $ProjectDir "temp_stderr.txt") -Force
    }

    # Log output
    if ($stdout) { $stdout -split "`n" | ForEach-Object { Write-Log $_ } }
    if ($stderr) { $stderr -split "`n" | ForEach-Object { Write-Log $_ "ERROR" } }

    return $process.ExitCode
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================
try {
    $startTime = Get-Date
    Write-Log "=" * 60
    Write-Log "DON OF VICE CITY — DAILY AUTOPILOT STARTED"
    Write-Log "=" * 60

    # Pre-flight
    if (-not (Test-Prerequisites)) {
        exit 1
    }

    # Health check
    $lastRun = Get-LastRunHealth
    if ($lastRun) {
        Write-Log "Last run: $($lastRun.timestamp) - $($lastRun.status)"
    }

    # Run autopilot
    $channelToRun = if ($Channel) { $Channel } else { "" }
    $exitCode = Invoke-Autopilot -ChannelArg $channelToRun

    $endTime = Get-Date
    $duration = [math]::Round(($endTime - $startTime).TotalSeconds)

    # Health record
    $health = @{
        timestamp = $endTime.ToString("yyyy-MM-dd HH:mm:ss")
        status = if ($exitCode -eq 0) { "SUCCESS" } else { "FAILED" }
        exitCode = $exitCode
        durationSeconds = $duration
        channel = if ($Channel) { $Channel } else { "default" }
    }
    Save-Health $health

    # Final logging
    if ($exitCode -eq 0) {
        Write-Log "Autopilot completed successfully in ${duration}s" "SUCCESS"
        Write-EventLog "Daily autopilot completed successfully in ${duration}s" "Information"
    } else {
        Write-Log "Autopilot FAILED with exit code $exitCode after ${duration}s" "ERROR"
        Write-EventLog "Daily autopilot FAILED with exit code $exitCode" "Error"
    }

    Write-Log "=" * 60
    Write-Log "DON OF VICE CITY — DAILY AUTOPILOT FINISHED"
    Write-Log "=" * 60

    exit $exitCode

} catch {
    $errorMsg = $_.Exception.Message
    Write-Log "FATAL ERROR: $errorMsg" "ERROR"
    Write-EventLog "Autopilot fatal error: $errorMsg" "Error"
    exit 1
}