# knowledge-base/ — Base Clínica NASA HRP/CSA

**Responsável:** Selliny (M1). Guia: [`docs/members/MEMBER-01-DATABASE-KNOWLEDGE.md`](../docs/members/MEMBER-01-DATABASE-KNOWLEDGE.md)

## Propósito
Conhecimento médico aeroespacial estruturado, legível por máquina, previsto para a carga inicial do banco operacional, tutoriais do painel e motor de correlação causal.

## Estrutura
| Pasta | Conteúdo |
| :--- | :--- |
| [`nasa_hrp_reports/`](nasa_hrp_reports/README.md) | 5 Perigos, 11 Riscos Fisiológicos, 8 Riscos Comportamentais/Bioquímicos |
| [`protocols/`](protocols/README.md) | Tutoriais passo a passo de autoexame |
| [`datasets/`](datasets/README.md) | Séries sintéticas e golden cases |

## Consumidores
- Selliny/M1: mantém o [pacote de pesquisa](../database/space_health_sqlite/README.md) e prepara a futura carga inicial operacional descrita em [database/README.md](../database/README.md).
- Rafael/M3: tutoriais (via REST da Central).
- Santiago/Leonardo/M5: grafo causal, golden cases, datasets de treino.

## Regras
- Todo item tem `source` (documento NASA HRP/CSA/NASA-STD-3001 e seção).
- Conteúdo é apoio à decisão, não substitui cirurgião de voo.
