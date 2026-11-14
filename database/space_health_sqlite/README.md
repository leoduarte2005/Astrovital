# Space Health SQLite

Base de pesquisa incorporada ao EdgeSpace. O banco completo permanece em `database/space_health_sqlite/space_health.db`, mantendo o caminho usado pela conexão **EdgeSpace - Pesquisa** no DBeaver.

O [guia de uso local e DBeaver](docs/COMO_RODAR_LOCAL_E_DBEAVER.md) mostra como instalar o snapshot em um novo clone, conectar, visualizar tabelas e colunas, executar as consultas e resolver o erro de conexão inativa.

O arquivo `space_health.db` tem cerca de 474 MiB e é mantido localmente, fora do Git. Os demais artefatos deste módulo continuam versionados. Para disponibilizar o banco completo em outra máquina, transfira o snapshot separadamente e instale-o no mesmo caminho relativo.

## Organização

```text
space_health_sqlite/
├── README.md
├── schema.sql
├── space_health.db          # snapshot local, ignorado pelo Git
├── scripts/
│   ├── build_db.py
│   ├── import_published_physiology.py
│   ├── apply_missingness_policy.py
│   └── validate_db.py
├── queries/
│   ├── queries.sql
│   ├── dbeaver_visualizacao.sql
│   └── consulta_fisiologia_completa.sql
├── docs/
│   └── COMO_RODAR_LOCAL_E_DBEAVER.md
├── reports/
│   └── supplied/
│       ├── validation_report.json
│       └── VALIDATION_REPORT.md
└── provenance/
    └── IMPORT_MANIFEST.json
```

- **Banco e schema:** arquivos principais na raiz do módulo.
- **Scripts:** construção, importação, política de ausências e validação.
- **Consultas:** arquivos SQL para exploração e DBeaver.
- **Documentação:** guia de uso local e DBeaver. Os documentos originais recebidos permanecem em Documentos; seus hashes estão registrados no manifesto de importação.
- **Relatórios recebidos:** preservados em `reports/supplied/`. Os relatórios recalculados ficam em `var/research/`, na raiz do projeto.
- **Proveniência:** o manifesto mantém `file` como nome original e `project_path` como caminho atual no módulo, com os respectivos hashes.

## Uso na raiz do EdgeSpace

```bash
make db-research-inventory
make db-research-queries
make db-research-validate
make db-research-test
```

Para gerar uma demonstração offline em `var/space_health_demo.db`:

```bash
make db-research-demo
```

## DBeaver

Mantenha a conexão no arquivo `space_health.db` da raiz deste módulo. Abra as consultas nos novos caminhos:

- [Visualização e auditoria: 24 consultas](queries/dbeaver_visualizacao.sql).
- [Fisiologia completa: 161 linhas e 39 colunas](queries/consulta_fisiologia_completa.sql).
- [Consultas recebidas com o pacote](queries/queries.sql).

A organização dos arquivos mantém o mesmo banco, dados e schema. O [guia de uso local](docs/COMO_RODAR_LOCAL_E_DBEAVER.md) contém os comandos de preparação, consulta e validação. As fontes e a auditoria de ausências também podem ser consultadas pelos arquivos SQL disponíveis neste módulo.
