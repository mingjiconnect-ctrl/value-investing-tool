# Architecture

The system is organized as a reproducible data-model-report pipeline:
1. Data input layer (manual/CSV/Excel/provider).
2. Normalization layer (financial standardization + owner earnings).
3. Valuation layer (DCF, scenarios, sensitivity, SOTP framework).
4. Risk layer (Monte Carlo, drawdown, stress presets).
5. Portfolio layer (allocation + constrained Kelly + rebalance).
6. Reporting/export layer (JSON/CSV/charts/markdown).
7. CLI pipeline orchestration.
