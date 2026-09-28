$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:TEMP=Join-Path $root '.cache\temp'; $env:TMP=$env:TEMP
$downloads=Get-Content docs/desktop-downloads.json -Raw | ConvertFrom-Json
foreach ($entry in $downloads.PSObject.Properties) {
    $file=Join-Path $root ('.cache\'+$entry.Name)
    if (!(Test-Path -LiteralPath $file)) { Invoke-WebRequest -UseBasicParsing -Uri $entry.Value.url -OutFile $file }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLower() -ne $entry.Value.sha256) { throw "Download hash mismatch: $($entry.Name)" }
}
$signature=Get-AuthenticodeSignature .cache/Obsidian-1.13.7.exe
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*O=Dynalist Inc*') { throw 'Obsidian installer signature is not the expected valid publisher' }
if (!(Test-Path .cache/7zip/7z.exe)) {
    & .cache/7zr.exe x .cache/7z2603-x64.exe '-o.cache\7zip' -y
    if ($LASTEXITCODE -ne 0) { throw '7-Zip extraction failed' }
}
if (!(Test-Path apps/Obsidian/Obsidian.exe)) {
    & .cache/7zip/7z.exe x .cache/Obsidian-1.13.7.exe '-o.cache\obsidian-installer' '-i!$PLUGINSDIR\app-64.7z' -y
    if ($LASTEXITCODE -ne 0) { throw 'Obsidian payload extraction failed' }
    & .cache/7zip/7z.exe x '.cache\obsidian-installer\$PLUGINSDIR\app-64.7z' '-oapps\Obsidian' -y
    if ($LASTEXITCODE -ne 0) { throw 'Obsidian extraction failed' }
}
& .venv/Scripts/python.exe scripts/setup_vault.py
if ($LASTEXITCODE -ne 0) { throw 'Vault setup failed' }
Write-Host 'Obsidian and the dedicated vault are ready. Use Open Obsidian.ps1 or the control panel.'
