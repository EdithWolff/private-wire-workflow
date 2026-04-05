from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AccountScreeningInput:
    account_name: str
    revenue_gbp: float
    uk_presence: bool
    entity_name: str = ""
    company_number: str = ""
    credit_rating: str = ""
    rating_source: str = ""
    latest_accounts_age_months: Optional[int] = None
    profitability_ratio: Optional[float] = None
    interest_cover_ratio: Optional[float] = None
    leverage_ratio: Optional[float] = None
    liquidity_ratio: Optional[float] = None
    group_support_available: bool = False
    accounts_source: str = "Companies House"
    notes: str = ""


@dataclass
class BankabilityResult:
    verdict: str
    confidence: str
    reason: str
    entity_used: str
    rating_status: str
    accounts_source: str


@dataclass
class SiteCandidate:
    site_name: str
    parcel_id: str = ""
    site_size_sqm: float = 0
    grade: str = ""
    urban_flag: bool = False
    adjacent_land_flag: bool = False
    energy_intensity_hint: bool = False
    evidence: str = ""
    notes: str = ""
    score: float = 0


@dataclass
class ContactCandidate:
    full_name: str
    title: str
    source: str
    email: str = ""
    linkedin_url: str = ""
    confidence: float = 0.0


@dataclass
class OutreachPackage:
    account_name: str
    bankability_verdict: str
    top_sites: List[SiteCandidate] = field(default_factory=list)
    contacts: List[ContactCandidate] = field(default_factory=list)
    cadence: str = "Cold outreach cadence - English"
    slack_message: str = ""


@dataclass
class FilingCandidate:
    transaction_id: str
    category: str
    description: str
    description_values: dict
    date: str
    type: str
    document_metadata_url: str = ""


@dataclass
class FilingSelection:
    filing: Optional[FilingCandidate] = None
    confidence: str = "none"
    filing_type: str = ""
    reason_codes: List[str] = field(default_factory=list)
    fallback_used: bool = False


@dataclass
class TextQualityAssessment:
    status: str = "poor"
    score: float = 0.0
    char_count: int = 0
    line_count: int = 0
    has_balance_sheet: bool = False
    has_income_statement: bool = False
    has_cash_markers: bool = False
    has_debt_markers: bool = False
    limited_accounts: bool = False
    reason_codes: List[str] = field(default_factory=list)


@dataclass
class FilingFinancials:
    turnover: Optional[float] = None
    ebitda: Optional[float] = None
    interest_expense: Optional[float] = None
    net_debt: Optional[float] = None
    depreciation: Optional[float] = None
    amortisation: Optional[float] = None
    source_format: str = ""
    extraction_confidence: str = "Low"
    extraction_engine: str = ""
    extracted_text_chars: int = 0
    extraction_notes: List[str] = field(default_factory=list)


@dataclass
class FilingBankabilityResult:
    account_name: str
    company_number: str
    entity_name: str
    filing_date: str
    filing_description: str
    entity_scope: str
    turnover: Optional[float]
    ebitda: Optional[float]
    interest_expense: Optional[float]
    net_debt: Optional[float]
    ebitda_margin: Optional[float]
    interest_cover: Optional[float]
    net_debt_to_ebitda: Optional[float]
    verdict: str
    review_reason: str
    document_url: str
    source_format: str
