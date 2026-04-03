import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import fitz
import numpy as np
import pytesseract
from PIL import Image

from .filing_parser import extract_financials_from_text
from .models import FilingCandidate
from .ratings import assess_official_rating


@dataclass
class OCRResult:
    text: str
    page_count: int
    runtime_sec: float
    engine: str = "tesseract-eng"


def normalize_company_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if ord(ch) < 128)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text[:80] or "company"


def select_latest_non_dormant_full_accounts(
    filings: List[FilingCandidate],
) -> Optional[FilingCandidate]:
    preferred = []
    fallback = []
    for filing in filings:
        description = (filing.description or "").lower()
        if "dormant" in description or "micro" in description:
            continue
        if not filing.document_metadata_url:
            continue
        if "full" in description or "group" in description:
            preferred.append(filing)
        else:
            fallback.append(filing)
    if preferred:
        return sorted(preferred, key=lambda filing: filing.date or "", reverse=True)[0]
    if fallback:
        return sorted(fallback, key=lambda filing: filing.date or "", reverse=True)[0]
    return None


def ocr_all_pdf_pages_with_tesseract(pdf_bytes: bytes, page_timeout_sec: int = 90) -> OCRResult:
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
