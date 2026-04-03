from dataclasses import dataclass
from typing import Optional

from .filing_bankability import assess_filing_bankability
from .models import FilingBankabilityResult, FilingCandidate, FilingFinancials
from .ratings import RatingAssessment, assess_official_rating


@dataclass
class FinalScreeningResult:
    company_name: str
    official_rating_text: str
    official_rating_sp_equivalent: Optional[str]
    official_rating_verdict: str
    matched_entity: str
    company_number: str
    filing_date: str
    filing_description: str
    turnover: Optional[float]
    ebitda: Optional[float]
    interest_expense: Optional[float]
    net_debt: Optional[float]
    ebitda_margin: Optional[float]
    interest_cover: Optional[float]
    net_debt_to_ebitda: Optional[float]
    final_status: str
    decision_basis: str
    notes: str
    document_url: str
    source_format: str


def combine_rating_and_filing(
    company_name: str,
    official_rating_text: str,
    matched_entity: str,
    company_number: str,
    filing: Optional[FilingCandidate],
    financials: Optional[FilingFinancials],
    document_url: str,
    source_format: str,
) -> FinalScreeningResult:
    rating = assess_official_rating(official_rating_text)

    if rating.verdict in {"Qualified", "Disqualified"}:
        return FinalScreeningResult(
            company_name=company_name,
            official_rating_text=official_rating_text,
            official_rating_sp_equivalent=rating.best_sp_equivalent,
            official_rating_verdict=rating.verdict,
            matched_entity=matched_entity,
            company_number=company_number,
            filing_date=filing.date if filing else "",
            filing_description=filing.description if filing else "",
            turnover=None,
            ebitda=None,
            interest_expense=None,
            net_debt=None,
            ebitda_margin=None,
            interest_cover=None,
            net_debt_to_ebitda=None,
            final_status=rating.verdict,
            decision_basis="Official rating",
            notes=rating.reason,
            document_url=document_url,
            source_format=source_format,
        )

    if filing is None or financials is None:
        return FinalScreeningResult(
            company_name=company_name,
            official_rating_text=official_rating_text,
            official_rating_sp_equivalent=rating.best_sp_equivalent,
            official_rating_verdict=rating.verdict,
            matched_entity=matched_entity,
            company_number=company_number,
            filing_date="",
            filing_description="",
            turnover=None,
            ebitda=None,
            interest_expense=None,
            net_debt=None,
            ebitda_margin=None,
            interest_cover=None,
            net_debt_to_ebitda=None,
            final_status="Needs review",
            decision_basis="Missing filing data",
            notes=rating.reason,
            document_url=document_url,
            source_format=source_format,
        )

    filing_result: FilingBankabilityResult = assess_filing_bankability(
        account_name=company_name,
        company_number=company_number,
        entity_name=matched_entity,
        filing=filing,
        financials=financials,
        document_url=document_url,
        entity_scope="group" if "group" in filing.description.lower() else "company",
    )
    final_status = {
        "Bankable": "Qualified",
        "Not bankable": "Disqualified",
        "Needs review": "Needs review",
    }[filing_result.verdict]
    return FinalScreeningResult(
        company_name=company_name,
        official_rating_text=official_rating_text,
        official_rating_sp_equivalent=rating.best_sp_equivalent,
        official_rating_verdict=rating.verdict,
        matched_entity=matched_entity,
        company_number=company_number,
        filing_date=filing_result.filing_date,
        filing_description=filing_result.filing_description,
        turnover=filing_result.turnover,
        ebitda=filing_result.ebitda,
        interest_expense=filing_result.interest_expense,
        net_debt=filing_result.net_debt,
        ebitda_margin=filing_result.ebitda_margin,
        interest_cover=filing_result.interest_cover,
        net_debt_to_ebitda=filing_result.net_debt_to_ebitda,
        final_status=final_status,
        decision_basis="Filing ratios",
        notes=filing_result.review_reason,
        document_url=document_url,
        source_format=source_format,
    )
