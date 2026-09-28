@echo off
cd /d "%~dp0"
if "%~1"=="" (
    start "Edit Photos with Prompt" "%~dp0.venv\Scripts\pythonw.exe" -m photo_workflow.batch_panel
    exit /b
)
"%~dp0.venv\Scripts\python.exe" -m photo_workflow.native_batch %*
exit /b %errorlevel%
