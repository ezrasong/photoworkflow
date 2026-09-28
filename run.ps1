$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location $PSScriptRoot
try {
    & "$PSScriptRoot\.venv\Scripts\python.exe" -m photo_workflow @args
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
