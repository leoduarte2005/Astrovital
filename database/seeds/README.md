# database/seeds/

**Responsável:** Selliny (M1).

## Propósito
Carga inicial reprodutível para desenvolvimento e demo.

## Conteúdo esperado
| Seed | Origem |
| :--- | :--- |
| Astronautas de demonstração (mín. 3 `crew_id`, perfis e particularidades distintas) | Membro 1 |
| Base clínica (5 Perigos, 11 Riscos Fisiológicos, 8 Riscos Comportamentais/Bioquímicos) | `knowledge-base/nasa_hrp_reports/` |
| Contramedidas e arestas causais | `knowledge-base/nasa_hrp_reports/` |
| Protocolos de autoexame | `knowledge-base/protocols/` |
| Histórico longitudinal sintético curto por astronauta | `knowledge-base/datasets/` |

## Regras
- Gerado a partir de `knowledge-base/`; não editar à mão dados que existem lá.
- Aplicável sobre banco recém-migrado (`make db-migrate && make db-seed`).
