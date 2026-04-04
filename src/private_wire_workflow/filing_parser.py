import html
import io
import re
import time
from typing import List, Optional, Tuple

from .models import FilingFinancials


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
NUM_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
_OCR_ENGINE = None

NUMBER_PATTERNS = {
    "turnover": [
        r"turnover[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
        r"revenue[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
    ],
    "ebitda": [
        r"ebitda[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
    ],
    "operating_profit": [
        r"operating profit[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
        r"profit before interest[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
    ],
    "depreciation": [
        r"depreciation[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
    ],
    "amortisation": [
        r"amorti[sz]ation[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
    ],
    "interest_expense": [
        r"interest payable.*?(\(?-?\s*[\d,]+(?:\.\d+)?\)?)",
        r"interest expense.*?(\(?-?\s*[\d,]+(?:\.\d+)?\)?)",
        r"finance costs.*?(\(?-?\s*[\d,]+(?:\.\d+)?\)?)",
    ],
    "net_debt": [
        r"net debt[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
    ],
    "borrowings": [
        r"borrowings[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
    ],
    "cash": [
        r"cash at bank and in hand[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
        r"cash and cash equivalents[^0-9\-()]{0,120}([\(\)\-]?\s*[\d,]+\s*(?:\.\d+)?)",
    ],
}


def html_to_text(content: str) -> str:
    text = TAG_RE.sub(" ", content)
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


def parse_number(raw: str) -> Optional[float]:
    value = raw.strip().replace(",", "")
    if not value:
        return None
    negative = False
    if value.startswith("(") and value.endswith(")"):
        negative = True
        value = value[1:-1].strip()
    if value.startswith("-"):
        negative = True
        value = value[1:].strip()
    try:
        number = float(value)
    except ValueError:
        return None
    return -number if negative else number


def _extract_first(text: str, patterns: List[str]) -> Optional[float]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return parse_number(match.group(1))
    return None


def _extract_all_numbers(text: str) -> List[float]:
    values = []
    for match in NUM_RE.findall(text):
        number = parse_number(match)
        if number is not None:
            values.append(number)
    return values


def _detect_unit_multiplier(text: str) -> float:
    lowered = text.lower()
    if "in million" in lowered or "gbp m" in lowered or "£m" in lowered:
        return 1_000_000.0
    if "in thousand" in lowered or "£000" in lowered or "000s" in lowered:
        return 1_000.0
    return 1.0


def _extract_candidates_by_keywords(lines: List[str], keywords: List[str]) -> List[Tuple[float, float]]:
    candidates = []
    lowered_lines = [line.lower() for line in lines]
    for index, lowered_line in enumerate(lowered_lines):
        if not any(keyword in lowered_line for keyword in keywords):
            continue
        multiplier = _detect_unit_multiplier(lowered_line)
        numbers_here = _extract_all_numbers(lines[index])
        numbers_near = _extract_all_numbers(
            " ".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
        )
        for pos, value in enumerate(numbers_here):
            candidates.append((value * multiplier, 1.0 - 0.1 * pos))
        if not numbers_here:
            for pos, value in enumerate(numbers_near):
                candidates.append((value * multiplier, 0.6 - 0.1 * pos))
    return candidates


def _pick_turnover(candidates: List[Tuple[float, float]]) -> Optional[float]:
    positives = [value for value, _ in candidates if value > 0]
    return max(positives) if positives else None


def _pick_ebitda(candidates: List[Tuple[float, float]]) -> Optional[float]:
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda item: (item[1], abs(item[0])), reverse=True)
    return ranked[0][0]


def _pick_interest(candidates: List[Tuple[float, float]]) -> Optional[float]:
    if not candidates:
        return None
    negatives = [value for value, score in candidates if value < 0]
    if negatives:
        return min(negatives)
    positives = [value for value, score in candidates if value > 0]
    if positives:
        return min(positives)
    return None


def _pick_net_debt(candidates: List[Tuple[float, float]]) -> Optional[float]:
    if not candidates:
        return None
    positives = [value for value, _ in candidates if value > 0]
    if positives:
        return max(positives)
    return max((value for value, _ in candidates), default=None)


def extract_financials_from_text(text: str, source_format: str = "text") -> FilingFinancials:
    financials = FilingFinancials(source_format=source_format)
    financials.extracted_text_chars = len(text)
    normalized = WS_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    turnover_candidates = _extract_candidates_by_keywords(lines, ["turnover", "revenue", "sales"])
    ebitda_candidates = _extract_candidates_by_keywords(lines, ["ebitda"])
    operating_profit_candidates = _extract_candidates_by_keywords(
        lines,
        ["operating profit", "operating income", "profit before interest"],
    )
    depreciation_candidates = _extract_candidates_by_keywords(lines, ["depreciation"])
    amortisation_candidates = _extract_candidates_by_keywords(lines, ["amortisation", "amortization"])
    interest_candidates = _extract_candidates_by_keywords(
        lines,
        ["interest payable", "interest expense", "finance costs", "net finance costs"],
    )
    net_debt_candidates = _extract_candidates_by_keywords(lines, ["net debt"])
    borrowing_candidates = _extract_candidates_by_keywords(lines, ["borrowings", "loans"])
    cash_candidates = _extract_candidates_by_keywords(
        lines,
        ["cash at bank and in hand", "cash and cash equivalents", "cash balances"],
    )

    # Fallback to legacy regex across normalized text when line extraction fails.
    if not turnover_candidates:
        value = _extract_first(normalized, NUMBER_PATTERNS["turnover"])
        if value is not None:
            turnover_candidates.append((value, 0.5))
    if not ebitda_candidates:
        value = _extract_first(normalized, NUMBER_PATTERNS["ebitda"])
        if value is not None:
            ebitda_candidates.append((value, 0.5))
    if not interest_candidates:
        value = _extract_first(normalized, NUMBER_PATTERNS["interest_expense"])
        if value is not None:
            interest_candidates.append((value, 0.5))
    if not net_debt_candidates:
        value = _extract_first(normalized, NUMBER_PATTERNS["net_debt"])
        if value is not None:
            net_debt_candidates.append((value, 0.5))

    financials.turnover = _pick_turnover(turnover_candidates)
    financials.ebitda = _pick_ebitda(ebitda_candidates)
    operating_profit = _pick_ebitda(operating_profit_candidates)
    financials.depreciation = _pick_ebitda(depreciation_candidates)
    financials.amortisation = _pick_ebitda(amortisation_candidates)
    financials.interest_expense = _pick_interest(interest_candidates)
    financials.net_debt = _pick_net_debt(net_debt_candidates)
    borrowings = _pick_net_debt(borrowing_candidates)
    cash = _pick_turnover(cash_candidates)

    if financials.ebitda is None and operating_profit is not None:
        add_backs = [value for value in [financials.depreciation, financials.amortisation] if value]
        if add_backs:
            financials.ebitda = operating_profit + sum(add_backs)
            financials.extraction_notes.append(
                "EBITDA derived from operating profit plus depreciation/amortisation."
            )
        else:
            financials.extraction_notes.append(
                "Operating profit found but EBITDA could not be derived safely."
            )

    if financials.net_debt is None and borrowings is not None and cash is not None:
        financials.net_debt = borrowings - cash
        financials.extraction_notes.append("Net debt derived from borrowings minus cash.")

    missing = [
        label
        for label, value in [
            ("turnover", financials.turnover),
            ("ebitda", financials.ebitda),
            ("interest_expense", financials.interest_expense),
            ("net_debt", financials.net_debt),
        ]
        if value is None
    ]
    if missing:
        financials.extraction_notes.append(f"Missing values: {', '.join(missing)}.")
        if len(missing) >= 3:
            financials.extraction_confidence = "Low"
        else:
            financials.extraction_confidence = "Medium"
    else:
        if any(
            note.startswith("EBITDA derived") or note.startswith("Net debt derived")
            for note in financials.extraction_notes
        ):
            financials.extraction_confidence = "Medium"
        else:
            financials.extraction_confidence = "High"

    # Guard against tiny values caused by poor extraction noise.
    for field_name in ["turnover", "ebitda", "interest_expense", "net_debt"]:
        value = getattr(financials, field_name)
        if value is not None and abs(value) < 1:
            setattr(financials, field_name, None)
            financials.extraction_notes.append(
                f"Discarded implausibly small parsed value for {field_name}."
            )

    return financials


def _extract_with_pypdf(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts)


def _extract_with_pymupdf(pdf_bytes: bytes) -> str:
    import fitz

    parts = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        for page in document:
            parts.append(page.get_text("text") or "")
    return "\n".join(parts)


def _extract_with_pdfplumber(pdf_bytes: bytes) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        for page in document.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _get_ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _extract_with_rapidocr(pdf_bytes: bytes) -> str:
    import fitz
    import numpy as np

    engine = _get_ocr_engine()
    all_lines = []
    start = time.time()
    max_pages = 3
    max_seconds = 8
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        for index, page in enumerate(document):
            if index >= max_pages:
                break
            if time.time() - start > max_seconds:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            result, _elapsed = engine(img)
            if not result:
                continue
            for item in result:
                if len(item) >= 2:
                    text = item[1]
                    all_lines.append(text)
    return "\n".join(all_lines)


def extract_text_from_pdf_bytes_with_metadata(
    pdf_bytes: bytes,
) -> Tuple[str, str, List[str]]:
    attempts = []
    notes = []
    for engine_name, extractor in [
        ("pypdf", _extract_with_pypdf),
        ("pymupdf", _extract_with_pymupdf),
        ("pdfplumber", _extract_with_pdfplumber),
    ]:
        try:
            text = extractor(pdf_bytes)
            score = len(re.findall(r"[A-Za-z0-9]", text))
            attempts.append((score, text, engine_name))
        except Exception as exc:
            notes.append(f"{engine_name} failed: {exc}")
    if not attempts:
        raise RuntimeError("All PDF extraction engines failed.")
    attempts.sort(key=lambda item: item[0], reverse=True)
    best = attempts[0]

    # OCR fallback for image-heavy/scanned reports where text engines produce almost nothing.
    if best[0] < 100 and len(pdf_bytes) <= 1_000_000:
        try:
            ocr_text = _extract_with_rapidocr(pdf_bytes)
            ocr_score = len(re.findall(r"[A-Za-z0-9]", ocr_text))
            attempts.append((ocr_score, ocr_text, "rapidocr"))
            attempts.sort(key=lambda item: item[0], reverse=True)
            best = attempts[0]
        except Exception as exc:
            notes.append(f"rapidocr failed: {exc}")

    notes.append(
        "Engine scores: "
        + ", ".join(f"{engine}={score}" for score, _text, engine in attempts)
    )
    return best[1], best[2], notes


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    text, _engine, _notes = extract_text_from_pdf_bytes_with_metadata(pdf_bytes)
    return text
