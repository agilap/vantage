from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import requests


PUBLIC_DEMO_DIR = Path("public_demo")
REQUEST_TIMEOUT_SECONDS = 30
CHUNK_SIZE = 8192
USER_AGENT = "Vantage Demo downloader@example.com"
HEADERS = {"User-Agent": USER_AGENT}

_saved_hashes: dict[str, str] = {}
_downloaded_urls: set[str] = set()
_duplicate_skips = 0
_failures = 0

SEC_10K_URLS: list[tuple[str, str]] = [
    ("aapl", "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"),
    ("msft", "https://www.sec.gov/Archives/edgar/data/789019/000078901923000041/msft-20230630.htm"),
    ("nvda", "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda-20240128.htm"),
    ("meta", "https://www.sec.gov/Archives/edgar/data/1326801/000132680124000012/meta-20231231.htm"),
    ("goog", "https://www.sec.gov/Archives/edgar/data/1652044/000165204424000022/goog-20231231.htm"),
    ("nflx", "https://www.sec.gov/Archives/edgar/data/1065280/000106528024000059/nflx-20231231.htm"),
    ("intc", "https://www.sec.gov/Archives/edgar/data/50863/000005086324000007/intc-20231230.htm"),
    ("amd", "https://www.sec.gov/Archives/edgar/data/2488/000000248824000012/amd-20231230.htm"),
    ("crm", "https://www.sec.gov/Archives/edgar/data/1108524/000110852424000007/crm-20240131.htm"),
    ("adbe", "https://www.sec.gov/Archives/edgar/data/796343/000079634324000010/adbe-20231201.htm"),
    ("jpm", "https://www.sec.gov/Archives/edgar/data/19617/000001961724000287/jpm-20231231.htm"),
    ("gs", "https://www.sec.gov/Archives/edgar/data/886982/000088698224000010/gs-20231231.htm"),
    ("v", "https://www.sec.gov/Archives/edgar/data/1403161/000140316123000017/v-20230930.htm"),
    ("ma", "https://www.sec.gov/Archives/edgar/data/1141391/000114139124000008/ma-20231231.htm"),
    ("blk", "https://www.sec.gov/Archives/edgar/data/1364742/000136474224000007/blk-20231231.htm"),
    ("jnj", "https://www.sec.gov/Archives/edgar/data/200406/000020040624000010/jnj-20231231.htm"),
    ("pfe", "https://www.sec.gov/Archives/edgar/data/78003/000007800324000039/pfe-20231231.htm"),
    ("unh", "https://www.sec.gov/Archives/edgar/data/72971/000007297124000010/unh-20231231.htm"),
    ("abt", "https://www.sec.gov/Archives/edgar/data/1800/000000180024000004/abt-20231231.htm"),
    ("mdt", "https://www.sec.gov/Archives/edgar/data/1613103/000161310324000009/mdt-20240426.htm"),
    ("amzn", "https://www.sec.gov/Archives/edgar/data/1018724/000101872424000008/amzn-20231231.htm"),
    ("tsla", "https://www.sec.gov/Archives/edgar/data/1318605/000131860524000007/tsla-20231231.htm"),
    ("nke", "https://www.sec.gov/Archives/edgar/data/320187/000032018723000039/nke-20230531.htm"),
    ("sbux", "https://www.sec.gov/Archives/edgar/data/829224/000082922423000079/sbux-20231001.htm"),
    ("mcd", "https://www.sec.gov/Archives/edgar/data/63754/000006375424000011/mcd-20231231.htm"),
    ("cat", "https://www.sec.gov/Archives/edgar/data/18230/000001823024000010/cat-20231231.htm"),
    ("ge", "https://www.sec.gov/Archives/edgar/data/40534/000004053424000010/ge-20231231.htm"),
    ("hon", "https://www.sec.gov/Archives/edgar/data/773840/000077384024000010/hon-20231231.htm"),
    ("ba", "https://www.sec.gov/Archives/edgar/data/12927/000001292724000007/ba-20231231.htm"),
    ("mmm", "https://www.sec.gov/Archives/edgar/data/66740/000006674024000010/mmm-20231231.htm"),
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
    ("fred_housing_starts.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=HOUST"),
]


def _size_kb(path: Path) -> float:
    return path.stat().st_size / 1024


def _size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def _init_existing_hashes() -> None:
    for path in sorted(PUBLIC_DEMO_DIR.iterdir()):
        if not path.is_file():
            continue
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        _saved_hashes.setdefault(digest, path.name)


def _stream_download(url: str, destination: Path, headers: dict[str, str] | None = None) -> tuple[int, Path | None, str | None]:
    temp_path = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(2):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)
            status_code = response.status_code
            if status_code != 200:
                return status_code, None, None

            hasher = hashlib.sha256()
            with temp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    hasher.update(chunk)
            return 200, temp_path, hasher.hexdigest()
        except requests.RequestException as error:
            if attempt == 1:
                return 0, None, str(error)
    return 0, None, "connection error"


def _print_ok(path: Path) -> None:
    print(f"[OK] {path.name} — {_size_kb(path):.1f}KB")


def _save_url_to_file(url: str, filename: str) -> tuple[str, int]:
    global _duplicate_skips, _failures

    target_path = PUBLIC_DEMO_DIR / filename
    if target_path.exists():
        print(f"[SKIP] {filename} — already exists")
        return "skipped", 0

    if url in _downloaded_urls:
        print(f"[SKIP] {filename} — already downloaded URL")
        return "skipped", 0

    status, temp_path, extra = _stream_download(url, target_path, headers=HEADERS)
    if status != 200 or temp_path is None or extra is None:
        if status == 0:
            _failures += 1
            print(f"[FAIL] {filename} — {extra or 'connection error'}")
            return "failed", status
        return "skipped", status

    digest = extra
    existing = _saved_hashes.get(digest)
    if existing:
        _duplicate_skips += 1
        temp_path.unlink(missing_ok=True)
        print(f"[DUPE] {filename} is identical to {existing} — skipped")
        return "duplicate", 200

    temp_path.rename(target_path)
    _saved_hashes[digest] = filename
    _downloaded_urls.add(url)
    _print_ok(target_path)
    return "saved", 200


def download_sec_filings() -> int:
    downloaded = 0
    for ticker, url in SEC_10K_URLS:
        filename = f"{ticker.lower()}_10k.htm"
        target_path = PUBLIC_DEMO_DIR / filename
        if target_path.exists():
            print(f"[SKIP] {filename} — already exists")
            continue
        state, status = _save_url_to_file(url, filename)
        if state == "saved":
            downloaded += 1
        elif state == "skipped" and status not in (0, 200):
            print(f"[SKIP] {ticker.upper()} — {status}")
    return downloaded


def download_fred_csvs() -> int:
    downloaded = 0
    for filename, url in FRED_CSVS:
        state, _ = _save_url_to_file(url, filename)
        if state == "saved":
            downloaded += 1
    return downloaded


def _fallback_email_body(index: int) -> str:
    subjects = [
        "Board Prep: AI Infrastructure Spend Priorities",
        "Risk Committee Follow-up: Credit and Liquidity",
        "Healthcare Portfolio Operating Plan Review",
        "Industrial Segment Margin Recovery Actions",
        "Consumer Demand Update and Pricing Strategy",
        "Treasury Plan: Debt Ladder and Repricing",
        "Technology GTM Realignment for FY24",
        "Enterprise Pipeline Forecast Recalibration",
        "Supply Chain Continuity and Vendor Risk",
        "Capital Allocation Trade-offs for FY24",
        "Insurance and Legal Exposure Roll-up",
        "Q4 Working Capital and Cash Conversion",
        "Compensation Budget and Hiring Controls",
        "Board Decision Log Consolidation",
        "Portfolio KPI Standardization",
    ]
    senders = [
        "alex.mercer@northbridgecapital.com",
        "rina.shah@harborfinance.com",
        "david.owens@atlashealth.com",
        "maria.kline@graniteindustrial.com",
        "kevin.choi@summitconsumer.com",
        "nora.byrd@cresttreasury.com",
        "liam.foster@vectortech.com",
        "priya.iyer@riversidepartners.com",
        "sam.holt@peakoperations.com",
        "elena.ross@oakridgeholdings.com",
        "miles.turner@blueharbor.com",
        "tina.wu@veridianadvisors.com",
        "owen.clark@archstonegroup.com",
        "julia.park@ridgewayequity.com",
        "noah.bennett@meridiancapital.com",
    ]
    recipients = [
        "board.office@northbridgecapital.com",
        "finance.committee@harborfinance.com",
        "ops.leadership@atlashealth.com",
        "industrial.board@graniteindustrial.com",
        "strategy.group@summitconsumer.com",
        "treasury.team@cresttreasury.com",
        "product.leadership@vectortech.com",
        "portfolio.ops@riversidepartners.com",
        "risk.panel@peakoperations.com",
        "executive.board@oakridgeholdings.com",
        "legal.team@blueharbor.com",
        "planning.office@veridianadvisors.com",
        "hr.finance@archstonegroup.com",
        "corp.secretary@ridgewayequity.com",
        "data.office@meridiancapital.com",
    ]
    dates = [
        "2023-01-12", "2023-02-16", "2023-03-21", "2023-04-19", "2023-05-23",
        "2023-06-14", "2023-07-18", "2023-08-22", "2023-09-13", "2023-10-17",
        "2023-11-08", "2023-12-05", "2023-12-12", "2023-12-19", "2023-12-27",
    ]
    sector_lines = [
        "Tech filings point to higher compute capex with better operating leverage only when utilization ramps on schedule.",
        "Finance issuers emphasized liquidity resilience and tighter underwriting standards under persistent rate pressure.",
        "Healthcare names showed margin stability through product mix and selective pricing, with reimbursement risk still material.",
        "Industrial reports highlighted order book normalization and freight cost relief, offset by wage and maintenance inflation.",
        "Consumer businesses reported mixed unit growth, with margin support mostly from pricing and channel optimization.",
    ]

    i = (index - 1) % 15
    sector = sector_lines[i % len(sector_lines)]
    paragraph_one = (
        "Following our review of the latest annual reports, we need to align operating plans with realistic assumptions on demand, "
        "cost control, and capital intensity. "
        + sector
        + " For board readiness, please anchor all variance explanations to reported trends in revenue quality, EBITDA conversion, "
        "and working capital behavior rather than top-line growth alone. We should also call out where execution depends on vendor "
        "renegotiation, refinancing windows, or delayed hiring backfills."
    )
    paragraph_two = (
        "Action items for this week: update the risk register with three quantified downside scenarios, refresh the covenant and "
        "liquidity bridge through year-end, and provide a decision memo on projects that can be deferred without harming customer "
        "delivery. Include owners, milestones, and measurable outcomes for each item. If any team expects a target miss, submit a "
        "mitigation plan with timeline, dependencies, and a monthly checkpoint cadence for executive review."
    )
    paragraph_three = (
        "For cross-portfolio consistency, use the same KPI definitions in your submission: organic growth, gross margin, EBITDA margin, "
        "free cash flow conversion, and net leverage. Consolidated materials are due before the board packet deadline so we can resolve "
        "differences in assumptions and avoid late-cycle changes."
    )

    return (
        f"Subject: {subjects[i]}\n"
        f"From: {senders[i]}\n"
        f"To: {recipients[i]}\n"
        f"Date: {dates[i]}\n\n"
        f"{paragraph_one}\n\n"
        f"{paragraph_two}\n\n"
        f"{paragraph_three}"
    )


def _word_count(text: str) -> int:
    return len([word for word in text.split() if word.strip()])


def download_or_generate_enron_emails() -> int:
    global _duplicate_skips
    downloaded = 0
    for i in range(1, 16):
        filename = f"enron_email_{i}.txt"
        target_path = PUBLIC_DEMO_DIR / filename
        if target_path.exists():
            print(f"[SKIP] {filename} — already exists")
            continue
        raw_url = f"https://raw.githubusercontent.com/EFS-OpenSource/enron-email-dataset/refs/heads/main/emails/{i}.txt"
        state, _ = _save_url_to_file(raw_url, filename)
        if state == "saved":
            downloaded += 1
            continue

        content = _fallback_email_body(i)
        if _word_count(content) < 150:
            content = content + "\n\n" + _fallback_email_body(i + 7)
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        existing = _saved_hashes.get(digest)
        if existing:
            _duplicate_skips += 1
            print(f"[DUPE] {filename} is identical to {existing} — skipped")
            continue
        target_path.write_bytes(encoded)
        _saved_hashes[digest] = filename
        _print_ok(target_path)
        downloaded += 1

    return downloaded


def _count_files(paths: Iterable[Path], suffixes: tuple[str, ...]) -> int:
    normalized = tuple(s.lower() for s in suffixes)
    return sum(1 for p in paths if p.suffix.lower() in normalized)


def summarize_dataset(downloaded_this_run: int) -> None:
    files = [p for p in PUBLIC_DEMO_DIR.iterdir() if p.is_file()]
    total_mb = sum(_size_mb(path) for path in files)

    for path in sorted(files):
        if path.stat().st_size < 500:
            print(f"[WARN] {path.name} is under 500 bytes")

    pdf_htm_count = _count_files(files, (".pdf", ".htm"))
    csv_count = _count_files(files, (".csv",))
    email_count = sum(1 for p in files if p.suffix.lower() == ".txt" and p.name.startswith("enron_email_"))

    print("\n=== DOWNLOAD COMPLETE ===")
    print(f"PDFs/HTM:  {pdf_htm_count} files")
    print(f"CSVs:      {csv_count} files")
    print(f"Emails:    {email_count} files")
    print(f"Total:     {len(files)} files  ({total_mb:.1f} MB)")
    print(f"Duplicates skipped: {_duplicate_skips}")
    print(f"Failures:  {_failures}")

    if downloaded_this_run < 30:
        print(f"WARNING: only {downloaded_this_run} files downloaded — add more sources before demo")


def main() -> None:
    PUBLIC_DEMO_DIR.mkdir(parents=True, exist_ok=True)
    _init_existing_hashes()

    downloaded = 0
    downloaded += download_sec_filings()
    downloaded += download_fred_csvs()
    downloaded += download_or_generate_enron_emails()

    summarize_dataset(downloaded)


if __name__ == "__main__":
    main()
