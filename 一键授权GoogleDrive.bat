@echo off
cd /d "%~dp0"
python auth_gdrive.py
if errorlevel 1 pause
