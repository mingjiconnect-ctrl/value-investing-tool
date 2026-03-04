# Value Investing Research System

A reproducible, testable, extensible data-model-report pipeline for value investing research.

## Install
```bash
python -m pip install -r requirements.txt
```

## Run E2E example
```bash
python -m src.cli run --example
```

Expected outputs:
- `outputs/report.md`
- `outputs/valuation.json`
- `outputs/charts/sensitivity_wacc_g.png`
- plus CSV artifacts for reproducibility

## Test
```bash
python -m pytest
```

## Data inputs
- CSV: `src.data.loaders.load_csv`
- Excel: `src.data.loaders.load_excel`
- Manual rows: `src.data.loaders.load_manual_input`
- External providers: implement `DataProvider` interface and pass into pipeline

## Replace data provider
1. Create class under `src/data/providers/` inheriting `DataProvider`.
2. Implement `get_fundamentals/get_prices/get_macro`.
3. Inject provider in pipeline (`run_single_stock`).

## CLI
- Required entry: `python -m src.cli run --example`

## Optional UI
- `apps/streamlit_app.py` placeholder for future extension.
