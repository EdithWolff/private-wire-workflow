import argparse
from pathlib import Path
from typing import Iterable

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


INPUT_PATH = Path("/Users/ssebl/Documents/New project/data/plastic_company_names.txt")
OUTPUT_DIR = Path("/Users/ssebl/Desktop/private_wire_outputs/filing_texts/plastic")

# A few names benefit from a simpler fallback if the literal search query does not resolve.
SEARCH_ALIASES = {
    "BPI group (BERRY and Amcor merged)": ["BPI Group"],
    "VISCOFAN S.A.": ["VISCOFAN SA"],
    "W. L. Gore & Associates": ["WL Gore & Associates"],
}


def load_company_names(input_path: Path) -> list[str]:
    names = []
    for line in input_path.read_text(encoding="utf-8").splitlines():
        company_name = line.strip()
        if company_name:
            names.append(company_name)
    return names


def iter_search_queries(company_name: str) -> Iterable[str]:
    yield company_name
    for alias in SEARCH_ALIASES.get(company_name, []):
        yield alias


def find_best_match_with_aliases(company_name: str, api_key: str):
    for query in iter_search_queries(company_name):
        match = find_best_match(query, api_key)
        if match:
            return match, query
    return None, company_name


def build_output_path(output_dir: Path, company_name: str, filing_date: str, company_number: str) -> Path:
    filing_year = (filing_date or "unknown")[:4]
    filename = f"{normalize_company_name(company_name)}__{filing_year}__{company_number}.txt"
    return output_dir / filename


def run(
    input_path: Path = INPUT_PATH,
    output_dir: Path = OUTPUT_DIR,
    limit: int = 0,
    ocr_page_timeout_sec: int = 30,
    overwrite: bool = False,
) -> int:
    api_key = get_api_key()
    output_dir.mkdir(parents=True, exist_ok=True)
    created = 0

    company_names = load_company_names(input_path)
    if limit:
        company_names = company_names[:limit]

    for index, company_name in enumerate(company_names, start=1):
        try:
            match, matched_query = find_best_match_with_aliases(company_name, api_key)
            if not match:
                print(f"[{index}] {company_name}: no entity match", flush=True)
                continue

            filings = list_accounts_filings(match.company_number, api_key)
            filing = select_latest_non_dormant_full_accounts(filings)
            if not filing:
                print(f"[{index}] {company_name}: no qualifying full non-dormant filing", flush=True)
                continue

            txt_path = build_output_path(
                output_dir=output_dir,
                company_name=company_name,
                filing_date=filing.date,
                company_number=match.company_number,
            )
            if not overwrite and txt_path.exists() and txt_path.stat().st_size > 0:
                print(f"[{index}] {company_name}: already exists", flush=True)
                continue

            pdf_bytes = download_document_pdf_content(filing.document_metadata_url, api_key)
            if not pdf_bytes:
                print(f"[{index}] {company_name}: pdf unavailable", flush=True)
                continue

            print(
                f"[{index}] {company_name}: running OCR via '{matched_query}' "
                f"(page-timeout={ocr_page_timeout_sec}s)",
                flush=True,
            )
            ocr = ocr_all_pdf_pages_with_tesseract(
                pdf_bytes,
                page_timeout_sec=ocr_page_timeout_sec,
            )
            txt_path.write_text(ocr.text, encoding="utf-8")
            created += 1
            print(
                f"[{index}] {company_name}: saved {txt_path} "
                f"(pages={ocr.page_count}, chars={len(ocr.text)})",
                flush=True,
            )
        except Exception as exc:
            print(f"[{index}] {company_name}: error {exc}", flush=True)
            continue

    print(f"Created {created} text files in {output_dir}.", flush=True)
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "OCR the latest qualifying Companies House filing for the plastics company batch "
            "and save .txt files to the Desktop output folder."
        )
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=INPUT_PATH,
        help="Text file containing one company name per line.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory where OCR text files should be written.",
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
