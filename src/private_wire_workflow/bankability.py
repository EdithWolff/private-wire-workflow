from typing import Optional

from .models import AccountScreeningInput, BankabilityResult


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
]

RATING_THRESHOLD_INDEX = RATING_ORDER.index("BBB-")


def normalize_rating(rating: str) -> str:
    return rating.strip().upper()


def rating_passes(rating: str) -> bool:
    normalized = normalize_rating(rating)
    if normalized not in RATING_ORDER:
        return False
    return RATING_ORDER.index(normalized) <= RATING_THRESHOLD_INDEX


def _has_strong_financials(data: AccountScreeningInput) -> bool:
    return (
        (data.profitability_ratio or 0) >= 0.08
        and (data.interest_cover_ratio or 0) >= 3.0
        and (data.leverage_ratio or 99) <= 4.5
        and (data.liquidity_ratio or 0) >= 1.0
    )


def _has_weak_financials(data: AccountScreeningInput) -> bool:
    return (
        (data.profitability_ratio is not None and data.profitability_ratio < 0.03)
        or (data.interest_cover_ratio is not None and data.interest_cover_ratio < 1.5)
        or (data.leverage_ratio is not None and data.leverage_ratio > 6.0)
        or (data.liquidity_ratio is not None and data.liquidity_ratio < 0.8)
    )


def _stale_accounts(latest_accounts_age_months: Optional[int]) -> bool:
    return latest_accounts_age_months is None or latest_accounts_age_months > 18


def assess_bankability(data: AccountScreeningInput) -> BankabilityResult:
    entity_used = data.entity_name or data.account_name
    if data.revenue_gbp <= 1_000_000_000:
        return BankabilityResult(
            verdict="Not bankable",
            confidence="High",
            reason="Below revenue threshold.",
            entity_used=entity_used,
            rating_status="Not assessed",
            accounts_source=data.accounts_source,
        )

    if not data.uk_presence:
        return BankabilityResult(
            verdict="Not bankable",
            confidence="High",
            reason="No confirmed UK presence.",
            entity_used=entity_used,
            rating_status="Not assessed",
            accounts_source=data.accounts_source,
        )

    if data.credit_rating:
        if rating_passes(data.credit_rating):
            return BankabilityResult(
                verdict="Bankable",
                confidence="High",
                reason=f"External rating {normalize_rating(data.credit_rating)} meets BBB- threshold.",
                entity_used=entity_used,
                rating_status="Rated pass",
                accounts_source=data.rating_source or data.accounts_source,
            )
        return BankabilityResult(
            verdict="Not bankable",
            confidence="High",
            reason=f"External rating {normalize_rating(data.credit_rating)} is below BBB-.",
            entity_used=entity_used,
            rating_status="Rated fail",
            accounts_source=data.rating_source or data.accounts_source,
        )

    if _stale_accounts(data.latest_accounts_age_months):
        return BankabilityResult(
            verdict="Needs review",
            confidence="Low",
            reason="Latest available accounts are stale or missing.",
            entity_used=entity_used,
            rating_status="Unrated",
            accounts_source=data.accounts_source,
        )

    if _has_strong_financials(data):
        return BankabilityResult(
            verdict="Bankable",
            confidence="Medium",
            reason="Unrated account passes proxy financial thresholds.",
            entity_used=entity_used,
            rating_status="Proxy pass",
            accounts_source=data.accounts_source,
        )

    if _has_weak_financials(data):
        if data.group_support_available:
            return BankabilityResult(
                verdict="Needs review",
                confidence="Medium",
                reason="Standalone entity looks weak but group support may exist.",
                entity_used=entity_used,
                rating_status="Proxy review",
                accounts_source=data.accounts_source,
            )
        return BankabilityResult(
            verdict="Not bankable",
            confidence="Medium",
            reason="Unrated account fails proxy financial thresholds.",
            entity_used=entity_used,
            rating_status="Proxy fail",
            accounts_source=data.accounts_source,
        )

    return BankabilityResult(
        verdict="Needs review",
        confidence="Low",
        reason="Financial profile is incomplete or mixed.",
        entity_used=entity_used,
        rating_status="Unrated",
        accounts_source=data.accounts_source,
    )
