import argparse
import csv
from pathlib import Path

from private_wire_workflow.companies_house import (
    download_document_pdf_content,
    find_best_match,
    get_api_key,
    list_accounts_filings,
)
from private_wire_workflow.filing_text_assessment import (
    normalize_company_name,
    ocr_all_pdf_pages_with_tesseract,
    select_latest_non_dormant_full_accounts,
)


DEFAULT_INPUT_PATH = Path(
    "/Users/ssebl/Documents/New project/data/company_rating_screening_findings.csv"
)
DEFAULT_OUTPUT_DIR = Path.home() / "Desktop"


def run(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit: int = 0,
    ocr_page_timeout_sec: int = 30,
    overwrite: bool = False,
) -> int:
    api_key = get_api_key()
    output_dir.mkdir(parents=True, exist_ok=True)
    created = 0

    with input_path.open(newline="", encoding="utf-8") as src:
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
                filing = select_latest_non_dormant_full_accounts(filings)
                if not filing:
                    processed += 1
                    print(f"[{processed}] {company_name}: no qualifying full non-dormant filing", flush=True)
                    continue

                filing_year = (filing.date or "unknown")[:4]
                txt_filename = (
                    f"{normalize_company_name(company_name)}__{filing_year}__{match.company_number}.txt"
                )
                txt_path = output_dir / txt_filename
                if not overwrite and txt_path.exists() and txt_path.stat().st_size > 0:
                    processed += 1
                    print(f"[{processed}] {company_name}: already exists on Desktop", flush=True)
                    continue

                pdf_bytes = download_document_pdf_content(filing.document_metadata_url, api_key)
                if not pdf_bytes:
                    processed += 1
                    print(f"[{processed}] {company_name}: pdf unavailable", flush=True)
                    continue

                print(
                    f"[{processed + 1}] {company_name}: running OCR "
                    f"(page-timeout={ocr_page_timeout_sec}s)",
                    flush=True,
                )
                ocr = ocr_all_pdf_pages_with_tesseract(
                    pdf_bytes,
                    page_timeout_sec=ocr_page_timeout_sec,
                )
                txt_path.write_text(ocr.text, encoding="utf-8")
                created += 1
                processed += 1
                print(
                    f"[{processed}] {company_name}: saved {txt_path} "
                    f"(pages={ocr.page_count}, chars={len(ocr.text)})",
                    flush=True,
                )
            except Exception as exc:
                processed += 1
                print(f"[{processed}] {company_name}: error {exc}", flush=True)
                continue

    print(f"Created {created} text files in {output_dir}.", flush=True)
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OCR the latest qualifying Companies House PDF filing for each company and save .txt files to the Desktop."
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="CSV containing a 'Company Name' column.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where OCR text files should be written. Defaults to the Desktop.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ocr-page-timeout-sec", type=int, default=30)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .txt files if they already exist.",
    )
    args = parser.parse_args()
    run(
        input_path=args.input_path,
        output_dir=args.output_dir,
        limit=args.limit,
        ocr_page_timeout_sec=args.ocr_page_timeout_sec,
        overwrite=args.overwrite,
    )
