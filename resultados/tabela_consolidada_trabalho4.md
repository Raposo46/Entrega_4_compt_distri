# Trabalho 4 – Link Extractor: Tabela Consolidada de Desempenho

- **Fonte:** linha `Aggregated` dos relatórios `*_stats.csv` do Locust.
- **Unidades:** latências em milissegundos (`ms`); vazão em requisições por segundo (`req/s`).
- **Regra de Calibragem:** Taxa de Perda = `Failure Count / Request Count × 100` (limite máximo exigido: **10.0%**).

## Métricas dos 12 Cenários

| Linguagem | Modo de Cache | Nível | Usuários Virtuais | Total de Requisições | Falhas | % de Perda | Perda <= 10% | Média (ms) | Mediana (ms) | P90 (ms) | P95 (ms) | P99 (ms) | Máximo (ms) | Vazão (req/s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Python | Sem Cache | U1 | 63 | 612 | 3 | 0.49 | Sim | 3708.06 | 3600.0 | 6100.0 | 6700.0 | 7600.0 | 8004.71 | 13.83 |
| Python | Sem Cache | U2 | 67 | 609 | 6 | 0.99 | Sim | 3958.75 | 3900.0 | 6500.0 | 7000.0 | 7900.0 | 8013.58 | 13.78 |
| Python | Sem Cache | U3 | 70 | 589 | 21 | 3.57 | Sim | 4290.89 | 4100.0 | 7200.0 | 7800.0 | 8000.0 | 8016.32 | 13.32 |
| Python | Com Cache | U1 | 63 | 8339 | 0 | 0.0 | Sim | 2.65 | 2.0 | 4.0 | 4.0 | 6.0 | 669.84 | 188.24 |
| Python | Com Cache | U2 | 67 | 8958 | 0 | 0.0 | Sim | 2.83 | 2.0 | 4.0 | 4.0 | 6.0 | 630.86 | 202.1 |
| Python | Com Cache | U3 | 70 | 9324 | 0 | 0.0 | Sim | 3.09 | 2.0 | 4.0 | 4.0 | 6.0 | 648.44 | 210.41 |
| Ruby | Sem Cache | U1 | 63 | 2165 | 131 | 6.05 | Sim | 794.49 | 280.0 | 1000.0 | 8000.0 | 8000.0 | 8015.48 | 48.84 |
| Ruby | Sem Cache | U2 | 67 | 1920 | 152 | 7.92 | Sim | 1011.16 | 340.0 | 1500.0 | 8000.0 | 8000.0 | 8015.72 | 43.27 |
| Ruby | Sem Cache | U3 | 70 | 1745 | 173 | 9.91 | Sim | 1198.81 | 350.0 | 3100.0 | 8000.0 | 8000.0 | 8015.36 | 39.41 |
| Ruby | Com Cache | U1 | 63 | 3720 | 104 | 2.8 | Sim | 350.12 | 140.0 | 250.0 | 280.0 | 8000.0 | 8018.56 | 84.06 |
| Ruby | Com Cache | U2 | 67 | 3743 | 120 | 3.21 | Sim | 387.57 | 150.0 | 270.0 | 330.0 | 8000.0 | 8016.55 | 84.48 |
| Ruby | Com Cache | U3 | 70 | 3758 | 132 | 3.51 | Sim | 408.81 | 140.0 | 260.0 | 330.0 | 8000.0 | 8014.99 | 84.88 |

## Estatísticas do Cache Redis (Baterias Com Cache)

| executado_em | linguagem | nivel | usuarios | cache_inicio | hits | misses | taxa_acerto_pct | chaves_no_redis |
|---|---|---|---|---|---|---|---|---|
| 2026-10-30T22:19:22 | python | U1 | 63 | frio | 8390 | 31 | 99.63 | 10 |
| 2026-10-30T22:20:16 | python | U2 | 67 | frio | 8999 | 40 | 99.56 | 10 |
| 2026-10-30T22:21:11 | python | U3 | 70 | frio | 9364 | 51 | 99.46 | 10 |
| 2026-10-30T22:25:16 | ruby | U1 | 63 | frio | 3636 | 44 | 98.8 | 10 |
| 2026-10-30T22:26:10 | ruby | U2 | 67 | frio | 3642 | 48 | 98.7 | 10 |
| 2026-10-30T22:27:04 | ruby | U3 | 70 | frio | 3646 | 46 | 98.75 | 10 |
