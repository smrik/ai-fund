# Patrik's Guide

## Understanding

`dashboard/` - legacy streamlit

`src\stage_02_valuation\professional_dcf.py`:

- we validate drivers to be correct (or within reasonable bounds) with `_validate_drivers` function

## Patrik's comments

- there should be a view for adjusting `config.yaml` numbers, this is way to vague and hard to read...:

```python
File: src\stage_02_valuation\wacc.py
23: def _load_wacc_params() -> dict:
24:     """Load Rf/ERP from config/config.yaml with hardcoded fallbacks."""
25:     config_path = Path(__file__).resolve().parent.parent.parent / "config" / "config.yaml"
26:     try:
27:         with config_path.open("r", encoding="utf-8") as f:
28:             cfg = yaml.safe_load(f) or {}
29:         return cfg.get("wacc_params", {})
30:     except Exception:
31:         return {}
```
