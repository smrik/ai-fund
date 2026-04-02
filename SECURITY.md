# Security Policy

## Reporting a Vulnerability

Do not open public GitHub issues for suspected security vulnerabilities.

Instead:

1. Email the maintainer directly with:
   - a concise summary
   - reproduction details
   - impact assessment
   - any suggested mitigation
2. Treat credentials, tokens, private data extracts, and local dossier material as sensitive by default.

## Scope

This repository contains:

- local research workflow automation
- API and frontend code
- deterministic valuation and data-processing logic
- machine-local configuration patterns

The highest-risk classes of issues are:

- accidental secret disclosure
- unsafe handling of local research artifacts
- workflow paths that bypass review or branch protection
- code paths that mix LLM judgment into deterministic valuation logic

## Expectations

- never commit secrets or local `.env` material
- prefer responsible private reporting over public disclosure
- include the affected path or workflow and the exact risk scenario when reporting
