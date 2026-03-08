# Patrik's Notes

## Universe workflow

Universe workflow is meant to produce a universe of stocks to evaluate

### Funnel

1. Seed universe
   - all listed US equities?
   - seed_universe.json
2. Stage 1 filter
   - based on:

## File description

### /config/

folder with config files

### /dashboard/

TBD

### /data/

#### /cache/

caching info for seed universe and yfinance info for the screening?

### main.py

does init

## To-do

- maybe add a help file for screening_rules.yaml that would explain the possible flags
  - add finance to excluded sectors
- change to openai oauth preferably to save costs
- maybe explain why do we have screening_rules.yaml, settings.py and **init**.py all with dome some central settings?
  - being improved rn - one yaml + one .env
- why do we have some info in .json, .csv, .db files? I feel like this should be simpler - what would be the fastest option / easiest to implement?

