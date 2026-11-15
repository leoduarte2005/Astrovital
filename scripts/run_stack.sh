#!/usr/bin/env bash
# EdgeSpace - sobe a stack completa (edge-ai :5006 + Central Go :8000) com um comando.
# Alvo: Linux / Orange Pi 4 Pro (ARM64) ou WSL.
#
# Uso:
#   ./scripts/run_stack.sh
#   ./scripts/run_stack.sh --scenario hypercapnia
#   ./scripts/run_stack.sh --real-cluster --http-addr :8000
#   ./scripts/run_stack.sh --no-build --smoke-seconds 5

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CENTRAL_DIR="$ROOT/central"
EDGE_AI_DIR="$ROOT/edge-ai"
MODELS_DIR="$EDGE_AI_DIR/models"
VAR_DIR="$ROOT/var"
BUILD_DIR="$ROOT/build"
CENTRAL_BIN="$BUILD_DIR/edgespace-central"
PYTHON_BIN="$EDGE_AI_DIR/.venv/bin/python"
DB_PATH="$VAR_DIR/edgespace.db"
AI_LOG="$VAR_DIR/edge-ai.log"
CENTRAL_LOG="$VAR_DIR/central.log"

SCENARIO=""
NO_BUILD=0
REAL_CLUSTER=0
HTTP_ADDR="127.0.0.1:8000"
IPC_ADDR="127.0.0.1:5006"
LOG_LEVEL="info"
SMOKE_SECONDS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --scenario|-s)       SCENARIO="${2:-}"; shift 2 ;;
        --scenario=*)        SCENARIO="${1#*=}"; shift ;;
        --no-build)          NO_BUILD=1; shift ;;
        --real-cluster)      REAL_CLUSTER=1; shift ;;
        --http-addr)         HTTP_ADDR="${2:-}"; shift 2 ;;
        --http-addr=*)       HTTP_ADDR="${1#*=}"; shift ;;
        --ipc-addr)          IPC_ADDR="${2:-}"; shift 2 ;;
        --ipc-addr=*)        IPC_ADDR="${1#*=}"; shift ;;
        --log-level)         LOG_LEVEL="${2:-}"; shift 2 ;;
        --log-level=*)       LOG_LEVEL="${1#*=}"; shift ;;
        --smoke-seconds)     SMOKE_SECONDS="${2:-0}"; shift 2 ;;
        --smoke-seconds=*)   SMOKE_SECONDS="${1#*=}"; shift ;;
        -h|--help)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "[run_stack] flag desconhecida: $1" >&2
            exit 2
            ;;
    esac
done

case "$SCENARIO" in
    ""|hypercapnia|sans|solar_storm|dehydration_sleep|node_loss) ;;
    *) echo "[run_stack] scenario invalido: '$SCENARIO' (use hypercapnia|sans|solar_storm|dehydration_sleep|node_loss)" >&2; exit 2 ;;
esac

IPC_PORT="${IPC_ADDR##*:}"
HTTP_PORT="${HTTP_ADDR##*:}"
HEALTH_URL="http://127.0.0.1:${HTTP_PORT}/healthz"
MODELS=(posture_cls.onnx exercise_cadence.onnx vitals_reg.onnx baseline_ae_default.onnx isolation_forest.onnx)

AI_PID=""
CENTRAL_PID=""
CLEANED=0

step() { printf '\033[36m[run_stack]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[run_stack]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[run_stack]\033[0m %s\n' "$*" >&2; }

port_pids() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    elif command -v fuser >/dev/null 2>&1; then
        fuser -n tcp "$port" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' || true
    elif command -v ss >/dev/null 2>&1; then
        ss -lptn "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true
    fi
}

clear_port() {
    local port="$1" pids
    pids="$(port_pids "$port")"
    if [[ -n "$pids" ]]; then
        warn "porta $port ocupada por PID(s): $(echo "$pids" | tr '\n' ' ') - encerrando"
        # shellcheck disable=SC2086
        kill -TERM $pids 2>/dev/null || true
        sleep 0.5
        pids="$(port_pids "$port")"
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

cleanup() {
    [[ "$CLEANED" -eq 1 ]] && return
    CLEANED=1
    step "encerrando stack..."
    for pid in "$CENTRAL_PID" "$AI_PID"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$CENTRAL_PID" "$AI_PID"; do
        if [[ -n "$pid" ]]; then
            for _ in {1..20}; do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.1
            done
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done
    clear_port "$IPC_PORT"
    clear_port "$HTTP_PORT"
    step "portas $IPC_PORT e $HTTP_PORT livres. Fim."
}
trap cleanup EXIT INT TERM

cd "$ROOT"
if [[ "$REAL_CLUSTER" -eq 1 ]]; then
    MODE_DESC="HARDWARE REAL (UDP :5005, mock-cluster=false)"
    CLUSTER_FLAG="false"
else
    MODE_DESC="SIMULADO (mock-cluster=inproc)"
    CLUSTER_FLAG="inproc"
fi
step "raiz: $ROOT"
step "modo: $MODE_DESC | IA: $IPC_ADDR | HTTP: $HTTP_ADDR | scenario: ${SCENARIO:-(nenhum)}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    fail "venv ausente: $PYTHON_BIN (rode: make edge-ai-setup)"
    exit 1
fi

# 1. portas
step "limpando portas $IPC_PORT e $HTTP_PORT"
clear_port "$IPC_PORT"
clear_port "$HTTP_PORT"

# 2. modelos .onnx
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

# 3. build Go
if [[ "$NO_BUILD" -eq 1 ]]; then
    [[ -x "$CENTRAL_BIN" ]] || { fail "--no-build mas $CENTRAL_BIN nao existe"; exit 1; }
    step "--no-build: usando $CENTRAL_BIN"
else
    step "compilando Central Go -> $CENTRAL_BIN"
    mkdir -p "$BUILD_DIR"
    (cd "$CENTRAL_DIR" && CGO_ENABLED=0 go build -o "$CENTRAL_BIN" ./cmd/edgespace-central)
fi

# Schema must be ready before the read-only worker opens SQLite.
"$PYTHON_BIN" "$ROOT/database/tools/operational.py" migrate --db "$DB_PATH"

# 4. worker IA em background
mkdir -p "$VAR_DIR"
step "subindo edge-ai em $IPC_ADDR (log: var/edge-ai.log)"
(
    cd "$EDGE_AI_DIR"
    PYTHONPATH=src PYTHONUNBUFFERED=1 exec "$PYTHON_BIN" -m edgespace_ai \
        --listen "$IPC_ADDR" --db "$DB_PATH" --models-dir "$MODELS_DIR"
) >"$AI_LOG" 2>&1 &
AI_PID=$!

for _ in {1..120}; do
    if port_open "$IPC_PORT"; then break; fi
    if ! kill -0 "$AI_PID" 2>/dev/null; then
        fail "edge-ai encerrou prematuramente. Ultimas linhas:"
        tail -n 20 "$AI_LOG" >&2 || true
        exit 1
    fi
    sleep 0.25
done
port_open "$IPC_PORT" || { fail "timeout aguardando porta $IPC_PORT"; tail -n 20 "$AI_LOG" >&2 || true; exit 1; }
step "edge-ai pronto (PID $AI_PID, porta $IPC_PORT aberta)"

# 5. Central Go (sem --mock-ai)
CENTRAL_ARGS=(
    "-mock-cluster=$CLUSTER_FLAG"
    "-ipc-addr=$IPC_ADDR"
    "-http-addr=$HTTP_ADDR"
    "-db=var/edgespace.db"
    "-migrations=database/migrations"
    "-log-level=$LOG_LEVEL"
)
[[ -n "$SCENARIO" ]] && CENTRAL_ARGS+=("-scenario=$SCENARIO")
step "subindo Central: build/edgespace-central ${CENTRAL_ARGS[*]}"

if [[ "$SMOKE_SECONDS" -gt 0 ]]; then
    "$CENTRAL_BIN" "${CENTRAL_ARGS[@]}" >"$CENTRAL_LOG" 2>&1 &
    CENTRAL_PID=$!
    BODY=""
    for _ in {1..40}; do
        kill -0 "$CENTRAL_PID" 2>/dev/null || { fail "Central morreu"; tail -n 20 "$CENTRAL_LOG" >&2; exit 1; }
        if BODY="$(curl -fsS --max-time 2 "$HEALTH_URL" 2>/dev/null)"; then break; fi
        sleep 0.3
    done
    [[ -n "$BODY" ]] || { fail "GET $HEALTH_URL falhou"; tail -n 20 "$CENTRAL_LOG" >&2; exit 1; }
    step "GET $HEALTH_URL -> 200 $BODY"

    # Valida ai_ready=true via WebSocket (stdlib Python, zero deps externas)
    WS_FRAME="$("$PYTHON_BIN" - "$HTTP_PORT" <<'PY'
import base64, json, os, socket, struct, sys, time
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
)" || { fail "WS /ws nao reportou ai_ready=true"; tail -n 20 "$CENTRAL_LOG" >&2; exit 1; }
    step "WS /ws ai_ready=true: $WS_FRAME"
    step "SMOKE OK. Mantendo por ${SMOKE_SECONDS}s..."
    sleep "$SMOKE_SECONDS"
else
    step "Central no ar: http://127.0.0.1:${HTTP_PORT}  (Ctrl+C encerra tudo)"
    "$CENTRAL_BIN" "${CENTRAL_ARGS[@]}" &
    CENTRAL_PID=$!
    wait "$CENTRAL_PID"
fi
