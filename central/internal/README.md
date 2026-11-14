# central/internal/

**Responsável:** Leonardo (M4).

## Pacotes e fluxo de dados
```text
Nicolas/M2 (UDP :5005)
    |
udp/ --> cluster/ --> pipeline/ --> ipc/ <--> Santiago/Leonardo/M5 (Edge AI :5006)
                          |          |
                          v          v
                       session/ ---> store/ (SQLite WAL único escritor)
                          |          |
                          v          v (schema Selliny/M1)
                       httpws/ <---> Rafael/M3 (Painel :8000)
                       
sim/ --(substitui udp em --mock-cluster)--> cluster/ & pipeline/
```
Todos compartilham tipos de [`contracts/`](contracts/README.md).
