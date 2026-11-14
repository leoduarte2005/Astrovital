# central/internal/contracts/

**Responsável:** Leonardo (M4). Espelha `contracts/` (guardião Leonardo).

## Propósito
Structs e constantes Go que espelham 1:1 os schemas e enums em `contracts/`.

## Entradas / Saídas
- Usado por todos os demais pacotes em `central/internal/`.
- Testes unitários deste pacote validam serialização/desserialização contra `contracts/fixtures/`.

## Regras
- Proibido inventar campo fora de `contracts/`.
- Manter structs leves para evitar alocações extras no hot path UDP.
