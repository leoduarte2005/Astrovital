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
GO             ?= go
OPERATIONAL_REPORT_PATH ?= ./var/operational/validation_report.json
RESEARCH_DB_PATH ?= ./database/space_health_sqlite/space_health.db
RESEARCH_REPORT_PATH ?= ./var/research/validation_report.json
RESEARCH_DEMO_PATH ?= ./var/space_health_demo.db

.PHONY: help contracts-validate firmware-build firmware-flash \
        db-migrate db-operational-validate db-operational-test db-intelligence-generate db-intelligence-check \
        frontend-build central-build central-run-mock edge-ai-setup edge-ai-run \
        db-research-inventory db-research-queries db-research-validate \
        db-research-demo db-research-import-physiology db-research-missingness db-research-test all clean

help:
	@echo "EdgeSpace — alvos disponíveis:"
	@echo "  contracts-validate  Valida fixtures contra JSON Schemas (tools/)          [Leonardo/M4]"
	@echo "  db-migrate          Aplica 0001 a 0004 ao banco operacional em $(DB_PATH)"
	@echo "  db-operational-validate  Confere schema, FTS5, baselines e golden cases"
	@echo "  db-operational-test  Testa migrations, persistência e qualidade dos fixtures"
	@echo "  db-intelligence-generate  Regera seeds SQL e datasets sintéticos"
	@echo "  db-intelligence-check  Confere a reprodução dos artefatos sem alterá-los"
	@echo "  db-research-inventory  Lista os datasets do pacote Space Health (offline) [Selliny/M1]"
	@echo "  db-research-queries    Executa as consultas de exemplo em leitura         [Selliny/M1]"
	@echo "  db-research-validate   Valida a base e gera relatórios em var/research/    [Selliny/M1]"
	@echo "  db-research-demo       Gera catálogo, fixtures e agregados offline         [Selliny/M1]"
	@echo "  db-research-import-physiology  Importa o corpus no banco de demonstração    [Selliny/M1]"
	@echo "  db-research-missingness  Aplica a política de ausências na demonstração    [Selliny/M1]"
	@echo "  db-research-test       Verifica importação, repetição e rollback           [Selliny/M1]"
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
	$(PYTHON) database/tools/operational.py migrate --db "$(DB_PATH)"

db-operational-validate:
	$(PYTHON) database/tools/operational.py validate --db "$(DB_PATH)" --out "$(OPERATIONAL_REPORT_PATH)"

db-intelligence-generate:
	$(PYTHON) database/tools/generate_intelligence_seeds.py

db-intelligence-check:
	$(PYTHON) database/tools/generate_intelligence_seeds.py --check

db-operational-test: db-intelligence-check
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s database/tests -p 'test_operational.py' -v

db-research-inventory:
	$(PYTHON) database/tools/research.py --db "$(RESEARCH_DB_PATH)"

db-research-queries:
	$(PYTHON) database/tools/research.py --db "$(RESEARCH_DB_PATH)" --queries database/space_health_sqlite/queries/queries.sql

db-research-validate:
	$(PYTHON) database/space_health_sqlite/scripts/validate_db.py --db "$(RESEARCH_DB_PATH)" --out "$(RESEARCH_REPORT_PATH)" --quiet

db-research-demo:
	$(PYTHON) database/space_health_sqlite/scripts/build_db.py --db "$(RESEARCH_DEMO_PATH)" --skip-network
	$(PYTHON) database/space_health_sqlite/scripts/import_published_physiology.py --db "$(RESEARCH_DEMO_PATH)"
	$(PYTHON) database/space_health_sqlite/scripts/apply_missingness_policy.py --db "$(RESEARCH_DEMO_PATH)"

db-research-import-physiology:
	$(PYTHON) database/space_health_sqlite/scripts/import_published_physiology.py --db "$(RESEARCH_DEMO_PATH)"
	$(PYTHON) database/space_health_sqlite/scripts/apply_missingness_policy.py --db "$(RESEARCH_DEMO_PATH)"

db-research-missingness:
	$(PYTHON) database/space_health_sqlite/scripts/apply_missingness_policy.py --db "$(RESEARCH_DEMO_PATH)"

db-research-test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s database/tests -p 'test_*.py' -v

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
	$(GO) build -trimpath -ldflags="-s -w" -o ../$(CENTRAL_BIN) ./cmd/edgespace-central; \
	else echo "[pendente] central/go.mod ausente"; fi

central-run-mock: db-migrate
	@if [ -f central/go.mod ]; then cd central && $(GO) run ./cmd/edgespace-central --mock-cluster=inproc --mock-ai --db "$(abspath $(DB_PATH))" --migrations "$(abspath database/migrations)"; \
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
