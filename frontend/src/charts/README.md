# frontend/src/charts/

**Responsável:** Rafael (M3). Dados de série temporal vêm de Leonardo (M4) via REST `/api/crew/{crew_id}/timeseries`.

## Propósito
Gráficos de variação longitudinal ao longo da missão, por astronauta.

## Métricas
FC, HRV, FR, SpO2, PA, CO2 cabine, temperatura/umidade, horas de sono, resultados de Amsler/ultrassom ONSD/glicemia capilar.

## Entradas
- Histórico: `GET /api/crew/{crew_id}/timeseries?metric=&from=&to=&bucket=` (decimado no backend).
- Ao vivo: append via `TELEMETRY_FRAME`.

## Regras
- Eixo X em dia de missão (MET); faixa basal individual sombreada.
- Limite de pontos renderizados por gráfico (ex.: 2000) para manter fluidez.
- Biblioteca de gráficos empacotada localmente (sem CDN).
