@echo off
cd /d "%~dp0"
start "Photo Workflow" "%~dp0.venv\Scripts\pythonw.exe" -m photo_workflow.harness
