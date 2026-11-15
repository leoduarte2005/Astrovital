# Roteiro Operacional — Stack Unificada EdgeSpace (`edge-ai` + `central`)

Guia rápido para compilar e subir juntos o worker **IA Local (`edge-ai` em `127.0.0.1:5006`)** e a **Central Orquestradora Go (`central` em `:8000`, sem `--mock-ai`)** com um único comando.

---

## 1. Subir a Stack Completa com 1 Comando

### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1
```
Ou, se tiver `make` (Git Bash / Chocolatey / Scoop):
```bash
make run-win
```

### Linux / Orange Pi 4 Pro (ARM64) / WSL
```bash
./scripts/run_stack.sh
# ou via Makefile:
make run
```

### O que o script faz automaticamente
1. **Limpa processos órfãos** presos nas portas `5006` (IPC IA) e `8000` (HTTP/WS Central).
2. **Verifica os 5 modelos `.onnx`** em `edge-ai/models/` (`posture_cls.onnx`, `exercise_cadence.onnx`, `vitals_reg.onnx`, `baseline_ae_default.onnx`, `isolation_forest.onnx`). Se faltar algum, roda `edge-ai/training/build_all_models.py`.
3. **Prepara o SLM conversacional (1ª execução após `git clone`)**: instala `llama-cpp-python` se ausente e baixa automaticamente `qwen2.5-1.5b-instruct-q4_k_m.gguf` (~1.1 GB, fora do Git pelo limite de 100 MB do GitHub) do Hugging Face para `edge-ai/models/slm/`, com retomada (`Range` sobre `.part`), verificação SHA-256 e rename atômico. Se a rede cair, basta rodar de novo que o download continua de onde parou; se estiver sem internet, a stack sobe normalmente usando o template determinístico.
4. **Compila a Central Go** atualizada em `build/edgespace-central(.exe)` (`CGO_ENABLED=0`).
5. **Cria `var/`** e sobe o worker Python `edgespace_ai` em background (`127.0.0.1:5006`), aguardando o socket TCP abrir antes de prosseguir.
6. **Sobe a Central Go** conectada ao worker real (`-ipc-addr=127.0.0.1:5006 -db=var/edgespace.db -migrations=database/migrations`, **sem** `--mock-ai`) com logs formatados no console.
7. **Encerramento limpo (`Ctrl+C`)**: `try/finally` (Windows) e `trap EXIT INT TERM` (Linux) encerram tanto a Central Go quanto toda a árvore de processos do worker Python, liberando as portas `5006` e `8000`.

---

## 2. Modos de Operação: Simulado (`inproc`) vs. Hardware Real (`ESP32-S3`)

| Modo | Quando usar | Flag Windows (`run_stack.ps1`) | Flag Linux (`run_stack.sh`) | Comportamento da Central Go |
| :--- | :--- | :--- | :--- | :--- |
| **Simulado (`inproc`)** *(padrão)* | Desenvolvimento e testes em notebook/PC sem os 5 nós físicos | *(padrão)* | *(padrão)* | `-mock-cluster=inproc` gera CSI sintético em memória e envia janelas reais ao `edge-ai` (`:5006`) |
| **Hardware Real (5× ESP32-S3)** | Bancada ou missão na **Orange Pi 4 Pro** recebendo UDP `:5005` da malha Wi-Fi CSI | `-RealCluster -HttpAddr ":8000"` | `--real-cluster --http-addr :8000` | `-mock-cluster=false` abre receptor UDP `:5005` e transmissor `CLUSTER_SYNC` (`10.42.0.255:5005`) |

Exemplos para **Hardware Real**:
```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -RealCluster -HttpAddr ":8000"
```
```bash
# Orange Pi 4 Pro / Linux
./scripts/run_stack.sh --real-cluster --http-addr :8000
# ou
make run ARGS="--real-cluster --http-addr :8000"
```

Para pular a recompilação Go em reinícios rápidos:
- Windows: `-NoBuild`
- Linux: `--no-build`

Para pular o download/uso do modelo SLM (~1.1 GB) e responder pelo template determinístico:
- Windows: `-NoSlm`
- Linux: `--no-slm`
- Ou baixar/verificar apenas o modelo antes: `PYTHONPATH=edge-ai/src python -m edgespace_ai.utils.model_fetch` (`--check` para só verificar, `--force` para rebaixar).

---

## 3. Cenários de Simulação (`hypercapnia`, `sans`, `node_loss`, ...)

No modo simulado (`inproc`), injete cenários clínicos/operacionais na inicialização:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Scenario hypercapnia
powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Scenario sans
powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Scenario node_loss
```
```bash
# Linux / Orange Pi 4 Pro
./scripts/run_stack.sh --scenario hypercapnia
./scripts/run_stack.sh --scenario sans
./scripts/run_stack.sh --scenario node_loss
```

Ou troque o cenário **em tempo de execução** via HTTP (sem reiniciar a stack):
```bash
curl -X POST http://127.0.0.1:8000/api/dev/scenario \
  -H "Content-Type: application/json" \
  -d '{"name":"hypercapnia"}'
```
Cenários suportados: `hypercapnia`, `sans`, `solar_storm`, `dehydration_sleep`, `node_loss`.

---

## 4. Verificação de Saúde e Integração IA (`ai_ready: true`)

### Healthcheck HTTP (`/healthz`) e Métricas (`/api/metrics`)
```bash
curl -i http://127.0.0.1:8000/healthz
# HTTP/1.1 200 OK
# {"db":"ok","status":"ok"}

curl -s http://127.0.0.1:8000/api/metrics
# {"ws_clients":0,"store_commits":...,"ipc_dropped_windows":0,"ipc_reconnects":0,...}
```

### Smoke Test Automatizado (compila, valida `/healthz` + `ai_ready: true` no WS e encerra)
```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -SmokeSeconds 5
```
```bash
# Linux / Orange Pi 4 Pro
./scripts/run_stack.sh --smoke-seconds 5
```

### Logs em Disco
- Worker Python (`edge-ai`): `var/edge-ai.log` e `var/edge-ai.err.log`
- Central Go (modo smoke): `var/central.log`

---

## 5. Diagnóstico de Portas Ocupadas (`5006` e `8000`)

Os scripts já limpam as portas antes de subir e ao sair. Para inspecionar ou liberar manualmente:

### Windows (PowerShell)
```powershell
# Inspecionar processos ouvindo nas portas 5006 e 8000
Get-NetTCPConnection -LocalPort 5006,8000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalPort,OwningProcess,@{N='Name';E={(Get-Process -Id $_.OwningProcess).ProcessName}}

# Matar árvore de um PID preso
taskkill /PID <PID> /T /F
```

### Linux / Orange Pi 4 Pro
```bash
# Inspecionar
ss -lptn 'sport = :5006 or sport = :8000'
# ou
lsof -iTCP:5006,8000 -sTCP:LISTEN

# Encerrar
fuser -k 5006/tcp 8000/tcp
```
