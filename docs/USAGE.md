# Usage

This document expands on how to run `dba_pricerunner_scraper.py`.

Basic invocation

```bash
python3 dba_pricerunner_scraper.py "search terms" --pricerunner --compare --format grid --top 8
```

Options

- `--engine`: `requests` (default) or `selenium`.
- `--pricerunner`: fetch PriceRunner results.
- `--compare`: show side-by-side comparison.
- `--format`: `text` | `markdown` | `grid`.
- `--min-price` / `--max-price`: filter by price.

Examples

- Top 5 DBA results only:

```bash
python3 dba_pricerunner_scraper.py "playstation 5" --top 5
```

- Compare results and save markdown output:

```bash
python3 dba_pricerunner_scraper.py "playstation 5" --pricerunner --compare --format markdown --top 10 > results.md
```

Notes on Selenium

If you pick `--engine selenium`, install a compatible browser (Chrome) and ensure `chromedriver` is available. `webdriver-manager` can install the driver automatically but still requires a Chrome binary.
