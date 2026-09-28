#Requires -RunAsAdministrator
# Run only with explicit approval: temporary program-specific outbound rules.
# All non-loopback IPv4/IPv6 destinations are blocked for Python, pythonw and
# llama-server. No global policy, adapter, Adobe or Obsidian changes.
# Suite chat additionally covers the workspace Oh My Pi executable.
param([ValidateSet('expanded','chat')][string]$Suite='expanded')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:TEMP=Join-Path $root '.cache\temp'
$env:TMP=$env:TEMP
$id='PhotoWorkflow-'+$Suite+'Test-'+[guid]::NewGuid().ToString('N')
$module="tests.verify_${Suite}_offline"
$rules=[System.Collections.Generic.List[string]]::new()
$reportPath=Join-Path $root "outputs\latest-$Suite-offline-os-verification.json"
$report=[ordered]@{status='running';rule_prefix=$id;started_utc=[DateTime]::UtcNow.ToString('o');rules_removed=$false}
function Save-Report {
    $report | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath "$reportPath.partial" -Encoding UTF8
    Move-Item -LiteralPath "$reportPath.partial" -Destination $reportPath -Force
}
function Control([string]$Name) {
    $path=Join-Path $root "outputs\$Suite-control-$Name.json"
    & $python -m $module --control $path
    if ($LASTEXITCODE -ne 0) {throw 'Native control process failed'}
    $result=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    $pwpath=Join-Path $root "outputs\$Suite-pythonw-$Name.json"
    $pw=Start-Process -FilePath (Join-Path $root '.venv\Scripts\pythonw.exe') -ArgumentList @('-m',$module,'--python-only',('"{0}"' -f $pwpath)) -WorkingDirectory $root -WindowStyle Hidden -Wait -PassThru
    if ($pw.ExitCode -ne 0) {throw 'Windowed Python native control failed'}
    $result | Add-Member -NotePropertyName pythonw -NotePropertyValue (Get-Content -LiteralPath $pwpath -Raw | ConvertFrom-Json)
    return $result
}
try {
    $report.profiles=@(Get-NetFirewallProfile -PolicyStore ActiveStore | Select-Object Name,Enabled)
    if ($report.profiles | Where-Object {!$_.Enabled}) {throw 'All firewall profiles must already be enabled'}
    $report.online_control=Control 'before'
    if (!$report.online_control.python.connected -or !$report.online_control.llama.connected -or !$report.online_control.pythonw.connected -or ($Suite -eq 'chat' -and !$report.online_control.omp.connected)) {
        throw 'Online controls must succeed for both Python WinHTTP and llama native HTTP'
    }
    $base=$report.online_control.python.executable
    $baseWindowed=$report.online_control.pythonw.executable
    $programs=@($python,(Join-Path $root '.venv\Scripts\pythonw.exe'),$base,$baseWindowed,
                (Join-Path $root 'apps\llama\llama-server.exe')) | Select-Object -Unique
    if ($Suite -eq 'chat') { $programs += (Join-Path $root 'apps\oh-my-pi\omp-windows-x64.exe') }
    $report.programs=@($programs)
    $remote=@('0.0.0.0-126.255.255.255','128.0.0.0-255.255.255.255','::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')
    $report.blocked_remote_addresses=$remote
    $report.allowed_by_exclusion=@('127.0.0.0/8','::1')
    $report.cleanup_command="Get-NetFirewallRule -Name '$id*' | Remove-NetFirewallRule"
    Save-Report
    $index=0
    foreach ($program in $programs) {
        if (!(Test-Path -LiteralPath $program)) {throw "Missing executable: $program"}
        $name="$id-$index";$index++
        # Register cleanup intent before creating each rule.
        $rules.Add($name);$report.rules=@($rules);Save-Report
        New-NetFirewallRule -Name $name -DisplayName $name -Program $program -Direction Outbound -Action Block -Profile Any -Enabled True -RemoteAddress $remote | Out-Null
        $active=Get-NetFirewallRule -Name $name -PolicyStore ActiveStore
        if ($active.Action -ne 'Block' -or $active.Enabled -ne 'True') {throw 'Rule did not activate'}
    }
    $report.active_rules=@(foreach ($name in $rules) {
        $rule=Get-NetFirewallRule -Name $name -PolicyStore ActiveStore
        [ordered]@{name=$name;action=[string]$rule.Action;enabled=[string]$rule.Enabled;
            program=($rule | Get-NetFirewallApplicationFilter).Program;
            remote_addresses=@(($rule | Get-NetFirewallAddressFilter).RemoteAddress)}
    })
    Save-Report
    $report.blocked_controls=Control 'blocked'
    if ($report.blocked_controls.python.connected -or $report.blocked_controls.llama.connected -or $report.blocked_controls.pythonw.connected -or ($Suite -eq 'chat' -and $report.blocked_controls.omp.connected)) {
        throw 'A native external request succeeded while rules were active'
    }
    $run=Start-Process -FilePath $python -ArgumentList @('-m',$module) -WorkingDirectory $root -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root "outputs\$Suite-offline-run.log") -RedirectStandardError (Join-Path $root "outputs\$Suite-offline-errors.log")
    if ($run.ExitCode -ne 0) {throw 'Blocked expanded runtime verification failed; inspect expanded-offline logs'}
    $report.blocked_run=Get-Content (Join-Path $root "outputs\$Suite-offline-blocked.json") -Raw | ConvertFrom-Json
    $report.status='passed'
} catch {
    $report.status='failed';$report.error=$_.Exception.Message
} finally {
    $cleanup=@()
    foreach ($name in $rules) {
        try {Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction Stop}
        catch {$cleanup+=$_.Exception.Message}
    }
    $remaining=@(Get-NetFirewallRule -Name "$id*" -ErrorAction SilentlyContinue)
    $report.rules_removed=($remaining.Count -eq 0 -and $cleanup.Count -eq 0)
    $report.cleanup_errors=$cleanup
    if (!$report.rules_removed) {$report.status='failed';$report.error='Cleanup failed; use the exact recorded cleanup command'}
    if ($report.rules_removed -and $report.Contains('online_control')) {
        try {
            $report.restored_control=Control 'after'
            if (!$report.restored_control.python.connected -or !$report.restored_control.llama.connected -or !$report.restored_control.pythonw.connected -or ($Suite -eq 'chat' -and !$report.restored_control.omp.connected)) {throw 'Connectivity did not recover'}
        } catch {$report.status='failed';$report.error=$_.Exception.Message}
    }
    $report.finished_utc=[DateTime]::UtcNow.ToString('o');Save-Report
}
if ($report.status -ne 'passed') {Write-Error $report.error;exit 1}
Write-Output "Passed: $reportPath. All temporary rules removed."
