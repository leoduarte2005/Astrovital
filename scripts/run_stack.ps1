<#
.SYNOPSIS
  EdgeSpace - sobe a stack completa (edge-ai :5006 + Central Go :8000) com um comando.

.DESCRIPTION
  1. Limpa processos orfaos nas portas 5006 e 8000.
  2. Gera modelos .onnx se faltar algum (edge-ai/training/build_all_models.py).
     Instala llama-cpp-python e baixa o modelo SLM GGUF (edge-ai/models/slm/) na 1a execucao.
  3. Compila build/edgespace-central.exe (go build dentro de central/).
  4. Sobe o worker Python edgespace_ai em background e espera a porta 5006.
  5. Sobe a Central Go (sem --mock-ai) com logs legiveis no console.
  6. Ctrl+C (ou fim do smoke test) encerra Central e worker (try/finally).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1
  powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Scenario hypercapnia
  powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -RealCluster -HttpAddr ":8000"
  powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -NoBuild -SmokeSeconds 10
#>
[CmdletBinding()]
param(
    [ValidateSet('', 'hypercapnia', 'sans', 'solar_storm', 'dehydration_sleep', 'node_loss')]
    [string]$Scenario = '',
    [switch]$NoBuild,
    [switch]$RealCluster,
    [string]$HttpAddr = '127.0.0.1:8000',
    [string]$IpcAddr = '127.0.0.1:5006',
    [ValidateSet('debug', 'info', 'warn', 'error')]
    [string]$LogLevel = 'info',
    [switch]$RawLogs,
    # Pula instalacao/download do SLM (GGUF) e usa template deterministico.
    [switch]$NoSlm,
    # >0: modo de teste. Sobe tudo, valida /healthz + ai_ready, espera N segundos e encerra.
    [int]$SmokeSeconds = 0
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

# ---------------------------------------------------------------- caminhos
$Root        = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$CentralDir  = Join-Path $Root 'central'
$EdgeAiDir   = Join-Path $Root 'edge-ai'
$ModelsDir   = Join-Path $EdgeAiDir 'models'
$VarDir      = Join-Path $Root 'var'
$BuildDir    = Join-Path $Root 'build'
$CentralExe  = Join-Path $BuildDir 'edgespace-central.exe'
$PythonExe   = Join-Path $EdgeAiDir '.venv\Scripts\python.exe'
$DbPath      = Join-Path $VarDir 'edgespace.db'
$AiLog       = Join-Path $VarDir 'edge-ai.log'
$AiErrLog    = Join-Path $VarDir 'edge-ai.err.log'
$CentralLog  = Join-Path $VarDir 'central.log'
$CentralErr  = Join-Path $VarDir 'central.err.log'
$Models      = @('posture_cls.onnx', 'exercise_cadence.onnx', 'vitals_reg.onnx',
                 'baseline_ae_default.onnx', 'isolation_forest.onnx')

$IpcPort   = [int]($IpcAddr.Split(':')[-1])
$HttpPort  = [int]($HttpAddr.Split(':')[-1])
$HealthUrl = "http://127.0.0.1:$HttpPort/healthz"

# ---------------------------------------------------------------- helpers
function Write-Step([string]$msg) { Write-Host "[run_stack] $msg" -ForegroundColor Cyan }
function Write-Warn([string]$msg) { Write-Host "[run_stack] $msg" -ForegroundColor Yellow }
function Write-Fail([string]$msg) { Write-Host "[run_stack] $msg" -ForegroundColor Red }

function Get-PortPids([int]$port) {
    $pids = @()
    try {
        $pids = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
                  Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        # Sem conexao (ou sem modulo NetTCPIP): fallback netstat -ano
        $pids = @(netstat -ano -p TCP | Select-String 'LISTENING' |
                  Where-Object { $_.Line -match "[:\.]$port\s" } |
                  ForEach-Object { ($_.Line.Trim() -split '\s+')[-1] } |
                  Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ } |
                  Select-Object -Unique)
    }
    return @($pids | Where-Object { $_ -gt 0 })
}

function Stop-Tree([int]$procId) {
    if ($procId -le 0) { return }
    $p = Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', "$procId", '/T', '/F') `
        -WindowStyle Hidden -Wait -PassThru -ErrorAction SilentlyContinue
}

function Clear-Port([int]$port) {
    foreach ($procId in (Get-PortPids $port)) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        $name = if ($p) { $p.ProcessName } else { '?' }
        Write-Warn "porta $port ocupada por PID $procId ($name) - encerrando"
        Stop-Tree $procId
    }
    $deadline = (Get-Date).AddSeconds(5)
    while (@(Get-PortPids $port).Count -gt 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    if (@(Get-PortPids $port).Count -gt 0) { throw "porta $port continua ocupada" }
}

function Test-TcpPort([int]$port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $c.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $ar.AsyncWaitHandle.WaitOne(300)) { return $false }
        $c.EndConnect($ar); return $true
    } catch { return $false } finally { $c.Close() }
}

function Find-Go {
    $cmd = Get-Command go -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Go\bin\go.exe'),
        'C:\Go\bin\go.exe',
        (Join-Path $env:LOCALAPPDATA 'go-sdk\go\bin\go.exe'),
        (Join-Path $env:LOCALAPPDATA 'edgespace-tools\go\bin\go.exe')
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    throw 'go.exe nao encontrado (instale Go ou adicione ao PATH)'
}

function Show-Tail([string]$path, [int]$n = 20) {
    if (Test-Path $path) { Get-Content $path -Tail $n | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
}

# Converte linha JSON do slog em linha legivel: "HH:MM:SS.mmm LEVEL msg k=v ..."
function Write-CentralLog([string]$line) {
    if ($RawLogs -or -not $line.StartsWith('{')) { Write-Host $line; return }
    try { $o = $line | ConvertFrom-Json -ErrorAction Stop } catch { Write-Host $line; return }
    $ts = ''; $lvl = 'INFO'; $msg = ''
    $extra = New-Object System.Collections.Generic.List[string]
    foreach ($p in $o.PSObject.Properties) {
        switch ($p.Name) {
            'time'  { $ts = [string]$p.Value; if ($ts.Length -ge 23) { $ts = $ts.Substring(11, 12) } }
            'level' { $lvl = [string]$p.Value }
            'msg'   { $msg = [string]$p.Value }
            default {
                $v = $p.Value
                if ($v -is [System.Management.Automation.PSCustomObject] -or $v -is [array]) {
                    $v = ($v | ConvertTo-Json -Compress -Depth 5)
                }
                $extra.Add("$($p.Name)=$v")
            }
        }
    }
    $color = switch ($lvl) { 'ERROR' { 'Red' } 'WARN' { 'Yellow' } 'DEBUG' { 'DarkGray' } default { 'Gray' } }
    Write-Host ('{0} {1,-5} {2}  {3}' -f $ts, $lvl, $msg, ($extra -join ' ')) -ForegroundColor $color
}

# ---------------------------------------------------------------- execucao
$aiProc = $null
$centralProc = $null
$exitCode = 0

try {
    Set-Location $Root
    $mode = if ($RealCluster) { 'HARDWARE REAL (UDP :5005, mock-cluster=false)' } else { 'SIMULADO (mock-cluster=inproc)' }
    $scen = if ($Scenario) { $Scenario } else { '(nenhum)' }
    Write-Step "raiz: $Root"
    Write-Step "modo: $mode | IA: $IpcAddr | HTTP: $HttpAddr | scenario: $scen"

    if (-not (Test-Path $PythonExe)) { throw "venv ausente: $PythonExe (crie com: python -m venv edge-ai\.venv e instale requirements)" }

    # 1. portas
    Write-Step "limpando portas $IpcPort e $HttpPort"
    Clear-Port $IpcPort
    Clear-Port $HttpPort

    # 2. modelos .onnx
    $missing = @($Models | Where-Object { -not (Test-Path (Join-Path $ModelsDir $_)) })
    if ($missing.Count -gt 0) {
        Write-Warn "modelos ausentes: $($missing -join ', ') - executando build_all_models.py"
        & $PythonExe (Join-Path $EdgeAiDir 'training\build_all_models.py')
        if ($LASTEXITCODE -ne 0) { throw "build_all_models.py falhou (exit $LASTEXITCODE)" }
    } else {
        Write-Step "modelos .onnx OK ($($Models.Count)/$($Models.Count))"
    }

    # 2b. SLM conversacional: runtime llama-cpp-python + modelo GGUF (~1.1 GB, fora do Git)
    if ($NoSlm) {
        Write-Warn '-NoSlm: SLM desativado (respostas por template deterministico)'
        $env:EDGESPACE_DISABLE_SLM = '1'
    } else {
        $prevEapSlm = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try {
            & $PythonExe -c 'import llama_cpp' 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Warn 'llama-cpp-python ausente - instalando (wheel CPU pre-compilada)'
                & $PythonExe -m pip install --disable-pip-version-check --prefer-binary `
                    --extra-index-url 'https://abetlen.github.io/llama-cpp-python/whl/cpu' 'llama-cpp-python>=0.3.0'
                if ($LASTEXITCODE -ne 0) { Write-Warn 'falha ao instalar llama-cpp-python; edge-ai seguira com template deterministico' }
            }

            $env:PYTHONPATH = Join-Path $EdgeAiDir 'src'
            & $PythonExe -m edgespace_ai.utils.model_fetch --models-dir $ModelsDir --check | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Warn 'modelo SLM ausente - baixando automaticamente do Hugging Face (~1.1 GB, so na 1a execucao)'
                & $PythonExe -m edgespace_ai.utils.model_fetch --models-dir $ModelsDir
                if ($LASTEXITCODE -ne 0) { Write-Warn 'download do modelo SLM falhou; edge-ai seguira com template deterministico (rode de novo para retomar)' }
            } else {
                Write-Step "modelo SLM OK ($(Join-Path $ModelsDir 'slm'))"
            }
        } finally {
            $ErrorActionPreference = $prevEapSlm
        }
    }

    # 3. build Go
    $goExe = Find-Go
    $useGoRun = $false
    if ($NoBuild -and (Test-Path $CentralExe)) {
        Write-Step "-NoBuild: usando $CentralExe"
    } else {
        Write-Step "go build ($goExe)"
        New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
        Push-Location $CentralDir
        try {
            $env:CGO_ENABLED = '0'
            & $goExe build -o $CentralExe ./cmd/edgespace-central
            if ($LASTEXITCODE -ne 0) { throw "go build falhou (exit $LASTEXITCODE)" }
        } finally { Pop-Location }
        Write-Step "binario: $CentralExe"
    }
    try {
        $prevEapTest = $ErrorActionPreference; $ErrorActionPreference = 'Stop'
        $null = & $CentralExe -h 2>&1
    } catch {
        if ($_.Exception.Message -match 'Controle de Aplicativo|Application Control|blocked') {
            Write-Warn "Smart App Control bloqueou $CentralExe; usando 'go run ./cmd/edgespace-central' automaticamente"
            $useGoRun = $true
        }
    } finally {
        $ErrorActionPreference = 'Stop'
    }

    # 4. worker IA (background, logs em var/)
    New-Item -ItemType Directory -Force -Path $VarDir | Out-Null
    Write-Step "subindo edge-ai em $IpcAddr (logs: var\edge-ai.log, var\edge-ai.err.log)"
    $env:PYTHONPATH = 'src'
    $env:PYTHONUNBUFFERED = '1'
    $aiArgs = @('-m', 'edgespace_ai', '--listen', $IpcAddr, '--db', "`"$DbPath`"", '--models-dir', "`"$ModelsDir`"")
    $aiProc = Start-Process -FilePath $PythonExe -WorkingDirectory $EdgeAiDir -NoNewWindow -PassThru `
        -ArgumentList $aiArgs -RedirectStandardOutput $AiLog -RedirectStandardError $AiErrLog

    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-TcpPort $IpcPort)) {
        if ($aiProc.HasExited) { Write-Fail "edge-ai morreu (exit $($aiProc.ExitCode))"; Show-Tail $AiErrLog; throw 'edge-ai falhou' }
        if ((Get-Date) -gt $deadline) { Show-Tail $AiErrLog; throw "timeout esperando porta $IpcPort" }
        Start-Sleep -Milliseconds 250
    }
    Write-Step "edge-ai pronto (PID $($aiProc.Id), porta $IpcPort aberta)"

    # 5. Central Go (sem -mock-ai)
    $clusterMode = if ($RealCluster) { 'false' } else { 'inproc' }
    $migrationsDir = Join-Path $Root 'database\migrations'
    $centralArgs = @(
        "-mock-cluster=$clusterMode",
        "-ipc-addr=$IpcAddr",
        "-http-addr=$HttpAddr",
        "-db=$DbPath",
        "-migrations=$migrationsDir",
        "-log-level=$LogLevel"
    )
    if ($Scenario) { $centralArgs += "-scenario=$Scenario" }
    Write-Step "subindo Central: $($centralArgs -join ' ')"

    if ($SmokeSeconds -gt 0) {
        # Modo teste: Central em background, valida /healthz (200 OK) + WS (ai_ready: true) e encerra.
        if ($useGoRun) {
            $env:CGO_ENABLED = '0'
            $goRunArgs = @('run', './cmd/edgespace-central') + $centralArgs
            $centralProc = Start-Process -FilePath $goExe -WorkingDirectory $CentralDir -NoNewWindow -PassThru `
                -ArgumentList $goRunArgs -RedirectStandardOutput $CentralLog -RedirectStandardError $CentralErr
        } else {
            $centralProc = Start-Process -FilePath $CentralExe -WorkingDirectory $Root -NoNewWindow -PassThru `
                -ArgumentList $centralArgs -RedirectStandardOutput $CentralLog -RedirectStandardError $CentralErr
        }
        $deadline = (Get-Date).AddSeconds(20)
        $body = ''; $status = 0
        $ProgressPreference = 'SilentlyContinue'
        while ((Get-Date) -lt $deadline) {
            if ($centralProc.HasExited) { Show-Tail $CentralErr; Show-Tail $CentralLog; throw "Central morreu (exit $($centralProc.ExitCode))" }
            try {
                $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
                $status = [int]$r.StatusCode; $body = ([string]$r.Content).Trim()
                if ($status -eq 200) { break }
            } catch { }
            Start-Sleep -Milliseconds 300
        }
        Write-Step "GET $HealthUrl -> $status $body"

        # Le frames em ws://127.0.0.1:<port>/ws via ClientWebSocket ate receber ai_ready=true
        $aiReady = $false; $wsSample = ''
        $ws = New-Object System.Net.WebSockets.ClientWebSocket
        $ws.Options.SetRequestHeader('Origin', "http://127.0.0.1:$HttpPort")
        $cts = New-Object System.Threading.CancellationTokenSource(10000)
        try {
            $null = $ws.ConnectAsync([Uri]"ws://127.0.0.1:$HttpPort/ws", $cts.Token).GetAwaiter().GetResult()
            $buf = New-Object byte[] 65536
            $seg = New-Object System.ArraySegment[byte]($buf, 0, $buf.Length)
            $wsDeadline = (Get-Date).AddSeconds(8)
            while ((Get-Date) -lt $wsDeadline -and -not $aiReady) {
                $ms = New-Object System.IO.MemoryStream
                do {
                    $res = $ws.ReceiveAsync($seg, $cts.Token).GetAwaiter().GetResult()
                    $ms.Write($buf, 0, $res.Count)
                } while (-not $res.EndOfMessage)
                $frame = [System.Text.Encoding]::UTF8.GetString($ms.ToArray())
                if ($frame -match '"ai_ready"\s*:\s*true') { $aiReady = $true; $wsSample = $frame }
            }
        } finally {
            try { $ws.Dispose() } catch { }
            $cts.Dispose()
        }
        Write-Step "WS /ws ai_ready=$aiReady"
        if ($wsSample) { Write-Host "    $wsSample" }

        if ($status -ne 200 -or -not $aiReady) {
            $exitCode = 1
            Write-Fail "SMOKE FALHOU (status=$status ai_ready=$aiReady)"
        } else {
            Write-Step "SMOKE OK: /healthz 200 OK + Central conectada ao edge-ai (ai_ready=true). Mantendo por $SmokeSeconds s..."
            Start-Sleep -Seconds $SmokeSeconds
        }
        Write-Step 'ultimas linhas da Central:'
        if (Test-Path $CentralLog) { Get-Content $CentralLog -Tail 8 | ForEach-Object { Write-CentralLog $_ } }
        Write-Step 'ultimas linhas do edge-ai:'
        if (Test-Path $AiLog) { Get-Content $AiLog -Tail 5 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkCyan } }
    } else {
        Write-Step "Central no ar: http://127.0.0.1:$HttpPort  (Ctrl+C encerra tudo)"
        # Foreground: logs JSON formatados; stderr tambem passa pelo formatador.
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try {
            if ($useGoRun) {
                Push-Location $CentralDir
                try {
                    $env:CGO_ENABLED = '0'
                    & $goExe run ./cmd/edgespace-central @centralArgs 2>&1 | ForEach-Object { Write-CentralLog ([string]$_) }
                    $exitCode = $LASTEXITCODE
                } finally { Pop-Location }
            } else {
                & $CentralExe @centralArgs 2>&1 | ForEach-Object { Write-CentralLog ([string]$_) }
                $exitCode = $LASTEXITCODE
            }
        } finally { $ErrorActionPreference = $prevEap }
        Write-Step "Central saiu (exit $exitCode)"
    }
}
catch {
    Write-Fail "erro: $($_.Exception.Message)"
    $exitCode = 1
}
finally {
    # Executa tambem no Ctrl+C (PowerShell roda finally ao interromper o pipeline).
    Write-Step 'encerrando stack...'
    $centrals = @()
    if ($centralProc) { $centrals += $centralProc }
    $centrals += @(Get-Process -Name 'edgespace-central' -ErrorAction SilentlyContinue |
                   Where-Object { try { $_.Path -eq $CentralExe } catch { $false } })
    foreach ($p in $centrals) {
        # Ctrl+C ja chega ao processo do console; da tempo para shutdown gracioso.
        if (-not $p.HasExited) { $null = $p.WaitForExit(2000) }
        Stop-Tree $p.Id
    }
    if ($aiProc) {
        # venv no Windows usa launcher + processo filho: mata a arvore.
        Stop-Tree $aiProc.Id
    }
    foreach ($port in @($IpcPort, $HttpPort)) {
        foreach ($procId in (Get-PortPids $port)) { Stop-Tree $procId }
    }
    Start-Sleep -Milliseconds 300
    $left = @(@(Get-PortPids $IpcPort) + @(Get-PortPids $HttpPort))
    if ($left.Count -eq 0) { Write-Step "portas $IpcPort e $HttpPort livres. Fim." }
    else { Write-Fail "processos ainda nas portas: $($left -join ', ')"; $exitCode = 1 }
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
}
exit $exitCode
