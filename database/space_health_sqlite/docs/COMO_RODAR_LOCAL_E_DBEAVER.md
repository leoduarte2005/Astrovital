# Como usar o banco localmente e consultar no DBeaver

Guia para o projeto em `/home/selliny/Edge_Space`. Caminhos e resultados conferidos no snapshot de 14 de novembro de 2026.

Neste ambiente, o banco completo já está preenchido neste arquivo:

```text
/home/selliny/Edge_Space/database/space_health_sqlite/space_health.db
```

Para consultar, basta conectar nesse arquivo. O SQLite funciona localmente, sem iniciar um servidor ou configurar porta, usuário e senha. Este guia cobre a base de pesquisa, seus scripts e consultas. A Central Go possui implementação própria e usa um banco operacional separado.

O snapshot completo tem cerca de 474 MiB e é ignorado pelo Git. Schema, scripts, consultas e relatórios continuam versionados; um novo clone precisa receber o `.db` separadamente. O GitHub bloqueia arquivos comuns maiores que 100 MiB, conforme sua [documentação sobre arquivos grandes](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).

## 1. Requisitos

| Ferramenta | Uso |
| --- | --- |
| DBeaver com driver SQLite | Abrir o banco e consultar pela interface. |
| Python 3.10 ou superior | Executar os scripts locais; usam a biblioteca padrão, sem `pip install`. |
| `make` | Usar os atalhos do projeto. Há comandos Python equivalentes abaixo. |

O arquivo completo pode ser consultado offline. Se o DBeaver solicitar o download do driver SQLite na primeira conexão, conclua essa instalação com acesso à internet; as consultas locais não precisam acessar as fontes NASA.

### Instalar o banco completo em um novo clone

Se o arquivo do banco já existir no caminho acima, siga para a seção 2. Se estiver ausente, obtenha o snapshot completo de quem mantém os dados. Neste computador, a cópia recebida está em `/home/selliny/Documentos/space_health_sqlite/space_health.db`.

O comando abaixo instala uma cópia consistente usando a API de backup do SQLite, incluindo transações confirmadas no WAL da origem. Ajuste o primeiro caminho ao local do banco recebido na outra máquina:

```bash
cd /home/selliny/Edge_Space
python3 - /home/selliny/Documentos/space_health_sqlite/space_health.db <<'PY'
from pathlib import Path
import sqlite3
import sys

source = Path(sys.argv[1]).expanduser().resolve()
target = Path("database/space_health_sqlite/space_health.db")
if not source.is_file():
    raise SystemExit(f"Banco de origem não encontrado: {source}")
if target.exists():
    raise SystemExit(f"O destino já existe; use o banco atual: {target}")
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as origin:
    with sqlite3.connect(target) as destination:
        origin.backup(destination)
        destination.execute("PRAGMA journal_mode=DELETE")
print(f"Banco instalado em {target.resolve()}")
PY
```

Depois, execute `make db-research-validate`. O caminho usado no DBeaver continua sendo o arquivo instalado dentro do projeto. Para uma demonstração sem o snapshot completo, use a seção 9.

## 2. Usar pelo terminal

Abra um terminal na raiz do projeto:

```bash
cd /home/selliny/Edge_Space
python3 --version
ls -lh database/space_health_sqlite/space_health.db
```

Liste os datasets, os agregados fisiológicos e os resumos de ausências:

```bash
make db-research-inventory
```

Execute as consultas de exemplo:

```bash
make db-research-queries
```

A ferramenta mostra até 25 linhas por consulta. Esse limite é da exibição no terminal e não representa a quantidade total de registros do banco.

Valide o arquivo em modo somente leitura:

```bash
make db-research-validate
```

Os relatórios atualizados ficam em:

```text
/home/selliny/Edge_Space/var/research/validation_report.json
/home/selliny/Edge_Space/var/research/VALIDATION_REPORT.md
```

No snapshot atual, as 13 verificações estruturais passam. O relatório também registra um desvio-padrão negativo preservado da origem para revisão; esse achado de qualidade é apresentado separadamente das verificações estruturais.

Para executar os testes dos importadores e da política de ausências:

```bash
make db-research-test
```

### Alternativa sem `make`

Na mesma pasta do projeto:

```bash
python3 database/tools/research.py
python3 database/tools/research.py --queries database/space_health_sqlite/queries/queries.sql --limit 100
python3 database/space_health_sqlite/scripts/validate_db.py --db database/space_health_sqlite/space_health.db --out var/research/validation_report.json --quiet
```

## 3. Conectar no DBeaver

Se já existir a conexão **EdgeSpace - Pesquisa**, abra **Editar conexão / Edit Connection** e confira o caminho do arquivo abaixo. Caso contrário:

1. Abra **Banco de dados → Nova conexão / Database → New Database Connection**.
2. Procure **SQLite**, selecione e avance.
3. No campo **Path / Caminho**, selecione o arquivo existente:

   ```text
   /home/selliny/Edge_Space/database/space_health_sqlite/space_health.db
   ```

4. Clique em **Testar conexão / Test Connection**. Se solicitado, baixe o driver.
5. Conclua em **Finalizar / Finish** e dê à conexão o nome **EdgeSpace - Pesquisa**.
6. No **Navegador de banco de dados / Database Navigator**, conecte e expanda a conexão.

Se a versão oferecer **Connect by → URL**, esta URL abre o arquivo em modo somente leitura:

```text
jdbc:sqlite:file:/home/selliny/Edge_Space/database/space_health_sqlite/space_health.db?mode=ro
```

O campo Path recebe o caminho do `.db`; a URL JDBC deve ser usada no campo URL. O arquivo já contém o schema e os dados, portanto não é necessário executar `schema.sql` nem reconstruir o banco para visualizá-lo. [Configuração SQLite no DBeaver](https://dbeaver.com/docs/dbeaver/Database-driver-SQLite/).

## 4. Ver tabelas, colunas e registros

1. Expanda **EdgeSpace - Pesquisa → Tables / Tabelas**. Dependendo da versão, existe o nível **main** antes de Tables.
2. Dê dois cliques em uma tabela, por exemplo `published_physiology_aggregates`.
3. Abra **Properties → Columns / Propriedades → Colunas** para ver nomes, tipos e restrições.
4. Abra **Data / Dados** para ver as linhas. A grade permite rolar horizontalmente para acessar as demais colunas.

O editor de objetos e o editor de dados são descritos na [documentação do DBeaver](https://dbeaver.com/docs/dbeaver/Data-Viewing-and-Editing/).

As tabelas principais para começar são:

| Tabela | Conteúdo | Linhas no snapshot |
| --- | --- | ---: |
| `datasets` | Catálogo dos conjuntos de dados | 13 |
| `physiology_publications` | Referências, DOI, links e situação da extração | 18 |
| `published_physiology_aggregates` | Valores fisiológicos, unidades, estatísticas e contexto | 161 |
| `environmental_measurements` | Temperatura, umidade e CO₂ de experimentos e controles | 1.269.126 |
| `radiation_measurements` | Medições de radiação de instrumentos | 6.342 |
| `biomedical_samples` | Metadados das amostras OSD-53 | 13 |
| `gene_expression_measurements` | Registros de expressão gênica | 3.159 |
| `differential_expression_results` | Resultados moleculares agregados | 243 |
| `synthetic_checkins` | Check-ins fictícios | 90 |
| `field_quality_events` | Motivos de ausência e proveniência por campo | 781.198 |

### Ver a quantidade completa de linhas

A grade pode carregar apenas um bloco, frequentemente de 200 linhas. Para carregar mais, use **Fetch next page**. Para carregar o resultado inteiro, clique com o botão direito na grade e escolha **Navigate → Fetch All Data**. Uma consulta com `LIMIT 100` continuará retornando no máximo 100 linhas, mesmo usando essa opção. [Navegação dos resultados](https://dbeaver.com/docs/dbeaver/Navigation/).

Para tabelas com centenas de milhares de registros, consulte a quantidade com `COUNT(*)` e explore recortes por dataset, data ou missão. O arquivo de fisiologia completa retorna somente 161 linhas e pode ser visualizado integralmente.

## 5. Abrir o editor SQL e executar uma consulta

1. Clique com o botão direito em **EdgeSpace - Pesquisa**.
2. Escolha **SQL Editor → New SQL Script / Novo script SQL**.
3. Confira se o seletor **Active datasource / Fonte de dados ativa** mostra **EdgeSpace - Pesquisa**. Para escolher a conexão do editor, use **Ctrl+9**. [Conexão ativa do editor](https://dbeaver.com/docs/dbeaver/SQL-Editor/#active-database).
4. Cole a consulta abaixo e pressione **Ctrl+Enter**:

   ```sql
   PRAGMA database_list;
   ```

5. Confira a coluna `file`: ela deve indicar o arquivo completo em `database/space_health_sqlite/space_health.db`.

| Ação no editor SQL | Como executar no Linux/Windows |
| --- | --- |
| Executar uma consulta | Cursor dentro dela, sem seleção, e **Ctrl+Enter**. |
| Executar um trecho | Selecione a instrução completa e pressione **Ctrl+Enter**. |
| Executar um arquivo com várias consultas | Remova a seleção e use **Alt+X** ou **SQL Editor → Execute SQL Script**. |

As instruções de um script são separadas por `;`. Os resultados aparecem no painel inferior; conforme a configuração, podem ficar em abas ou blocos. [Execução SQL no DBeaver](https://dbeaver.com/docs/dbeaver/SQL-Execution/).

## 6. Abrir os arquivos de consultas do projeto

Com o editor conectado, use **File → Open File / Arquivo → Abrir arquivo** para abrir um dos arquivos abaixo. Confira novamente a conexão ativa depois de abrir o arquivo.

| Arquivo | Uso |
| --- | --- |
| [dbeaver_visualizacao.sql](../queries/dbeaver_visualizacao.sql) | 24 consultas: tabelas, contagens, fontes, dados e auditoria. |
| [consulta_fisiologia_completa.sql](../queries/consulta_fisiologia_completa.sql) | Todos os 161 agregados em 39 colunas, com publicação, contexto, fontes e motivos de ausência. |
| [queries.sql](../queries/queries.sql) | Consultas de exploração recebidas com o pacote. |

Os caminhos absolutos são:

```text
/home/selliny/Edge_Space/database/space_health_sqlite/queries/dbeaver_visualizacao.sql
/home/selliny/Edge_Space/database/space_health_sqlite/queries/consulta_fisiologia_completa.sql
/home/selliny/Edge_Space/database/space_health_sqlite/queries/queries.sql
```

Para a fisiologia, abra `consulta_fisiologia_completa.sql`, deixe o cursor dentro da instrução `WITH ... SELECT ...`, sem selecionar apenas uma parte, e pressione **Ctrl+Enter**. O resultado esperado é:

| Domínio | Registros |
| --- | ---: |
| Pressão arterial | 60 |
| Frequência cardíaca | 20 |
| Resposta cardiovascular | 41 |
| Intolerância ortostática | 7 |
| Saúde óssea | 33 |
| **Total** | **161** |

São resultados publicados por estudo/grupo. As colunas `valor`, `unidade`, `tipo_estatistica`, `grupo_estudado`, `fase_da_missao`, `local_no_artigo` e `link_artigo` permitem entender cada linha. `detalhes_ausencias_json` explica as ausências documentadas; `NULL` representa ausência e zero continua sendo um valor observado.

## 7. Consultas rápidas para copiar e colar

Execute uma instrução por vez com **Ctrl+Enter**, ou o bloco inteiro com **Alt+X**.

```sql
-- Conferir o arquivo conectado.
PRAGMA database_list;

-- Contar as tabelas: esperado 26.
SELECT COUNT(*) AS total_tabelas
FROM sqlite_master
WHERE type = 'table' AND name NOT LIKE 'sqlite_%';

-- Listar todas as tabelas e o SQL que define suas colunas e restrições.
SELECT name AS tabela, sql AS definicao
FROM sqlite_master
WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
ORDER BY name;

-- Detalhar as colunas dos agregados: nome, tipo, obrigatoriedade e chave.
PRAGMA table_info(published_physiology_aggregates);

-- Ver os relacionamentos dessa tabela.
PRAGMA foreign_key_list(published_physiology_aggregates);

-- Ver todas as colunas e as 60 linhas de pressão arterial.
SELECT *
FROM published_physiology_aggregates
WHERE domain = 'BLOOD_PRESSURE'
ORDER BY aggregate_id;

-- Ver todas as publicações e seus campos.
SELECT *
FROM physiology_publications
ORDER BY publication_id;

-- Contar as linhas ambientais sem carregar os registros na grade.
SELECT COUNT(*) AS total_linhas_ambientais
FROM environmental_measurements;

-- Explorar uma amostra ambiental com todas as colunas da tabela.
SELECT *
FROM environmental_measurements
ORDER BY measurement_id
LIMIT 100;
```

Troque o nome da tabela em `PRAGMA table_info(...)` para inspecionar suas outras estruturas. Para visualizar os registros de fisiologia junto com as publicações e a auditoria, use a consulta completa da seção anterior.

## 8. Resolver os erros mais comuns

| Situação | Como resolver |
| --- | --- |
| **Cannot obtain session / No active connection** | Conecte **EdgeSpace - Pesquisa** no navegador. Volte à aba SQL, pressione **Ctrl+9**, selecione essa conexão e execute novamente. Abrir um `.sql` sozinho pode deixar o editor sem uma conexão associada. |
| **no such table** | Execute `PRAGMA database_list;` e confira o arquivo. A conexão deve apontar para `database/space_health_sqlite/space_health.db`, e não para outro `.db`. |
| Só aparecem poucas linhas | Confira se a consulta tem `LIMIT` e use os controles de navegação da grade. Compare com `COUNT(*)` para saber o total. |
| As tabelas não aparecem após uma atualização do arquivo | Desconecte, conecte novamente e atualize a conexão no navegador. |
| **unable to open database file** | Confira o caminho absoluto e a permissão de leitura. No terminal, use o comando `ls -lh` da seção 2. |
| O driver SQLite não está disponível | Conclua a instalação do driver solicitada pelo DBeaver e repita o teste de conexão. |

## 9. Opcional: gerar uma demonstração local

Para experimentar os scripts, gere uma base separada:

```bash
cd /home/selliny/Edge_Space
make db-research-demo
make db-research-validate RESEARCH_DB_PATH=./var/space_health_demo.db RESEARCH_REPORT_PATH=./var/research-demo/validation_report.json
```

Essa demonstração contém catálogo, 90 check-ins sintéticos, 161 agregados de artigos e sua auditoria. As medições NASA já importadas no arquivo completo não são reconstruídas pela demonstração offline.

Para abri-la no DBeaver, crie outra conexão, chamada **EdgeSpace - Demo**, apontando para:

```text
/home/selliny/Edge_Space/var/space_health_demo.db
```

Para explorar todos os dados recebidos, use **EdgeSpace - Pesquisa** e o arquivo completo indicado no início do guia. O [índice do módulo](../README.md) mostra a organização dos scripts, consultas e relatórios.
