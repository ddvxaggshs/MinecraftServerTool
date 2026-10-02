param([Parameter(Mandatory=$true)][string]$PlanPath,
      [Parameter(Mandatory=$true)][int]$ParentProcessId)
$ErrorActionPreference = 'Stop'
$updateFolder = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($PlanPath))
$reportPath = Join-Path $updateFolder 'last-install.json'
$heldMutex = $false
$mutex = $null
$replacements = @()
$copyStarted = $false

function Inside-Path([string]$basePath, [string]$relative) {
    $full = [IO.Path]::GetFullPath((Join-Path $basePath $relative))
    if (-not $full.StartsWith($basePath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Update path escapes its directory: $relative"
    }
    $check = $full
    while ($check -and $check.Length -ge $basePath.Length) {
        if (Test-Path -LiteralPath $check) {
            $item = Get-Item -LiteralPath $check -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point in update path: $check" }
        }
        $check = [IO.Path]::GetDirectoryName($check)
    }
    return $full
}

try {
    # Capture the process object before waiting, rather than repeatedly looking up a PID.
    try { $parentProcess = [Diagnostics.Process]::GetProcessById($ParentProcessId) }
    catch [ArgumentException] { $parentProcess = $null }
    if ($parentProcess -and -not $parentProcess.WaitForExit(300000)) { throw 'Application did not exit; update deferred.' }
    $plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
    if ($plan.schema -ne 1 -or $plan.kind -notin @('source','windows')) { throw 'Invalid update plan.' }
    $appRoot = [IO.Path]::GetFullPath($plan.app_dir).TrimEnd('\')
    $expectedFolder = Join-Path $appRoot 'data\updates'
    if ($updateFolder -ne $expectedFolder) { throw 'Update plan is outside application data.' }
    $stage = Inside-Path $updateFolder ([IO.Path]::GetFileName($plan.stage))
    if ($stage -ne [IO.Path]::GetFullPath($plan.stage)) { throw 'Invalid staging directory.' }
    $hashAlgorithm = [Security.Cryptography.SHA256]::Create()
    $mutexHash = [BitConverter]::ToString($hashAlgorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($appRoot.ToLowerInvariant()))).Replace('-','').ToLowerInvariant()
    $mutex = New-Object Threading.Mutex($false, ('Local\MinecraftRelay-' + $mutexHash))
    try { $heldMutex = $mutex.WaitOne(30000) } catch [Threading.AbandonedMutexException] { $heldMutex = $true }
    if (-not $heldMutex) { throw 'Another application instance is using these files; update deferred.' }
    $backup = Inside-Path $updateFolder ('rollback-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $backup | Out-Null
    $seen = @{}
    foreach ($entry in $plan.files) {
        $name = [string]$entry.path
        if ($name -match '[\\:]|^/|(^|/)\.\.?(/|$)|(^|/)([^/]*[ .])(/|$)' -or $seen.ContainsKey($name.ToLowerInvariant())) { throw "Invalid update path: $name" }
        $seen[$name.ToLowerInvariant()] = $true
        $allowed = if ($plan.kind -eq 'windows') {
            $name -in @('MinecraftRelay.exe','apply-update.ps1','release-state.json','README.md','README.txt') -or $name.StartsWith('_internal/')
        } else {
            $name -in @('MinecraftRelay.py','Run-Source.vbs','Run-Source.bat','Build-Windows.bat','README.md','README.txt','apply-update.ps1','release-state.json') -or $name -match '^(relay|tools)/.+\.py$'
        }
        if (-not $allowed) { throw "Non-program file in update: $name" }
        $source = Inside-Path $stage $name
        $target = Inside-Path $appRoot $name
        $saved = Inside-Path $backup $name
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw "Staged file checksum mismatch: $name" }
        $existed = Test-Path -LiteralPath $target -PathType Leaf
        if ($existed) {
            New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($saved)) -Force | Out-Null
            Copy-Item -LiteralPath $target -Destination $saved
        }
        $replacements += [pscustomobject]@{ source=$source; target=$target; saved=$saved; existed=$existed }
    }
    if (-not $seen.ContainsKey('release-state.json')) { throw 'Missing release state.' }
    $stamp = Get-Content -LiteralPath (Join-Path $stage 'release-state.json') -Raw | ConvertFrom-Json
    if ($stamp.state -ne $plan.state) { throw 'Release state mismatch.' }
    # A backup of every replaced file exists before the first write.
    $replacements | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backup 'journal.json') -Encoding UTF8
    $copyStarted = $true
    foreach ($entry in $replacements | Sort-Object { [IO.Path]::GetFileName($_.target) -eq 'release-state.json' }) {
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($entry.target)) -Force | Out-Null
        Copy-Item -LiteralPath $entry.source -Destination $entry.target -Force
    }
    Remove-Item -LiteralPath $PlanPath -Force
    @{ok=$true; state=$plan.state; backup=$backup} | ConvertTo-Json | Set-Content -LiteralPath $reportPath -Encoding UTF8
} catch {
    $failure = $_.Exception.Message
    $rollbackFailure = $null
    if ($copyStarted) {
        foreach ($entry in $replacements) {
            try {
                if ($entry.existed) { Copy-Item -LiteralPath $entry.saved -Destination $entry.target -Force }
                elseif (Test-Path -LiteralPath $entry.target -PathType Leaf) { Remove-Item -LiteralPath $entry.target -Force }
            } catch { $rollbackFailure = $_.Exception.Message }
        }
    }
    @{ok=$false; error=$failure; rollback_error=$rollbackFailure} | ConvertTo-Json | Set-Content -LiteralPath $reportPath -Encoding UTF8
    exit 1
} finally {
    if ($heldMutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
