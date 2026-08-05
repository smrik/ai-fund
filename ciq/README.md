# Capital IQ Loading

This folder contains the Capital IQ Excel loading tools.

The loading chain is:

```text
ciq/templates/financials_input.json
  -> ciq/templates/ciq_cleandata.xlsx
  -> data/exports/{TICKER}_Standard.xlsx
  -> data/alpha_pod.db
```

`ciq/templates/ciq_cleandata.xlsx` is the main CIQ Standard source template.

`ciq/templates/financials_input.json` controls the ticker, date, and currency.

Power Query reads this fixed local path:

```text
C:\Projects\03-Finance\ai-fund\ciq\templates\financials_input.json
```

Do not move the control file. A move will break the current Excel refresh.

Generated PM review workbooks do not belong here. They go in `data/exports/generated/`.

Read [CIQ Operations](../docs/handbook/operations-runbook.md#ciq-single-ticker-refresh) for instructions.
