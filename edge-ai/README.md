# edge-ai/ — Inteligência Artificial Local (Python + ONNX)

**Responsável:** Santiago / Leonardo (M5). Guia: [`docs/members/MEMBER-05-EDGE-AI-ADAPTIVE.md`](../docs/members/MEMBER-05-EDGE-AI-ADAPTIVE.md)

## Propósito
Worker Python em `127.0.0.1:5006` executando DSP RuView para 1 antena, modelos `.onnx` (`onnxruntime` CPU ARM64), adaptação individual por `crew_id` (hot-swap) e correlação causal sobre a base clínica NASA HRP/CSA de Selliny (M1).

## Integração
- Consome: CSI/I2C de Leonardo (M4), base SQLite (Selliny/M1), datasets (Selliny/M1).
- Produz: inferências, anomalias, correlações para Leonardo (M4).

## Estrutura
| Pasta | Conteúdo |
| :--- | :--- |
| [`models/`](models/README.md) | Modelos `.onnx` base e baselines individuais `baseline_ae_<crew_id>.onnx` |
| [`training/`](training/README.md) | Scripts de treino em solo (Teacher-Student e autoencoders) |
| [`src/edgespace_ai/`](src/edgespace_ai/README.md) | Pacote de runtime (`dsp/`, `inference/`, `adaptation/`, `correlation/`) |

## Regras
- Runtime usa apenas `numpy`, `scipy`, `onnxruntime` e `sqlite3` padrão (`mode=ro`). Sem PyTorch em produção.
- Proibido escrever no SQLite (toda persistência volta à Central via IPC `:5006`).
- Dependências empacotadas em wheels locais para instalação `--no-index`.
