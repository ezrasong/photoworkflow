#Requires -RunAsAdministrator
# Temporary Windows Firewall rules for the project Python and its underlying
# interpreter. No adapter, global firewall policy, Adobe, or other application changes.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = Join-Path $root '.cache\temp'
$env:TMP = $env:TEMP
$id = 'PhotoWorkflow-OfflineTest-' + [guid]::NewGuid().ToString('N')
$rules = [System.Collections.Generic.List[string]]::new()
$reportPath = Join-Path $root 'outputs\latest-offline-os-verification.json'
$report = [ordered]@{ status='running'; rule_prefix=$id; started_utc=[DateTime]::UtcNow.ToString('o'); rules_removed=$false }
try {
    $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore | Select-Object Name,Enabled)
    if ($profiles | Where-Object { !$_.Enabled }) { throw 'All firewall profiles must already be enabled. No global settings were changed.' }
    $report.profiles = $profiles
    $before = & $python -m tests.verify_offline_os --probe-only
    if ($LASTEXITCODE -ne 0) { throw 'Native online control failed. Cannot attribute a later failure to firewall rules.' }
    $report.online_control = $before | ConvertFrom-Json
    $executables = @($python, $report.online_control.executable) | Select-Object -Unique
    $report.programs = @($executables)
    $index=0
    foreach ($program in $executables) {
        $name="$id-$index"; $index++
        New-NetFirewallRule -Name $name -DisplayName $name -Program $program -Direction Outbound -Action Block -Profile Any -Enabled True | Out-Null
        $rules.Add($name)
        $active=Get-NetFirewallRule -Name $name -PolicyStore ActiveStore
        if ($active.Action -ne 'Block' -or $active.Enabled -ne 'True') { throw 'Block rule was not activated' }
    }
    $report.rules = @($rules)
    $run = Start-Process -FilePath $python -ArgumentList @('-m','tests.verify_offline_os') -WorkingDirectory $root -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'outputs\offline-os-run.log') -RedirectStandardError (Join-Path $root 'outputs\offline-os-errors.log')
    if ($run.ExitCode -ne 0) { throw 'Blocked-network CUDA verification failed; see outputs\offline-os-run.log and offline-os-errors.log' }
    $report.blocked_run = Get-Content (Join-Path $root 'outputs\latest-precision-verification.json') -Raw | ConvertFrom-Json
    $report.status='passed'
} catch {
    $report.status='failed'; $report.error=$_.Exception.Message
} finally {
    $cleanupErrors=@()
    foreach ($name in $rules) {
        try { Remove-NetFirewallRule -Name $name -ErrorAction Stop } catch { $cleanupErrors += $_.Exception.Message }
    }
    $remaining=@(Get-NetFirewallRule -Name "$id*" -ErrorAction SilentlyContinue)
    $report.rules_removed=($remaining.Count -eq 0 -and $cleanupErrors.Count -eq 0)
    $report.cleanup_errors=$cleanupErrors
    if (!$report.rules_removed) { $report.status='failed'; $report.error='Rule cleanup incomplete; remove only rules with the recorded unique prefix.' }
    if ($report.rules_removed -and $report.Contains('online_control')) {
        $after = & $python -m tests.verify_offline_os --probe-only
        if ($LASTEXITCODE -eq 0) { $report.restored_control=$after | ConvertFrom-Json }
        else { $report.status='failed'; $report.error='Native network did not recover after rule removal' }
    }
    $report.finished_utc=[DateTime]::UtcNow.ToString('o')
    $temporary="$reportPath.partial"
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $reportPath -Force
}
if ($report.status -ne 'passed') { Write-Error $report.error; exit 1 }
Write-Output "Passed: $reportPath. Temporary firewall rules removed."
