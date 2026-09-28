$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$app = Join-Path $root 'apps\Obsidian\Obsidian.exe'
if (!(Test-Path -LiteralPath $app)) { throw 'Run scripts\setup_obsidian.ps1 first.' }
& "$root\.venv\Scripts\python.exe" "$root\scripts\setup_vault.py"
if ($LASTEXITCODE -ne 0) { throw 'Vault setup failed' }
$profile = Join-Path $root 'apps\ObsidianData'
$env:TEMP = Join-Path $root '.cache\temp'
$env:TMP = $env:TEMP
# The user explicitly opens an interactive local editor.
Start-Process -FilePath $app -ArgumentList @("--user-data-dir=`"$profile`"", '--disable-background-networking')
