import argparse
import csv
from pathlib import Path

from private_wire_workflow.companies_house import (
    find_best_match,
    get_api_key,
    list_accounts_filings,
)
from private_wire_workflow.filing_text_assessment import (
    assess_electricity_consumption,
    assess_filing_text_quality,
    assess_investment_grade_from_filing_text,
    assess_previous_ppa,
    assess_ratio_thresholds,
    assess_sustainability_targets,
    build_evidence_snippets,
    build_no_information_flags,
    compute_ratio_assessment_from_text,
    normalize_company_name,
    select_and_extract_best_filing_text,
)


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = BASE_DIR / "data" / "company_rating_screening_findings.csv"
TXT_DIR = BASE_DIR / "data" / "filing_texts"
OUTPUT_PATH = BASE_DIR / "data" / "company_filing_text_assessment.csv"


def _empty_assessment_row(company_name: str, notes: str) -> dict:
    return {
        "company_name": company_name,
        "matched_entity_name": "",
        "company_number": "",
        "entity_match_score": "",
        "entity_confidence": "",
        "matched_query": "",
        "runner_up_score": "",
        "filing_date": "",
        "filing_description": "",
        "filing_confidence": "",
        "filing_type": "",
        "filing_attempts": "",
        "txt_file_path": "",
        "page_count": "",
        "ocr_engine": "",
        "ocr_runtime_sec": "",
        "ocr_char_count": "",
        "txt_quality_status": "poor",
        "txt_quality_score": "",
        "txt_quality_flags": "",
        "turnover": "",
        "ebitda": "",
        "interest_expense": "",
        "debt": "",
        "cash": "",
        "net_debt": "",
        "ebitda_margin": "",
        "interest_coverage": "",
        "net_debt_to_ebitda": "",
        "q1_investment_grade_from_filing_text": "No information found",
        "q2_ratio_test_result": "No information found",
        "q3_electricity_consumption_signal": "No information found",
        "q4_sustainability_target_signal": "No information found",
        "q5_previous_ppa_signal": "No information found",
        "evidence_snippets": "",
        "notes": notes,
        "no_information_flags": "q1;q2;q3;q4;q5;missing_turnover;missing_ebitda;missing_interest_expense;missing_debt;missing_cash;missing_net_debt",
    }


def run(limit: int = 0) -> Path:
    api_key = get_api_key()
    TXT_DIR.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "company_name",
        "matched_entity_name",
        "company_number",
        "entity_match_score",
        "entity_confidence",
        "matched_query",
        "runner_up_score",
        "filing_date",
        "filing_description",
        "filing_confidence",
        "filing_type",
        "filing_attempts",
        "txt_file_path",
        "page_count",
        "ocr_engine",
        "ocr_runtime_sec",
        "ocr_char_count",
        "txt_quality_status",
        "txt_quality_score",
        "txt_quality_flags",
        "turnover",
        "ebitda",
        "interest_expense",
        "debt",
        "cash",
        "net_debt",
        "ebitda_margin",
        "interest_coverage",
        "net_debt_to_ebitda",
        "q1_investment_grade_from_filing_text",
        "q2_ratio_test_result",
        "q3_electricity_consumption_signal",
        "q4_sustainability_target_signal",
        "q5_previous_ppa_signal",
        "evidence_snippets",
        "notes",
        "no_information_flags",
    ]

    with INPUT_PATH.open(newline="", encoding="utf-8") as src, OUTPUT_PATH.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()

        processed = 0
        for row in reader:
            if limit and processed >= limit:
                break

            company_name = (row.get("Company Name") or "").strip()
            if not company_name:
                continue

            match = find_best_match(company_name, api_key)
            if not match:
                writer.writerow(_empty_assessment_row(company_name, "No legal entity match found."))
                processed += 1
                continue

            filings = list_accounts_filings(match.company_number, api_key)
            extraction = select_and_extract_best_filing_text(filings, api_key, max_attempts=5)
            if not extraction or not extraction.selection.filing:
                writer.writerow(
                    _empty_assessment_row(
                        company_name,
                        "No qualifying accounts filing found.",
                    )
                )
                processed += 1
                continue
            selection = extraction.selection
            filing = selection.filing

            ocr = extraction.ocr
            filing_year = (filing.date or "unknown")[:4]
            txt_filename = (
                f"{normalize_company_name(company_name)}__{filing_year}__{match.company_number}.txt"
            )
            txt_path = TXT_DIR / txt_filename
            txt_path.write_text(ocr.text, encoding="utf-8")
            quality = extraction.quality

            q1, q1_note = assess_investment_grade_from_filing_text(ocr.text)
            metrics = compute_ratio_assessment_from_text(ocr.text)
            q2 = assess_ratio_thresholds(metrics)
            q3 = assess_electricity_consumption(ocr.text)
            q4 = assess_sustainability_targets(ocr.text)
            q5 = assess_previous_ppa(ocr.text)

            evidence = build_evidence_snippets(ocr.text)
            flags = build_no_information_flags(q1, q2, q3, q4, q5, metrics)
            notes_parts = [
                q1_note or "",
                f"entity_confidence={match.confidence_tier}",
                f"filing_confidence={selection.confidence}",
                f"txt_quality={quality.status}",
            ]
            if selection.reason_codes:
                notes_parts.append("filing_flags=" + ",".join(selection.reason_codes))
            if quality.reason_codes:
                notes_parts.append("txt_flags=" + ",".join(quality.reason_codes))
            notes = " | ".join(part for part in notes_parts if part)

            writer.writerow(
                {
                    "company_name": company_name,
                    "matched_entity_name": match.company_name,
                    "company_number": match.company_number,
                    "entity_match_score": round(match.query_score, 3),
                    "entity_confidence": match.confidence_tier,
                    "matched_query": match.matched_query,
                    "runner_up_score": round(match.runner_up_score, 3) if match.runner_up_score else "",
                    "filing_date": filing.date,
                    "filing_description": filing.description,
                    "filing_confidence": selection.confidence,
                    "filing_type": selection.filing_type,
                    "filing_attempts": len(extraction.attempts),
                    "txt_file_path": str(txt_path),
                    "page_count": ocr.page_count,
                    "ocr_engine": ocr.engine,
                    "ocr_runtime_sec": round(ocr.runtime_sec, 2),
                    "ocr_char_count": len(ocr.text),
                    "txt_quality_status": quality.status,
                    "txt_quality_score": quality.score,
                    "txt_quality_flags": ";".join(quality.reason_codes),
                    "turnover": metrics["turnover"],
                    "ebitda": metrics["ebitda"],
                    "interest_expense": metrics["interest_expense"],
                    "debt": metrics["debt"],
                    "cash": metrics["cash"],
                    "net_debt": metrics["net_debt"],
                    "ebitda_margin": metrics["ebitda_margin"],
                    "interest_coverage": metrics["interest_coverage"],
                    "net_debt_to_ebitda": metrics["net_debt_to_ebitda"],
                    "q1_investment_grade_from_filing_text": q1,
                    "q2_ratio_test_result": q2,
                    "q3_electricity_consumption_signal": q3,
                    "q4_sustainability_target_signal": q4,
                    "q5_previous_ppa_signal": q5,
                    "evidence_snippets": evidence,
                    "notes": notes,
                    "no_information_flags": flags,
                }
            )
            processed += 1
            if processed % 5 == 0:
                print(f"Processed {processed} companies", flush=True)

    return OUTPUT_PATH


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(run(limit=args.limit))
