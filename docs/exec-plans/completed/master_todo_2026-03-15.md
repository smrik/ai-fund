# Todo list 2026-03-15

1. Replace remaining use_container_width calls with Streamlit 1.55 width="stretch" / width="content".
2. do the Streamlit deprecation cleanup next.
3. Add options for selecting different metrics for comp valuation (check [SKILL.md](skills/financial-analysis/skills/comps-analysis/SKILL.md) [SKILL.md](skills/financial-analysis/skills/competitive-analysis/SKILL.md) and add everything to the comps tab). In the comps there is no way to see what our company's values are and how each value would compare (maybe a football chart could be nice).
4. Check if the 10-K are actually correct, I don't see any financial statements in them, and I'm pretty sure that the agents don't see the entire thing? how are we doing with embeddings here?
5. Also the news tab only shows the news for last two days? I think that there should be a brief at the top of all material news in the last couple of years or so - to kind of summarize the company changes and events, and then below the table with articles with the most material news in the last quarter
6. Also check all tables for better number formatting (percent should be percent instead of 0.10, and bigger numbers should have 10K instead of 10,000.00 written for better legibility, they should also be aligned correctly and have a one decimal point usually (unless data specifically requires something else), brackets around negative numbers instead of -
7. I would also like there to be multiples tab to compare how the stock is doing compared to it's (and the peers' past multiples) - check out the financial analysis and equity research skills in the skills folder and systematically go through each to check where the gaps our to our current setup.

## Canonical ExecPlan
- [Dashboard Research Surface Remediation and Auditability](./2026-03-15-master-dashboard-and-research-program.md)
- Full implementation plan: [docs/plans/completed/2026-03-15-dashboard-research-program.md](../../plans/completed/2026-03-15-dashboard-research-program.md)

## Supporting Workstream Briefs
- [SP01 Streamlit 1.55 and Presentation System](./2026-03-15-sp01-streamlit-1-55-and-presentation-system.md)
- [SP02 Comps and Multiples Workbench](./2026-03-15-sp02-comps-and-multiples-workbench.md)
- [SP03 Filings Corpus Audit and Retrieval Diagnostics](./2026-03-15-sp03-filings-corpus-audit-and-retrieval-diagnostics.md)
- [SP04 Market Intel History Brief](./2026-03-15-sp04-market-intel-history-brief.md)
- [SP05 Formatting and Table Legibility](./2026-03-15-sp05-formatting-and-table-legibility.md)
- [SP06 Skill Gap Review and Research Surface Audit](./2026-03-15-sp06-skill-gap-review-and-research-surface-audit.md)
