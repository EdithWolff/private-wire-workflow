"""
Reads existing credit ratings from master_company_list.csv and:

1. Marks those companies as 'pre_qualified' in data/pipeline_state.json
   so build_company_filing_text_assessment.py skips them.

2. Writes synthetic rows into data/company_filing_text_assessment.csv
   so enrich_master_from_assessment.py can set Account Status,
   Bankability Confirmed, and Comment Bankability.

Companies with a rating ≥ BBB- (S&P/Fitch) or ≥ Baa3 (Moody's) are
marked Qualified. Those with only sub-investment-grade ratings are
marked Disqualified. Those with only unrecognised strings are skipped.

Usage
-----
PYTHONPATH=src python3 scripts/seed_ratings_from_master.py
PYTHONPATH=src python3 scripts/seed_ratings_from_master.py --dry-run
"""

import argparse
import csv
import json
import re
import shutil
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
MASTER_PATH = BASE_DIR / "data" / "inputs" / "master_company_list.csv"
ASSESSMENT_PATH = BASE_DIR / "data" / "company_filing_text_assessment.csv"
STATE_PATH = BASE_DIR / "data" / "pipeline_state.json"

# ── Rating classification ─────────────────────────────────────────────────────

INVESTMENT_GRADE_SP = {
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
    "BBB+", "BBB", "BBB-",
}
INVESTMENT_GRADE_MOODYS = {
    "Aaa", "Aa1", "Aa2", "Aa3",
    "A1", "A2", "A3",
    "Baa1", "Baa2", "Baa3",
}
BELOW_GRADE_SP_PREFIXES = ("BB", "B", "CCC", "CC", "C", "D", "SD", "R")
BELOW_GRADE_MOODYS_PREFIXES = ("Ba", "B", "Caa", "Ca", "C", "D")


def _strip_year(value: str) -> str:
    """Remove trailing year annotation, e.g. 'BBB+ (2024)' → 'BBB+'."""
    return re.sub(r"\s*\(.*?\)", "", value).strip()


def _classify_sp(rating: str) -> str | None:
    """Return 'investment_grade', 'below_grade', or None if unrecognised."""
    r = _strip_year(rating)
    if not r or r.upper() in ("N/A", "NR", "-"):
        return None
    if r in INVESTMENT_GRADE_SP:
        return "investment_grade"
    if any(r.startswith(p) for p in BELOW_GRADE_SP_PREFIXES):
        return "below_grade"
    return None


def _classify_moodys(rating: str) -> str | None:
    r = _strip_year(rating)
    if not r or r.upper() in ("N/A", "NR", "-"):
        return None
    if r in INVESTMENT_GRADE_MOODYS:
        return "investment_grade"
    if any(r.startswith(p) for p in BELOW_GRADE_MOODYS_PREFIXES):
        return "below_grade"
    return None


def classify_company(moodys_simple: str, sp_simple: str,
                     moodys_full: str, sp_full: str, fitch_full: str) -> tuple[str, str]:
    """
    Returns (verdict, best_rating_text) where verdict is one of:
      'investment_grade', 'below_grade', 'unrecognised'
    """
    pairs = [
        (_classify_sp(sp_simple),       sp_simple),
        (_classify_sp(sp_full),         sp_full),
        (_classify_sp(fitch_full),      fitch_full),
        (_classify_moodys(moodys_simple), moodys_simple),
        (_classify_moodys(moodys_full),   moodys_full),
    ]
    checks = [c for c, _ in pairs]
    rating_values = [r for _, r in pairs]

    if "investment_grade" in checks:
        idx = checks.index("investment_grade")
        return "investment_grade", _strip_year(rating_values[idx])
    if "below_grade" in checks:
        idx = checks.index("below_grade")
        return "below_grade", _strip_year(rating_values[idx])
    return "unrecognised", ""


# ── Assessment CSV helpers ────────────────────────────────────────────────────

ASSESSMENT_FIELDNAMES = [
    "company_name", "matched_entity_name", "company_number",
    "entity_match_score", "entity_confidence", "matched_query", "runner_up_score",
    "filing_date", "filing_description", "filing_confidence", "filing_type",
    "filing_attempts", "txt_file_path", "page_count", "ocr_engine",
    "ocr_runtime_sec", "ocr_char_count", "txt_quality_status", "txt_quality_score",
    "txt_quality_flags", "turnover", "ebitda", "interest_expense", "debt", "cash",
    "net_debt", "ebitda_margin", "interest_coverage", "net_debt_to_ebitda",
    "q1_investment_grade_from_filing_text", "q2_ratio_test_result",
    "q3_electricity_consumption_signal", "q4_sustainability_target_signal",
    "q5_previous_ppa_signal", "evidence_snippets", "notes", "no_information_flags",
]


def _synthetic_row(company_name: str, verdict: str, rating_text: str) -> dict:
    q1 = f"Yes — {rating_text}" if verdict == "investment_grade" else (
        f"No — {rating_text}" if rating_text else "No information found"
    )
    q2 = "No information found"
    return {
        "company_name": company_name,
        "q1_investment_grade_from_filing_text": q1,
        "q2_ratio_test_result": q2,
        "q3_electricity_consumption_signal": "No information found",
        "q4_sustainability_target_signal": "No information found",
        "q5_previous_ppa_signal": "No information found",
        "notes": f"pre_seeded from master list | rating={rating_text}",
        **{k: "" for k in ASSESSMENT_FIELDNAMES
           if k not in ("company_name", "q1_investment_grade_from_filing_text",
                        "q2_ratio_test_result", "q3_electricity_consumption_signal",
                        "q4_sustainability_target_signal", "q5_previous_ppa_signal", "notes")},
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    # Load master list (raw rows to avoid duplicate-column issues)
    with MASTER_PATH.open(newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    headers = raw[0]

    # Locate rating columns by index (first occurrence for duplicates)
    col = {h: i for i, h in enumerate(reversed(headers))}
    col = {h: len(headers) - 1 - i for h, i in col.items()}  # first occurrence

    COL_NAME = col["Name"]
    COL_MOODYS_SIMPLE = col.get("Moody's", -1)
    COL_SP_SIMPLE = col.get("S&P", -1)
    COL_MOODYS_FULL = col.get("Moody's Rating", -1)
    COL_SP_FULL = col.get("S&P Rating", -1)
    COL_FITCH_FULL = col.get("Fitch Rating", -1)

    def _get(row: list, idx: int) -> str:
        return row[idx].strip() if 0 <= idx < len(row) else ""

    # Load existing state and assessment
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    existing_assessment: set[str] = set()
    if ASSESSMENT_PATH.exists():
        with ASSESSMENT_PATH.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_assessment.add((row.get("company_name") or "").strip().lower())

    to_seed: list[tuple[str, str, str]] = []  # (company_name, verdict, rating_text)
    skipped_already_done = 0
    skipped_unrecognised = 0

    for row in raw[1:]:
        name = _get(row, COL_NAME)
        if not name:
            continue

        # Skip if already in assessment CSV or pipeline as completed
        if name.lower() in existing_assessment:
            skipped_already_done += 1
            continue
        existing_status = state.get(name, {}).get("status", "")
        if existing_status in ("completed", "no_match", "no_filing", "pre_qualified"):
            skipped_already_done += 1
            continue

        verdict, rating_text = classify_company(
            _get(row, COL_MOODYS_SIMPLE), _get(row, COL_SP_SIMPLE),
            _get(row, COL_MOODYS_FULL), _get(row, COL_SP_FULL), _get(row, COL_FITCH_FULL),
        )

        if verdict == "unrecognised":
            skipped_unrecognised += 1
            continue

        to_seed.append((name, verdict, rating_text))

    print(f"Found {len(to_seed)} companies to pre-seed "
          f"({skipped_already_done} already done, {skipped_unrecognised} unrecognised/no rating)")

    if dry_run:
        for name, verdict, rating in to_seed[:30]:
            print(f"  {name:<45} {verdict:<20} {rating}")
        if len(to_seed) > 30:
            print(f"  ... and {len(to_seed) - 30} more")
        return

    # Update pipeline state
    today = date.today().isoformat()
    for name, verdict, rating_text in to_seed:
        state[name] = {
            "status": "pre_qualified",
            "processed_date": today,
            "source": "master_company_list rating columns",
            "rating": rating_text,
            "verdict": verdict,
        }
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Updated pipeline_state.json with {len(to_seed)} pre_qualified entries")

    # Append synthetic rows to assessment CSV (create with header if new)
    write_header = not ASSESSMENT_PATH.exists()
    # Back up first if file exists
    if ASSESSMENT_PATH.exists():
        backup = ASSESSMENT_PATH.with_suffix(".backup.csv")
        shutil.copy2(ASSESSMENT_PATH, backup)
        print(f"Assessment CSV backed up to {backup.name}")

    with ASSESSMENT_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ASSESSMENT_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for name, verdict, rating_text in to_seed:
            writer.writerow(_synthetic_row(name, verdict, rating_text))

    print(f"Appended {len(to_seed)} synthetic rows to {ASSESSMENT_PATH.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pre-seed pipeline state and assessment CSV from known master list ratings."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be seeded without writing anything.")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
