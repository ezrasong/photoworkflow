param([string]$Python = 'C:\Users\ezras\AppData\Local\Programs\Python\Python312\python.exe')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force .cache,models,inputs,outputs,references | Out-Null
$env:UV_CACHE_DIR = "$PWD\.cache\uv"
$env:TEMP = "$PWD\.cache"
$env:TMP = $env:TEMP
$env:PYTHONDONTWRITEBYTECODE = '1'
if (!(Test-Path .venv/Scripts/python.exe)) {
    uv venv --python $Python .venv
    if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed' }
}
uv pip sync --python .venv/Scripts/python.exe requirements.lock --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .venv/Scripts/python.exe scripts/download_models.py
if ($LASTEXITCODE -ne 0) { throw 'Model download or integrity check failed' }
& .venv/Scripts/python.exe scripts/setup_assistant.py
if ($LASTEXITCODE -ne 0) { throw 'Local assistant installation or integrity check failed' }
& "$PSScriptRoot\setup_obsidian.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Obsidian setup failed' }
Write-Host 'Ready. Double-click Launch Photo Studio.cmd, or run .\run.ps1 single <image>.'
