param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$dataDirectory = Join-Path $PSScriptRoot '.mathlens'
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
Add-Type -AssemblyName System.Net.Http
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.UseProxy = $false
$client = New-Object System.Net.Http.HttpClient($handler)
$client.Timeout = [TimeSpan]::FromSeconds(2)
function Read-MathLensHealth {
    try { return ($client.GetStringAsync('http://127.0.0.1:4173/api/health').GetAwaiter().GetResult() | ConvertFrom-Json) }
    catch { return $null }
}
try {
    $health = Read-MathLensHealth
    if ($health -and $health.version -ne '0.4.1') {
        $pidFile = Join-Path $dataDirectory 'server.pid'
        if (-not (Test-Path -LiteralPath $pidFile)) { throw 'An older server is running without a managed PID. Stop that MathLens server first.' }
        $ownedPid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
        $ownedProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$ownedPid"
        $expectedPython = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.venv/Scripts/python.exe'))
        if (-not $ownedProcess -or $ownedProcess.ExecutablePath -ne $expectedPython -or $ownedProcess.CommandLine -notmatch 'server\.py.*--port\s+4173') {
            throw 'The saved PID is not this project server. Stop the older MathLens service before launching.'
        }
        $ownedChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ownedPid" | Where-Object { $_.CommandLine -match 'server\.py.*--port\s+4173' }
        foreach ($child in $ownedChildren) { Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $ownedPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        $health = Read-MathLensHealth
        if ($health) { throw 'The older service is still listening. It was not replaced.' }
    }
    if (-not $health) {
        $pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
        $pythonPrefix = @()
        if (-not (Test-Path -LiteralPath $pythonPath)) {
            $command = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $command) { throw 'Install Python 3.12, then run setup_mathlens.bat.' }
            $pythonPath = $command.Source
        }
        & $pythonPath -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,13), 'Python 3.11 or 3.12 is required'"
        if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.11/3.12 and run setup_mathlens.bat.' }
        $arguments = $pythonPrefix + @('-u','-X','utf8','server.py','--host','127.0.0.1','--port','4173')
        $process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataDirectory 'server.stdout.log') -RedirectStandardError (Join-Path $dataDirectory 'server.stderr.log') -PassThru
        $process.Id | Set-Content -LiteralPath (Join-Path $dataDirectory 'server.pid')
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            $health = Read-MathLensHealth
            if ($health) { break }
            if ($process.HasExited) {
                throw (Get-Content -LiteralPath (Join-Path $dataDirectory 'server.stderr.log') -Raw)
            }
            Start-Sleep -Milliseconds 500
        }
        if (-not $health) { throw 'Server did not become ready. Check .mathlens/server.stderr.log.' }
    }
    Write-Host 'MathLens is ready: http://127.0.0.1:4173/'
    Write-Host 'The service runs in the background. Closing this launcher does not stop it.'
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:4173/' }
}
catch {
    Write-Host ('MathLens: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
finally { $client.Dispose(); $handler.Dispose() }
