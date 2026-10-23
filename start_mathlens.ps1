param([switch]$NoBrowser, [ValidateRange(1,65535)][int]$Port = 4173)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
Set-Location -LiteralPath $PSScriptRoot
$dataDirectory = if ($env:MATHLENS_DATA_DIR) { [IO.Path]::GetFullPath($env:MATHLENS_DATA_DIR) } else { [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.mathlens')) }
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$sha = [Security.Cryptography.SHA256]::Create()
try { $dataId = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($dataDirectory.ToLowerInvariant())))).Replace('-','').ToLowerInvariant() }
finally { $sha.Dispose() }
$addressFile = Join-Path $dataDirectory 'server.json'
$mutex = [Threading.Mutex]::new($false, "Local\MathLens-$dataId")
$ownsMutex = $false
Add-Type -AssemblyName System.Net.Http
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.UseProxy = $false
$client = New-Object System.Net.Http.HttpClient($handler)
$client.Timeout = [TimeSpan]::FromSeconds(2)
function Read-Health([string]$Url) {
    try { return ($client.GetStringAsync($Url + 'api/health').GetAwaiter().GetResult() | ConvertFrom-Json) }
    catch { return $null }
}
function Read-Address {
    try {
        $saved = Get-Content -LiteralPath $addressFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $uri = [Uri]$saved.url
        if ($saved.data_id -eq $dataId -and $uri.Scheme -eq 'http' -and $uri.Host -eq '127.0.0.1' -and $uri.AbsolutePath -eq '/' -and -not $uri.UserInfo -and -not $uri.Query -and -not $uri.Fragment) { return $saved }
    } catch {}
    return $null
}
function Is-OwnHealth($Value) { return ($Value -and $Value.ok -and $Value.app -eq 'mathlens' -and $Value.data_id -eq $dataId) }
function Stop-OldServer([int]$OwnedPid) {
    $ownedProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$OwnedPid"
    $expectedPython = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.venv/Scripts/python.exe'))
    $allowedPython = @($expectedPython)
    if (Test-Path -LiteralPath $expectedPython) {
        $basePython = & $expectedPython -c "import sys; print(sys._base_executable)"
        if ($LASTEXITCODE -eq 0) { $allowedPython += $basePython.Trim() }
    }
    if (-not $ownedProcess -or $ownedProcess.ExecutablePath -notin $allowedPython -or $ownedProcess.CommandLine -notmatch 'server\.py.*--port\s+\d+') {
        throw 'An older MathLens is running. Its saved PID cannot be verified; stop that MathLens service before launching.'
    }
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$OwnedPid" | Where-Object { $_.CommandLine -match 'server\.py.*--port\s+\d+' }
    foreach ($child in $children) { Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $OwnedPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}
try {
    try { $ownsMutex = $mutex.WaitOne(30000) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { throw 'Another MathLens launcher is still starting. Please try again shortly.' }
    $saved = Read-Address
    $health = if ($saved) { Read-Health $saved.url } else { $null }
    if (Is-OwnHealth $health) {
        if ($health.version -ne '0.5.2') { Stop-OldServer ([int]$saved.pid); $health = $null }
    } else { $health = $null }
    # Recognise managed releases that predate the address file.
    if (-not $health) {
        $legacy = Read-Health 'http://127.0.0.1:4173/'
        if ($legacy -and $legacy.ok -and $legacy.version -match '^0\.[1-5]\.' -and -not $legacy.app) {
            $pidFile = Join-Path $dataDirectory 'server.pid'
            if (-not (Test-Path -LiteralPath $pidFile)) { throw 'Stop the older MathLens service before launching this version.' }
            Stop-OldServer ([int](Get-Content -LiteralPath $pidFile -Raw).Trim())
        }
        $pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $pythonPath)) {
            $command = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $command) { throw 'Install Python 3.12, then run setup_mathlens.bat.' }
            $pythonPath = $command.Source
        }
        & $pythonPath -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,13), 'Python 3.11 or 3.12 is required'"
        if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.11/3.12 and run setup_mathlens.bat.' }
        $arguments = @('-u','-X','utf8','server.py','--host','127.0.0.1','--port',"$Port",'--auto-port')
        $process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataDirectory 'server.stdout.log') -RedirectStandardError (Join-Path $dataDirectory 'server.stderr.log') -PassThru
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            $saved = Read-Address
            $health = if ($saved) { Read-Health $saved.url } else { $null }
            if ((Is-OwnHealth $health) -and $health.version -eq '0.5.2') { break }
            $health = $null
            $process.Refresh()
            if ($process.HasExited) {
                $detail = Get-Content -LiteralPath (Join-Path $dataDirectory 'server.stderr.log') -Raw -Encoding UTF8
                throw "Server exited. $detail"
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $health) { throw 'Server did not become ready. Check .mathlens/server.stderr.log.' }
        $saved.pid | Set-Content -LiteralPath (Join-Path $dataDirectory 'server.pid')
    }
    Write-Host ('MathLens is ready: ' + $saved.url)
    Write-Host 'The service runs in the background. Closing this launcher does not stop it.'
    if (-not $NoBrowser) { Start-Process $saved.url }
}
catch {
    Write-Host ('MathLens: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
finally {
    $client.Dispose(); $handler.Dispose()
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
