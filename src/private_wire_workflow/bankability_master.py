import csv
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook

from .companies_house import (
    download_document_pdf_content,
    find_best_match,
    get_api_key,
    list_accounts_filings,
)
from .filing_text_assessment import (
    assess_previous_ppa,
    assess_sustainability_targets,
    build_evidence_snippets,
    compute_ratio_assessment_from_text,
    normalize_company_name,
    ocr_all_pdf_pages_with_tesseract,
    select_latest_non_dormant_full_accounts,
)
from .ratings import MOODYS_TO_SP, RATING_ORDER
from .report_utils import NO_INFO, fmt_number as _fmt_number, fmt_pct as _fmt_pct, ratio_flags as _ratio_flags
TERMINAL_STATUSES = {"completed", "no_match", "no_filing", "failed_after_retries"}
SCHEMA_VERSION = "v2_1_enriched_output"


@dataclass
class PipelineConfig:
    input_csv_path: Path
    txt_dir: Path
    output_xlsx_path: Path
    checkpoint_path: Path
    summary_path: Path
    max_workers: int = 5
    retries: int = 3
    retry_backoff_sec: float = 2.0
    ocr_page_timeout_sec: int = 25
    limit: int = 0


def _extract_sp_like(text: str) -> str:
    if not text:
        return ""
    ordered = sorted(RATING_ORDER, key=len, reverse=True)
    upper = text.upper()
    for rating in ordered:
        pattern = rf"(?<![A-Z0-9]){re.escape(rating)}(?![A-Z0-9])"
        if re.search(pattern, upper):
            return rating
    return ""


def _extract_moodys_like(text: str) -> str:
    if not text:
        return ""
    match = re.search(
        r"\b(?:AAA|AA1|AA2|AA3|A1|A2|A3|BAA1|BAA2|BAA3|BA1|BA2|BA3|B1|B2|B3|CAA1|CAA2|CAA3|CAA|CA|C)\b",
        text.upper(),
    )
    return match.group(0) if match else ""


def _parse_rating_columns(row: Dict[str, str]) -> Tuple[str, str, str]:
    moodys = (row.get("Moody's Rating") or "").strip()
    sp = (row.get("S&P Rating") or "").strip()
    fitch = (row.get("Fitch Rating") or "").strip()
    combined = (row.get("Credit Rating (S&P / Moody's / Fitch)") or "").strip()
    if not combined:
        return moodys, sp, fitch

    chunks = [chunk.strip() for chunk in combined.split("/") if chunk.strip()]
    for chunk in chunks:
        lowered = chunk.lower()
        if "mood" in lowered and not moodys:
            moodys = _extract_moodys_like(chunk) or chunk
        elif ("s&p" in lowered or "sp" in lowered) and not sp:
            sp = _extract_sp_like(chunk) or chunk
        elif "fitch" in lowered and not fitch:
            fitch = _extract_sp_like(chunk) or chunk
        elif not sp:
            sp = _extract_sp_like(chunk) or sp
        elif not moodys:
            moodys = _extract_moodys_like(chunk) or moodys
    return moodys, sp, fitch


def _sp_equivalent_from_columns(moodys: str, sp: str, fitch: str) -> str:
    if sp:
        parsed = _extract_sp_like(sp)
        return parsed or sp
    if fitch:
        parsed = _extract_sp_like(fitch)
        return parsed or fitch
    if moodys:
        m = _extract_moodys_like(moodys)
        return MOODYS_TO_SP.get(m, "")
    return ""


def rating_at_least_bbb_minus(sp_like_rating: str) -> bool:
    value = _extract_sp_like(sp_like_rating)
    if not value:
        return False
    return RATING_ORDER.index(value) <= RATING_ORDER.index("BBB-")


def _ratio_based_status(metrics: Dict[str, Optional[float]]) -> Tuple[str, str]:
    margin = metrics.get("ebitda_margin")
    coverage = metrics.get("interest_coverage")
    leverage = metrics.get("net_debt_to_ebitda")
    if margin is None or coverage is None or leverage is None:
        return "Needs review", NO_INFO
    if margin >= 0.10 and coverage >= 3 and leverage <= 2:
        return "Qualified", "Ratios meet thresholds"
    return "Disqualified", "Ratio threshold not met"


def _extract_ppa_fields(text: str) -> Tuple[str, str, str, str]:
    has_ppa = assess_previous_ppa(text) == "Yes"
    signed = "Yes" if has_ppa else NO_INFO
    lowered = text.lower()

    uk_tokens = [" uk ", "united kingdom", "britain", "england", "scotland", "wales"]
    uk = "Yes" if has_ppa and any(token in lowered for token in uk_tokens) else NO_INFO

    wind = "wind" in lowered and "ppa" in lowered
    solar = "solar" in lowered and "ppa" in lowered
    if wind and solar:
        ppa_type = "Wind/Solar"
    elif wind:
        ppa_type = "Wind"
    elif solar:
        ppa_type = "Solar"
    else:
        ppa_type = NO_INFO

    year_match = re.search(r"\b(20\d{2})\b", text)
    ppa_year = year_match.group(1) if has_ppa and year_match else NO_INFO
    return signed, uk, ppa_type, ppa_year


def _build_headers() -> List[str]:
    return [
        "Company Name",
        "Matched UK Entity",
        "Company Number",
        "CH Match Status",
        "Filing Status",
        "Official Rating Present?",
        "Moody's Rating",
        "S&P Rating",
        "Fitch Rating",
        "Turnover",
        "EBITDA",
        "Interest Expense",
        "Debt",
        "Cash",
        "Net Debt",
        "EBITDA Margin",
        "Interest Coverage",
        "Net Debt/EBITDA",
        "Margin>=10%",
        "Coverage>=3x",
        "NetDebt/EBITDA<=2x",
        "Bankability Decision",
        "Disqualification Reason",
        "Renewable/Sustainability Signal",
        "Solar/PPA Signal",
        "PPA Type",
        "PPA Year",
        "Evidence Snippets",
        "TXT File Path",
        "Notes",
        # Keep familiar workflow columns for easy reconciliation with original scope.
        "Account status** (qualified or not depends on credit rating (BBB- or higher) or LTV (if site meet criteria)",
        "Discqualification reason",
        "UK PPA?",
        "Signed PPAs before? (Yes/No)",
        "Filing Date",
        "Processing Status",
    ]


def _empty_output_row(company_name: str, moodys: str, sp: str, fitch: str, status: str, reason: str) -> Dict[str, str]:
    official_present = "Yes" if any([moodys, sp, fitch]) else "No"
    row = {
        "Company Name": company_name,
        "Matched UK Entity": NO_INFO,
        "Company Number": NO_INFO,
        "CH Match Status": "no_match" if status == "no_match" else "matched",
        "Filing Status": "no_qualifying_filing",
        "Official Rating Present?": official_present,
        "Moody's Rating": moodys or NO_INFO,
        "S&P Rating": sp or NO_INFO,
        "Fitch Rating": fitch or NO_INFO,
        "Turnover": NO_INFO,
        "EBITDA": NO_INFO,
        "Interest Expense": NO_INFO,
        "Debt": NO_INFO,
        "Cash": NO_INFO,
        "Net Debt": NO_INFO,
        "EBITDA Margin": NO_INFO,
        "Interest Coverage": NO_INFO,
        "Net Debt/EBITDA": NO_INFO,
        "Margin>=10%": NO_INFO,
        "Coverage>=3x": NO_INFO,
        "NetDebt/EBITDA<=2x": NO_INFO,
        "Bankability Decision": "Needs review",
        "Disqualification Reason": reason,
        "Renewable/Sustainability Signal": NO_INFO,
        "Solar/PPA Signal": NO_INFO,
        "PPA Type": NO_INFO,
        "PPA Year": NO_INFO,
        "Evidence Snippets": NO_INFO,
        "TXT File Path": NO_INFO,
        "Notes": reason,
        "Account status** (qualified or not depends on credit rating (BBB- or higher) or LTV (if site meet criteria)": "Needs review",
        "Discqualification reason": reason,
        "UK PPA?": NO_INFO,
        "Signed PPAs before? (Yes/No)": NO_INFO,
        "Filing Date": NO_INFO,
        "Processing Status": status,
    }
    return row


def _load_input_rows(input_csv_path: Path, limit: int = 0) -> List[Dict[str, str]]:
    with input_csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [row for row in reader if (row.get("Company Name") or "").strip()]
    if limit and limit > 0:
        return rows[:limit]
    return rows


def _load_checkpoint(checkpoint_path: Path) -> Dict[str, Dict]:
    if not checkpoint_path.exists():
        return {}
    try:
        return json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_checkpoint(checkpoint_path: Path, state: Dict[str, Dict]) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(
        json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _process_company_row(
    row: Dict[str, str],
    api_key: str,
    txt_dir: Path,
    retries: int,
    retry_backoff_sec: float,
    ocr_page_timeout_sec: int,
) -> Dict[str, Dict]:
    company_name = (row.get("Company Name") or "").strip()
    moodys, sp, fitch = _parse_rating_columns(row)
    best_sp = _sp_equivalent_from_columns(moodys, sp, fitch)
    has_official_rating = bool(best_sp)

    for attempt in range(1, retries + 1):
        try:
            match = find_best_match(company_name, api_key)
            if not match:
                output_row = _empty_output_row(
                    company_name,
                    moodys,
                    sp,
                    fitch,
                    "no_match",
                    "No legal entity match found",
                )
                if has_official_rating:
                    qualified = rating_at_least_bbb_minus(best_sp)
                    output_row["Account status** (qualified or not depends on credit rating (BBB- or higher) or LTV (if site meet criteria)"] = "Qualified" if qualified else "Disqualified"
                    output_row["Bankability Decision"] = output_row["Account status** (qualified or not depends on credit rating (BBB- or higher) or LTV (if site meet criteria)"]
                    output_row["Notes"] = "Decision based on official rating"
                    if not qualified:
                        output_row["Disqualification Reason"] = "Credit rating below BBB-"
                        output_row["Discqualification reason"] = "Credit rating below BBB-"
                return {"status": "no_match", "row": output_row, "schema_version": SCHEMA_VERSION}

            filings = list_accounts_filings(match.company_number, api_key)
            filing = select_latest_non_dormant_full_accounts(filings)
            if not filing:
                output_row = _empty_output_row(
                    company_name,
                    moodys,
                    sp,
                    fitch,
                    "no_filing",
                    "No latest non-dormant full accounts filing found",
                )
                output_row["Matched UK Entity"] = match.company_name
                output_row["Company Number"] = match.company_number
                output_row["CH Match Status"] = "matched"
                output_row["Filing Status"] = "no_qualifying_filing"
                if has_official_rating:
                    qualified = rating_at_least_bbb_minus(best_sp)
                    output_row["Account status** (qualified or not depends on credit rating (BBB- or higher) or LTV (if site meet criteria)"] = "Qualified" if qualified else "Disqualified"
                    output_row["Bankability Decision"] = output_row["Account status** (qualified or not depends on credit rating (BBB- or higher) or LTV (if site meet criteria)"]
                    output_row["Notes"] = "Decision based on official rating"
                    if not qualified:
                        output_row["Disqualification Reason"] = "Credit rating below BBB-"
                        output_row["Discqualification reason"] = "Credit rating below BBB-"
                return {"status": "no_filing", "row": output_row, "schema_version": SCHEMA_VERSION}

            filing_year = (filing.date or "unknown")[:4]
            txt_filename = f"{normalize_company_name(company_name)}__{filing_year}__{match.company_number}.txt"
            txt_path = txt_dir / txt_filename

            if txt_path.exists() and txt_path.stat().st_size > 0:
                text = txt_path.read_text(encoding="utf-8", errors="ignore")
            else:
                pdf_bytes = download_document_pdf_content(filing.document_metadata_url, api_key)
                if not pdf_bytes:
                    output_row = _empty_output_row(
                        company_name,
                        moodys,
                        sp,
                        fitch,
                        "no_filing",
                        "PDF content unavailable for selected filing",
                    )
                    output_row["Matched UK Entity"] = match.company_name
                    output_row["Company Number"] = match.company_number
                    output_row["CH Match Status"] = "matched"
                    output_row["Filing Status"] = "no_qualifying_filing"
                    return {"status": "no_filing", "row": output_row, "schema_version": SCHEMA_VERSION}
                ocr = ocr_all_pdf_pages_with_tesseract(pdf_bytes, page_timeout_sec=ocr_page_timeout_sec)
                text = ocr.text
                txt_dir.mkdir(parents=True, exist_ok=True)
                txt_path.write_text(text, encoding="utf-8")

            metrics = compute_ratio_assessment_from_text(text)
            flags = _ratio_flags(metrics)
            ratio_status, ratio_reason = _ratio_based_status(metrics)

            if has_official_rating:
                status = "Qualified" if rating_at_least_bbb_minus(best_sp) else "Disqualified"
                reason = "Decision based on official rating"
                if status == "Disqualified":
                    disq = "Credit rating below BBB-"
                else:
                    disq = ""
            else:
                status = ratio_status
                reason = ratio_reason
                disq = "Ratio threshold not met" if status == "Disqualified" else (NO_INFO if status == "Needs review" else "")

            signed_ppa, uk_ppa, ppa_type, ppa_year = _extract_ppa_fields(text)
            sustainability = "Yes" if assess_sustainability_targets(text) == "Yes" else NO_INFO
            solar_ppa_signal = "Yes" if signed_ppa == "Yes" else NO_INFO
            evidence = build_evidence_snippets(text) or NO_INFO

            output_row = {
                "Company Name": company_name,
                "Matched UK Entity": match.company_name,
                "Company Number": match.company_number,
                "CH Match Status": "matched",
                "Filing Status": "non_dormant_full_found",
                "Official Rating Present?": "Yes" if has_official_rating else "No",
                "Moody's Rating": moodys or NO_INFO,
                "S&P Rating": sp or NO_INFO,
                "Fitch Rating": fitch or NO_INFO,
                "Turnover": _fmt_number(metrics.get("turnover")),
                "EBITDA": _fmt_number(metrics.get("ebitda")),
                "Interest Expense": _fmt_number(metrics.get("interest_expense")),
                "Debt": _fmt_number(metrics.get("debt")),
                "Cash": _fmt_number(metrics.get("cash")),
                "Net Debt": _fmt_number(metrics.get("net_debt")),
                "EBITDA Margin": _fmt_pct(metrics.get("ebitda_margin")),
                "Interest Coverage": _fmt_number(metrics.get("interest_coverage")),
                "Net Debt/EBITDA": _fmt_number(metrics.get("net_debt_to_ebitda")),
                "Margin>=10%": flags["margin_ge_10"],
                "Coverage>=3x": flags["coverage_ge_3x"],
                "NetDebt/EBITDA<=2x": flags["netdebt_ebitda_le_2x"],
                "Bankability Decision": status,
                "Disqualification Reason": disq or "",
                "Renewable/Sustainability Signal": sustainability,
                "Solar/PPA Signal": solar_ppa_signal,
                "PPA Type": ppa_type,
                "PPA Year": ppa_year,
                "Evidence Snippets": evidence,
                "TXT File Path": str(txt_path),
                "Notes": reason,
                "Account status** (qualified or not depends on credit rating (BBB- or higher) or LTV (if site meet criteria)": status,
                "Discqualification reason": disq or "",
                "UK PPA?": uk_ppa,
                "Signed PPAs before? (Yes/No)": signed_ppa,
                "Filing Date": filing.date or NO_INFO,
                "Processing Status": "completed",
            }
            return {"status": "completed", "row": output_row, "schema_version": SCHEMA_VERSION}
        except Exception as exc:
            if attempt >= retries:
                output_row = _empty_output_row(
                    company_name,
                    moodys,
                    sp,
                    fitch,
                    "failed_after_retries",
                    f"Failed after retries: {exc}",
                )
                return {"status": "failed_after_retries", "row": output_row, "schema_version": SCHEMA_VERSION}
            time.sleep(retry_backoff_sec * attempt)
    output_row = _empty_output_row(company_name, moodys, sp, fitch, "failed_after_retries", "Unknown failure")
    return {"status": "failed_after_retries", "row": output_row, "schema_version": SCHEMA_VERSION}


def _write_output_workbook(output_xlsx_path: Path, rows: List[Dict[str, str]]) -> None:
    output_xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    headers = _build_headers()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Company_Assessment"
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    workbook.save(output_xlsx_path)


def _write_summary(summary_path: Path, payload: Dict) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def run_pipeline(config: PipelineConfig) -> Dict[str, int]:
    api_key = get_api_key()
    rows = _load_input_rows(config.input_csv_path, config.limit)
    checkpoint = _load_checkpoint(config.checkpoint_path)
    lock = threading.Lock()

    indexed_rows = {}
    for index, row in enumerate(rows):
        company_name = (row.get("Company Name") or "").strip()
        indexed_rows[company_name] = {"index": index, "row": row}

    pending = []
    output_by_company = {}
    for company_name, payload in indexed_rows.items():
        saved = checkpoint.get(company_name)
        if (
            saved
            and saved.get("status") in TERMINAL_STATUSES
            and isinstance(saved.get("row"), dict)
            and saved.get("schema_version") == SCHEMA_VERSION
        ):
            output_by_company[company_name] = saved["row"]
        else:
            pending.append(payload["row"])

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, config.max_workers)) as executor:
            futures = {
                executor.submit(
                    _process_company_row,
                    row,
                    api_key,
                    config.txt_dir,
                    config.retries,
                    config.retry_backoff_sec,
                    config.ocr_page_timeout_sec,
                ): (row.get("Company Name") or "").strip()
                for row in pending
            }
            for future in as_completed(futures):
                company_name = futures[future]
                result = future.result()
                with lock:
                    checkpoint[company_name] = result
                    output_by_company[company_name] = result["row"]
                    _save_checkpoint(config.checkpoint_path, checkpoint)
                print(f"{company_name}: {result['status']}", flush=True)

    ordered_output_rows = []
    for row in rows:
        company_name = (row.get("Company Name") or "").strip()
        ordered_output_rows.append(output_by_company.get(company_name, _empty_output_row(company_name, "", "", "", "failed_after_retries", "Missing pipeline output")))

    _write_output_workbook(config.output_xlsx_path, ordered_output_rows)

    summary = {"total": len(rows), "completed": 0, "no_match": 0, "no_filing": 0, "failed_after_retries": 0}
    decision_counts = {"Qualified": 0, "Disqualified": 0, "Needs review": 0}
    for row in ordered_output_rows:
        status = row.get("Processing Status", "")
        if status in summary:
            summary[status] += 1
        decision = row.get("Bankability Decision", "")
        if decision in decision_counts:
            decision_counts[decision] += 1
    _write_summary(
        config.summary_path,
        {
            "schema_version": SCHEMA_VERSION,
            "processing_summary": summary,
            "decision_summary": decision_counts,
            "output_xlsx_path": str(config.output_xlsx_path),
            "checkpoint_path": str(config.checkpoint_path),
        },
    )
    return summary
