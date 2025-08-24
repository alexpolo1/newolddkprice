# newolddkprice

DBA vs PriceRunner price comparator

This small Python tool searches DBA (dba.dk) and PriceRunner for product
results and prints a side-by-side comparison of titles, prices and links.

Features
- Fetch DBA search results (requests or Selenium)
- Fetch PriceRunner search results by extracting embedded JSON from the results page
- Filter results by minimum and maximum price
- Compare results in three output formats: plain text table, Markdown, or an ASCII grid

Quick start

Prerequisites
- Python 3.10+ (or 3.8+)
- pip

Install dependencies (recommended in a virtualenv):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the script (basic example):

```bash
python3 dba_pricerunner_scraper.py "playstation 5" --pricerunner --compare --format markdown --top 8
```

Common options
- `--pricerunner` : fetch PriceRunner results as well
- `--compare` : show a side-by-side comparison (requires `--pricerunner`)
- `--format` : `text` (default), `markdown`, or `grid`
- `--top N` : when used without `--compare`, prints top N DBA results; when used with `--compare` it controls number of rows in the comparison
- `--min-price` / `--max-price` : numeric filters to exclude accessories or outliers

Examples

- Compare PlayStation 5 results and print a Markdown table:
	`python3 dba_pricerunner_scraper.py "playstation 5" --pricerunner --compare --format markdown --top 10`

- Compare Google Pixel results and exclude accessories under 3000 DKK:
	`python3 dba_pricerunner_scraper.py "google pixel 8" --pricerunner --compare --format grid --min-price 3000 --max-price 12000`

Notes
- PriceRunner pages are parsed by extracting an embedded JSON blob. This works at time of writing but may break if the site changes.
- For very reliable scraping of JS-heavy pages, consider installing Playwright or using the Selenium renderer (the script already contains a Selenium path).

License
This project contains a small utility script; add a license file if you plan to publish.

More detailed usage is in `docs/USAGE.md`.