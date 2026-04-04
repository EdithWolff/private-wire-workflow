import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from .filing_parser import extract_financials_from_text, extract_text_from_pdf_bytes_with_metadata
from .models import FilingCandidate, FilingSelection, TextQualityAssessment
from .ratings import assess_official_rating


@dataclass
class OCRResult:
    text: str
    page_count: int
    runtime_sec: float
    engine: str = "tesseract-eng"
    notes: List[str] = field(default_factory=list)


@dataclass
class FilingExtractionAttempt:
    transaction_id: str
    filing_date: str
    filing_description: str
    filing_confidence: str
    txt_quality_status: str
    txt_quality_score: float
    reason_codes: List[str] = field(default_factory=list)


@dataclass
class FilingExtractionResult:
    selection: FilingSelection
    ocr: OCRResult
    quality: TextQualityAssessment
    attempts: List[FilingExtractionAttempt] = field(default_factory=list)


def normalize_company_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if ord(ch) < 128)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text[:80] or "company"


def select_latest_non_dormant_full_accounts(
    filings: List[FilingCandidate],
) -> Optional[FilingCandidate]:
    return select_accounts_filing_automated(filings).filing


def _filing_type(description: str) -> str:
    lowered = (description or "").lower()
    if "full" in lowered and "group" in lowered:
        return "full_group"
    if "full" in lowered:
        return "full"
    if "group" in lowered:
        return "group"
    if any(token in lowered for token in ["small", "abridged", "filleted"]):
        return "small_or_abridged"
    if "dormant" in lowered:
        return "dormant"
    if "micro" in lowered:
        return "micro"
    return "other_accounts"


def _likely_has_financial_information(description: str) -> bool:
    lowered = (description or "").lower()
    if any(token in lowered for token in ["dormant", "micro-entity", "micro entity"]):
        return False
    return any(
        token in lowered
        for token in [
            "accounts",
            "full",
            "group",
            "small",
            "abridged",
            "filleted",
        ]
    )


def _filing_age_days(filing_date: str) -> Optional[int]:
    if not filing_date:
        return None
    try:
        return (date.today() - datetime.strptime(filing_date, "%Y-%m-%d").date()).days
    except ValueError:
        return None


def select_accounts_filing_automated(filings: List[FilingCandidate]) -> FilingSelection:
    ranked = rank_accounts_filings(filings)
    if not ranked:
        if not filings:
            return FilingSelection(reason_codes=["no_accounts_filings"])
        return FilingSelection(reason_codes=["no_document_metadata_url"])
    return ranked[0]


def rank_accounts_filings(filings: List[FilingCandidate]) -> List[FilingSelection]:
    if not filings:
        return []

    candidates = [
        filing
        for filing in filings
        if filing.document_metadata_url and _likely_has_financial_information(filing.description)
    ]
    if not candidates:
        candidates = [filing for filing in filings if filing.document_metadata_url]
    if not candidates:
        return []

    def score(filing: FilingCandidate) -> Tuple[int, str]:
        filing_type = _filing_type(filing.description)
        weight = 0
        if filing_type == "full_group":
            weight += 120
        elif filing_type in {"full", "group"}:
            weight += 100
        elif filing_type == "small_or_abridged":
            weight += 60
        elif filing_type == "other_accounts":
            weight += 40
        elif filing_type == "micro":
            weight += 10
        elif filing_type == "dormant":
            weight -= 20
        age_days = _filing_age_days(filing.date)
        if age_days is not None:
            if age_days <= 550:
                weight += 15
            elif age_days <= 900:
                weight += 5
            else:
                weight -= 10
        return weight, filing.date or ""

    ranked = sorted(candidates, key=score, reverse=True)
    selections: List[FilingSelection] = []
    for index, selected in enumerate(ranked):
        filing_type = _filing_type(selected.description)
        age_days = _filing_age_days(selected.date)
        reason_codes: List[str] = []
        fallback_used = index > 0 or filing_type not in {"full_group", "full", "group"}
        if fallback_used:
            reason_codes.append("filing_fallback_used")
        if filing_type in {"dormant", "micro"}:
            reason_codes.append(filing_type)
        if age_days is not None and age_days > 900:
            reason_codes.append("stale_filing")

        if filing_type in {"full_group", "full", "group"} and (age_days is None or age_days <= 550):
            confidence = "high"
        elif filing_type in {"small_or_abridged", "other_accounts"} or (age_days is not None and age_days <= 900):
            confidence = "medium"
        else:
            confidence = "low"

        selections.append(
            FilingSelection(
                filing=selected,
                confidence=confidence,
                filing_type=filing_type,
                reason_codes=reason_codes,
                fallback_used=fallback_used,
            )
        )
    return selections


def assess_filing_text_quality(text: str) -> TextQualityAssessment:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lowered = text.lower()
    char_count = len(text)
    line_count = len(lines)
    has_balance_sheet = any(
        marker in lowered
        for marker in ["balance sheet", "statement of financial position", "net assets"]
    )
    has_income_statement = any(
        marker in lowered
        for marker in [
            "profit and loss",
            "statement of comprehensive income",
            "operating profit",
            "turnover",
            "revenue",
        ]
    )
    has_cash_markers = any(marker in lowered for marker in ["cash at bank", "cash and cash equivalents", "cash balances"])
    has_debt_markers = any(marker in lowered for marker in ["creditors", "borrowings", "bank loans", "debtors", "loan"])
    limited_accounts = any(
        marker in lowered
        for marker in [
            "profit & loss account has not been delivered",
            "profit and loss account has not been delivered",
            "filleted accounts",
            "abridged accounts",
        ]
    )

    score = 0.0
    reason_codes: List[str] = []
    if char_count >= 1000:
        score += 0.30
    elif char_count >= 300:
        score += 0.15
    else:
        reason_codes.append("low_char_count")

    if line_count >= 20:
        score += 0.20
    elif line_count >= 8:
        score += 0.10
    else:
        reason_codes.append("low_line_count")

    if has_balance_sheet:
        score += 0.20
    else:
        reason_codes.append("missing_balance_sheet_marker")

    if has_income_statement:
        score += 0.20
    elif not limited_accounts:
        reason_codes.append("missing_income_statement_marker")

    if has_cash_markers:
        score += 0.05
    if has_debt_markers:
        score += 0.05
    if limited_accounts:
        score += 0.05
        reason_codes.append("limited_accounts_text")

    if score >= 0.65 and has_balance_sheet and (has_income_statement or limited_accounts):
        status = "usable"
    elif score >= 0.35 or limited_accounts:
        status = "partial"
    else:
        status = "poor"

    return TextQualityAssessment(
        status=status,
        score=round(score, 2),
        char_count=char_count,
        line_count=line_count,
        has_balance_sheet=has_balance_sheet,
        has_income_statement=has_income_statement,
        has_cash_markers=has_cash_markers,
        has_debt_markers=has_debt_markers,
        limited_accounts=limited_accounts,
        reason_codes=reason_codes,
    )


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    import fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        return document.page_count


def extract_best_filing_text(pdf_bytes: bytes, page_timeout_sec: int = 90) -> OCRResult:
    page_count = _count_pdf_pages(pdf_bytes)
    extraction_notes: List[str] = []
    native_text = ""
    native_engine = ""
    native_runtime = 0.0

    try:
        native_start = time.time()
        native_text, native_engine, native_notes = extract_text_from_pdf_bytes_with_metadata(pdf_bytes)
        native_runtime = time.time() - native_start
        extraction_notes.extend(native_notes)
        native_quality = assess_filing_text_quality(native_text)
    except Exception as exc:
        native_quality = TextQualityAssessment(status="poor", reason_codes=[f"native_extract_failed:{exc}"])
        extraction_notes.append(f"native_extract_failed:{exc}")

    if native_quality.status == "usable":
        extraction_notes.append(f"selected_engine:{native_engine}")
        return OCRResult(
            text=native_text,
            page_count=page_count,
            runtime_sec=native_runtime,
            engine=native_engine,
            notes=extraction_notes,
        )

    ocr = ocr_all_pdf_pages_with_tesseract(pdf_bytes, page_timeout_sec=page_timeout_sec)
    ocr_quality = assess_filing_text_quality(ocr.text)

    native_rank = {"poor": 0, "partial": 1, "usable": 2}[native_quality.status]
    ocr_rank = {"poor": 0, "partial": 1, "usable": 2}[ocr_quality.status]
    if (ocr_rank, ocr_quality.score, len(ocr.text)) >= (native_rank, native_quality.score, len(native_text)):
        ocr.notes = extraction_notes + [f"selected_engine:{ocr.engine}"]
        return ocr

    extraction_notes.append(f"selected_engine:{native_engine}")
    return OCRResult(
        text=native_text,
        page_count=page_count,
        runtime_sec=native_runtime,
        engine=native_engine,
        notes=extraction_notes,
    )


def select_and_extract_best_filing_text(
    filings: List[FilingCandidate],
    api_key: str,
    page_timeout_sec: int = 90,
    max_attempts: int = 5,
) -> Optional[FilingExtractionResult]:
    from .companies_house import download_document_pdf_content

    ranked = rank_accounts_filings(filings)
    if not ranked:
        return None

    attempts: List[FilingExtractionAttempt] = []
    fallback_result: Optional[FilingExtractionResult] = None
    best_partial_result: Optional[FilingExtractionResult] = None
    capped_ranked = ranked[: max(1, min(max_attempts, 5))]

    for index, selection in enumerate(capped_ranked):
        if selection.filing is None:
            continue
        pdf_bytes = download_document_pdf_content(selection.filing.document_metadata_url, api_key)
        if not pdf_bytes:
            attempts.append(
                FilingExtractionAttempt(
                    transaction_id=selection.filing.transaction_id,
                    filing_date=selection.filing.date,
                    filing_description=selection.filing.description,
                    filing_confidence=selection.confidence,
                    txt_quality_status="poor",
                    txt_quality_score=0.0,
                    reason_codes=list(selection.reason_codes) + ["pdf_unavailable"],
                )
            )
            continue

        ocr = extract_best_filing_text(pdf_bytes, page_timeout_sec=page_timeout_sec)
        quality = assess_filing_text_quality(ocr.text)
        reason_codes = list(selection.reason_codes)
        if index > 0:
            reason_codes.append("retried_next_best_filing")
        attempt = FilingExtractionAttempt(
            transaction_id=selection.filing.transaction_id,
            filing_date=selection.filing.date,
            filing_description=selection.filing.description,
            filing_confidence=selection.confidence,
            txt_quality_status=quality.status,
            txt_quality_score=quality.score,
            reason_codes=reason_codes + list(quality.reason_codes),
        )
        attempts.append(attempt)

        result = FilingExtractionResult(
            selection=selection,
            ocr=ocr,
            quality=quality,
            attempts=list(attempts),
        )
        if quality.status == "usable":
            return result
        if quality.status == "partial" and best_partial_result is None:
            best_partial_result = result
        if fallback_result is None:
            fallback_result = result

    return best_partial_result or fallback_result


def ocr_all_pdf_pages_with_tesseract(pdf_bytes: bytes, page_timeout_sec: int = 90) -> OCRResult:
    import fitz
    import numpy as np
    import pytesseract
    from PIL import Image

    start = time.time()
    lines = []
    page_count = 0
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        for page in document:
            page_count += 1
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            image = Image.fromarray(arr)
            try:
                text = pytesseract.image_to_string(
                    image,
                    lang="eng",
                    timeout=page_timeout_sec,
                )
            except RuntimeError:
                text = ""
            lines.append(text)
    return OCRResult(
        text="\n".join(lines),
        page_count=page_count,
        runtime_sec=time.time() - start,
    )


def _collect_evidence(text: str, patterns: List[str], max_items: int = 4) -> List[str]:
    evidence = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(re.search(pattern, lowered) for pattern in patterns):
            clean = line.strip()
            if clean and clean not in evidence:
                evidence.append(clean[:220])
                if len(evidence) >= max_items:
                    break
    return evidence


def assess_investment_grade_from_filing_text(text: str) -> Tuple[str, str]:
    rating = assess_official_rating(text)
    if rating.verdict == "TBD":
        return "No information found", ""
    if rating.verdict == "Qualified":
        return "Yes", rating.reason
    return "No", rating.reason


def compute_ratio_assessment_from_text(text: str) -> Dict[str, Optional[float]]:
    fin = extract_financials_from_text(text, source_format="txt:tesseract")

    turnover = fin.turnover
    ebitda = fin.ebitda
    interest_expense = fin.interest_expense
    debt = None
    cash = None
    net_debt = fin.net_debt

    def _safe_parse_number(raw: str) -> Optional[float]:
        if raw is None:
            return None
        cleaned = (
            raw.replace(",", "")
            .replace("(", "-")
            .replace(")", "")
            .replace("+", "")
            .strip()
        )
        if not cleaned:
            return None
        if cleaned in {"-", ".", "-."}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    debt_match = re.search(
        r"(?:total\s+)?debt[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if debt_match:
        debt = _safe_parse_number(debt_match.group(1))

    cash_match = re.search(
        r"cash(?:\s+and\s+cash\s+equivalents)?[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if cash_match:
        cash = _safe_parse_number(cash_match.group(1))

    if net_debt is None and debt is not None and cash is not None:
        net_debt = debt - cash

    ebitda_margin = None
    interest_coverage = None
    net_debt_to_ebitda = None
    if turnover not in (None, 0) and ebitda is not None:
        ebitda_margin = ebitda / turnover
    if interest_expense not in (None, 0) and ebitda is not None:
        interest_coverage = ebitda / abs(interest_expense)
    if net_debt is not None and ebitda not in (None, 0):
        net_debt_to_ebitda = net_debt / ebitda

    return {
        "turnover": turnover,
        "ebitda": ebitda,
        "interest_expense": interest_expense,
        "debt": debt,
        "cash": cash,
        "net_debt": net_debt,
        "ebitda_margin": ebitda_margin,
        "interest_coverage": interest_coverage,
        "net_debt_to_ebitda": net_debt_to_ebitda,
    }


def assess_ratio_thresholds(metrics: Dict[str, Optional[float]]) -> str:
    if (
        metrics["ebitda_margin"] is None
        or metrics["interest_coverage"] is None
        or metrics["net_debt_to_ebitda"] is None
    ):
        return "No information found"
    if (
        metrics["ebitda_margin"] >= 0.10
        and metrics["interest_coverage"] >= 3
        and metrics["net_debt_to_ebitda"] <= 2
    ):
        return "Yes"
    return "No"


def assess_electricity_consumption(text: str) -> str:
    gwh_values = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*gwh", text, flags=re.IGNORECASE)]
    if not gwh_values:
        return "No information found"
    total_ok = any(value >= 30 for value in gwh_values)
    site_ok = any(value >= 8 for value in gwh_values)
    return "Yes" if total_ok and site_ok else "No"


def assess_sustainability_targets(text: str) -> str:
    patterns = [
        r"net\s*zero",
        r"science\s*based\s*target",
        r"renewable",
        r"decarbon",
        r"emission",
        r"scope\s*1",
        r"scope\s*2",
        r"sustainability\s*target",
    ]
    return "Yes" if _collect_evidence(text, patterns, max_items=1) else "No information found"


def assess_previous_ppa(text: str) -> str:
    patterns = [
        r"\bppa\b",
        r"power\s*purchase\s*agreement",
        r"wind\s*ppa",
        r"solar\s*ppa",
        r"renewable\s*power\s*purchase",
    ]
    if _collect_evidence(text, patterns, max_items=1):
        return "Yes"
    return "No information found"


def build_evidence_snippets(text: str) -> str:
    patterns = [
        r"bbb",
        r"ebitda",
        r"turnover",
        r"revenue",
        r"interest",
        r"debt",
        r"cash",
        r"gwh",
        r"renewable",
        r"sustainability",
        r"\bppa\b",
    ]
    snippets = _collect_evidence(text, patterns, max_items=8)
    return " | ".join(snippets)


def build_no_information_flags(
    q1: str,
    q2: str,
    q3: str,
    q4: str,
    q5: str,
    metrics: Dict[str, Optional[float]],
) -> str:
    flags = []
    if q1 == "No information found":
        flags.append("q1")
    if q2 == "No information found":
        flags.append("q2")
    if q3 == "No information found":
        flags.append("q3")
    if q4 == "No information found":
        flags.append("q4")
    if q5 == "No information found":
        flags.append("q5")
    for metric in ["turnover", "ebitda", "interest_expense", "debt", "cash", "net_debt"]:
        if metrics.get(metric) is None:
            flags.append(f"missing_{metric}")
    return ";".join(flags)
