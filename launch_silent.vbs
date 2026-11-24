' ============================================================================
' DON OF VICE CITY — Silent Boot Launcher (VBScript)
' Runs run_daily.bat completely hidden (no console window)
' Place shortcut in Windows Startup folder: shell:startup
' ============================================================================

Option Explicit

Dim WshShell, fso, scriptPath, batchFile, logFile, strCommand
Dim exitCode, startTime, endTime, duration

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' ============================================================================
' CONFIGURATION - UPDATE THESE PATHS IF NEEDED
' ============================================================================
scriptPath = "C:\Ajfiles\Youtube"
batchFile = scriptPath & "\run_daily.bat"
logFile = scriptPath & "\autopilot_boot.log"

' ============================================================================
' PRE-FLIGHT CHECKS
' ============================================================================
If Not fso.FolderExists(scriptPath) Then
    Call LogError("Project folder not found: " & scriptPath)
    WScript.Quit 1
End If

If Not fso.FileExists(batchFile) Then
    Call LogError("Batch file not found: " & batchFile)
    WScript.Quit 1
End If

' ============================================================================
' RUN BATCH FILE SILENTLY
' ============================================================================
startTime = Now()

' Run completely hidden (0 = hidden window, True = wait for completion)
' Using cmd /c to run batch and exit
strCommand = "cmd /c """ & batchFile & """"

On Error Resume Next
exitCode = WshShell.Run(strCommand, 0, True)
On Error GoTo 0

endTime = Now()
duration = DateDiff("s", startTime, endTime)

' ============================================================================
' LOG RESULT
' ============================================================================
Dim resultMsg
If exitCode = 0 Then
    resultMsg = "SUCCESS"
Else
    resultMsg = "FAILED (Exit Code: " & exitCode & ")"
End If

Call LogResult(resultMsg, duration, exitCode)

' ============================================================================
' HELPER FUNCTIONS
' ============================================================================
Sub LogResult(status, durationSec, code)
    Dim ts, logEntry
    ts = FormatDateTime(Now, vbShortDate) & " " & FormatDateTime(Now, vbLongTime)
    logEntry = "[" & ts & "] BOOT RUN: " & status & " | Duration: " & durationSec & "s | Code: " & code

    ' Write to boot log
    Dim logStream
    Set logStream = fso.OpenTextFile(logFile, 8, True, -2) ' 8=append, True=create, -2=Unicode
    logStream.WriteLine logEntry
    logStream.Close

    ' Also write to Windows Event Log (optional, requires admin)
    ' WshShell.LogEvent 4, "DonOfViceCity Autopilot: " & logEntry
End Sub

Sub LogError(msg)
    Dim ts, logEntry
    ts = FormatDateTime(Now, vbShortDate) & " " & FormatDateTime(Now, vbLongTime)
    logEntry = "[" & ts & "] BOOT ERROR: " & msg

    Dim logStream
    Set logStream = fso.OpenTextFile(logFile, 8, True, -2)
    logStream.WriteLine logEntry
    logStream.Close
End Sub

' ============================================================================
' CLEANUP
' ============================================================================
Set WshShell = Nothing
Set fso = Nothing