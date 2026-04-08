import argparse
import csv
import json
from datetime import date
from pathlib import Path

from private_wire_workflow.companies_house import (
    find_best_match_with_filings,
    get_api_key,
)
from private_wire_workflow.filing_text_assessment import (
    normalize_company_name,
    select_and_extract_best_filing_text,
)


BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = BASE_DIR / "data" / "inputs" / "company_rating_screening_findings.csv"
TXT_DIR = BASE_DIR / "data" / "filing_texts"
OUTPUT_PATH = BASE_DIR / "data" / "company_filing_text_assessment.csv"
STATE_PATH = BASE_DIR / "data" / "pipeline_state.json"

TERMINAL_STATUSES = {"completed", "no_match", "no_filing"}

FIELDNAMES = [
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
    # Analysis fields — left blank by this script, populated by /rating command
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
    "credit_view_summary",
    "notes",
    "no_information_flags",
]


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _update_state(state: dict, company_name: str, status: str, **kwargs) -> None:
    state[company_name] = {
        "status": status,
        "processed_date": date.today().isoformat(),
        **{k: v for k, v in kwargs.items() if v is not None},
    }
    _save_state(state)


def _empty_row(company_name: str, notes: str) -> dict:
    row = {field: "" for field in FIELDNAMES}
    row["company_name"] = company_name
    row["txt_quality_status"] = "poor"
    row["credit_view_summary"] = f"Needs review — {notes}" if notes else ""
    row["notes"] = notes
    return row


def _extraction_row(company_name, match, selection, ocr, quality, txt_path) -> dict:
    """Build a CSV row with pipeline metadata only — no financial analysis."""
    filing = selection.filing
    row = {field: "" for field in FIELDNAMES}
    row.update({
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
        "filing_attempts": len(getattr(selection, "reason_codes", [])),
        "txt_file_path": str(txt_path.relative_to(BASE_DIR)),
        "page_count": ocr.page_count,
        "ocr_engine": ocr.engine,
        "ocr_runtime_sec": round(ocr.runtime_sec, 2),
        "ocr_char_count": len(ocr.text),
        "txt_quality_status": quality.status,
        "txt_quality_score": quality.score,
        "txt_quality_flags": ";".join(quality.reason_codes),
        "credit_view_summary": "Awaiting /rating analysis",
        "notes": f"entity_confidence={match.confidence_tier} | filing_confidence={selection.confidence} | txt_quality={quality.status}",
    })
    return row


def run(input_path: Path = INPUT_PATH, limit: int = 0, reprocess: bool = False) -> Path:
    api_key = get_api_key()
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()

    # Determine name column — master list uses "Name", curated list uses "Company Name"
    with input_path.open(newline="", encoding="utf-8") as f:
        headers = next(csv.reader(f))
    name_col = "Name" if "Name" in headers else "Company Name"

    with input_path.open(newline="", encoding="utf-8") as src, OUTPUT_PATH.open(
        "w", newline="", encoding="utf-8"
    ) as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=FIELDNAMES)
        writer.writeheader()

        processed = 0
        skipped = 0
        for row in reader:
            if limit and processed >= limit:
                break

            company_name = (row.get(name_col) or "").strip()
            if not company_name:
                continue

            # Skip already-processed companies unless --reprocess is set
            existing = state.get(company_name, {})
            if not reprocess and existing.get("status") in TERMINAL_STATUSES:
                skipped += 1
                print(f"[skip] {company_name} ({existing['status']})", flush=True)
                continue

            result = find_best_match_with_filings(company_name, api_key)
            if not result:
                writer.writerow(_empty_row(company_name, "No legal entity match found."))
                _update_state(state, company_name, "no_match", notes="No substantive legal entity match found.")
                processed += 1
                continue
            match, filings = result

            extraction = select_and_extract_best_filing_text(
                filings, api_key, max_attempts=5, expected_entity_name=company_name,
            )
            if not extraction or not extraction.selection.filing:
                writer.writerow(_empty_row(company_name, "No qualifying accounts filing found."))
                _update_state(
                    state, company_name, "no_filing",
                    company_number=match.company_number,
                    entity_name=match.company_name,
                    notes="No qualifying accounts filing found.",
                )
                processed += 1
                continue

            selection = extraction.selection
            ocr = extraction.ocr
            filing = selection.filing
            filing_year = (filing.date or "unknown")[:4]
            txt_filename = f"{normalize_company_name(company_name)}__{filing_year}__{match.company_number}.txt"
            txt_path = TXT_DIR / txt_filename
            txt_path.write_text(ocr.text, encoding="utf-8")
            quality = extraction.quality

            writer.writerow(_extraction_row(
                company_name, match, selection, ocr, quality, txt_path,
            ))

            _update_state(
                state, company_name, "completed",
                company_number=match.company_number,
                entity_name=match.company_name,
                filing_date=filing.date,
                txt_file=str(txt_path.relative_to(BASE_DIR)),
            )

            processed += 1
            print(f"[{processed}] {company_name}: done", flush=True)
            if processed % 10 == 0:
                print(f"--- {processed} processed, {skipped} skipped ---", flush=True)

    print(f"Finished: {processed} processed, {skipped} skipped.", flush=True)
    return OUTPUT_PATH


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", type=Path, default=INPUT_PATH,
                        help="Input CSV. Defaults to company_rating_screening_findings.csv. "
                             "Use data/inputs/master_company_list.csv for the full 2796-company list.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N companies (0 = no limit). Useful for testing.")
    parser.add_argument("--reprocess", action="store_true",
                        help="Re-run even companies already marked completed in pipeline_state.json.")
    args = parser.parse_args()
    print(run(input_path=args.input_csv, limit=args.limit, reprocess=args.reprocess))
