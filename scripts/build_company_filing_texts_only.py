import argparse
import csv
from pathlib import Path

from private_wire_workflow.companies_house import (
    find_best_match,
    get_api_key,
    list_accounts_filings,
)
from private_wire_workflow.filing_text_assessment import (
    assess_filing_text_quality,
    normalize_company_name,
    select_and_extract_best_filing_text,
)


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = BASE_DIR / "data" / "company_rating_screening_findings.csv"
TXT_DIR = BASE_DIR / "data" / "filing_texts"


def run(limit: int = 0, ocr_page_timeout_sec: int = 30) -> int:
    api_key = get_api_key()
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    created = 0

    with INPUT_PATH.open(newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        processed = 0
        for row in reader:
            if limit and processed >= limit:
                break

            company_name = (row.get("Company Name") or "").strip()
            if not company_name:
                continue

            try:
                match = find_best_match(company_name, api_key)
                if not match:
                    processed += 1
                    print(f"[{processed}] {company_name}: no entity match", flush=True)
                    continue

                filings = list_accounts_filings(match.company_number, api_key)
                extraction = select_and_extract_best_filing_text(
                    filings,
                    api_key,
                    page_timeout_sec=ocr_page_timeout_sec,
                    max_attempts=5,
                )
                if not extraction or not extraction.selection.filing:
                    processed += 1
                    print(f"[{processed}] {company_name}: no qualifying filing", flush=True)
                    continue
                selection = extraction.selection
                filing = selection.filing

                filing_year = (filing.date or "unknown")[:4]
                txt_filename = (
                    f"{normalize_company_name(company_name)}__{filing_year}__{match.company_number}.txt"
                )
                txt_path = TXT_DIR / txt_filename
                if txt_path.exists() and txt_path.stat().st_size > 0:
                    processed += 1
                    print(f"[{processed}] {company_name}: already exists", flush=True)
                    continue

                print(
                    f"[{processed + 1}] {company_name}: extracting text "
                    f"(page-timeout={ocr_page_timeout_sec}s)",
                    flush=True,
                )
                ocr = extraction.ocr
                txt_path.write_text(ocr.text, encoding="utf-8")
                quality = extraction.quality
                created += 1
                processed += 1
                print(
                    f"[{processed}] {company_name}: saved {txt_filename} "
                    f"(match={match.confidence_tier}, filing={selection.confidence}, quality={quality.status}, attempts={len(extraction.attempts)}, engine={ocr.engine}, pages={ocr.page_count}, chars={len(ocr.text)})"
                    ,
                    flush=True,
                )
            except Exception as exc:
                processed += 1
                print(f"[{processed}] {company_name}: error {exc}", flush=True)
                continue

    print(f"Created {created} text files.", flush=True)
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ocr-page-timeout-sec", type=int, default=30)
    args = parser.parse_args()
    run(limit=args.limit, ocr_page_timeout_sec=args.ocr_page_timeout_sec)
