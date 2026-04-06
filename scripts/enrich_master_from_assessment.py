"""
Reads company_filing_text_assessment.csv and writes the results into the
relevant columns of data/inputs/master_company_list.csv.

Column mapping
--------------
Assessment                         → Master list
---------------------------------    ------------------------------------------
company_name                         Name  (join key, case-insensitive)
turnover                             Revenue  (col 17 — the financial one)
q2_ratio_test_result                 Bankability confirmed?
q1_investment_grade_from_filing_text S&P Rating  (only if not already filled)
q5_previous_ppa_signal               Signed PPAs before? (Yes/No)
q4_sustainability_target_signal      Comments  (appended)
[derived verdict]                    Account status**
[derived disqualification]           Discqualification reason
[formatted financials + Q answers]   Comment bankability

Only empty cells are updated by default. Use --overwrite to replace existing values.

Usage
-----
PYTHONPATH=src python3 scripts/enrich_master_from_assessment.py
PYTHONPATH=src python3 scripts/enrich_master_from_assessment.py --overwrite
PYTHONPATH=src python3 scripts/enrich_master_from_assessment.py --dry-run
"""

import argparse
import csv
import re
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
ASSESSMENT_PATH = BASE_DIR / "data" / "company_filing_text_assessment.csv"
MASTER_PATH = BASE_DIR / "data" / "inputs" / "master_company_list.csv"
BACKUP_PATH = BASE_DIR / "data" / "inputs" / "master_company_list.backup.csv"

# Master list column names (exactly as they appear in the file)
COL_NAME = "Name"
COL_ACCOUNT_STATUS = "Account status** (qualified or not depends on credit rating or LTV)"
COL_DISQUALIFICATION = "Discqualification reason"
COL_SP_RATING = "S&P Rating"
COL_REVENUE = "Revenue"
COL_BANKABILITY_CONFIRMED = "Bankability confirmed?"
COL_COMMENT_BANKABILITY = "Comment bankability"
COL_SIGNED_PPA = "Signed PPAs before? (Yes/No)"
COL_COMMENTS = "Comments"


def _verdict(q1: str, q2: str) -> str:
    if q1.startswith("Yes") or q2 == "Yes":
        return "Qualified"
    if q2 == "No":
        return "Disqualified"
    return "Needs review"


def _disqualification_reason(q2: str, notes: str) -> str:
    if q2 == "No":
        return "Ratio thresholds not met per filing text analysis"
    return ""


def _bankability_comment(row: dict) -> str:
    parts = []
    if row.get("filing_date"):
        parts.append(f"Filing: {row['filing_date']}")
    for label, key in [
        ("Turnover", "turnover"),
        ("EBITDA", "ebitda"),
        ("EBITDA margin", "ebitda_margin"),
        ("Interest cover", "interest_coverage"),
        ("Net debt/EBITDA", "net_debt_to_ebitda"),
    ]:
        val = row.get(key, "")
        if val:
            if key == "ebitda_margin":
                try:
                    parts.append(f"{label}: {float(val)*100:.1f}%")
                except ValueError:
                    parts.append(f"{label}: {val}")
            elif key in ("interest_coverage", "net_debt_to_ebitda"):
                try:
                    parts.append(f"{label}: {float(val):.2f}x")
                except ValueError:
                    parts.append(f"{label}: {val}")
            else:
                parts.append(f"{label}: {val}")
    for label, key in [
        ("Q1 rating", "q1_investment_grade_from_filing_text"),
        ("Q2 ratios", "q2_ratio_test_result"),
        ("Q3 electricity", "q3_electricity_consumption_signal"),
        ("Q4 sustainability", "q4_sustainability_target_signal"),
        ("Q5 PPA", "q5_previous_ppa_signal"),
    ]:
        val = row.get(key, "")
        if val:
            parts.append(f"{label}: {val}")
    if row.get("notes"):
        parts.append(f"Notes: {row['notes']}")
    return " | ".join(parts)


def _set(master_row: dict, col: str, value: str, overwrite: bool) -> bool:
    """Set a column value. Returns True if the cell was changed."""
    if not value:
        return False
    existing = (master_row.get(col) or "").strip()
    if existing and not overwrite:
        return False
    master_row[col] = value
    return True


def run(overwrite: bool = False, dry_run: bool = False) -> None:
    # Load assessment results keyed by normalised company name
    assessment: dict[str, dict] = {}
    with ASSESSMENT_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("company_name") or "").strip()
            if name:
                assessment[name.lower()] = row

    if not assessment:
        print("No assessment rows found. Run build_company_filing_text_assessment.py first.")
        return

    # Load master list — handle duplicate column names (e.g. two "Revenue" columns)
    # by reading raw rows and building dicts manually with deduplicated keys.
    with MASTER_PATH.open(newline="", encoding="utf-8") as f:
        raw_reader = csv.reader(f)
        original_fieldnames = next(raw_reader)  # preserve exact original headers
        # Build unique internal keys: first occurrence keeps the name, duplicates get _2, _3, ...
        seen: dict[str, int] = {}
        unique_fieldnames: list[str] = []
        for col in original_fieldnames:
            if col in seen:
                seen[col] += 1
                unique_fieldnames.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                unique_fieldnames.append(col)
        master_rows = [dict(zip(unique_fieldnames, row)) for row in raw_reader]
    fieldnames = original_fieldnames  # used when writing back

    updated = 0
    matched = 0

    for master_row in master_rows:
        name = (master_row.get(COL_NAME) or "").strip()
        if not name:
            continue

        a = assessment.get(name.lower())
        if not a:
            continue

        matched += 1
        changed = False

        q1 = (a.get("q1_investment_grade_from_filing_text") or "").strip()
        q2 = (a.get("q2_ratio_test_result") or "").strip()

        verdict = _verdict(q1, q2)
        disq = _disqualification_reason(q2, a.get("notes", ""))
        comment = _bankability_comment(a)
        turnover = (a.get("turnover") or "").strip()
        ppa = (a.get("q5_previous_ppa_signal") or "").strip()
        sustainability = (a.get("q4_sustainability_target_signal") or "").strip()

        changed |= _set(master_row, COL_ACCOUNT_STATUS, verdict, overwrite)
        changed |= _set(master_row, COL_DISQUALIFICATION, disq, overwrite)
        changed |= _set(master_row, COL_BANKABILITY_CONFIRMED, q2, overwrite)
        changed |= _set(master_row, COL_COMMENT_BANKABILITY, comment, overwrite)
        changed |= _set(master_row, COL_REVENUE, turnover, overwrite)
        changed |= _set(master_row, COL_SIGNED_PPA, ppa, overwrite)
        if q1 and not q1.startswith("No information"):
            # Extract actual rating from several possible formats:
            # "Yes — BBB+" (synthetic pre-seeded row)
            # "Official rating AA is above BBB-." (from notes field)
            # Fallback: use q1 as-is
            dash_match = re.search(r"(?:Yes|No)\s*[—–-]\s*([A-Za-z0-9+\-]+)", q1)
            notes_text = a.get("notes", "")
            notes_match = re.search(r"Official rating\s+([A-Za-z0-9+\-]+)\s+is", notes_text)
            seed_match = re.search(r"rating=([A-Za-z0-9+\-]+)", notes_text)
            sp_value = (dash_match or notes_match or seed_match)
            sp_value = sp_value.group(1) if sp_value else q1
            changed |= _set(master_row, COL_SP_RATING, sp_value, overwrite)
        if sustainability.startswith("Yes"):
            existing_comments = (master_row.get(COL_COMMENTS) or "").strip()
            note = "Sustainability target signal: Yes (from filing text)"
            if note not in existing_comments:
                master_row[COL_COMMENTS] = (existing_comments + " | " + note).lstrip(" | ")
                changed = True

        if changed:
            updated += 1
            if dry_run:
                print(f"[dry-run] Would update: {name} → verdict={verdict}, q2={q2}, ppa={ppa}")

    print(f"Matched {matched} companies. {updated} rows {'would be' if dry_run else 'were'} updated.")

    if dry_run:
        return

    # Back up original before writing
    shutil.copy2(MASTER_PATH, BACKUP_PATH)
    print(f"Backup saved to {BACKUP_PATH.name}")

    # Write back: map unique internal keys back to original column order
    with MASTER_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(original_fieldnames)
        for row in master_rows:
            writer.writerow([row.get(uk, "") for uk in unique_fieldnames])

    print(f"Master list updated: {MASTER_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Write assessment results into master_company_list.csv."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing non-empty cells. Default: skip cells that already have a value.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing anything.",
    )
    args = parser.parse_args()
    run(overwrite=args.overwrite, dry_run=args.dry_run)
