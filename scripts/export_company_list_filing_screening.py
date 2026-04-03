import argparse
import csv
from pathlib import Path

from private_wire_workflow.companies_house import (
    download_document_content,
    find_best_match,
    get_api_key,
    list_accounts_filings,
    select_best_accounts_filing,
)
from private_wire_workflow.filing_bankability import assess_filing_bankability
from private_wire_workflow.filing_parser import (
    extract_financials_from_text,
    extract_text_from_pdf_bytes_with_metadata,
    html_to_text,
)


INPUT_PATH = Path("/Users/ssebl/Documents/New project/data/company_rating_screening_findings.csv")
OUTPUT_PATH = Path("/Users/ssebl/Documents/New project/data/company_rating_screening_with_filing_bankability.csv")


def _entity_scope(description: str) -> str:
    return "group" if "group" in description.lower() else "company"


def export_screening(limit: int = 0) -> Path:
    api_key = get_api_key()

    with INPUT_PATH.open(newline="", encoding="utf-8") as src, OUTPUT_PATH.open(
        "w", newline="", encoding="utf-8"
    ) as dst:
        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames + [
            "Matched UK Entity",
            "Company Number",
            "Filing Date",
            "Filing Description",
            "Entity Scope",
            "Turnover",
            "EBITDA",
            "Interest Expense",
            "Net Debt",
            "EBITDA / Turnover",
            "EBITDA / Interest Expense",
            "Net Debt / EBITDA",
            "Filing-Based Verdict",
            "Filing Review Reason",
            "Document URL",
            "Source Format",
            "Extraction Confidence",
            "Extraction Engine",
        ]
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()

        processed = 0
        for row in reader:
            if limit and processed >= limit:
                break

            company_name = (row.get("Company Name") or "").strip()
            output_row = dict(row)
            if not company_name:
                writer.writerow(output_row)
                continue

            match = find_best_match(company_name, api_key)
            if match is None:
                output_row.update(
                    {
                        "Filing-Based Verdict": "Needs review",
                        "Filing Review Reason": "No clear Companies House entity match.",
                    }
                )
                writer.writerow(output_row)
                processed += 1
                continue

            output_row["Matched UK Entity"] = match.company_name
            output_row["Company Number"] = match.company_number

            filings = list_accounts_filings(match.company_number, api_key)
            filing = select_best_accounts_filing(filings)
            if filing is None or not filing.document_metadata_url:
                output_row.update(
                    {
                        "Filing-Based Verdict": "Needs review",
                        "Filing Review Reason": "No usable accounts filing with document metadata found.",
                    }
                )
                writer.writerow(output_row)
                processed += 1
                continue

            output_row["Filing Date"] = filing.date
            output_row["Filing Description"] = filing.description
            output_row["Entity Scope"] = _entity_scope(filing.description)
            output_row["Document URL"] = filing.document_metadata_url

            document_bytes, source_format = download_document_content(
                filing.document_metadata_url,
                api_key,
            )
            output_row["Source Format"] = source_format

            if not document_bytes:
                output_row.update(
                    {
                        "Filing-Based Verdict": "Needs review",
                        "Filing Review Reason": "Accounts document is unavailable for parsing.",
                    }
                )
                writer.writerow(output_row)
                processed += 1
                continue

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
            result = assess_filing_bankability(
                account_name=company_name,
                company_number=match.company_number,
                entity_name=match.company_name,
                filing=filing,
                financials=financials,
                document_url=filing.document_metadata_url,
                entity_scope=_entity_scope(filing.description),
            )

            output_row.update(
                {
                    "Turnover": result.turnover,
                    "EBITDA": result.ebitda,
                    "Interest Expense": result.interest_expense,
                    "Net Debt": result.net_debt,
                    "EBITDA / Turnover": result.ebitda_margin,
                    "EBITDA / Interest Expense": result.interest_cover,
                    "Net Debt / EBITDA": result.net_debt_to_ebitda,
                    "Filing-Based Verdict": result.verdict,
                    "Filing Review Reason": result.review_reason,
                    "Extraction Confidence": financials.extraction_confidence,
                    "Extraction Engine": financials.extraction_engine,
                }
            )
            writer.writerow(output_row)
            processed += 1

            if processed % 10 == 0:
                print(f"Processed {processed} companies", flush=True)

    return OUTPUT_PATH


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(export_screening(limit=args.limit))
