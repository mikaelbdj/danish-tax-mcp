# danish-tax-mcp

MCP server for Danish personal income tax. It has the yearly rates and thresholds, each
with the official source it came from, and calculators for income tax and the skattekort.

The results are estimates for planning. What you actually owe is set by your årsopgørelse
from Skattestyrelsen.

## Install

You need [uv](https://docs.astral.sh/uv/). For Claude Code:

```sh
claude mcp add dk-tax -- uvx --from git+https://github.com/mikaelbdj/danish-tax-mcp@v0.1.0 dk-tax
```

Other MCP clients can run the same command over stdio.

## Tools

| Tool | |
|---|---|
| `list_figures(year)` | The figure keys for a year, with name and unit |
| `get_figures(year, keys)` | Values with source, date checked and status |
| `get_kommune(year, kommune)` | Kommuneskat, kirkeskat, skatteloftsnedslag and grundskyld |
| `estimate_salary_tax(...)` | Income tax for an unmarried employee, with take-home pay and marginal rate |
| `estimate_payslip(...)` | Trækprocent and månedsfradrag from a forskudsopgørelse, monthly payout, share vests and expected restskat (2026 onwards) |

Example questions:

- Hvad er topskattegrænsen i 2027?
- How much tax do I pay on 900.000 kr. in Aarhus?
- What happens to my trækprocent if I put my bonus and RSUs in the forskudsopgørelse?

## Coverage

Income years 2025 to 2027, and all 98 kommuner. 2023 is included only because the
official worked example is from that year. Married couples, aktieindkomst,
ejendomsværdiskat and the positivliste are not covered yet.

## Testing

The salary calculator reproduces svmn.dk's worked example for 2023 to the øre, and the
skatteloft reduction matches svmn.dk's table for every kommune in 2025 to 2027. The
skattekort formulas reproduce SKAT's examples. Where the law doesn't settle something
(mostly rounding), the assumption is written down in the docstring of `calc/salary.py`
or `calc/payslip.py`.

```sh
uv run pytest
uv run dk-tax     # start the server
```

## Data

One YAML file per year in `src/dk_tax/figures/`:

```yaml
bundskat:
  name: Bundskatteprocent     # term used in the source
  value: 12.01                # as printed: 12.01 means 12,01 %
  unit: percent               # percent or DKK
  source: https://svmn.dk/...
  verified: 2026-11-01
  status: verified            # verified, secondary, unverified or proposed
  note: PSL § 6.
```

Keys are the Danish terms with æ, ø, å written as ae, oe, aa. They follow the law of each
year, so 2025 has the old 15 % topskat and no mellemskat.

New figures come out every autumn. [CONTRIBUTING.md](CONTRIBUTING.md) describes how to add
a year.

## License

MIT
