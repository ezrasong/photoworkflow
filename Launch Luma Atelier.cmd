@echo off
cd /d "%~dp0"
start "Luma Atelier" "%~dp0.venv\Scripts\pythonw.exe" -m photo_workflow.harness
