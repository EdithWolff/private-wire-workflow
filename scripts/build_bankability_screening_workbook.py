import argparse
import csv
from pathlib import Path

from openpyxl import Workbook

from private_wire_workflow.companies_house import (
    download_document_content,
    find_best_match,
    get_api_key,
    list_accounts_filings,
    select_best_accounts_filing,
)
from private_wire_workflow.filing_parser import (
    extract_financials_from_text,
    extract_text_from_pdf_bytes_with_metadata,
    html_to_text,
)
from private_wire_workflow.final_screening import combine_rating_and_filing


INPUT_PATH = Path("/Users/ssebl/Documents/New project/data/company_rating_screening_findings.csv")
OUTPUT_XLSX = Path("/Users/ssebl/Documents/New project/data/company_bankability_screening_results.xlsx")


def build_workbook(limit: int = 0) -> Path:
    api_key = get_api_key()
    wb = Workbook()
    ws = wb.active
    ws.title = "Bankability screening"

    headers = [
        "Company Name",
        "Official Rating Text",
        "Official Rating SP Equivalent",
        "Official Rating Verdict",
        "Matched UK Entity",
        "Company Number",
        "Filing Date",
        "Filing Description",
        "Turnover",
        "EBITDA",
        "Interest Expense",
        "Net Debt",
        "EBITDA / Turnover",
        "EBITDA / Interest Expense",
        "Net Debt / EBITDA",
        "Final Status",
        "Decision Basis",
        "Notes",
        "Document URL",
        "Source Format",
        "Extraction Confidence",
        "Extraction Engine",
    ]
    ws.append(headers)

    with INPUT_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        processed = 0
        for row in reader:
            if limit and processed >= limit:
                break

            company_name = (row.get("Company Name") or "").strip()
            official_rating_text = (row.get("Credit Rating (S&P / Moody's / Fitch)") or "").strip()
            if not company_name:
                continue

            match = find_best_match(company_name, api_key)
            matched_entity = match.company_name if match else ""
            company_number = match.company_number if match else ""
            filing = None
            financials = None
            document_url = ""
            source_format = ""

            if match:
                filings = list_accounts_filings(match.company_number, api_key)
                filing = select_best_accounts_filing(filings)
                if filing and filing.document_metadata_url:
                    document_url = filing.document_metadata_url
                    document_bytes, source_format = download_document_content(
                        filing.document_metadata_url,
                        api_key,
                    )
                    if document_bytes:
                        if source_format == "pdf":
                            text, engine, extract_notes = extract_text_from_pdf_bytes_with_metadata(
                                document_bytes
                            )
                            source_format = f"{source_format}:{engine}"
                        else:
                            text = html_to_text(document_bytes.decode("utf-8", errors="ignore"))
                            extract_notes = []
                        financials = extract_financials_from_text(text, source_format=source_format)
                        financials.extraction_engine = source_format.split(":")[-1]
                        financials.extraction_notes.extend(extract_notes)

            result = combine_rating_and_filing(
                company_name=company_name,
                official_rating_text=official_rating_text,
                matched_entity=matched_entity,
                company_number=company_number,
                filing=filing,
                financials=financials,
                document_url=document_url,
                source_format=source_format,
            )

            ws.append(
                [
                    result.company_name,
                    result.official_rating_text,
                    result.official_rating_sp_equivalent,
                    result.official_rating_verdict,
                    result.matched_entity,
                    result.company_number,
                    result.filing_date,
                    result.filing_description,
                    result.turnover,
                    result.ebitda,
                    result.interest_expense,
                    result.net_debt,
                    result.ebitda_margin,
                    result.interest_cover,
                    result.net_debt_to_ebitda,
                    result.final_status,
                    result.decision_basis,
                    result.notes,
                    result.document_url,
                    result.source_format,
                    financials.extraction_confidence if financials else "",
                    financials.extraction_engine if financials else "",
                ]
            )
            processed += 1
            if processed % 10 == 0:
                print(f"Processed {processed} companies", flush=True)

    wb.save(OUTPUT_XLSX)
    return OUTPUT_XLSX


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(build_workbook(limit=args.limit))
