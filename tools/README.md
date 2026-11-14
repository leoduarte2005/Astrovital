# tools/ — Utilitários de Desenvolvimento

**Responsável:** Leonardo (M4).

## Propósito
Scripts de suporte a desenvolvimento e CI local. Nunca rodam em produção na Orange Pi.

## Conteúdo esperado
| Item | Função |
| :--- | :--- |
| `validate_contracts.py` | Valida `contracts/fixtures/` contra `contracts/jsonschema/` (chamado por `make contracts-validate`) |
| Receptor UDP de teste | Escuta `:5005` e imprime pacotes do firmware (usado pelo Membro 2 sem Central) |
| Verificador offline | Varre `frontend/dist` por URLs externas (`http://`, `https://` fora da LAN) |

## Status
Artefatos da Sprint 0 não estavam presentes neste workspace. Restaurar versão validada antes da Sprint 1.
