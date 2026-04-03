from typing import Optional, Tuple

from .models import FilingBankabilityResult, FilingCandidate, FilingFinancials


def calculate_bankability_ratios(
    turnover: Optional[float],
    ebitda: Optional[float],
    interest_expense: Optional[float],
    net_debt: Optional[float],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    ebitda_margin = None
    interest_cover = None
    net_debt_to_ebitda = None

    if turnover not in (None, 0) and ebitda is not None:
        ebitda_margin = ebitda / turnover
    if interest_expense not in (None, 0) and ebitda is not None:
        interest_cover = ebitda / abs(interest_expense)
    if ebitda not in (None, 0) and net_debt is not None:
        net_debt_to_ebitda = net_debt / ebitda
    return ebitda_margin, interest_cover, net_debt_to_ebitda


def assess_filing_bankability(
    account_name: str,
    company_number: str,
    entity_name: str,
    filing: FilingCandidate,
    financials: FilingFinancials,
    document_url: str,
    entity_scope: str = "company",
) -> FilingBankabilityResult:
    ebitda_margin, interest_cover, net_debt_to_ebitda = calculate_bankability_ratios(
        financials.turnover,
        financials.ebitda,
        financials.interest_expense,
        financials.net_debt,
    )

    missing_core = [
        label
        for label, value in [
            ("turnover", financials.turnover),
            ("ebitda", financials.ebitda),
            ("interest expense", financials.interest_expense),
            ("net debt", financials.net_debt),
        ]
        if value is None
    ]
    if missing_core:
        detail = f"Extraction confidence={financials.extraction_confidence}."
        if financials.extraction_notes:
            detail = f"{detail} Notes: {' '.join(financials.extraction_notes)}"
        return FilingBankabilityResult(
            account_name=account_name,
            company_number=company_number,
            entity_name=entity_name,
            filing_date=filing.date,
            filing_description=filing.description,
            entity_scope=entity_scope,
            turnover=financials.turnover,
            ebitda=financials.ebitda,
            interest_expense=financials.interest_expense,
            net_debt=financials.net_debt,
            ebitda_margin=ebitda_margin,
            interest_cover=interest_cover,
            net_debt_to_ebitda=net_debt_to_ebitda,
            verdict="Needs review",
            review_reason=f"Missing required values: {', '.join(missing_core)}. {detail}",
            document_url=document_url,
            source_format=financials.source_format,
        )

    if financials.ebitda is not None and financials.ebitda <= 0:
        verdict = "Not bankable"
        reason = "EBITDA is zero or negative."
    elif (
        ebitda_margin is not None
        and interest_cover is not None
        and net_debt_to_ebitda is not None
        and ebitda_margin > 0.10
        and interest_cover > 3
        and net_debt_to_ebitda < 2
    ):
        verdict = "Bankable"
        reason = "All filing-based thresholds pass."
    else:
        verdict = "Not bankable"
        failures = []
        if ebitda_margin is None or ebitda_margin <= 0.10:
            failures.append("EBITDA/Turnover <= 10%")
        if interest_cover is None or interest_cover <= 3:
            failures.append("Interest cover <= 3")
        if net_debt_to_ebitda is None or net_debt_to_ebitda >= 2:
            failures.append("Net debt/EBITDA >= 2")
        reason = "; ".join(failures) if failures else "Thresholds not met."

    reason = (
        f"{reason} Extraction confidence={financials.extraction_confidence}."
        + (f" Notes: {' '.join(financials.extraction_notes)}" if financials.extraction_notes else "")
    )

    return FilingBankabilityResult(
        account_name=account_name,
        company_number=company_number,
        entity_name=entity_name,
        filing_date=filing.date,
        filing_description=filing.description,
        entity_scope=entity_scope,
        turnover=financials.turnover,
        ebitda=financials.ebitda,
        interest_expense=financials.interest_expense,
        net_debt=financials.net_debt,
        ebitda_margin=ebitda_margin,
        interest_cover=interest_cover,
        net_debt_to_ebitda=net_debt_to_ebitda,
        verdict=verdict,
        review_reason=reason,
        document_url=document_url,
        source_format=financials.source_format,
    )
