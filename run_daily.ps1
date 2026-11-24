<#
.SYNOPSIS
    DON OF VICE CITY - Daily Autopilot Launcher (PowerShell)
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
$ProjectDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$PythonExe = "C:\Users\Awesh\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $PythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $PythonExe = $pythonCommand.Source }
}
$Script = "master_autopilot.py"
# Python writes its own rotating autopilot.log.  Keep launcher messages
# separate so two processes never write different formats to one file.
$LogFile = Join-Path $ProjectDir "autopilot_launcher.log"
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

function Write-AutopilotEventLog {
    param([string]$Message, [string]$Level = "Information")
    try {
        if (-not [System.Diagnostics.EventLog]::SourceExists("DonOfViceCity")) {
            [System.Diagnostics.EventLog]::CreateEventSource("DonOfViceCity", "Application")
        }
        Write-EventLog -LogName "Application" -Source "DonOfViceCity" -EventId 1000 -EntryType $Level -Message $Message
    } catch {
        # Silently fail if no admin rights
    }
}

function Test-Prerequisites {
    Write-Log "Checking prerequisites..."

    # Python: $PythonExe may be a bare command when the preferred path is absent.
    $pythonCommand = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        Write-Log "Python not found: $PythonExe" "ERROR"
        return $false
    }
    Write-Log "Python: $($pythonCommand.Source)" "DEBUG"

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
        try {
            $content = Get-Content $HealthFile -Raw
            if ($content) { return $content | ConvertFrom-Json }
        } catch {
            Write-Log "Could not parse health file: $($_.Exception.Message)" "WARN"
        }
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
    $pyArgs = @()

    if ($QuotaOnly) { $pyArgs += "--quota" }
    if ($VerifyOnly) { $pyArgs += "--verify" }
    if ($LongOnly) { $pyArgs += "--long-only" }
    if ($ShortsOnly) { $pyArgs += "--shorts-only" }
    if ($AllChannels) { $pyArgs += "--all-channels" }
    if ($ChannelArg) { $pyArgs += "--channel", $ChannelArg }

    # Start-Process receives one argument string. Quote every value so paths
    # and channel names with spaces survive intact.
    $quotedArgs = @("`"$scriptPath`"")
    foreach ($arg in $pyArgs) { $quotedArgs += "`"$arg`"" }

    $stdoutFile = Join-Path $env:TEMP "autopilot_stdout_$PID.txt"
    $stderrFile = Join-Path $env:TEMP "autopilot_stderr_$PID.txt"
    $process = Start-Process -FilePath $PythonExe -ArgumentList ($quotedArgs -join " ") -WorkingDirectory $ProjectDir -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile -Wait -PassThru -NoNewWindow

    # Read output files
    if (Test-Path $stdoutFile) {
        $stdout = Get-Content $stdoutFile -Raw
        Remove-Item $stdoutFile -Force
    }
    if (Test-Path $stderrFile) {
        $stderr = Get-Content $stderrFile -Raw
        Remove-Item $stderrFile -Force
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
    Write-Log ("=" * 60)
    Write-Log "DON OF VICE CITY - DAILY AUTOPILOT STARTED"
    Write-Log ("=" * 60)

    # Pre-flight
    if (-not (Test-Prerequisites)) {
        exit 1
    }

    # Health check
    $lastRun = Get-LastRunHealth
    if ($lastRun) {
        $lastRunTime = if ($lastRun.timestamp) { $lastRun.timestamp } else { $lastRun.last_run }
        Write-Log "Last run: $lastRunTime - $($lastRun.status)"
    }

    # Run autopilot
    $channelToRun = if ($Channel) { $Channel } else { "" }
    $exitCode = Invoke-Autopilot -ChannelArg $channelToRun
    if ($null -eq $exitCode) { $exitCode = 1 }

    $endTime = Get-Date
    $duration = [math]::Round(($endTime - $startTime).TotalSeconds)

    # Diagnostic-only runs must not overwrite the last full-run health record.
    $diagnosticOnly = $QuotaOnly -or $VerifyOnly
    if (-not $diagnosticOnly) {
        $health = @{
            timestamp = $endTime.ToString("yyyy-MM-dd HH:mm:ss")
            status = if ($exitCode -eq 0) { "SUCCESS" } else { "FAILED" }
            exitCode = $exitCode
            durationSeconds = $duration
            channel = if ($Channel) { $Channel } else { "default" }
            mode = if ($LongOnly) { "long-only" } elseif ($ShortsOnly) { "shorts-only" } elseif ($AllChannels) { "all-channels" } else { "full" }
        }
        Save-Health $health
    }

    # Final logging
    if ($exitCode -eq 0) {
        Write-Log "Autopilot completed successfully in ${duration}s" "SUCCESS"
        Write-AutopilotEventLog "Daily autopilot completed successfully in ${duration}s" "Information"
    } else {
        Write-Log "Autopilot FAILED with exit code $exitCode after ${duration}s" "ERROR"
        Write-AutopilotEventLog "Daily autopilot FAILED with exit code $exitCode" "Error"
    }

    Write-Log ("=" * 60)
    Write-Log "DON OF VICE CITY - DAILY AUTOPILOT FINISHED"
    Write-Log ("=" * 60)

    exit $exitCode

} catch {
    $errorMsg = $_.Exception.Message
    Write-Log "FATAL ERROR: $errorMsg" "ERROR"
    Write-AutopilotEventLog "Autopilot fatal error: $errorMsg" "Error"
    exit 1
}