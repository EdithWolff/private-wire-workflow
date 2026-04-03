import re
from dataclasses import dataclass
from typing import Optional


RATING_ORDER = [
    "AAA",
    "AA+",
    "AA",
    "AA-",
    "A+",
    "A",
    "A-",
    "BBB+",
    "BBB",
    "BBB-",
    "BB+",
    "BB",
    "BB-",
    "B+",
    "B",
    "B-",
    "CCC",
    "CC",
    "C",
    "D",
]

MOODYS_TO_SP = {
    "AAA": "AAA",
    "AA1": "AA+",
    "AA2": "AA",
    "AA3": "AA-",
    "A1": "A+",
    "A2": "A",
    "A3": "A-",
    "BAA1": "BBB+",
    "BAA2": "BBB",
    "BAA3": "BBB-",
    "BA1": "BB+",
    "BA2": "BB",
    "BA3": "BB-",
    "B1": "B+",
    "B2": "B",
    "B3": "B-",
    "CAA": "CCC",
    "CAA1": "CCC",
    "CAA2": "CCC",
    "CAA3": "CCC",
    "CA": "CC",
    "C": "C",
}


@dataclass
class RatingAssessment:
    source_text: str
    best_sp_equivalent: Optional[str]
    source_agency: str
    verdict: str
    reason: str


def _clean_rating(value: str) -> str:
    return re.sub(r"[^A-Z0-9+\-]", "", value.upper())


def _extract_sp_like(text: str) -> Optional[str]:
    upper = text.upper()
    ordered = sorted(RATING_ORDER, key=len, reverse=True)
    for rating in ordered:
        pattern = rf"(?<![A-Z0-9]){re.escape(rating)}(?![A-Z0-9])"
        if re.search(pattern, upper):
            return rating
    return None


def _extract_moodys(text: str) -> Optional[str]:
    candidates = re.findall(r"\b(?:AAA|AA1|AA2|AA3|A1|A2|A3|BAA1|BAA2|BAA3|BA1|BA2|BA3|B1|B2|B3|CAA1|CAA2|CAA3|CAA|CA|C)\b", text.upper())
    return candidates[0] if candidates else None


def rating_strictly_above_bbb_minus(rating: str) -> bool:
    normalized = _clean_rating(rating)
    if normalized not in RATING_ORDER:
        return False
    return RATING_ORDER.index(normalized) < RATING_ORDER.index("BBB-")


def assess_official_rating(text: str) -> RatingAssessment:
    source = text.strip()
    if not source or "UNRATED" in source.upper():
        return RatingAssessment(
            source_text=source,
            best_sp_equivalent=None,
            source_agency="",
            verdict="TBD",
            reason="No official rating found in rating source text.",
        )

    sp = _extract_sp_like(source)
    moodys = _extract_moodys(source)

    if sp:
        verdict = "Qualified" if rating_strictly_above_bbb_minus(sp) else "Disqualified"
        return RatingAssessment(
            source_text=source,
            best_sp_equivalent=sp,
            source_agency="S&P/Fitch-style",
            verdict=verdict,
            reason=f"Official rating {sp} {'is above' if verdict == 'Qualified' else 'is not above'} BBB-.",
        )

    if moodys:
        sp_equivalent = MOODYS_TO_SP.get(_clean_rating(moodys))
        verdict = "Qualified" if sp_equivalent and rating_strictly_above_bbb_minus(sp_equivalent) else "Disqualified"
        return RatingAssessment(
            source_text=source,
            best_sp_equivalent=sp_equivalent,
            source_agency="Moody's",
            verdict=verdict,
            reason=(
                f"Official Moody's rating {moodys} maps to {sp_equivalent}."
                if sp_equivalent
                else f"Official Moody's rating {moodys} could not be mapped."
            ),
        )

    return RatingAssessment(
        source_text=source,
        best_sp_equivalent=None,
        source_agency="",
        verdict="TBD",
        reason="Could not parse an official rating from source text.",
    )
