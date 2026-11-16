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
$ToolsDir     = Join-Path $env:LOCALAPPDATA 'edgespace-tools'
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

function Get-RequiredGoVersion {
    $goMod = Join-Path $CentralDir 'go.mod'
    if (Test-Path $goMod) {
        $m = [regex]::Match((Get-Content $goMod -Raw), '(?m)^go\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)')
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return '1.27.4'
}

function Expand-ZipFast([string]$zipPath, [string]$destDir) {
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($tar) {
        & $tar.Source -xf $zipPath -C $destDir
        if ($LASTEXITCODE -eq 0) { return }
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $destDir)
}

function Install-Go([string]$targetVer) {
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
    $goRoot = Join-Path $ToolsDir 'go'
    $goExe = Join-Path $goRoot 'bin\go.exe'
    $zipPath = Join-Path $env:TEMP "edgespace-go-${targetVer}-windows-${arch}.zip"
    $urls = @("https://go.dev/dl/go${targetVer}.windows-${arch}.zip")

    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

    $downloaded = $false
    foreach ($url in $urls) {
        try {
            Write-Step "baixando Go $targetVer ($arch) de $url..."
            Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -TimeoutSec 120
            $downloaded = $true
            break
        } catch { }
    }
    if (-not $downloaded) {
        $releases = Invoke-RestMethod -Uri 'https://go.dev/dl/?mode=json' -UseBasicParsing -TimeoutSec 30
        $file = $releases | Where-Object { $_.stable } | ForEach-Object { $_.files } |
            Where-Object { $_.os -eq 'windows' -and $_.arch -eq $arch -and $_.kind -eq 'archive' } |
            Select-Object -First 1
        if (-not $file) { throw "nenhum pacote Go windows/$arch encontrado em go.dev" }
        $fallbackUrl = "https://go.dev/dl/$($file.filename)"
        Write-Step "baixando Go $($file.version) ($arch) de $fallbackUrl..."
        Invoke-WebRequest -Uri $fallbackUrl -OutFile $zipPath -UseBasicParsing -TimeoutSec 120
    }

    try {
        if (Test-Path $goRoot) { Remove-Item -Recurse -Force $goRoot }
        Write-Step "extraindo Go para $goRoot..."
        Expand-ZipFast $zipPath $ToolsDir
    } finally {
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path $goExe)) { throw "falha ao instalar Go em $goExe" }
    $env:PATH = "$(Split-Path $goExe);$env:PATH"
    return $goExe
}

function Find-Go {
    $reqRaw = Get-RequiredGoVersion
    if ($reqRaw -match '^\d+\.\d+\.\d+$') { $reqVer = [version]$reqRaw } else { $reqVer = [version]"$reqRaw.0" }
    $cmd = Get-Command go -ErrorAction SilentlyContinue
    $candidates = @()
    if ($cmd) { $candidates += $cmd.Source }
    $candidates += @(
        (Join-Path $ToolsDir 'go\bin\go.exe'),
        (Join-Path $env:ProgramFiles 'Go\bin\go.exe'),
        'C:\Go\bin\go.exe',
        (Join-Path $env:LOCALAPPDATA 'go-sdk\go\bin\go.exe')
    )
    $candidates = @($candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)

    $prevEapGo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        foreach ($c in $candidates) {
            $out = (& $c version 2>$null | Select-Object -First 1)
            if ($LASTEXITCODE -eq 0 -and $out -match 'go([0-9]+\.[0-9]+(?:\.[0-9]+)?)') {
                $vStr = if ($Matches[1] -match '^\d+\.\d+\.\d+$') { $Matches[1] } else { "$($Matches[1]).0" }
                if ([version]$vStr -ge $reqVer) {
                    $binDir = Split-Path $c
                    if ($env:PATH -notlike "*$binDir*") { $env:PATH = "$binDir;$env:PATH" }
                    return $c
                }
            }
        }
    } finally {
        $ErrorActionPreference = $prevEapGo
    }
    return (Install-Go $reqRaw)
}

function Install-Python {
    $pyVer = '3.12.8'
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
    $installer = Join-Path $env:TEMP "edgespace-python-${pyVer}-${arch}.exe"
    $url = "https://www.python.org/ftp/python/${pyVer}/python-${pyVer}-${arch}.exe"

    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Step "baixando Python $pyVer ($arch) de $url..."
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -TimeoutSec 120
    try {
        Write-Step "instalando Python $pyVer para o usuario atual..."
        $p = Start-Process -FilePath $installer -ArgumentList @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0') -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "instalador Python retornou exit $($p.ExitCode)" }
    } finally {
        Remove-Item $installer -Force -ErrorAction SilentlyContinue
    }

    $installed = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (-not (Test-Path $installed)) {
        $installed = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe') -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $installed -or -not (Test-Path $installed)) { throw 'Python instalado mas python.exe nao encontrado' }
    $binDir = Split-Path $installed
    if ($env:PATH -notlike "*$binDir*") { $env:PATH = "$binDir;$(Join-Path $binDir 'Scripts');$env:PATH" }
    return $installed
}

function Find-PythonBase {
    $candidates = @(@('python3'), @('python'), @('py', '-3'))
    $localPys = @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe') -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName)
    foreach ($lp in $localPys) { $candidates += ,@($lp) }

    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        foreach ($cand in $candidates) {
            $cmd = Get-Command $cand[0] -ErrorAction SilentlyContinue
            if (-not $cmd) { continue }
            $extraArgs = if ($cand.Count -gt 1) { $cand[1..($cand.Count - 1)] } else { @() }
            $exePath = (& $cmd.Source @extraArgs -c "import sys, venv; assert sys.version_info >= (3, 11); print(sys.executable)" 2>$null | Select-Object -First 1)
            if ($LASTEXITCODE -eq 0 -and $exePath -and (Test-Path $exePath.Trim())) {
                return $exePath.Trim()
            }
        }
    } finally {
        $ErrorActionPreference = $prevEap
    }
    return (Install-Python)
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

function Ensure-EspIdf {
    $idfCmd = Get-Command idf.py -ErrorAction SilentlyContinue
    if ($idfCmd) { return }

    $exportCandidates = @()
    if ($env:IDF_PATH) { $exportCandidates += (Join-Path $env:IDF_PATH 'export.ps1') }
    $exportCandidates += @(
        (Join-Path $ToolsDir 'esp-idf\export.ps1'),
        (Join-Path $env:USERPROFILE 'esp\esp-idf\export.ps1')
    )
    $espressifDirs = @(Get-ChildItem 'C:\Espressif\frameworks\esp-idf-v5*\export.ps1' -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName)
    $exportCandidates += $espressifDirs

    foreach ($exp in $exportCandidates) {
        if ($exp -and (Test-Path $exp)) {
            $env:IDF_PATH = Split-Path $exp
            Write-Step "carregando ambiente ESP-IDF de $env:IDF_PATH"
            . $exp
            if (Get-Command idf.py -ErrorAction SilentlyContinue) { return }
        }
    }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'git nao encontrado no PATH para clonar ESP-IDF' }
        Write-Step 'instalando Git via winget para baixar ESP-IDF...'
        & $winget.Source install --id Git.Git -e --accept-package-agreements --accept-source-agreements --silent
        $git = Get-Command git -ErrorAction SilentlyContinue
        if (-not $git) { $git = Get-Command "$env:ProgramFiles\Git\cmd\git.exe" -ErrorAction SilentlyContinue }
        if (-not $git) { throw 'git instalado mas nao encontrado no PATH' }
    }

    $idfDir = Join-Path $ToolsDir 'esp-idf'
    $env:IDF_TOOLS_PATH = Join-Path $ToolsDir 'espressif'
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

    if (-not (Test-Path (Join-Path $idfDir 'export.ps1'))) {
        Write-Step "clonando ESP-IDF v5.4 em $idfDir..."
        & $git.Source clone --branch v5.4 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git $idfDir
        if ($LASTEXITCODE -ne 0) { throw "git clone esp-idf falhou (exit $LASTEXITCODE)" }
    }

    $env:IDF_PATH = $idfDir
    Write-Step 'instalando toolchain ESP-IDF para esp32s3 (install.ps1 esp32s3)...'
    & (Join-Path $idfDir 'install.ps1') esp32s3
    if ($LASTEXITCODE -ne 0) { throw "esp-idf install.ps1 falhou (exit $LASTEXITCODE)" }

    Write-Step "carregando ambiente ESP-IDF de $idfDir"
    . (Join-Path $idfDir 'export.ps1')
    if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
        throw 'ESP-IDF instalado mas idf.py nao ficou disponivel apos export.ps1'
    }
}

function Invoke-EspFlash {
    if (-not (Test-Path (Join-Path $FirmwareDir 'CMakeLists.txt'))) {
        throw "firmware/CMakeLists.txt ausente em $FirmwareDir"
    }
    Ensure-EspIdf

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

function Ensure-EdgeAiVenv {
    if (-not (Test-Path $PythonExe)) {
        $basePy = Find-PythonBase
        Write-Step "criando venv edge-ai ($basePy)..."
        & $basePy -m venv (Join-Path $EdgeAiDir '.venv')
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $PythonExe)) {
            throw "falha ao criar venv em $EdgeAiDir\.venv"
        }
    }

    $wheelsDir = Join-Path $EdgeAiDir 'wheels'
    $reqFile = Join-Path $EdgeAiDir 'requirements.txt'
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        & $PythonExe -c "import edgespace_ai, onnxruntime, sklearn, skl2onnx, pytest" 2>$null
        if ($LASTEXITCODE -eq 0) { return }

        if ((Test-Path $wheelsDir) -and (Test-Path $reqFile)) {
            Write-Step 'instalando deps edge-ai offline (wheels)...'
            & $PythonExe -m pip install --no-index --find-links $wheelsDir -r $reqFile
            if ($LASTEXITCODE -ne 0) { throw 'falha ao configurar edge-ai/.venv offline' }
            & $PythonExe -m pip install --no-deps --no-build-isolation -e $EdgeAiDir 2>$null
            return
        }

        Write-Step 'instalando deps edge-ai (pip install -e "edge-ai[dev,slm]")...'
        & $PythonExe -m pip install --disable-pip-version-check --prefer-binary `
            --extra-index-url 'https://abetlen.github.io/llama-cpp-python/whl/cpu' `
            -e "${EdgeAiDir}[dev,slm]"
        if ($LASTEXITCODE -ne 0) {
            Write-Warn 'pip install -e edge-ai[dev,slm] falhou; tentando sem [slm] (-e edge-ai[dev])...'
            & $PythonExe -m pip install --disable-pip-version-check --prefer-binary -e "${EdgeAiDir}[dev]"
            if ($LASTEXITCODE -ne 0) { throw "pip install -e edge-ai[dev] falhou (exit $LASTEXITCODE)" }
        }
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Find-Pnpm {
    $cmd = Get-Command pnpm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $localPnpmDir = Join-Path $ToolsDir 'pnpm'
    $candidates = @(
        (Join-Path $localPnpmDir 'node_modules\.bin\pnpm.cmd'),
        (Join-Path $env:LOCALAPPDATA 'pnpm\pnpm.cmd'),
        (Join-Path $env:APPDATA 'npm\pnpm.cmd')
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) {
            $binDir = Split-Path $c
            if ($env:PATH -notlike "*$binDir*") { $env:PATH = "$binDir;$env:PATH" }
            return $c
        }
    }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) { return $null }

    Write-Step "instalando pnpm localmente em $localPnpmDir..."
    New-Item -ItemType Directory -Force -Path $localPnpmDir | Out-Null
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        & $npm.Source install --prefix $localPnpmDir --no-save --no-audit --no-fund pnpm | Out-Null
    } finally {
        $ErrorActionPreference = $prevEap
    }
    $installed = Join-Path $localPnpmDir 'node_modules\.bin\pnpm.cmd'
    if (Test-Path $installed) {
        $binDir = Split-Path $installed
        if ($env:PATH -notlike "*$binDir*") { $env:PATH = "$binDir;$env:PATH" }
        return $installed
    }
    return $null
}

function Ensure-FrontendDeps {
    if (-not (Test-Path (Join-Path $FrontendDir 'package.json'))) { return $false }
    $viteJs = Join-Path $FrontendDir 'node_modules\vite\bin\vite.js'
    if (Test-Path $viteJs) { return $true }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Warn 'node.exe ausente; pulando setup de frontend.'
        return $false
    }

    $pnpmExe = Find-Pnpm
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    Push-Location $FrontendDir
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        if ($pnpmExe) {
            & $pnpmExe install --offline --frozen-lockfile 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Step 'instalando deps do frontend (pnpm install --frozen-lockfile)...'
                & $pnpmExe install --frozen-lockfile
            }
            if ($LASTEXITCODE -eq 0 -and (Test-Path (Join-Path $FrontendDir 'node_modules'))) { return $true }
        }
        if ($npmCmd) {
            Write-Step 'instalando deps do frontend (npm)...'
            & $npmCmd.Source install --no-package-lock --no-audit --no-fund
            if ($LASTEXITCODE -eq 0 -and (Test-Path (Join-Path $FrontendDir 'node_modules'))) { return $true }
        }
    } finally {
        $ErrorActionPreference = $prevEap
        Pop-Location
    }
    return $false
}

function Sync-Frontend {
    $pkg = Join-Path $FrontendDir 'package.json'
    $uiIndex = Join-Path $UiTargetDir 'index.html'
    if (-not (Test-Path $pkg)) {
        Write-Warn 'frontend/package.json ausente; mantendo UI embarcada atual.'
        return
    }
    $null = Ensure-FrontendDeps
    $pnpmExe = Find-Pnpm
    $npm  = Get-Command npm  -ErrorAction SilentlyContinue
    $nodeModules = Join-Path $FrontendDir 'node_modules'

    $built = $false
    Push-Location $FrontendDir
    try {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        if ($pnpmExe -and (Test-Path $nodeModules)) {
            Write-Step 'compilando frontend (pnpm run build)'
            & $pnpmExe run build
            if ($LASTEXITCODE -eq 0) { $built = $true }
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
$pushedRoot = $false
$exitCode = 0

try {
    Push-Location $Root
    $pushedRoot = $true

    if ($Flash -or $FlashOnly) {
        Invoke-EspFlash
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
    Ensure-EdgeAiVenv

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

    # 5. Frontend deps + Central Go (build + frontend estatico apenas se -StaticUi)
    if ($StaticUi) {
        if (-not $NoBuild) { Sync-Frontend }
    } else {
        $null = Ensure-FrontendDeps
    }
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
            if (-not (Test-Path $viteJs)) { $null = Ensure-FrontendDeps }
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
    Write-Fail "erro: $($_.Exception.Message) (linha $($_.InvocationInfo.ScriptLineNumber))"
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
    if ($pushedRoot) { Pop-Location }
    Write-Step "portas $UdpPort, $IpcPort, $HttpPort e $VitePort livres. Fim."
}
exit $exitCode