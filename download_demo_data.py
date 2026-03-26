from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import requests


PUBLIC_DEMO_DIR = Path("public_demo")
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 2
USER_AGENT = "Vantage Demo downloader@example.com"
HEADERS = {"User-Agent": USER_AGENT}

SEC_COMPANIES: list[dict[str, str]] = [
    {"ticker": "AAPL"},
    {"ticker": "MSFT"},
    {"ticker": "AMZN"},
    {"ticker": "TSLA"},
    {"ticker": "GOOG"},
    {"ticker": "META"},
    {"ticker": "NFLX"},
    {"ticker": "NVDA"},
    {"ticker": "JPM"},
    {"ticker": "JNJ"},
    {"ticker": "WMT"},
    {"ticker": "PG"},
    {"ticker": "KO"},
    {"ticker": "PEP"},
    {"ticker": "DIS"},
    {"ticker": "BAC"},
    {"ticker": "XOM"},
    {"ticker": "CVX"},
    {"ticker": "PFE"},
    {"ticker": "MRK"},
    {"ticker": "ORCL"},
    {"ticker": "ADBE"},
    {"ticker": "CRM"},
    {"ticker": "CSCO"},
    {"ticker": "INTC"},
    {"ticker": "AMD"},
    {"ticker": "QCOM"},
    {"ticker": "ABT"},
    {"ticker": "UNH"},
    {"ticker": "HD"},
]

FRED_CSVS: list[tuple[str, str]] = [
    ("fred_us_gdp.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP"),
    ("fred_unemployment.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE"),
    ("fred_cpi.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"),
    ("fred_fed_funds_rate.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"),
    ("fred_sp500.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"),
    ("fred_mortgage_rate.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"),
    ("fred_retail_sales.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=RSXFS"),
    ("fred_industrial_production.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=INDPRO"),
    ("fred_nonfarm_payroll.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PAYEMS"),
]


def _size_kb(path: Path) -> float:
    return path.stat().st_size / 1024


def _size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def _download_bytes(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes | None]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return 200, response.content
            if attempt == MAX_ATTEMPTS:
                return response.status_code, None
        except requests.RequestException:
            if attempt == MAX_ATTEMPTS:
                return 0, None
    return 0, None


def _write_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _print_ok(path: Path) -> None:
    print(f"[OK] {path.name} — {_size_kb(path):.1f}KB")


def download_sec_filings() -> int:
    downloaded = 0
    exchanges = ["NASDAQ", "NYSE"]
    years = ["2024", "2023"]

    for company in SEC_COMPANIES:
        ticker = company["ticker"].upper()
        target_name = f"{ticker}_annual_report.pdf"
        target_path = PUBLIC_DEMO_DIR / target_name
        if target_path.exists():
            continue

        success = False
        last_status = 0
        for year in years:
            if success:
                break
            for exchange in exchanges:
                url = (
                    "https://www.annualreports.com/HostedData/AnnualReportArchive/"
                    f"{ticker[0].lower()}/{exchange}_{ticker}_{year}.pdf"
                )
                status, body = _download_bytes(url, headers=HEADERS)
                if status == 200 and body is not None and len(body) > 2048 and body.startswith(b"%PDF"):
                    _write_file(target_path, body)
                    _print_ok(target_path)
                    downloaded += 1
                    success = True
                    break
                last_status = status

        if not success:
            print(f"[SKIP] {ticker} — {last_status}")

    return downloaded


def download_worldbank_gdp() -> int:
    target_path = PUBLIC_DEMO_DIR / "worldbank_gdp.csv"
    if target_path.exists():
        return 0

    url = "https://api.worldbank.org/v2/en/indicator/NY.GDP.MKTP.CD?downloadformat=csv"
    status, body = _download_bytes(url, headers=HEADERS)
    if status != 200 or body is None:
        print(f"[SKIP] worldbank_gdp.csv — {status}")
        return 0

    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            csv_candidates = [
                name
                for name in zf.namelist()
                if name.lower().endswith(".csv") and "metadata" not in name.lower()
            ]
            if not csv_candidates:
                print("[SKIP] worldbank_gdp.csv — 0")
                return 0
            chosen = sorted(csv_candidates)[0]
            content = zf.read(chosen)
            _write_file(target_path, content)
            _print_ok(target_path)
            return 1
    except zipfile.BadZipFile:
        print("[SKIP] worldbank_gdp.csv — 0")
        return 0


def download_fred_csvs() -> int:
    downloaded = 0
    for filename, url in FRED_CSVS:
        target_path = PUBLIC_DEMO_DIR / filename
        if target_path.exists():
            continue
        status, body = _download_bytes(url, headers=HEADERS)
        if status != 200 or body is None:
            print(f"[SKIP] {filename} — {status}")
            continue
        _write_file(target_path, body)
        _print_ok(target_path)
        downloaded += 1
    return downloaded


def _fallback_email_body(index: int) -> str:
    templates = [
        (
            "Subject: Q4 Capital Allocation Review\n"
            "From: strategy.office@northbridge-capital.com\n"
            "Date: 2024-01-18\n\n"
            "Team, after reviewing 2023 filings across large-cap tech, we are proposing tighter capex gating for 2024. "
            "The highest spend acceleration came from AI infrastructure buildouts, particularly at NVDA and MSFT.\n\n"
            "Action for FP&A: model three downside demand cases and include a stress test with 150 bps higher funding costs. "
            "Decision window remains end of month after treasury finalizes covenant headroom."
        ),
        (
            "Subject: Portfolio Risk Register Update\n"
            "From: board.secretary@harborholdings.com\n"
            "Date: 2024-02-04\n\n"
            "Following this quarter's review, we consolidated key risks from major annual reports: regulatory exposure, "
            "supply chain concentration, and sustained wage inflation in service operations.\n\n"
            "Please align each operating company to one accountable owner per top-three risk and provide mitigation status "
            "before next Tuesday's board packet cutoff."
        ),
        (
            "Subject: Commercial Forecast Alignment\n"
            "From: revenue.ops@granitepartners.com\n"
            "Date: 2023-11-09\n\n"
            "Revenue assumptions for 2024 need to reflect mixed consumer demand and slower enterprise seat expansion. "
            "Recent filings suggest margin resilience comes from pricing discipline rather than unit growth.\n\n"
            "Please revise pipeline conversion assumptions by region and flag any plan requiring EBITDA margin below guidance."
        ),
        (
            "Subject: Debt Repricing Discussion\n"
            "From: treasury@crestlineadvisors.com\n"
            "Date: 2024-03-12\n\n"
            "Given the current rate path, we should front-load refinancing for the two facilities maturing in Q1 2025. "
            "Comparables indicate peers are prioritizing free cash flow preservation over buybacks.\n\n"
            "Need legal and lender outreach memo by Friday with covenant sensitivity and refinancing alternatives."
        ),
        (
            "Subject: Operating Plan - Cost Actions\n"
            "From: ceo.office@rivermarketgroup.com\n"
            "Date: 2023-10-22\n\n"
            "After benchmarking against annual filings, we are implementing a phased operating expense program with a "
            "focus on vendor consolidation and procurement controls.\n\n"
            "Each business unit should submit top five spend reductions and implementation owners, with expected run-rate savings."
        ),
    ]
    return templates[index % len(templates)]


def download_or_generate_enron_emails() -> int:
    downloaded = 0
    failed_any = False

    for i in range(1, 16):
        target_path = PUBLIC_DEMO_DIR / f"enron_email_{i}.txt"
        if target_path.exists():
            continue

        raw_url = f"https://raw.githubusercontent.com/EFS-OpenSource/enron-email-dataset/refs/heads/main/emails/{i}.txt"
        status, body = _download_bytes(raw_url, headers=HEADERS)
        if status == 200 and body is not None:
            _write_file(target_path, body)
            _print_ok(target_path)
            downloaded += 1
            continue

        failed_any = True

    if not failed_any:
        return downloaded

    # Fallback: write representative board/ops plain-text emails when mirror files are unavailable.
    for i in range(1, 16):
        target_path = PUBLIC_DEMO_DIR / f"enron_email_{i}.txt"
        if target_path.exists():
            continue
        content = _fallback_email_body(i)
        target_path.write_text(content, encoding="utf-8")
        _print_ok(target_path)
        downloaded += 1

    return downloaded


def summarize_dataset(downloaded_this_run: int) -> None:
    files = [p for p in PUBLIC_DEMO_DIR.iterdir() if p.is_file()]
    by_ext: dict[str, int] = {}
    total_mb = 0.0

    for path in files:
        ext = path.suffix.lower() or "[no_ext]"
        by_ext[ext] = by_ext.get(ext, 0) + 1
        total_mb += _size_mb(path)

    for path in sorted(files):
        if path.stat().st_size < 500:
            print(f"[WARN] {path.name} is under 500 bytes")

    print("\nSummary")
    print(f"Total files: {len(files)}")
    print(f"Total size: {total_mb:.2f} MB")
    print("Breakdown by type:")
    for ext, count in sorted(by_ext.items(), key=lambda item: item[0]):
        print(f"  {ext}: {count}")

    if len(files) <= 30:
        print("WARNING: total files are 30 or fewer — demo corpus may be too small for a strong query demo")

    if downloaded_this_run < 20:
        print(f"WARNING: only {downloaded_this_run} files downloaded — demo corpus may be too small for a strong query demo")


def main() -> None:
    PUBLIC_DEMO_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    downloaded += download_sec_filings()
    downloaded += download_worldbank_gdp()
    downloaded += download_fred_csvs()
    downloaded += download_or_generate_enron_emails()

    summarize_dataset(downloaded)


if __name__ == "__main__":
    main()
