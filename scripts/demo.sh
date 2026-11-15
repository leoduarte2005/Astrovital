#!/usr/bin/env bash
# EdgeSpace One-Command Demo (Linux / Orange Pi 4 Pro ARM64 / WSL).
# Sobe todo o ecossistema: Frontend + Central Go + Edge AI + SQLite + ESP32-S3 (opcional).
#
# Uso:
#   ./scripts/demo.sh --mock
#   ./scripts/demo.sh --mock --scenario hypercapnia --no-slm
#   ./scripts/demo.sh --real --flash
#   ./scripts/demo.sh --real --no-open
#   ./scripts/demo.sh --mock --no-open --smoke-seconds 5

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CENTRAL_DIR="$ROOT/central"
EDGE_AI_DIR="$ROOT/edge-ai"
FRONTEND_DIR="$ROOT/frontend"
FIRMWARE_DIR="$ROOT/firmware"
UI_TARGET_DIR="$CENTRAL_DIR/internal/httpws/ui"
MODELS_DIR="$EDGE_AI_DIR/models"
VAR_DIR="$ROOT/var"
BUILD_DIR="$ROOT/build"
CENTRAL_BIN="$BUILD_DIR/edgespace-central"
PYTHON_BIN="$EDGE_AI_DIR/.venv/bin/python"
DB_PATH="$VAR_DIR/edgespace.db"
AI_LOG="$VAR_DIR/edge-ai.log"
CENTRAL_LOG="$VAR_DIR/central.log"
VITE_LOG="$VAR_DIR/vite.log"

MODE="mock"
FLASH=0
FLASH_ONLY=0
NO_SLM=0
STATIC_UI=0
NO_OPEN=0
NO_BUILD=0
SCENARIO=""
PORT=""
HTTP_ADDR=""
IPC_ADDR="127.0.0.1:5006"
UDP_ADDR=":5005"
VITE_PORT=5173
LOG_LEVEL="info"
SMOKE_SECONDS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mock)              MODE="mock"; shift ;;
        --real)              MODE="real"; shift ;;
        --mode)              MODE="${2:-mock}"; shift 2 ;;
        --mode=*)            MODE="${1#*=}"; shift ;;
        --flash)             FLASH=1; shift ;;
        --flash-only)        FLASH=1; FLASH_ONLY=1; shift ;;
        --no-slm)            NO_SLM=1; shift ;;
        --static-ui)         STATIC_UI=1; shift ;;
        --no-open)           NO_OPEN=1; shift ;;
        --no-build)          NO_BUILD=1; shift ;;
        --scenario|-s)       SCENARIO="${2:-}"; shift 2 ;;
        --scenario=*)        SCENARIO="${1#*=}"; shift ;;
        --port|-p)           PORT="${2:-}"; shift 2 ;;
        --port=*)            PORT="${1#*=}"; shift ;;
        --http-addr)         HTTP_ADDR="${2:-}"; shift 2 ;;
        --http-addr=*)       HTTP_ADDR="${1#*=}"; shift ;;
        --ipc-addr)          IPC_ADDR="${2:-}"; shift 2 ;;
        --ipc-addr=*)        IPC_ADDR="${1#*=}"; shift ;;
        --udp-addr)          UDP_ADDR="${2:-}"; shift 2 ;;
        --udp-addr=*)        UDP_ADDR="${1#*=}"; shift ;;
        --vite-port)         VITE_PORT="${2:-5173}"; shift 2 ;;
        --vite-port=*)       VITE_PORT="${1#*=}"; shift ;;
        --log-level)         LOG_LEVEL="${2:-info}"; shift 2 ;;
        --log-level=*)       LOG_LEVEL="${1#*=}"; shift ;;
        --smoke-seconds)     SMOKE_SECONDS="${2:-0}"; shift 2 ;;
        --smoke-seconds=*)   SMOKE_SECONDS="${1#*=}"; shift ;;
        -h|--help)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "[demo] flag desconhecida: $1" >&2
            exit 2
            ;;
    esac
done

case "$MODE" in
    mock|real) ;;
    *) echo "[demo] --mode invalido: '$MODE' (use mock|real)" >&2; exit 2 ;;
esac

case "$SCENARIO" in
    ""|nominal|hypercapnia|sans|solar_storm|dehydration_sleep|node_loss) ;;
    *) echo "[demo] cenario invalido: '$SCENARIO' (use nominal|hypercapnia|sans|solar_storm|dehydration_sleep|node_loss)" >&2; exit 2 ;;
esac

if [[ -z "$HTTP_ADDR" ]]; then
    if [[ "$MODE" == "real" ]]; then HTTP_ADDR=":8000"; else HTTP_ADDR="127.0.0.1:8000"; fi
fi
EFFECTIVE_SCENARIO=""
if [[ "$SCENARIO" != "nominal" ]]; then
    EFFECTIVE_SCENARIO="$SCENARIO"
fi

IPC_PORT="${IPC_ADDR##*:}"
HTTP_PORT="${HTTP_ADDR##*:}"
UDP_PORT="${UDP_ADDR##*:}"
HEALTH_URL="http://127.0.0.1:${HTTP_PORT}/healthz"
CENTRAL_URL="http://127.0.0.1:${HTTP_PORT}"
FRONTEND_URL="http://localhost:${VITE_PORT}/#/crew"
MODELS=(posture_cls.onnx exercise_cadence.onnx vitals_reg.onnx baseline_ae_default.onnx isolation_forest.onnx)

AI_PID=""
CENTRAL_PID=""
VITE_PID=""
TAIL_PID=""
CLEANED=0

step() { printf '\033[36m[demo]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[demo]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[demo]\033[0m %s\n' "$*" >&2; }

tcp_pids() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    elif command -v fuser >/dev/null 2>&1; then
        fuser -n tcp "$port" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' || true
    elif command -v ss >/dev/null 2>&1; then
        ss -lptn "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true
    fi
}

udp_pids() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -tiUDP:"$port" 2>/dev/null || true
    elif command -v fuser >/dev/null 2>&1; then
        fuser -n udp "$port" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' || true
    elif command -v ss >/dev/null 2>&1; then
        ss -ulpn "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true
    fi
}

clear_port() {
    local proto="$1" port="$2" pids
    if [[ "$proto" == "UDP" ]]; then pids="$(udp_pids "$port")"; else pids="$(tcp_pids "$port")"; fi
    if [[ -n "$pids" ]]; then
        warn "porta ${proto}/${port} ocupada por PID(s): $(echo "$pids" | tr '\n' ' ') - encerrando"
        # shellcheck disable=SC2086
        kill -TERM $pids 2>/dev/null || true
        sleep 0.5
        if [[ "$proto" == "UDP" ]]; then pids="$(udp_pids "$port")"; else pids="$(tcp_pids "$port")"; fi
        if [[ -n "$pids" ]]; then
            # shellcheck disable=SC2086
            kill -KILL $pids 2>/dev/null || true
            sleep 0.3
        fi
    fi
}

port_open() {
    local port="$1"
    "$PYTHON_BIN" - "$port" <<'PY' >/dev/null 2>&1
import socket, sys
s = socket.socket()
s.settimeout(0.3)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
}

detect_esp_ports() {
    if [[ -n "$PORT" ]]; then
        echo "$PORT"
        return 0
    fi
    local found=() p
    shopt -s nullglob
    for p in /dev/ttyACM* /dev/ttyUSB*; do
        found+=("$p")
    done
    shopt -u nullglob
    printf '%s\n' "${found[@]}"
}

flash_esp() {
    [[ -f "$FIRMWARE_DIR/CMakeLists.txt" ]] || { fail "firmware/CMakeLists.txt ausente"; exit 1; }
    if ! command -v idf.py >/dev/null 2>&1; then
        if [[ -n "${IDF_PATH:-}" ]] && [[ -f "$IDF_PATH/export.sh" ]]; then
            step "carregando ambiente ESP-IDF de $IDF_PATH"
            # shellcheck disable=SC1091
            source "$IDF_PATH/export.sh" >/dev/null 2>&1
        fi
    fi
    command -v idf.py >/dev/null 2>&1 || { fail "idf.py nao encontrado. Rode 'source \$IDF_PATH/export.sh' antes."; exit 1; }

    mapfile -t PORTS < <(detect_esp_ports)
    if [[ "${#PORTS[@]}" -eq 0 ]]; then
        fail "nenhuma porta serial (/dev/ttyACM* ou /dev/ttyUSB*) detectada. Conecte via USB ou use --port."
        exit 1
    fi
    step "portas seriais detectadas: ${PORTS[*]}"

    (
        cd "$FIRMWARE_DIR"
        step "compilando firmware homogeneo ESP32-S3 (idf.py set-target esp32s3 build)"
        idf.py set-target esp32s3 build
        for p in "${PORTS[@]}"; do
            step "gravando firmware em $p (idf.py -p $p flash)..."
            idf.py -p "$p" flash
        done
    )
    step "firmware gravado com sucesso em ${#PORTS[@]} placa(s)."
}

sync_frontend() {
    if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
        warn "frontend/package.json ausente; mantendo UI embarcada atual."
        return 0
    fi
    local built=0
    (
        cd "$FRONTEND_DIR"
        if command -v pnpm >/dev/null 2>&1; then
            if [[ ! -d node_modules ]]; then
                step "instalando deps do frontend offline (pnpm install --offline --frozen-lockfile)"
                pnpm install --offline --frozen-lockfile >/dev/null 2>&1 || true
            fi
            if [[ -d node_modules ]] && pnpm run build; then
                built=1
            fi
        elif command -v npm >/dev/null 2>&1 && [[ -d node_modules ]]; then
            step "compilando frontend (npm run build)"
            if npm run build; then built=1; fi
        else
            warn "pnpm/node_modules indisponiveis; usando fallback da UI embarcada."
        fi
        exit $(( built == 1 ? 0 : 1 ))
    ) && built=1 || built=0

    if [[ "$built" -eq 1 ]] && [[ -f "$FRONTEND_DIR/dist/index.html" ]]; then
        rm -rf "$UI_TARGET_DIR"
        mkdir -p "$UI_TARGET_DIR"
        cp -r "$FRONTEND_DIR/dist/." "$UI_TARGET_DIR/"
        step "frontend dist/ sincronizado em central/internal/httpws/ui/"
    elif [[ -f "$UI_TARGET_DIR/index.html" ]]; then
        warn "mantendo UI embarcada existente em central/internal/httpws/ui/"
    else
        fail "nenhum frontend compilado nem fallback em central/internal/httpws/ui/index.html"
        exit 1
    fi
}

cleanup() {
    [[ "$CLEANED" -eq 1 ]] && return
    CLEANED=1
    step "encerrando stack (graceful shutdown)..."
    for pid in "$TAIL_PID" "$VITE_PID" "$CENTRAL_PID" "$AI_PID"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$VITE_PID" "$CENTRAL_PID" "$AI_PID"; do
        if [[ -n "$pid" ]]; then
            for _ in {1..20}; do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.1
            done
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done
    clear_port UDP "$UDP_PORT"
    clear_port TCP "$IPC_PORT"
    clear_port TCP "$HTTP_PORT"
    clear_port TCP "$VITE_PORT"
    step "portas $UDP_PORT, $IPC_PORT, $HTTP_PORT e $VITE_PORT livres. Fim."
}
trap cleanup EXIT INT TERM

cd "$ROOT"

if [[ "$FLASH" -eq 1 ]]; then
    flash_esp
    if [[ "$FLASH_ONLY" -eq 1 ]]; then exit 0; fi
fi

if [[ "$MODE" == "real" ]]; then
    MODE_DESC="HARDWARE REAL (UDP ${UDP_ADDR}, mock-cluster=false)"
    CLUSTER_FLAG="false"
else
    MODE_DESC="MOCK (5x ESP32-S3 em memoria, mock-cluster=inproc)"
    CLUSTER_FLAG="inproc"
fi
SCEN_DESC="${SCENARIO:-nominal}"
step "raiz: $ROOT"
step "modo: $MODE_DESC | IPC: $IPC_ADDR | Central: $HTTP_ADDR | Vite: :$VITE_PORT | cenario: $SCEN_DESC"

# 1. Limpeza preventiva de portas
step "limpando portas preventivamente (UDP/$UDP_PORT, TCP/$IPC_PORT, TCP/$HTTP_PORT, TCP/$VITE_PORT)"
clear_port UDP "$UDP_PORT"
clear_port TCP "$IPC_PORT"
clear_port TCP "$HTTP_PORT"
clear_port TCP "$VITE_PORT"

# 2. Venv Python Edge AI
if [[ ! -x "$PYTHON_BIN" ]]; then
    if [[ -d "$EDGE_AI_DIR/wheels" ]] && [[ -f "$EDGE_AI_DIR/requirements.txt" ]]; then
        step "criando venv edge-ai offline..."
        python3 -m venv "$EDGE_AI_DIR/.venv"
        "$PYTHON_BIN" -m pip install --no-index --find-links "$EDGE_AI_DIR/wheels" -r "$EDGE_AI_DIR/requirements.txt"
    else
        fail "venv ausente: $PYTHON_BIN (rode: make edge-ai-setup)"
        exit 1
    fi
fi

# 3. Migracao SQLite
mkdir -p "$VAR_DIR"
step "aplicando migrations SQLite (var/edgespace.db)"
"$PYTHON_BIN" "$ROOT/database/tools/operational.py" migrate --db "$DB_PATH" \
    || { fail "migrate falhou"; exit 1; }

# 4. Modelos .onnx + SLM
MISSING=()
for m in "${MODELS[@]}"; do
    [[ -f "$MODELS_DIR/$m" ]] || MISSING+=("$m")
done
if [[ "${#MISSING[@]}" -gt 0 ]]; then
    warn "modelos ausentes (${MISSING[*]}) - executando build_all_models.py"
    "$PYTHON_BIN" "$EDGE_AI_DIR/training/build_all_models.py"
else
    step "modelos .onnx OK (${#MODELS[@]}/${#MODELS[@]})"
fi

SLM_STATUS="ATIVO"
if [[ "$NO_SLM" -eq 1 ]]; then
    warn "--no-slm: SLM desativado (apenas ONNX + Grafo Causal SQLite)"
    export EDGESPACE_DISABLE_SLM=1
    SLM_STATUS="DESATIVADO (--no-slm)"
else
    if ! "$PYTHON_BIN" -c 'import llama_cpp' >/dev/null 2>&1; then
        warn "llama-cpp-python ausente - tentando wheel CPU..."
        "$PYTHON_BIN" -m pip install --disable-pip-version-check --prefer-binary \
            --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu 'llama-cpp-python>=0.3.0' \
            || { warn "llama-cpp-python indisponivel; seguindo com template deterministico"; SLM_STATUS="FALLBACK (template deterministico)"; }
    fi
    if ! PYTHONPATH="$EDGE_AI_DIR/src" "$PYTHON_BIN" -m edgespace_ai.utils.model_fetch --models-dir "$MODELS_DIR" --check >/dev/null 2>&1; then
        warn "modelo SLM ausente - tentando model_fetch..."
        PYTHONPATH="$EDGE_AI_DIR/src" "$PYTHON_BIN" -m edgespace_ai.utils.model_fetch --models-dir "$MODELS_DIR" \
            || { warn "modelo SLM indisponivel; seguindo com template deterministico"; SLM_STATUS="FALLBACK (template deterministico)"; }
    else
        step "modelo SLM OK ($MODELS_DIR/slm)"
    fi
fi

# 5. Central Go (frontend estatico apenas se --static-ui)
if [[ "$NO_BUILD" -eq 0 ]] && [[ "$STATIC_UI" -eq 1 ]]; then
    sync_frontend
fi

if [[ "$NO_BUILD" -eq 1 ]]; then
    [[ -x "$CENTRAL_BIN" ]] || { fail "--no-build mas $CENTRAL_BIN nao existe"; exit 1; }
    step "--no-build: usando $CENTRAL_BIN"
else
    step "compilando Central Go -> $CENTRAL_BIN"
    mkdir -p "$BUILD_DIR"
    (cd "$CENTRAL_DIR" && CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o "$CENTRAL_BIN" ./cmd/edgespace-central) \
        || { fail "Central build falhou"; exit 1; }
fi

# 6. Subida encadeada: Edge AI (:5006)
step "subindo Edge AI em $IPC_ADDR..."
(
    cd "$EDGE_AI_DIR"
    PYTHONPATH=src PYTHONUNBUFFERED=1 exec "$PYTHON_BIN" -m edgespace_ai \
        --listen "$IPC_ADDR" --db "$DB_PATH" --models-dir "$MODELS_DIR"
) >"$AI_LOG" 2>&1 &
AI_PID=$!

for _ in {1..120}; do
    if port_open "$IPC_PORT"; then break; fi
    if ! kill -0 "$AI_PID" 2>/dev/null; then
        fail "Edge AI encerrou prematuramente:"
        tail -n 20 "$AI_LOG" >&2 || true
        exit 1
    fi
    sleep 0.25
done
port_open "$IPC_PORT" || { fail "timeout aguardando porta $IPC_PORT"; tail -n 20 "$AI_LOG" >&2 || true; exit 1; }
step "Edge AI pronto (PID $AI_PID, TCP/$IPC_PORT aberto)"

# 7. Subida encadeada: Central Go (:8000 / :5005)
CENTRAL_ARGS=(
    "-mock-cluster=$CLUSTER_FLAG"
    "-udp-addr=$UDP_ADDR"
    "-ipc-addr=$IPC_ADDR"
    "-http-addr=$HTTP_ADDR"
    "-db=var/edgespace.db"
    "-migrations=database/migrations"
    "-log-level=$LOG_LEVEL"
)
[[ -n "$EFFECTIVE_SCENARIO" ]] && CENTRAL_ARGS+=("-scenario=$EFFECTIVE_SCENARIO")

: > "$CENTRAL_LOG"
step "subindo Central Go ($CENTRAL_BIN ${CENTRAL_ARGS[*]})..."
"$CENTRAL_BIN" "${CENTRAL_ARGS[@]}" >"$CENTRAL_LOG" 2>&1 &
CENTRAL_PID=$!

BODY=""
for _ in {1..50}; do
    kill -0 "$CENTRAL_PID" 2>/dev/null || { fail "Central morreu"; tail -n 20 "$CENTRAL_LOG" >&2; exit 1; }
    if BODY="$(curl -fsS --max-time 2 "$HEALTH_URL" 2>/dev/null)"; then break; fi
    sleep 0.3
done
[[ -n "$BODY" ]] || { fail "Healthcheck falhou em $HEALTH_URL"; tail -n 20 "$CENTRAL_LOG" >&2; exit 1; }

# 8. Subida encadeada: Frontend Vite (:5173) conectado a Central Go (:8000)
ACTIVE_WEB_URL="${CENTRAL_URL}/#/crew"
ACTIVE_PROXY_PORT="$HTTP_PORT"
if [[ "$STATIC_UI" -eq 0 ]] && [[ -f "$FRONTEND_DIR/package.json" ]] && command -v node >/dev/null 2>&1; then
    VITE_BIN="$FRONTEND_DIR/node_modules/vite/bin/vite.js"
    if [[ ! -f "$VITE_BIN" ]]; then
        step "instalando dependencias do frontend..."
        (
            cd "$FRONTEND_DIR"
            if command -v pnpm >/dev/null 2>&1; then
                pnpm install --offline --frozen-lockfile || pnpm install --frozen-lockfile
            elif command -v npm >/dev/null 2>&1; then
                npm install --no-package-lock --no-audit --no-fund
            fi
        ) || warn "falha ao instalar deps do frontend"
    fi
    if [[ -f "$VITE_BIN" ]]; then
        step "subindo Frontend Vite em :$VITE_PORT (EDGE_CENTRAL=$CENTRAL_URL)..."
        : > "$VITE_LOG"
        (
            cd "$FRONTEND_DIR"
            EDGE_CENTRAL="$CENTRAL_URL" exec node "$VITE_BIN" --host --port "$VITE_PORT" --strictPort
        ) >"$VITE_LOG" 2>&1 &
        VITE_PID=$!
        for _ in {1..60}; do
            if port_open "$VITE_PORT"; then break; fi
            if ! kill -0 "$VITE_PID" 2>/dev/null; then
                warn "Vite encerrou prematuramente:"
                tail -n 20 "$VITE_LOG" >&2 || true
                VITE_PID=""
                break
            fi
            sleep 0.25
        done
        if [[ -n "$VITE_PID" ]] && port_open "$VITE_PORT"; then
            ACTIVE_WEB_URL="$FRONTEND_URL"
            ACTIVE_PROXY_PORT="$VITE_PORT"
            step "Frontend Vite pronto (PID $VITE_PID, $FRONTEND_URL)"
        fi
    fi
fi

# 9. Painel de status
if [[ "$MODE" == "real" ]]; then
    UDP_BANNER="UDP 0.0.0.0:${UDP_PORT} (5x ESP32-S3 fisicos)"
else
    UDP_BANNER=":${UDP_PORT} (simulado inproc - sem hardware)"
fi

printf '\n'
printf '\033[32m========================================================================\033[0m\n'
printf '\033[32m  EdgeSpace - Ecossistema Ativo (100%% Offline)\033[0m\n'
printf '\033[32m========================================================================\033[0m\n'
printf '  Modo          : %s\n' "$MODE_DESC"
printf '  Cenario       : %s\n' "$SCEN_DESC"
printf '  SLM Offline   : %s\n' "$SLM_STATUS"
printf '  ----------------------------------------------------------------------\n'
printf '  Painel Web    : %s\n' "$ACTIVE_WEB_URL"
printf '  Central API   : %s\n' "$CENTRAL_URL"
printf '  IPC IA        : %s\n' "$IPC_ADDR"
printf '  Cluster UDP   : %s\n' "$UDP_BANNER"
printf '  Banco SQLite  : var/edgespace.db\n'
printf '  ----------------------------------------------------------------------\n'
printf '  Testes rapidos:\n'
printf '    Health      : curl %s\n' "$HEALTH_URL"
printf '    Cenario     : curl -X POST %s/api/dev/scenario -d '\''{"scenario":"hypercapnia"}'\''\n' "$CENTRAL_URL"
printf '    Encerrar    : Pressione Ctrl+C (graceful shutdown)\n'
printf '\033[32m========================================================================\033[0m\n\n'

if [[ "$SMOKE_SECONDS" -gt 0 ]]; then
    if [[ "$ACTIVE_PROXY_PORT" -eq "$VITE_PORT" ]]; then
        curl -fsS --max-time 5 "http://127.0.0.1:${VITE_PORT}/api/crew" >/dev/null \
            || { fail "Vite proxy /api/crew falhou"; tail -n 20 "$VITE_LOG" >&2; exit 1; }
    fi
    WS_FRAME="$("$PYTHON_BIN" - "$ACTIVE_PROXY_PORT" <<'PY'
import base64, os, socket, struct, sys, time
port = int(sys.argv[1])
s = socket.create_connection(("127.0.0.1", port), timeout=5)
key = base64.b64encode(os.urandom(16)).decode()
req = (f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
       f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
       f"Origin: http://127.0.0.1:{port}\r\n\r\n")
s.sendall(req.encode())
buf = b""
while b"\r\n\r\n" not in buf:
    buf += s.recv(4096)
rem = buf.split(b"\r\n\r\n", 1)[1]
def rbytes(n):
    global rem
    while len(rem) < n:
        rem += s.recv(4096)
    out, rem = rem[:n], rem[n:]
    return out
deadline = time.time() + 8
while time.time() < deadline:
    b1, b2 = rbytes(2)
    ln = b2 & 0x7F
    if ln == 126: ln = struct.unpack(">H", rbytes(2))[0]
    elif ln == 127: ln = struct.unpack(">Q", rbytes(8))[0]
    if b2 & 0x80: rbytes(4)
    data = rbytes(ln)
    if (b1 & 0x0F) == 1:
        txt = data.decode("utf-8", "replace")
        if '"ai_ready":true' in txt.replace(" ", ""):
            print(txt); sys.exit(0)
sys.exit(1)
PY
)" || { fail "WS /ws (porta $ACTIVE_PROXY_PORT) nao reportou ai_ready=true"; tail -n 20 "$CENTRAL_LOG" >&2; exit 1; }
    step "SMOKE OK: /healthz 200 ($BODY) + Frontend/Proxy (:$ACTIVE_PROXY_PORT) + /ws ai_ready=true. Mantendo por ${SMOKE_SECONDS}s..."
    sleep "$SMOKE_SECONDS"
else
    if [[ "$NO_OPEN" -eq 0 ]]; then
        if command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
            step "abrindo painel no navegador: $ACTIVE_WEB_URL"
            xdg-open "$ACTIVE_WEB_URL" >/dev/null 2>&1 &
        else
            warn "ambiente headless/sem xdg-open; acesse manualmente: $ACTIVE_WEB_URL"
        fi
    fi
    tail -n +1 -f "$CENTRAL_LOG" &
    TAIL_PID=$!
    wait "$CENTRAL_PID"
fi