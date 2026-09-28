@echo off
cd /d "%~dp0"
start "Photo Studio" "%~dp0.venv\Scripts\pythonw.exe" -m photo_workflow.harness
