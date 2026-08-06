# Data

This folder contains saved local data and generated files.

| Path | Purpose | Keep it? |
| --- | --- | --- |
| `alpha_pod.db` | Main local SQLite database | Yes |
| `exports/{TICKER}_Standard.xlsx` | Refreshed CIQ workbook for database loading | Yes |
| `ciq_archive/` | Saved copies of successful CIQ refreshes | Yes |
| `exports/generated/` | Generated PM review files | Can rebuild |
| `valuations/` | Generated valuation files | Can rebuild |
| `cache/` | Downloaded source cache | Can rebuild |

Source code and workbook templates do not belong here.

The CIQ source template is in `ciq/templates/`.

PM review templates are in `templates/`.

Read [Storage And Runtime Data](../docs/reference/storage-runtime-map.md) before you delete a file.
