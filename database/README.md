# Banco de dados do EdgeSpace

**Responsável pelo schema e dados:** Selliny (M1). **Escritor operacional previsto:** Central Go, mantida por Leonardo (M4). **Leitura para análise:** Edge AI e ferramentas locais.

Para começar, siga o [passo a passo para usar localmente e visualizar no DBeaver](space_health_sqlite/docs/COMO_RODAR_LOCAL_E_DBEAVER.md).

## Estrutura

| Caminho | Conteúdo |
| --- | --- |
| [`space_health_sqlite/`](space_health_sqlite/README.md) | Base de pesquisa, schema, scripts, consultas, documentação e proveniência. |
| [`tools/research.py`](tools/research.py) | Inventário e execução de consultas em modo somente leitura. |
| [`tests/`](tests/) | Testes de importação, política de ausências e rollback. |

## Base de pesquisa disponível

O snapshot completo fica em `database/space_health_sqlite/space_health.db`: 26 tabelas, 13 datasets, 1.269.126 linhas ambientais, 6.342 medições de radiação, dados moleculares, cinco estudos ESA/HREDA em metadados, 18 publicações com 161 agregados fisiológicos e 90 check-ins fictícios.

O `.db` completo tem cerca de 474 MiB e fica fora do Git, preservado no disco local. Schema, scripts, consultas e relatórios continuam versionados. Em um novo clone, instale o snapshot recebido separadamente conforme o guia acima; a demonstração offline contém apenas parte dos dados.

Os 781.198 eventos de ausência preservam motivos, proveniência e valores `NULL`. Zero continua sendo valor observado; não houve imputação. O [guia de uso local e DBeaver](space_health_sqlite/docs/COMO_RODAR_LOCAL_E_DBEAVER.md) explica as consultas, a validação e o achado de SD negativa preservado para revisão.

Scripts ficam em `space_health_sqlite/scripts/`; SQL de exploração em `space_health_sqlite/queries/`; documentação em `space_health_sqlite/docs/`; relatórios recebidos em `space_health_sqlite/reports/supplied/`; manifesto em `space_health_sqlite/provenance/`.

## Comandos na raiz do projeto

```bash
make db-research-inventory
make db-research-queries
make db-research-validate
make db-research-test
```

Consultas e validação usam somente leitura. Os relatórios recalculados são escritos em `var/research/`; os recebidos permanecem preservados. `make db-research-demo` executa as três etapas de preparação offline em `var/space_health_demo.db`. Os alvos `db-research-import-physiology` e `db-research-missingness` reaplicam etapas nesse banco de demonstração.

No DBeaver, a conexão **EdgeSpace - Pesquisa** continua apontando para o mesmo `space_health.db`. Os arquivos SQL agora estão na pasta [queries/](space_health_sqlite/queries/).

## Base operacional planejada

`var/edgespace.db` é o banco operacional previsto para perfis, sensores, autoexames, conversas, alertas e comunicação da Central. Seu schema e sua carga inicial ainda precisam ser implementados; o escopo está no [guia do Membro 1](../docs/members/MEMBER-01-DATABASE-KNOWLEDGE.md).

Configuração prevista da conexão operacional: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON` e `busy_timeout=5000`. O snapshot de pesquisa usa uma conexão separada somente leitura. Seus experimentos, amostras e perfis fictícios não possuem correspondência automática com os identificadores operacionais `crew_id`.
