from typing import Dict, Optional

NO_INFO = "No information found"


def fmt_number(value: Optional[float]) -> str:
    if value is None:
        return NO_INFO
    return f"{value:.6g}"


def fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return NO_INFO
    return f"{value * 100:.2f}%"


def ratio_flags(metrics: Dict[str, Optional[float]]) -> Dict[str, str]:
    margin = metrics.get("ebitda_margin")
    coverage = metrics.get("interest_coverage")
    leverage = metrics.get("net_debt_to_ebitda")
    return {
        "margin_ge_10": "Yes" if margin is not None and margin >= 0.10 else ("No" if margin is not None else NO_INFO),
        "coverage_ge_3x": "Yes" if coverage is not None and coverage >= 3 else ("No" if coverage is not None else NO_INFO),
        "netdebt_ebitda_le_2x": "Yes" if leverage is not None and leverage <= 2 else ("No" if leverage is not None else NO_INFO),
    }


def entity_scope(description: str) -> str:
    return "group" if "group" in description.lower() else "company"
