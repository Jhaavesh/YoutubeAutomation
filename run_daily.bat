@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "c:\Ajfiles\Youtube"
"C:\Users\Awesh\AppData\Local\Programs\Python\Python312\python.exe" "c:\Ajfiles\Youtube\auto_pilot_bot.py" >> "c:\Ajfiles\Youtube\autopilot.log" 2>&1
