@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m photo_workflow.chat %*
