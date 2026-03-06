# Alpha Pod - AI-augmented fundamental research

Alpha Pod separates deterministic research mechanics from selective LLM judgment.

## Core architecture

- `src/data/`: deterministic data ingestion from yfinance, EDGAR, and CIQ
- `src/valuation/` and `screening/`: deterministic DCF, reverse DCF, WACC, and ranking logic
- `src/agents/`: judgment-only LLM agents that never feed numbers back into intrinsic value computation

## Documentation

- [Docs index](docs/index.md)
- [Handbook](docs/handbook/index.md)
- [Architecture](ARCHITECTURE.md)
- [Deterministic valuation workflow](docs/design-docs/deterministic-valuation-workflow.md)
- [Config reference](docs/reference/config-reference.md)
- [Local wiki setup](docs/reference/local-wiki.md)

### Run docs locally

```bash
python -m pip install mkdocs mkdocs-material
python -m mkdocs serve
```

## Setup

1. Create `.env` from `.env.example` and add `ANTHROPIC_API_KEY`.
2. Review `config/config.yaml` for committed project defaults.
3. Run `python setup.py` to initialize the local database.
4. Run `python -m pytest -q` to verify the environment.

## Notes

- `config/config.yaml` is the single committed configuration source.
- `.env` is only for secrets and machine-local runtime overrides.
- Use `python -m pytest` instead of plain `pytest` if your shell does not include the repo root on `PYTHONPATH`.
