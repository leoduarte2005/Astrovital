# contracts/ — Fonte Única de Verdade

**Responsável:** todos consomem; **guardião: Leonardo (M4)**. Mudança exige PR aprovado pelo guardião + 1 membro afetado.

## Propósito
Definir formato canônico de toda mensagem trocada entre firmware, Central, Edge AI e painel. Código Go/Python/TS/C espelha estes arquivos; nunca o contrário.

## Estrutura
| Pasta | Conteúdo |
| :--- | :--- |
| [`enums/`](enums/README.md) | Enumerações compartilhadas (modos de missão, subsistemas, severidade, tipos de mensagem, sensores) |
| [`jsonschema/`](jsonschema/README.md) | JSON Schema (draft 2020-12) por canal: `udp/`, `ipc/`, `ws/`, `rest/` |
| [`fixtures/`](fixtures/README.md) | Exemplos válidos/inválidos usados em testes de todos os módulos |

## Regras
- Versionamento: campo `v` no envelope. Mudança incompatível = nova versão (`v2`), mantendo `v1` até todos migrarem.
- Todo schema novo precisa de ao menos 1 fixture válida e 1 inválida.
- `make contracts-validate` deve passar antes de qualquer merge.

## Status
**Atenção:** contratos v1 da Sprint 0 não estavam presentes neste workspace na estruturação. Restaurar os arquivos originais validados nas subpastas antes da Sprint 1. Não recriar do zero sem revisão do guardião.
