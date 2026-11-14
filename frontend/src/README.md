# frontend/src/

**Responsável:** Rafael (M3).

## Propósito
Código-fonte do painel, organizado por domínio. Ver READMEs de cada subpasta:
[`components/`](components/README.md), [`scene/`](scene/README.md), [`chatbot/`](chatbot/README.md), [`charts/`](charts/README.md), [`store/`](store/README.md).

## Regras de dependência entre pastas
- `store/` não importa nada de UI.
- `scene/`, `charts/`, `chatbot/`, `components/` leem/escrevem estado só via `store/`.
- Tipos de mensagem vêm de um único módulo de tipos espelhando `contracts/`.
