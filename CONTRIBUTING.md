# Contributing

If you find a wrong figure or rule, please open an issue and include the official source
(a URL, and the § or JV section if you have it).

## Figures

Use official sources only: skat.dk, info.skat.dk, svmn.dk and retsinformation.dk. A value
from anywhere else gets `status: secondary` and a note saying where it came from.

Write values the way the source prints them, so 12,01 % becomes `12.01`. Set `verified`
to the day you compared the value with the source. If a value isn't final yet, for example
because a bill hasn't passed, use `proposed` or `unverified` and add a note.
`tests/test_data.py` checks these rules.

## Adding a year

Figures for a year are usually published the autumn before. From November,
`test_next_year_has_figures` fails until the next year is added.

1. Copy the latest file in `src/dk_tax/figures/` and rename it to the new year.
2. Update the values from svmn.dk's "Satser og beløbsgrænser i lovgivningen" (the pages for
   personskatteloven, ligningsloven, pensionsbeskatningsloven, aktiesparekontoloven,
   arbejdsmarkedsbidragsloven, pensionsafkastbeskatningsloven and ejendomsskatteloven).
3. If brackets were added or removed, update `calc/salary.py` and `calc/payslip.py` and
   branch on the year, as `REFORM_YEAR` does for 2026.
4. Generate the kommune table from Skatteministeriet's Excel file (linked from
   "Kommuneskatteprocenter siden 1977" on svmn.dk):

   ```sh
   uv run python scripts/kommuner_from_xlsx.py <year> <xlsx URL>
   ```

5. Compare with skat.dk's rate overview. A DIFF is a reason to look again, not to copy
   the value, since the YAML cites svmn.dk or the law:

   ```sh
   uv run python scripts/check_satser.py <year>
   ```

6. Add a few of the new values to `test_pinned_values` in `tests/test_data.py` and run
   `uv run pytest`.

## Checks

CI runs these on every push. Run them before you open a pull request:

```sh
uv run ruff check .
uv run ruff format .
uv run pytest
```

The lint rules are listed in `pyproject.toml`, and ruff is pinned in the dev group so
everyone gets the same results.

## Evals

`evals/run_evals.py` asks Claude nine realistic questions with only this server attached
and checks which tools it called, with what inputs, and that the answer cites a source and
the income year. It uses your Claude Code login and costs about half a dollar per run, so
it is run by hand before a release, not in CI:

```sh
uv run python evals/run_evals.py
```

Add a case when you add a tool or find a question Claude gets wrong.
