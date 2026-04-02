# Alpha Pod

Alpha Pod is an AI-augmented fundamental research system built around a strict separation between deterministic finance code and selective LLM judgment.

## Core Architecture

- `src/stage_00_data/`: deterministic ingestion from yfinance, EDGAR, CIQ, FRED, and related sources
- `src/stage_01_screening/` and `src/stage_02_valuation/`: deterministic screening, DCF, WACC, factor, and portfolio-risk logic
- `src/stage_03_judgment/`: judgment-only agents that must not feed numbers directly into deterministic intrinsic value logic
- `src/stage_04_pipeline/`: orchestration, dashboard support, refresh flows, and export helpers

## Documentation

- [Agent Map](AGENTS.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Release Process](docs/reference/release-process.md)
- [Docs Home](docs/index.md)
- [Repository Guidance](docs/PLANS.md)
- [Architecture Overview](docs/design-docs/architecture-overview.md)
- [Workflow End To End](docs/handbook/workflow-end-to-end.md)
- [React Frontend Setup And Runtime Map](docs/handbook/react-frontend-setup.md)
- [React Playwright Review Loop](docs/handbook/react-playwright-review-loop.md)
- [Plan Registry](docs/plans/index.md)

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in only the secrets you actually need on this machine.
3. Review `config/config.yaml` for committed project defaults.
4. Run `python setup.py` to initialize the local database.
5. Run `python -m pytest -q` to verify the environment.

## Local Git Hygiene

Install the local git hooks once per clone:

```bash
python -m pip install pre-commit ruff pytest
python -m pre_commit install
python -m pre_commit install --hook-type pre-push
```

Before pushing a branch, run the lightweight local gate:

```bash
python scripts/dev/run_local_quality_gate.py
```

That command runs Ruff on changed Python files versus `origin/main` and then runs the architecture-boundary test. To force a full-repo Ruff pass:

```bash
python scripts/dev/run_local_quality_gate.py --all-files
```

## Release Readiness

The repo now uses a canonical repo version in `VERSION` and tracks release notes in `CHANGELOG.md`.

To validate release metadata without generating artifacts:

```bash
python scripts/release/prepare_mock_release.py --check-only
```

### Optional Conda Setup

If you use Conda, create the environment with:

`conda env create -f environment.yml`

## Local Docs Preview

```bash
python -m pip install mkdocs mkdocs-material
python -m mkdocs serve
```

## One-Script Dashboard Run

For the React dashboard + FastAPI backend on WSL, use the launcher script:

```bash
bash scripts/manual/launch-react-wsl.sh
```

Useful variants:

```bash
bash scripts/manual/launch-react-wsl.sh --status
bash scripts/manual/launch-react-wsl.sh --stop
bash scripts/manual/launch-react-wsl.sh --bootstrap
```

After changing `.env`, restart the stack so the backend reloads the new keys:

```bash
bash scripts/manual/launch-react-wsl.sh --stop
bash scripts/manual/launch-react-wsl.sh
```

Default URLs:

- frontend: `http://127.0.0.1:4173`
- API: `http://127.0.0.1:8000`

## Notes

- `config/config.yaml` is the committed configuration source of truth.
- `.env` is only for local secrets and machine-specific overrides.
- `.env.example` is the safe template for onboarding.
