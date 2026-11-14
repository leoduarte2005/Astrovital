# docs/ — Documentação Mestre

**Responsável:** todos (revisão cruzada obrigatória). Guardião da consistência: Leonardo (M4, integrador).

| Documento | Conteúdo |
| :--- | :--- |
| [`00-PROJECT-MASTER-PLAN.md`](00-PROJECT-MASTER-PLAN.md) | Visão do sistema, topologia, fluxo multi-astronauta, fluxo de correlação clínica, diagramas |
| [`01-TEAM-DIVISION-AND-WORKFLOW.md`](01-TEAM-DIVISION-AND-WORKFLOW.md) | Matriz RACI, contratos de integração, fluxo paralelo sem bloqueios, cronograma |
| [`members/`](members/README.md) | Guia de execução individual de cada um dos 5 membros |

## Regras

- Documento que contradiz `contracts/` está errado: `contracts/` vence.
- Mudança de arquitetura: atualizar `00`, `01` e os guias afetados no mesmo PR.
- Sem links para recursos que exijam internet em tempo de execução.
- Toda decisão clínica deve citar a fonte (NASA HRP Evidence/Risk, CSA, NASA-STD-3001) via ID da base em `knowledge-base/`.
