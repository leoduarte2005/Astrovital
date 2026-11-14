# EdgeSpace — Makefile raiz (orquestração de build; sem lógica de aplicação)
# Requer shell POSIX (Linux, WSL ou Git Bash). Alvo de produção: Orange Pi 4 Pro linux/arm64.
# Cada alvo verifica se o módulo já existe; caso contrário informa "pendente".

SHELL := /bin/sh

DB_PATH        ?= ./var/edgespace.db
GOOS_TARGET    ?= linux
GOARCH_TARGET  ?= arm64
CENTRAL_BIN    ?= ./build/edgespace-central
IDF_TARGET     ?= esp32s3
PYTHON         ?= python3

.PHONY: help contracts-validate db-migrate db-seed firmware-build firmware-flash \
        frontend-build central-build central-run-mock edge-ai-setup edge-ai-run \
        all clean

help:
	@echo "EdgeSpace — alvos disponíveis:"
	@echo "  contracts-validate  Valida fixtures contra JSON Schemas (tools/)          [Leonardo/M4]"
	@echo "  db-migrate          Aplica database/migrations em $(DB_PATH)              [Selliny/M1]"
	@echo "  db-seed             Carrega database/seeds (astronautas + base NASA)      [Selliny/M1]"
	@echo "  firmware-build      idf.py build para $(IDF_TARGET)                        [Nicolas/M2]"
	@echo "  firmware-flash      idf.py flash (PORT=COMx ou /dev/ttyUSBx)               [Nicolas/M2]"
	@echo "  frontend-build      Vite build e cópia para central/internal/httpws/ui     [Rafael/M3]"
	@echo "  central-build       Go CGO_ENABLED=0 $(GOOS_TARGET)/$(GOARCH_TARGET)       [Leonardo/M4]"
	@echo "  central-run-mock    Central com --mock-cluster (sem hardware)              [Leonardo/M4]"
	@echo "  edge-ai-setup       Cria venv e instala requirements do edge-ai            [Santiago+Leonardo/M5]"
	@echo "  edge-ai-run         Sobe worker IA em 127.0.0.1:5006                       [Santiago+Leonardo/M5]"
	@echo "  all                 contracts-validate + frontend-build + central-build"

contracts-validate:
	@if [ -f tools/validate_contracts.py ]; then $(PYTHON) tools/validate_contracts.py; \
	else echo "[pendente] tools/validate_contracts.py ausente (restaurar Sprint 0)"; fi

db-migrate:
	@if ls database/migrations/*.sql >/dev/null 2>&1; then mkdir -p $(dir $(DB_PATH)); \
	for f in database/migrations/*.sql; do echo "-> $$f"; sqlite3 $(DB_PATH) < $$f || exit 1; done; \
	else echo "[pendente] nenhuma migration em database/migrations/"; fi

db-seed:
	@if ls database/seeds/*.sql >/dev/null 2>&1; then \
	for f in database/seeds/*.sql; do echo "-> $$f"; sqlite3 $(DB_PATH) < $$f || exit 1; done; \
	else echo "[pendente] nenhum seed em database/seeds/"; fi

firmware-build:
	@if [ -f firmware/CMakeLists.txt ]; then cd firmware && idf.py set-target $(IDF_TARGET) build; \
	else echo "[pendente] firmware/CMakeLists.txt ausente"; fi

firmware-flash:
	@if [ -f firmware/CMakeLists.txt ]; then cd firmware && idf.py -p $(PORT) flash monitor; \
	else echo "[pendente] firmware/CMakeLists.txt ausente"; fi

frontend-build:
	@if [ -f frontend/package.json ]; then cd frontend && npm ci --offline && npm run build && \
	rm -rf ../central/internal/httpws/ui && mkdir -p ../central/internal/httpws/ui && \
	cp -r dist/. ../central/internal/httpws/ui/; \
	else echo "[pendente] frontend/package.json ausente"; fi

central-build:
	@if [ -f central/go.mod ]; then mkdir -p build && cd central && \
	CGO_ENABLED=0 GOOS=$(GOOS_TARGET) GOARCH=$(GOARCH_TARGET) \
	go build -trimpath -ldflags="-s -w" -o ../$(CENTRAL_BIN) ./cmd/edgespace-central; \
	else echo "[pendente] central/go.mod ausente"; fi

central-run-mock:
	@if [ -f central/go.mod ]; then cd central && go run ./cmd/edgespace-central --mock-cluster=inproc --mock-ai --db ../$(DB_PATH); \
	else echo "[pendente] central/go.mod ausente"; fi

edge-ai-setup:
	@if [ -f edge-ai/requirements.txt ]; then cd edge-ai && $(PYTHON) -m venv .venv && \
	./.venv/bin/pip install --no-index --find-links ./wheels -r requirements.txt; \
	else echo "[pendente] edge-ai/requirements.txt ausente"; fi

edge-ai-run:
	@if [ -d edge-ai/src/edgespace_ai ] && [ -f edge-ai/requirements.txt ]; then cd edge-ai && \
	PYTHONPATH=src ./.venv/bin/python -m edgespace_ai --listen 127.0.0.1:5006 --db ../$(DB_PATH); \
	else echo "[pendente] worker edge-ai ainda não implementado"; fi

all: contracts-validate frontend-build central-build

clean:
	rm -rf build var
