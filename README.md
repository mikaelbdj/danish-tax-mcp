# dk-tax

Danish personal tax figures and calculators, exposed as an MCP server. Every figure
carries its official source (skat.dk, svmn.dk, retsinformation.dk), the date it was
checked, and a status, so an agent can cite instead of guessing.

**Not tax advice.** The calculators estimate; your årsopgørelse decides.

## Tools

| Tool | What it does |
|---|---|
| `list_figures(year)` | Index of the figure keys for an income year (name, unit) |
| `get_figures(year, keys)` | Values with source, verified date and status |
| `get_kommune(year, kommune)` | Kommuneskat, kirkeskat, skatteloftsnedslag, grundskyld for a municipality |
| `estimate_salary_tax(...)` | One year's income tax for an unmarried employee, full breakdown, take-home, effective and marginal rate |
| `estimate_payslip(...)` | Skattekort (trækprocent, månedsfradrag) from a forskudsopgørelse, normal- and bonus-month payout, share vests, year-end restskat (2026+) |

## Data

`src/dk_tax/figures/<year>.yaml`: one record per figure.

```yaml
bundskat:
  name: Bundskatteprocent          # exact term in the source
  value: 12.01                     # as printed (percent as 12.01, amounts in whole DKK)
  unit: percent                    # percent | DKK
  source: https://svmn.dk/...
  verified: 2026-11-01
  status: verified                 # verified | secondary | unverified | proposed
  note: PSL § 6.
```

Keys are the Danish terms in ASCII snake_case and follow the law of that year (2025 has
the old 15 % topskat; mellemskat/toptopskat start in 2026). `figures/kommuner/<year>.yaml`
is generated from Skatteministeriet's Excel file by `scripts/kommuner_from_xlsx.py`.
Shipped years: 2023 (official worked example only), 2025, 2026, 2027.

## Correctness

- `estimate_salary_tax` reproduces svmn.dk's official 2023 worked example to the øre, and
  the skatteloft reduction for all 98 kommuner in svmn.dk's tables (2025–2027).
- The skattekort formulas reproduce SKAT's worked examples (trækprocent, fradrag).
- Rules and assumptions, with § references, are in the module docstrings of
  `calc/salary.py` and `calc/payslip.py`.

Not covered: married couples, aktieindkomst, ejendomsværdiskat, under-18/senior rules.

## Develop

```sh
uv run pytest
uv run dk-tax          # stdio MCP server
```
