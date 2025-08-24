#!/usr/bin/env python3
"""Minimal scraper for dba.dk search results.

Keeps only the DBA scraping code: requests-based fetch and an optional
Selenium renderer. Provides price parsing, simple location heuristics and
CLI for fetching and printing top results.

Usage: python dba_pricerunner_scraper.py "search terms"
"""

import sys
import time
import json
import re
import argparse
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.options import Options as ChromeOptions
except Exception:
    webdriver = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36"
}


class ScraperError(Exception):
    pass


def normalize_price(price_str):
    """Extract a numeric price (float) from a string like 'kr. 1.234' or '1.234,00 kr'."""
    if not price_str:
        return None
    # remove currency tokens and non-number suffixes
    s = price_str.replace("kr.", "").replace("kr", "").replace("DKK", "")
    s = s.replace("\u00A0", " ")
    s = s.strip()

    # keep only digits, dot, comma and spaces for analysis
    import re
    cleaned = re.sub(r"[^0-9\.,\s]", "", s)
    if not cleaned:
        return None

    # If there are separators followed by exactly three digits (e.g. '3.250' or '1 234'),
    # it's very likely a thousands separator. Remove dots/spaces in that case.
    if re.search(r'(?:[\.\s]\d{3})', cleaned):
        core = re.sub(r'[\.\s]', '', cleaned)
        core = core.replace(',', '.')
        core = ''.join(ch for ch in core if (ch.isdigit() or ch == '.'))
        try:
            return float(core)
        except Exception:
            return None

    # Decide which of '.' or ',' is the decimal separator by looking at the last occurrence
    last_dot = cleaned.rfind('.')
    last_comma = cleaned.rfind(',')
    decimal_sep = None
    if last_dot == -1 and last_comma == -1:
        decimal_sep = None
    elif last_dot > last_comma:
        # dot occurs later
        if len(cleaned) - last_dot - 1 in (1, 2, 3):
            decimal_sep = '.'
    else:
        if len(cleaned) - last_comma - 1 in (1, 2, 3):
            decimal_sep = ','

    # remove thousands separators (either '.' or ',') except the decimal separator
    if decimal_sep is None:
        # just remove spaces and separators
        digits = re.sub(r"[\s\.,]", "", cleaned)
        try:
            return float(digits)
        except Exception:
            return None
    else:
        if decimal_sep == '.':
            # remove commas and spaces, keep dot
            core = re.sub(r"[\s,]", "", cleaned)
        else:
            # decimal_sep == ',' -> remove dots and spaces, replace comma with dot
            core = re.sub(r"[\.\s]", "", cleaned)
            core = core.replace(',', '.')
        core = ''.join(ch for ch in core if (ch.isdigit() or ch == '.'))
        try:
            return float(core)
        except Exception:
            return None


def extract_price_string(text):
    """Return a short price string from a larger text blob, e.g. '3.999 kr.' or '150 kr.'

    Uses a regex to find a Danish-style price (thousands sep '.' or space, decimal comma).
    """
    if not text:
        return ''
    # look for number patterns optionally followed/preceded by currency
    import re
    m = re.search(r"(\d{1,3}(?:[\.\s]\d{3})*(?:,\d{1,2})?)\s*(kr\.?|DKK)?", text, flags=re.IGNORECASE)
    if not m:
        # fallback: try a simpler digit sequence
        m = re.search(r"(\d+[\d\.\s,]*)", text)
        if not m:
            return ''
    num = m.group(1)
    cur = m.group(2) or 'kr.'
    cur = cur.strip()
    # normalize currency display
    if cur.upper() == 'DKK':
        cur = 'DKK'
    elif not cur:
        cur = 'kr.'
    return f"{num} {cur}".strip()


def extract_location_from_element(el):
    """Heuristic: try to find a location string near a listing element."""
    if el is None:
        return ''
    for cls in ('cAdList__location', 'ad-location', 'dba-location', 'location', 'by', 'region'):
        node = el.find(class_=cls)
        if node and node.get_text(strip=True):
            return node.get_text(strip=True)
    for small in el.find_all(['small', 'span', 'p']):
        txt = small.get_text(strip=True)
        if txt and any(ch.isdigit() for ch in txt) is False and len(txt) < 60:
            return txt
    return ''


def search_dba_requests(query, max_results=10):
    """Search dba.dk (requests) and return list of dicts with title, price, url, location."""
    q = quote_plus(query)
    url = f"https://www.dba.dk/recommerce/forsale/search?q={q}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise ScraperError(f"DBA returned status {r.status_code}")
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    results = soup.select('article') or soup.select('.cAdList__item') or soup.select('.dba-result')
    for el in results[:max_results]:
        a = el.select_one('h2 a') or el.select_one('a.sf-search-ad-link') or el.select_one('a')
        title = a.get_text(strip=True) if a else ''
        link = urljoin('https://www.dba.dk', a['href']) if a and a.get('href') else None
        price = ''
        for tag in el.find_all(['span', 'div', 'p']):
            txt = tag.get_text(' ', strip=True)
            if not txt:
                continue
            pstr = extract_price_string(txt)
            if pstr:
                price = pstr
                break
        location = ''
        loc_block = el.select_one('.text-xs.s-text-subtle') or el.select_one('.cAdList__location')
        if loc_block:
            sp = loc_block.select_one('span')
            if sp and sp.get_text(strip=True):
                location = sp.get_text(strip=True)
        if not location:
            location = extract_location_from_element(el) or ''
        price_num = normalize_price(price)
        items.append({
            "site": "dba",
            "title": title,
            "price": price,
            "price_num": price_num,
            "url": link,
            "location": location,
        })
    time.sleep(1)
    return items


def search_dba_selenium(query, max_results=10, headless=True):
    """Render DBA with Selenium and extract the same fields as requests path."""
    if webdriver is None:
        raise ScraperError('Selenium or webdriver-manager not installed')
    opts = ChromeOptions()
    if headless:
        opts.add_argument('--headless=new')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
    try:
        q = quote_plus(query)
        url = f"https://www.dba.dk/soeg/?soegeord={q}"
        driver.get(url)
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, 'lxml')
        items = []
        results = soup.select('article') or soup.select('.cAdList__item') or soup.select('.dba-result')
        for el in results[:max_results]:
            a = el.select_one('h2 a') or el.select_one('a.sf-search-ad-link') or el.select_one('a')
            title = a.get_text(strip=True) if a else ''
            link = urljoin('https://www.dba.dk', a['href']) if a and a.get('href') else None
            price = ''
            for tag in el.find_all(['span', 'div', 'p']):
                txt = tag.get_text(' ', strip=True)
                if not txt:
                    continue
                pstr = extract_price_string(txt)
                if pstr:
                    price = pstr
                    break
            location = ''
            loc_block = el.select_one('.text-xs.s-text-subtle') or el.select_one('.cAdList__location')
            if loc_block:
                sp = loc_block.select_one('span')
                if sp and sp.get_text(strip=True):
                    location = sp.get_text(strip=True)
            if not location:
                location = extract_location_from_element(el) or ''
            price_num = normalize_price(price)
            items.append({'site': 'dba', 'title': title, 'price': price, 'price_num': price_num, 'url': link, 'location': location})
        time.sleep(1)
        return items
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def sort_items_by_price(items):
    def keyfn(it):
        v = it.get('price_num')
        return v if v is not None else float('inf')
    return sorted(items, key=keyfn)


def _extract_json_array(text, key):
    """Find a JSON array by key in a large HTML/JS blob and return the array text.

    Scans for '"key":[' and returns the bracketed array (handles nested brackets
    and strings). Returns None on failure.
    """
    needle = f'"{key}":['
    idx = text.find(needle)
    if idx == -1:
        return None
    i = text.find('[', idx)
    if i == -1:
        return None
    in_str = False
    esc = False
    depth = 0
    for j, ch in enumerate(text[i:], start=i):
        if ch == '"' and not esc:
            in_str = not in_str
        if ch == '\\' and not esc:
            esc = True
            continue
        esc = False
        if not in_str:
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    return text[i:j+1]
    return None


def search_pricerunner_requests(query, max_results=10):
    """Fetch PriceRunner search page and extract embedded product JSON (requests).

    Returns list of dicts: title, price, price_num, url, site='pricerunner'.
    """
    q = quote_plus(query)
    url = f"https://www.pricerunner.dk/results?q={q}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise ScraperError(f"PriceRunner returned status {r.status_code}")
    arr_text = _extract_json_array(r.text, 'products')
    items = []
    if not arr_text:
        # fallback: try to find simple product blocks
        soup = BeautifulSoup(r.text, 'lxml')
        cards = soup.select('.product, .product-item, .search-result')
        for el in cards[:max_results]:
            t = el.select_one('.product-title, h3, .title')
            p = el.select_one('.price, .product-price')
            a = el.select_one('a[href]')
            title = t.get_text(strip=True) if t else ''
            price = p.get_text(' ', strip=True) if p else ''
            link = urljoin('https://www.pricerunner.dk', a['href']) if a and a.get('href') else None
            price_num = normalize_price(price)
            items.append({'site': 'pricerunner', 'title': title, 'price': price, 'price_num': price_num, 'url': link})
        return items
    try:
        products = json.loads(arr_text)
    except Exception:
        return items
    for p in products[:max_results]:
        name = p.get('name')
        price = None
        lp = p.get('lowestPrice') or {}
        if isinstance(lp, dict):
            price = lp.get('amount')
        # price may be a string like '3289.00' or None
        price_str = f"{price} {lp.get('currency','')}".strip() if price else ''
        path = p.get('url')
        full = urljoin('https://www.pricerunner.dk', path) if path else None
        price_num = normalize_price(price_str)
        items.append({'site': 'pricerunner', 'title': name, 'price': price_str, 'price_num': price_num, 'url': full})
    time.sleep(1)
    return items


def print_top_results(items, n=5):
    print(f"Top {n} DBA results (title — price — location):\n")
    for it in items[:n]:
        loc = it.get('location') or ''
        print(f"- {it.get('title','')}")
        print(f"  price: {it.get('price','')}\n  location: {loc}\n  url: {it.get('url','')}\n")


def _short(s, n=60):
    if not s:
        return ''
    s = ' '.join(s.split())
    return s if len(s) <= n else s[: n-3] + '...'


def print_comparison_table(dba_items, pr_items, n=5):
    """Print a simple comparison table between DBA and PriceRunner results."""
    rows = []
    maxrows = max(len(dba_items), len(pr_items), n)
    for i in range(maxrows):
        left = dba_items[i] if i < len(dba_items) else None
        right = pr_items[i] if i < len(pr_items) else None
        rows.append((
            str(i+1),
            _short(left.get('title','')) if left else '',
            left.get('price','') if left else '',
            left.get('location','') if left else '',
            _short(right.get('title','')) if right else '',
            right.get('price','') if right else '',
        ))

    # column widths
    widths = [3, 50, 12, 12, 50, 12]
    hdr = ('#', 'DBA title', 'DBA price', 'DBA loc', 'PriceRunner title', 'PR price')
    sep = ' | '
    def fmt(row):
        return sep.join(row[i].ljust(widths[i]) for i in range(len(row)))

    print('\nComparison table (DBA vs PriceRunner):')
    print(fmt(hdr))
    print('-' * (sum(widths) + len(sep) * (len(widths)-1)))
    for r in rows[:n]:
        print(fmt(r))
    print()


def print_comparison_markdown(dba_items, pr_items, n=10):
    """Print a markdown table with two columns: DBA and PriceRunner.

    Each cell contains a linked title (if URL available), price and optional location.
    """
    lines = []
    lines.append("| DBA | PriceRunner |")
    lines.append("|-----|------------|")

    def cell(it):
        if not it:
            return ''
        title = _short(it.get('title',''), 80)
        url = it.get('url','') or ''
        if url:
            title_md = f"[{title}]({url})"
        else:
            title_md = title
        price = it.get('price','')
        loc = it.get('location','')
        parts = [title_md, price]
        if loc:
            parts.append(loc)
        return '<br>'.join(p for p in parts if p)

    for i in range(n):
        left = dba_items[i] if i < len(dba_items) else None
        right = pr_items[i] if i < len(pr_items) else None
        lines.append(f"| {cell(left)} | {cell(right)} |")

    print('\n'.join(lines))
    print()


def print_comparison_grid(dba_items, pr_items, n=10):
    """Print a simple ASCII grid with two columns: DBA and PriceRunner."""
    left_col = []
    right_col = []
    for i in range(n):
        l = dba_items[i] if i < len(dba_items) else None
        r = pr_items[i] if i < len(pr_items) else None
        def cell_lines(it):
            if not it:
                return ['']
            title = it.get('title','')
            price = it.get('price','')
            loc = it.get('location','')
            url = it.get('url','') or ''
            # shorten URL for display
            if url and len(url) > 80:
                url = url[:77] + '...'
            lines = [title, price]
            if loc:
                lines.append(loc)
            if url:
                lines.append(url)
            # wrap lines to preferred width later
            return lines
        left_col.append(cell_lines(l))
        right_col.append(cell_lines(r))
    # preferred maximum widths
    LEFT_MAX = 60
    RIGHT_MAX = 80

    # wrap each cell's lines to the column max width
    def wrap_lines(block, width):
        import textwrap
        wrapped = []
        for line in block:
            if not line:
                wrapped.append('')
            else:
                # use textwrap to preserve words
                for w in textwrap.wrap(line, width=width) or ['']:
                    wrapped.append(w)
        return wrapped

    left_col = [wrap_lines(b, LEFT_MAX) for b in left_col]
    right_col = [wrap_lines(b, RIGHT_MAX) for b in right_col]

    # compute column widths (use the max of wrapped lines but cap at the MAX)
    left_w = min(max((len(line) for block in left_col for line in block), default=10), LEFT_MAX)
    right_w = min(max((len(line) for block in right_col for line in block), default=10), RIGHT_MAX)
    sep = ' | '
    hor = '+' + '-'*(left_w+2) + '+' + '-'*(right_w+2) + '+'
    for idx in range(n):
        lblock = left_col[idx]
        rblock = right_col[idx]
        maxlines = max(len(lblock), len(rblock))
        print(hor)
        for i in range(maxlines):
            lline = lblock[i] if i < len(lblock) else ''
            rline = rblock[i] if i < len(rblock) else ''
            print(f"| {lline.ljust(left_w)} | {rline.ljust(right_w)} |")
    print(hor)
    print()


def main():
    parser = argparse.ArgumentParser(description='Fetch DBA search results')
    parser.add_argument('query', nargs='+')
    parser.add_argument('--engine', choices=['requests', 'selenium'], default='requests')
    parser.add_argument('--max', type=int, default=15)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--top', type=int, default=0, help='Print top N DBA results with price and location')
    parser.add_argument('--pricerunner', action='store_true', help='Fetch PriceRunner search results as well')
    parser.add_argument('--compare', action='store_true', help='Print a comparison table of DBA vs PriceRunner (uses --pricerunner)')
    parser.add_argument('--format', choices=['text', 'markdown', 'grid'], default='text', help='Output format for comparison table')
    parser.add_argument('--min-price', type=str, default=None, help='Filter out items below this price (e.g. 500 or "3.000")')
    parser.add_argument('--max-price', type=str, default=None, help='Filter out items above this price')
    args = parser.parse_args()
    query = ' '.join(args.query)
    print(f"Searching for: {query}\n")
    try:
        if args.engine == 'requests':
            dba = search_dba_requests(query, max_results=args.max)
        else:
            dba = search_dba_selenium(query, max_results=args.max)
    except ScraperError as e:
        print("Error while scraping DBA:", e)
        sys.exit(1)

    pr = []
    if args.pricerunner or args.compare:
        try:
            pr = search_pricerunner_requests(query, max_results=args.max)
        except ScraperError as e:
            print('Error while scraping PriceRunner:', e)

    # parse min/max price args into floats using normalize_price
    def _parse_price_arg(s):
        if s is None:
            return None
        v = normalize_price(s)
        if v is None:
            # try to strip currency and commas
            try:
                s2 = s.replace('.', '').replace(',', '.')
                return float(''.join(ch for ch in s2 if (ch.isdigit() or ch == '.')))
            except Exception:
                return None
        return v

    minp = _parse_price_arg(args.min_price)
    maxp = _parse_price_arg(args.max_price)

    if minp is not None or maxp is not None:
        def in_range(it):
            pn = it.get('price_num')
            if pn is None:
                return False
            if minp is not None and pn < minp:
                return False
            if maxp is not None and pn > maxp:
                return False
            return True
        before_d = len(dba)
        before_p = len(pr)
        dba = [it for it in dba if in_range(it)]
        pr = [it for it in pr if in_range(it)]
        print(f"Applied price filter: min={minp} max={maxp}. DBA: {before_d}->{len(dba)}, PR: {before_p}->{len(pr)}\n")

    print(f"Found {len(dba)} items on DBA\n")
    if args.json:
        print(json.dumps(dba, ensure_ascii=False, indent=2))
        return
    # If the user asked for a simple top-N DBA listing (without compare), show and exit.
    if args.top and args.top > 0 and not args.compare:
        print_top_results(dba, n=args.top)
        return

    if args.pricerunner and not args.compare:
        print(f"Found {len(pr)} items on PriceRunner\n")
        if args.json:
            print(json.dumps(pr, ensure_ascii=False, indent=2))
            return

    if args.compare:
        # sort both lists by price_num for a reasonable alignment
        d_sorted = sort_items_by_price(dba)
        p_sorted = sort_items_by_price(pr)
        if args.format == 'markdown':
            print_comparison_markdown(d_sorted, p_sorted, n=args.top if args.top and args.top>0 else 10)
        elif args.format == 'grid':
            print_comparison_grid(d_sorted, p_sorted, n=args.top if args.top and args.top>0 else 10)
        else:
            print_comparison_table(d_sorted, p_sorted, n=args.top if args.top and args.top>0 else 10)
        return

    dba_sorted = sort_items_by_price(dba)
    print(f"DBA — top {min(len(dba_sorted), args.max)} by price:")
    for it in dba_sorted[:args.max]:
        print(f"- {it.get('title','')} — {it.get('price','')} — {it.get('location','')} — {it.get('url','')}")


if __name__ == '__main__':
    main()
