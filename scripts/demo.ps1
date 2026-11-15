<#
.SYNOPSIS
  EdgeSpace One-Command Demo (Windows PowerShell).
  Sobe todo o ecossistema EdgeSpace (Frontend + Central Go + Edge AI + SQLite + ESP32-S3 opcional).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/demo.ps1 -Mode mock
  powershell -ExecutionPolicy Bypass -File scripts/demo.ps1 -Mode mock -Scenario hypercapnia -NoSlm
  powershell -ExecutionPolicy Bypass -File scripts/demo.ps1 -Mode real -Flash
  powershell -ExecutionPolicy Bypass -File scripts/demo.ps1 -Mode mock -NoOpen -SmokeSeconds 5
  powershell -ExecutionPolicy Bypass -File scripts/demo.ps1 -Mode mock -StaticUi   # sem Vite dev server (:8000)
#>
[CmdletBinding()]
param(
    [ValidateSet('mock', 'real')]
    [string]$Mode = 'mock',
    [switch]$Mock,
    [switch]$Real,
    [switch]$Flash,
    [switch]$FlashOnly,
    [switch]$NoSlm,
    [switch]$StaticUi,
    [ValidateSet('', 'nominal', 'hypercapnia', 'sans', 'solar_storm', 'dehydration_sleep', 'node_loss')]
    [string]$Scenario = '',
    [switch]$NoOpen,
    [switch]$NoBuild,
    [string]$Port = '',
    [string]$HttpAddr = '',
    [string]$IpcAddr = '127.0.0.1:5006',
    [string]$UdpAddr = ':5005',
    [int]$VitePort = 5173,
    [ValidateSet('debug', 'info', 'warn', 'error')]
    [string]$LogLevel = 'info',
    [switch]$RawLogs,
    [int]$SmokeSeconds = 0
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

if ($Real) { $Mode = 'real' }
elseif ($Mock) { $Mode = 'mock' }

if (-not $HttpAddr) {
    $HttpAddr = if ($Mode -eq 'real') { ':8000' } else { '127.0.0.1:8000' }
}
$EffectiveScenario = if ($Scenario -eq 'nominal') { '' } else { $Scenario }

# ---------------------------------------------------------------- caminhos
$Root         = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$CentralDir   = Join-Path $Root 'central'
$EdgeAiDir    = Join-Path $Root 'edge-ai'
$FrontendDir  = Join-Path $Root 'frontend'
$FirmwareDir  = Join-Path $Root 'firmware'
$UiTargetDir  = Join-Path $CentralDir 'internal\httpws\ui'
$ModelsDir    = Join-Path $EdgeAiDir 'models'
$VarDir       = Join-Path $Root 'var'
$BuildDir     = Join-Path $Root 'build'
$CentralExe   = Join-Path $BuildDir 'edgespace-central.exe'
$PythonExe    = Join-Path $EdgeAiDir '.venv\Scripts\python.exe'
$DbPath       = Join-Path $VarDir 'edgespace.db'
$AiLog        = Join-Path $VarDir 'edge-ai.log'
$AiErrLog     = Join-Path $VarDir 'edge-ai.err.log'
$CentralLog   = Join-Path $VarDir 'central.log'
$CentralErr   = Join-Path $VarDir 'central.err.log'
$ViteLog      = Join-Path $VarDir 'vite.log'
$ViteErr      = Join-Path $VarDir 'vite.err.log'
$Models       = @('posture_cls.onnx', 'exercise_cadence.onnx', 'vitals_reg.onnx',
                  'baseline_ae_default.onnx', 'isolation_forest.onnx')

$IpcPort     = [int]($IpcAddr.Split(':')[-1])
$HttpPort    = [int]($HttpAddr.Split(':')[-1])
$UdpPort     = [int]($UdpAddr.Split(':')[-1])
$HealthUrl   = "http://127.0.0.1:$HttpPort/healthz"
$CentralUrl  = "http://127.0.0.1:$HttpPort"
$FrontendUrl = "http://localhost:${VitePort}/#/crew"

function Write-Step([string]$msg) { Write-Host "[demo] $msg" -ForegroundColor Cyan }
function Write-Warn([string]$msg) { Write-Host "[demo] $msg" -ForegroundColor Yellow }

function Get-TcpPortPids([int]$port) {
    $pids = @()
    try {
        $pids = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
                  Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        $pids = @(netstat -ano -p TCP | Select-String 'LISTENING' |
                  Where-Object { $_.Line -match "[:\.]$port\s" } |
                  ForEach-Object { ($_.Line.Trim() -split '\s+')[-1] } |
                  Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ } |
                  Select-Object -Unique)
    }
    return @($pids | Where-Object { $_ -gt 0 })
}

function Get-UdpPortPids([int]$port) {
    $pids = @()
    try {
        $pids = @(Get-NetUDPEndpoint -LocalPort $port -ErrorAction Stop |
                  Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        $pids = @(netstat -ano -p UDP 2>$null |
                  Where-Object { $_ -match "[:\.]$port\s" } |
                  ForEach-Object { ($_.Trim() -split '\s+')[-1] } |
                  Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ } |
                  Select-Object -Unique)
    }
    return @($pids | Where-Object { $_ -gt 0 })
}

function Stop-Tree([int]$procId) {
    if ($procId -le 0 -or $procId -eq $PID) { return }
    $null = Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', "$procId", '/T', '/F') `
        -WindowStyle Hidden -Wait -PassThru -ErrorAction SilentlyContinue
}

function Clear-Port([int]$port, [ValidateSet('TCP', 'UDP')][string]$proto = 'TCP') {
    $pids = if ($proto -eq 'UDP') { Get-UdpPortPids $port } else { Get-TcpPortPids $port }
    foreach ($procId in $pids) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        $name = if ($p) { $p.ProcessName } else { '?' }
        Write-Warn "porta $proto/$port ocupada por PID $procId ($name) - encerrando"
        Stop-Tree $procId
    }
    $deadline = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        $rem = if ($proto -eq 'UDP') { Get-UdpPortPids $port } else { Get-TcpPortPids $port }
        if (@($rem).Count -eq 0) { return }
        Start-Sleep -Milliseconds 200
    }
    $left = if ($proto -eq 'UDP') { Get-UdpPortPids $port } else { Get-TcpPortPids $port }
    if (@($left).Count -gt 0) { throw "porta $proto/$port continua ocupada" }
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

function Find-PythonBase {
    foreach ($name in @('python3', 'python', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw 'Python 3 nao encontrado no PATH'
}

function Show-Tail([string]$path, [int]$n = 20) {
    if (Test-Path $path) { Get-Content $path -Tail $n | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
}

function Write-CentralLog([string]$line) {
    if ([string]::IsNullOrWhiteSpace($line)) { return }
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


function Get-EspSerialPorts {
    if ($Port) { return @($Port) }
    $ports = New-Object System.Collections.Generic.List[string]
    try {
        $pnp = Get-CimInstance Win32_PnPEntity -ErrorAction Stop |
               Where-Object { $_.Name -match '\((COM\d+)\)' }
        foreach ($dev in $pnp) {
            if ($dev.Name -match '(USB|UART|CP210|CH340|CH910|JTAG|ESP|Serial)') {
                if ($dev.Name -match '\((COM\d+)\)') {
                    $p = $Matches[1]
                    if (-not $ports.Contains($p)) { $ports.Add($p) }
                }
            }
        }
    } catch { }
    if ($ports.Count -eq 0) {
        foreach ($p in ([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object -Unique)) {
            if ($p -match '^COM\d+$' -and -not $ports.Contains($p)) { $ports.Add($p) }
        }
    }
    return @($ports)
}

function Invoke-EspFlash {
    if (-not (Test-Path (Join-Path $FirmwareDir 'CMakeLists.txt'))) {
        throw "firmware/CMakeLists.txt ausente em $FirmwareDir"
    }
    $idfCmd = Get-Command idf.py -ErrorAction SilentlyContinue
    if (-not $idfCmd -and $env:IDF_PATH -and (Test-Path (Join-Path $env:IDF_PATH 'export.ps1'))) {
        Write-Step "carregando ambiente ESP-IDF de $env:IDF_PATH"
        . (Join-Path $env:IDF_PATH 'export.ps1')
        $idfCmd = Get-Command idf.py -ErrorAction SilentlyContinue
    }
    if (-not $idfCmd) {
        throw 'ESP-IDF (idf.py) nao encontrado. Abra o ESP-IDF PowerShell ou defina $env:IDF_PATH.'
    }

    $ports = @(Get-EspSerialPorts)
    if ($ports.Count -eq 0) {
        throw 'nenhuma porta serial COM* detectada para os ESP32-S3. Conecte via USB ou passe -Port COMx.'
    }
    Write-Step "portas seriais detectadas: $($ports -join ', ')"

    Push-Location $FirmwareDir
    try {
        Write-Step 'compilando firmware homogeneo ESP32-S3 (idf.py set-target esp32s3 build)'
        & idf.py set-target esp32s3 build
        if ($LASTEXITCODE -ne 0) { throw "idf.py build falhou (exit $LASTEXITCODE)" }

        foreach ($p in $ports) {
            Write-Step "gravando firmware em $p (idf.py -p $p flash)..."
            & idf.py -p $p flash
            if ($LASTEXITCODE -ne 0) { throw "idf.py flash falhou na porta $p (exit $LASTEXITCODE)" }
        }
        Write-Step "firmware gravado com sucesso em $($ports.Count) placa(s)."
    } finally {
        Pop-Location
    }
}

function Sync-Frontend {
    $pkg = Join-Path $FrontendDir 'package.json'
    $uiIndex = Join-Path $UiTargetDir 'index.html'
    if (-not (Test-Path $pkg)) {
        Write-Warn 'frontend/package.json ausente; mantendo UI embarcada atual.'
        return
    }
    $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    $npm  = Get-Command npm  -ErrorAction SilentlyContinue
    $nodeModules = Join-Path $FrontendDir 'node_modules'

    $built = $false
    Push-Location $FrontendDir
    try {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        if ($pnpm) {
            if (-not (Test-Path $nodeModules)) {
                Write-Step 'instalando deps do frontend offline (pnpm install --offline --frozen-lockfile)'
                & $pnpm.Source install --offline --frozen-lockfile 2>&1 | Out-Null
            }
            if ((Test-Path $nodeModules) -or $LASTEXITCODE -eq 0) {
                Write-Step 'compilando frontend (pnpm run build)'
                & $pnpm.Source run build
                if ($LASTEXITCODE -eq 0) { $built = $true }
            }
        } elseif ($npm -and (Test-Path $nodeModules)) {
            Write-Step 'compilando frontend (npm run build)'
            & $npm.Source run build
            if ($LASTEXITCODE -eq 0) { $built = $true }
        } else {
            Write-Warn 'pnpm/node_modules indisponiveis; usando fallback da UI embarcada.'
        }
    } catch {
        Write-Warn "build do frontend ignorado ($($_.Exception.Message)); usando fallback da UI embarcada."
    } finally {
        $ErrorActionPreference = $prevEap
        Pop-Location
    }

    $distDir = Join-Path $FrontendDir 'dist'
    if ($built -and (Test-Path (Join-Path $distDir 'index.html'))) {
        if (Test-Path $UiTargetDir) { Remove-Item -Recurse -Force $UiTargetDir }
        New-Item -ItemType Directory -Force -Path $UiTargetDir | Out-Null
        Copy-Item -Path (Join-Path $distDir '*') -Destination $UiTargetDir -Recurse -Force
        Write-Step 'frontend dist/ sincronizado em central/internal/httpws/ui/'
    } elseif (Test-Path $uiIndex) {
        Write-Warn 'mantendo UI embarcada existente em central/internal/httpws/ui/'
    } else {
        throw 'nenhum frontend compilado nem fallback em central/internal/httpws/ui/index.html encontrado.'
    }
}

function Write-Fail([string]$msg) { Write-Host "[demo] $msg" -ForegroundColor Red }

# ---------------------------------------------------------------- execucao
$aiProc = $null
$centralProc = $null
$viteProc = $null
$exitCode = 0

try {
    Set-Location $Root

    if ($Flash -or $FlashOnly) {
        Invoke-EspFlash
        if ($FlashOnly) { exit 0 }
    }

    $modeDesc = if ($Mode -eq 'real') { "HARDWARE REAL (UDP $UdpAddr, mock-cluster=false)" } else { 'MOCK (5x ESP32-S3 em memoria, mock-cluster=inproc)' }
    $scenDesc = if ($Scenario) { $Scenario } else { 'nominal' }
    Write-Step "raiz: $Root"
    Write-Step "modo: $modeDesc | IPC: $IpcAddr | Central: $HttpAddr | Vite: :$VitePort | cenario: $scenDesc"

    # 1. Limpeza preventiva de portas (:5005, :5006, :8000, :5173)
    Write-Step "limpando portas preventivamente (UDP/$UdpPort, TCP/$IpcPort, TCP/$HttpPort, TCP/$VitePort)"
    Clear-Port $UdpPort 'UDP'
    Clear-Port $IpcPort 'TCP'
    Clear-Port $HttpPort 'TCP'
    Clear-Port $VitePort 'TCP'

    # 2. Venv Python Edge AI
    if (-not (Test-Path $PythonExe)) {
        $wheelsDir = Join-Path $EdgeAiDir 'wheels'
        $reqFile = Join-Path $EdgeAiDir 'requirements.txt'
        if ((Test-Path $wheelsDir) -and (Test-Path $reqFile)) {
            $basePy = Find-PythonBase
            Write-Step 'criando venv edge-ai offline...'
            & $basePy -m venv (Join-Path $EdgeAiDir '.venv')
            & $PythonExe -m pip install --no-index --find-links $wheelsDir -r $reqFile
            if ($LASTEXITCODE -ne 0) { throw 'falha ao configurar edge-ai/.venv offline' }
        } else {
            throw "venv ausente: $PythonExe (rode setup de edge-ai antes)"
        }
    }

    # 3. Migracao SQLite (antes do worker IA abrir em mode=ro)
    New-Item -ItemType Directory -Force -Path $VarDir | Out-Null
    Write-Step 'aplicando migrations SQLite (var/edgespace.db)'
    & $PythonExe (Join-Path $Root 'database\tools\operational.py') migrate --db $DbPath
    if ($LASTEXITCODE -ne 0) { throw "operational.py migrate falhou (exit $LASTEXITCODE)" }

    # 4. Modelos .onnx + SLM
    $missing = @($Models | Where-Object { -not (Test-Path (Join-Path $ModelsDir $_)) })
    if ($missing.Count -gt 0) {
        Write-Warn "modelos .onnx ausentes ($($missing -join ', ')) - gerando via build_all_models.py"
        & $PythonExe (Join-Path $EdgeAiDir 'training\build_all_models.py')
        if ($LASTEXITCODE -ne 0) { throw "build_all_models.py falhou (exit $LASTEXITCODE)" }
    } else {
        Write-Step "modelos .onnx OK ($($Models.Count)/$($Models.Count))"
    }

    $slmStatus = 'ATIVO'
    if ($NoSlm) {
        Write-Warn '-NoSlm: SLM desativado (apenas ONNX + Grafo Causal SQLite)'
        $env:EDGESPACE_DISABLE_SLM = '1'
        $slmStatus = 'DESATIVADO (-NoSlm)'
    } else {
        Remove-Item Env:EDGESPACE_DISABLE_SLM -ErrorAction SilentlyContinue
        $prevEapSlm = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try {
            & $PythonExe -c 'import llama_cpp' 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Warn 'llama-cpp-python ausente - tentando instalacao offline/wheel CPU'
                & $PythonExe -m pip install --disable-pip-version-check --prefer-binary `
                    --extra-index-url 'https://abetlen.github.io/llama-cpp-python/whl/cpu' 'llama-cpp-python>=0.3.0'
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn 'llama-cpp-python indisponivel; seguindo com template deterministico'
                    $slmStatus = 'FALLBACK (template deterministico)'
                }
            }
            $env:PYTHONPATH = Join-Path $EdgeAiDir 'src'
            & $PythonExe -m edgespace_ai.utils.model_fetch --models-dir $ModelsDir --check | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Warn 'modelo SLM ausente - tentando model_fetch...'
                & $PythonExe -m edgespace_ai.utils.model_fetch --models-dir $ModelsDir
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn 'modelo SLM indisponivel offline; seguindo com template deterministico'
                    $slmStatus = 'FALLBACK (template deterministico)'
                }
            } else {
                Write-Step "modelo SLM OK ($(Join-Path $ModelsDir 'slm'))"
            }
        } finally {
            $ErrorActionPreference = $prevEapSlm
        }
    }

    # 5. Central Go (build + frontend estatico apenas se -StaticUi)
    if (-not $NoBuild -and $StaticUi) { Sync-Frontend }
    $goExe = Find-Go
    $useGoRun = $false
    if ($NoBuild -and (Test-Path $CentralExe)) {
        Write-Step "-NoBuild: usando $CentralExe"
    } else {
        Write-Step "compilando Central Go -> $CentralExe"
        New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
        Push-Location $CentralDir
        try {
            $env:CGO_ENABLED = '0'
            & $goExe build -trimpath -ldflags='-s -w' -o $CentralExe ./cmd/edgespace-central
            if ($LASTEXITCODE -ne 0) { throw "go build falhou (exit $LASTEXITCODE)" }
        } finally { Pop-Location }
    }
    try {
        $prevEapTest = $ErrorActionPreference; $ErrorActionPreference = 'Stop'
        $null = & $CentralExe -h 2>&1
    } catch {
        if ($_.Exception.Message -match 'Controle de Aplicativo|Application Control|blocked') {
            Write-Warn "Smart App Control bloqueou $CentralExe; usando 'go run ./cmd/edgespace-central'"
            $useGoRun = $true
        }
    } finally {
        $ErrorActionPreference = 'Stop'
    }

    # 6. Subida encadeada: Edge AI (:5006)
    Write-Step "subindo Edge AI em $IpcAddr..."
    $env:PYTHONPATH = 'src'
    $env:PYTHONUNBUFFERED = '1'
    $aiArgs = @('-m', 'edgespace_ai', '--listen', $IpcAddr, '--db', "`"$DbPath`"", '--models-dir', "`"$ModelsDir`"")
    $aiProc = Start-Process -FilePath $PythonExe -WorkingDirectory $EdgeAiDir -NoNewWindow -PassThru `
        -ArgumentList $aiArgs -RedirectStandardOutput $AiLog -RedirectStandardError $AiErrLog

    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-TcpPort $IpcPort)) {
        if ($aiProc.HasExited) { Write-Fail "edge-ai morreu (exit $($aiProc.ExitCode))"; Show-Tail $AiErrLog; throw 'edge-ai falhou' }
        if ((Get-Date) -gt $deadline) { Show-Tail $AiErrLog; throw "timeout aguardando porta $IpcPort" }
        Start-Sleep -Milliseconds 250
    }
    Write-Step "Edge AI pronto (PID $($aiProc.Id), TCP/$IpcPort aberto)"

    # 7. Subida encadeada: Central Go (:8000 / :5005)
    $clusterMode = if ($Mode -eq 'real') { 'false' } else { 'inproc' }
    $migrationsDir = Join-Path $Root 'database\migrations'
    $centralArgs = @(
        "-mock-cluster=$clusterMode",
        "-udp-addr=$UdpAddr",
        "-ipc-addr=$IpcAddr",
        "-http-addr=$HttpAddr",
        "`"-db=$DbPath`"",
        "`"-migrations=$migrationsDir`"",
        "-log-level=$LogLevel"
    )
    if ($EffectiveScenario) { $centralArgs += "-scenario=$EffectiveScenario" }

    if (Test-Path $CentralLog) { Remove-Item $CentralLog -Force -ErrorAction SilentlyContinue }
    if (Test-Path $CentralErr) { Remove-Item $CentralErr -Force -ErrorAction SilentlyContinue }

    Write-Step "subindo Central Go ($($centralArgs -join ' '))..."
    if ($useGoRun) {
        $env:CGO_ENABLED = '0'
        $goRunArgs = @('run', './cmd/edgespace-central') + $centralArgs
        $centralProc = Start-Process -FilePath $goExe -WorkingDirectory $CentralDir -NoNewWindow -PassThru `
            -ArgumentList $goRunArgs -RedirectStandardOutput $CentralLog -RedirectStandardError $CentralErr
    } else {
        $centralProc = Start-Process -FilePath $CentralExe -WorkingDirectory $Root -NoNewWindow -PassThru `
            -ArgumentList $centralArgs -RedirectStandardOutput $CentralLog -RedirectStandardError $CentralErr
    }

    $deadline = (Get-Date).AddSeconds(25)
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
    if ($status -ne 200) { Show-Tail $CentralErr; Show-Tail $CentralLog; throw "Healthcheck falhou em $HealthUrl" }

    # 8. Subida encadeada: Frontend Vite (:5173) conectado a Central Go (:8000)
    $activeWebUrl = "$CentralUrl/#/crew"
    $activeProxyPort = $HttpPort
    if (-not $StaticUi -and (Test-Path (Join-Path $FrontendDir 'package.json'))) {
        $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCmd) {
            $viteJs = Join-Path $FrontendDir 'node_modules\vite\bin\vite.js'
            if (-not (Test-Path $viteJs)) {
                $pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
                $npmCmd  = Get-Command npm  -ErrorAction SilentlyContinue
                Push-Location $FrontendDir
                try {
                    if ($pnpmCmd) {
                        Write-Step 'instalando deps do frontend (pnpm)...'
                        & $pnpmCmd.Source install --offline --frozen-lockfile 2>$null
                        if ($LASTEXITCODE -ne 0) { & $pnpmCmd.Source install --frozen-lockfile }
                    } elseif ($npmCmd) {
                        Write-Step 'instalando deps do frontend (npm)...'
                        & $npmCmd.Source install --no-package-lock --no-audit --no-fund
                    }
                } finally { Pop-Location }
            }
            if (Test-Path $viteJs) {
                Write-Step "subindo Frontend Vite em :$VitePort (EDGE_CENTRAL=$CentralUrl)..."
                $env:EDGE_CENTRAL = $CentralUrl
                $viteProc = Start-Process -FilePath $nodeCmd.Source -WorkingDirectory $FrontendDir -NoNewWindow -PassThru `
                    -ArgumentList @("`"$viteJs`"", '--host', '--port', "$VitePort", '--strictPort') `
                    -RedirectStandardOutput $ViteLog -RedirectStandardError $ViteErr
                $vDeadline = (Get-Date).AddSeconds(30)
                while (-not (Test-TcpPort $VitePort)) {
                    if ($viteProc.HasExited) { Show-Tail $ViteErr; Write-Warn "Vite morreu (exit $($viteProc.ExitCode)); usando fallback $activeWebUrl"; $viteProc = $null; break }
                    if ((Get-Date) -gt $vDeadline) { Show-Tail $ViteErr; Write-Warn "timeout Vite :$VitePort; usando fallback $activeWebUrl"; Stop-Tree $viteProc.Id; $viteProc = $null; break }
                    Start-Sleep -Milliseconds 250
                }
                if ($viteProc) {
                    $activeWebUrl = $FrontendUrl
                    $activeProxyPort = $VitePort
                    Write-Step "Frontend Vite pronto (PID $($viteProc.Id), $FrontendUrl)"
                }
            }
        } else {
            Write-Warn "node.exe ausente; usando fallback $activeWebUrl"
        }
    }

    # 9. Painel de status no terminal
    $udpBanner = if ($Mode -eq 'real') { "UDP 0.0.0.0:$UdpPort (5x ESP32-S3 fisicos)" } else { ":$UdpPort (simulado inproc - sem hardware)" }
    Write-Host ''
    Write-Host '========================================================================' -ForegroundColor Green
    Write-Host '  EdgeSpace - Ecossistema Ativo (100% Offline)' -ForegroundColor Green
    Write-Host '========================================================================' -ForegroundColor Green
    Write-Host ("  Modo          : {0}" -f $modeDesc) -ForegroundColor White
    Write-Host ("  Cenario       : {0}" -f $scenDesc) -ForegroundColor White
    Write-Host ("  SLM Offline   : {0}" -f $slmStatus) -ForegroundColor White
    Write-Host '  ----------------------------------------------------------------------' -ForegroundColor DarkGray
    Write-Host ("  Painel Web    : {0}" -f $activeWebUrl) -ForegroundColor Cyan
    Write-Host ("  Central API   : {0}" -f $CentralUrl) -ForegroundColor Cyan
    Write-Host ("  IPC IA        : {0}" -f $IpcAddr) -ForegroundColor Cyan
    Write-Host ("  Cluster UDP   : {0}" -f $udpBanner) -ForegroundColor Cyan
    Write-Host '  Banco SQLite  : var/edgespace.db' -ForegroundColor Gray
    Write-Host '  ----------------------------------------------------------------------' -ForegroundColor DarkGray
    Write-Host '  Testes rapidos:' -ForegroundColor Yellow
    Write-Host ("    Health      : Invoke-RestMethod {0}" -f $HealthUrl) -ForegroundColor Gray
    Write-Host ("    Cenario     : Invoke-RestMethod -Method Post {0}/api/dev/scenario -Body '{{""scenario"":""hypercapnia""}}' -ContentType application/json" -f $CentralUrl) -ForegroundColor Gray
    Write-Host '    Encerrar    : Pressione Ctrl+C (graceful shutdown)' -ForegroundColor Gray
    Write-Host '========================================================================' -ForegroundColor Green
    Write-Host ''

    if ($SmokeSeconds -gt 0) {
        if ($activeProxyPort -eq $VitePort) {
            $crewRes = Invoke-WebRequest -Uri "http://127.0.0.1:${VitePort}/api/crew" -UseBasicParsing -TimeoutSec 5
            if ([int]$crewRes.StatusCode -ne 200) { throw "Vite proxy /api/crew falhou ($($crewRes.StatusCode))" }
        }
        $aiReady = $false
        $ws = New-Object System.Net.WebSockets.ClientWebSocket
        $ws.Options.SetRequestHeader('Origin', "http://127.0.0.1:$activeProxyPort")
        $cts = New-Object System.Threading.CancellationTokenSource(10000)
        try {
            $null = $ws.ConnectAsync([Uri]"ws://127.0.0.1:$activeProxyPort/ws", $cts.Token).GetAwaiter().GetResult()
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
                if ($frame -match '"ai_ready"\s*:\s*true') { $aiReady = $true }
            }
        } finally {
            try { $ws.Dispose() } catch { }
            $cts.Dispose()
        }
        if (-not $aiReady) { throw "WS /ws (porta $activeProxyPort) nao reportou ai_ready=true" }
        Write-Step "SMOKE OK: /healthz 200 ($body) + Frontend/Proxy (:$activeProxyPort) + /ws ai_ready=true. Mantendo por ${SmokeSeconds}s..."
        Start-Sleep -Seconds $SmokeSeconds
    } else {
        if (-not $NoOpen) {
            Write-Step "abrindo painel no navegador: $activeWebUrl"
            Start-Process $activeWebUrl | Out-Null
        }
        $seenLines = 0
        while (-not $centralProc.HasExited) {
            if (Test-Path $CentralLog) {
                $lines = @(Get-Content $CentralLog -ErrorAction SilentlyContinue)
                if ($lines.Count -gt $seenLines) {
                    for ($i = $seenLines; $i -lt $lines.Count; $i++) {
                        Write-CentralLog ([string]$lines[$i])
                    }
                    $seenLines = $lines.Count
                }
            }
            Start-Sleep -Milliseconds 250
        }
        $exitCode = $centralProc.ExitCode
        Write-Step "Central encerrou (exit $exitCode)"
    }
}
catch {
    Write-Fail "erro: $($_.Exception.Message)"
    $exitCode = 1
}
finally {
    Write-Step 'encerrando stack (graceful shutdown)...'
    if ($viteProc) { Stop-Tree $viteProc.Id }
    $centrals = @()
    if ($centralProc) { $centrals += $centralProc }
    $centrals += @(Get-Process -Name 'edgespace-central' -ErrorAction SilentlyContinue |
                   Where-Object { try { $_.Path -eq $CentralExe } catch { $false } })
    foreach ($p in $centrals) {
        if (-not $p.HasExited) {
            $null = $p.CloseMainWindow()
            $null = $p.WaitForExit(2000)
        }
        Stop-Tree $p.Id
    }
    if ($aiProc) { Stop-Tree $aiProc.Id }
    Clear-Port $UdpPort 'UDP'
    Clear-Port $IpcPort 'TCP'
    Clear-Port $HttpPort 'TCP'
    Clear-Port $VitePort 'TCP'
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:EDGESPACE_DISABLE_SLM -ErrorAction SilentlyContinue
    Remove-Item Env:EDGE_CENTRAL -ErrorAction SilentlyContinue
    Write-Step "portas $UdpPort, $IpcPort, $HttpPort e $VitePort livres. Fim."
}
exit $exitCode