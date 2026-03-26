from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests


BASE_DIR = Path("data/raw/edgar")
RATE_LIMIT_SECONDS = 0.5
TIMEOUT_SECONDS = 30
HEADERS = {"User-Agent": "Vantage Demo contact@example.com"}


@dataclass(frozen=True)
class Company:
    ticker: str
    cik: str


COMPANIES: list[Company] = [
    Company("AAPL", "0000320193"),
    Company("MSFT", "0000789019"),
    Company("GOOGL", "0001652044"),
    Company("AMZN", "0001018724"),
    Company("META", "0001326801"),
    Company("TSLA", "0001318605"),
]

_last_request_ts = 0.0


def _sleep_for_rate_limit() -> None:
    global _last_request_ts
    now = time.monotonic()
    elapsed = now - _last_request_ts
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)


def _sec_get(url: str, stream: bool = False) -> requests.Response:
    global _last_request_ts
    _sleep_for_rate_limit()
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS, stream=stream)
    _last_request_ts = time.monotonic()
    response.raise_for_status()
    return response


def _full_text_search_url(ticker: str, cik: str) -> str:
    query = quote(f"ticker:{ticker} AND cik:{cik} AND formType:\"10-K\"")
    return f"https://www.sec.gov/edgar/search/#/q={query}"


def _latest_10k_index_url(cik: str) -> str:
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = _sec_get(submissions_url).json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])

    for form, accession in zip(forms, accessions):
        if str(form).upper() == "10-K":
            cik_int = int(cik)
            accession_nodashes = str(accession).replace("-", "")
            return (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik_int}/{accession_nodashes}/{accession}-index.html"
            )

    raise RuntimeError("No 10-K filing found in recent submissions")


def _extract_table_rows(html: str) -> Iterable[tuple[str, str]]:
    table_match = re.search(
        r'<table[^>]*class="[^"]*tableFile[^"]*"[^>]*>(.*?)</table>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not table_match:
        return []

    rows: list[tuple[str, str]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", table_match.group(1), flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)
        if len(cells) < 4:
            continue

        href_match = re.search(r'href="([^"]+)"', cells[2], flags=re.IGNORECASE)
        if not href_match:
            continue

        href = href_match.group(1).strip()
        doc_type = re.sub(r"<[^>]+>", "", cells[3]).strip().upper()
        rows.append((href, doc_type))

    return rows


def _normalize_doc_url(index_url: str, href: str) -> str:
    absolute = urljoin(index_url, href)
    parsed = urlparse(absolute)

    if "/ixviewer/ix.html" in parsed.path and parsed.query:
        doc_path = parse_qs(parsed.query).get("doc", [""])[0]
        if doc_path:
            return urljoin("https://www.sec.gov", doc_path)

    return absolute


def _choose_primary_document(index_url: str) -> str:
    html = _sec_get(index_url).text
    rows = list(_extract_table_rows(html))
    if not rows:
        raise RuntimeError("No document rows found on filing index page")

    # Prefer a PDF if present; otherwise use the first listed filing document.
    for href, _doc_type in rows:
        if href.lower().endswith(".pdf"):
            return _normalize_doc_url(index_url, href)

    return _normalize_doc_url(index_url, rows[0][0])


def _download_file(url: str, destination: Path) -> int:
    response = _sec_get(url, stream=True)
    total_bytes = 0
    with destination.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            handle.write(chunk)
            total_bytes += len(chunk)
    return total_bytes


def _extension_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    return suffix or ".htm"


def main() -> int:
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    succeeded = 0
    failed = 0
    total_bytes = 0

    for company in COMPANIES:
        ticker = company.ticker
        try:
            search_url = _full_text_search_url(ticker, company.cik)
            index_url = _latest_10k_index_url(company.cik)
            primary_doc_url = _choose_primary_document(index_url)

            extension = _extension_from_url(primary_doc_url)
            filename = f"{ticker.lower()}_10k{extension}"
            out_path = BASE_DIR / filename

            file_bytes = _download_file(primary_doc_url, out_path)
            total_bytes += file_bytes
            succeeded += 1
            print(f"Downloaded: {filename} ({file_bytes / 1024:.1f} KB)")
        except Exception as error:  # noqa: BLE001 - continue on a single-ticker failure
            failed += 1
            print(f"Warning: failed to download {ticker} 10-K: {error}")
            print(f"Search URL: {search_url if 'search_url' in locals() else 'n/a'}")
            continue

    print("\nSummary")
    print(f"Succeeded: {succeeded}")
    print(f"Failed: {failed}")
    print(f"Total downloaded: {total_bytes / (1024 * 1024):.2f} MB")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
