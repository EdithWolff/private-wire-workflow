import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from .models import FilingCandidate


API_BASE_URL = "https://api.company-information.service.gov.uk"
DOCUMENT_API_BASE_URL = "https://document-api.company-information.service.gov.uk"


@dataclass
class CompanyMatch:
    company_name: str
    company_number: str
    status: str
    company_type: str
    sic_codes: List[str]
    date_of_creation: str
    accounts_next_due: str
    accounts_last_made_up_to: str
    query_score: float
    source_url: str


def _build_request(path: str, api_key: str) -> urllib.request.Request:
    token = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    return urllib.request.Request(
        f"{API_BASE_URL}{path}",
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "private-wire-workflow/1.0",
        },
    )


def _build_document_request(path: str, api_key: str, accept: str = "application/json") -> urllib.request.Request:
    token = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    return urllib.request.Request(
        f"{DOCUMENT_API_BASE_URL}{path}",
        headers={
            "Authorization": f"Basic {token}",
            "Accept": accept,
            "User-Agent": "private-wire-workflow/1.0",
        },
    )


def _load_json(request: urllib.request.Request) -> Dict:
    ssl_context = ssl.create_default_context()
    with urllib.request.urlopen(request, context=ssl_context, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_name(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or ch.isspace()).strip()


def _strip_legal_suffixes(value: str) -> str:
    text = _normalize_name(value)
    tokens = [tok for tok in text.split() if tok not in {"ltd", "limited", "plc", "inc", "sa", "ag", "co"}]
    return " ".join(tokens).strip()


def _query_variants(company_name: str) -> List[str]:
    base = company_name.strip()
    variants = [base]
    stripped = _strip_legal_suffixes(base)
    if stripped and stripped != _normalize_name(base):
        variants.append(stripped)
    if "&" in base:
        variants.append(base.replace("&", "and"))
    return list(dict.fromkeys([v for v in variants if v]))


def _score_candidate(query: str, item: Dict) -> float:
    title = item.get("title", "")
    normalized_query = _normalize_name(query)
    normalized_title = _normalize_name(title)
    similarity = SequenceMatcher(None, normalized_query, normalized_title).ratio()

    score = similarity
    if item.get("company_status") == "active":
        score += 0.2
    if "ltd" in normalized_query and "ltd" in normalized_title:
        score += 0.03
    if normalized_query == normalized_title:
        score += 0.2
    return score


def search_companies(company_name: str, api_key: str, items_per_page: int = 10) -> List[Dict]:
    query = urllib.parse.quote(company_name)
    request = _build_request(
        f"/search/companies?q={query}&items_per_page={items_per_page}",
        api_key,
    )
    payload = _load_json(request)
    return payload.get("items", [])


def get_company_profile(company_number: str, api_key: str) -> Dict:
    request = _build_request(f"/company/{company_number}", api_key)
    return _load_json(request)


def get_filing_history(company_number: str, api_key: str, items_per_page: int = 100) -> Dict:
    request = _build_request(
        f"/company/{company_number}/filing-history?items_per_page={items_per_page}",
        api_key,
    )
    return _load_json(request)


def list_accounts_filings(company_number: str, api_key: str) -> List[FilingCandidate]:
    payload = get_filing_history(company_number, api_key)
    filings = []
    for item in payload.get("items", []):
        if item.get("category") != "accounts":
            continue
        filings.append(
            FilingCandidate(
                transaction_id=item.get("transaction_id", ""),
                category=item.get("category", ""),
                description=item.get("description", ""),
                description_values=item.get("description_values", {}),
                date=item.get("date", ""),
                type=item.get("type", ""),
                document_metadata_url=item.get("links", {}).get("document_metadata", ""),
            )
        )
    return filings


def select_best_accounts_filing(filings: List[FilingCandidate]) -> Optional[FilingCandidate]:
    if not filings:
        return None

    def is_dormant_or_micro(filing: FilingCandidate) -> bool:
        description = filing.description.lower()
        return "dormant" in description or "micro" in description

    candidates = [filing for filing in filings if filing.document_metadata_url]
    if not candidates:
        candidates = filings
    non_dormant = [filing for filing in candidates if not is_dormant_or_micro(filing)]
    if non_dormant:
        candidates = non_dormant

    def score(filing: FilingCandidate) -> Tuple[int, str]:
        description = filing.description.lower()
        weight = 0
        if "full" in description:
            weight += 4
        if "group" in description:
            weight += 3
        if "accounts-with-accounts-type-full" in description:
            weight += 5
        if "small" in description:
            weight -= 2
        if "micro" in description or "dormant" in description:
            weight -= 5
        if filing.document_metadata_url:
            weight += 2
        return weight, filing.date

    ranked = sorted(candidates, key=score, reverse=True)
    return ranked[0]


def get_document_metadata(document_metadata_url: str, api_key: str) -> Dict:
    path = urllib.parse.urlparse(document_metadata_url).path
    request = _build_document_request(path, api_key)
    return _load_json(request)


def download_document_content(document_metadata_url: str, api_key: str) -> Tuple[bytes, str]:
    metadata = get_document_metadata(document_metadata_url, api_key)
    resources = metadata.get("resources", {})
    preferred_types = [
        ("application/xhtml+xml", "xhtml"),
        ("text/html", "html"),
        ("application/xml", "xml"),
        ("application/pdf", "pdf"),
    ]
    content_path = urllib.parse.urlparse(metadata.get("links", {}).get("document", "")).path
    if not content_path:
        content_path = urllib.parse.urlparse(document_metadata_url).path + "/content"

    for mime_type, label in preferred_types:
        if mime_type in resources:
            request = _build_document_request(content_path, api_key, accept=mime_type)
            ssl_context = ssl.create_default_context()

            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None

            opener = urllib.request.build_opener(_NoRedirect)
            try:
                response = opener.open(request, timeout=60)
                return response.read(), label
            except urllib.error.HTTPError as error:
                if error.code not in (301, 302, 303, 307, 308):
                    raise
                redirect_url = error.headers.get("Location")
                if not redirect_url:
                    raise
                redirected = urllib.request.Request(
                    redirect_url,
                    headers={"User-Agent": "private-wire-workflow/1.0"},
                )
                with urllib.request.urlopen(redirected, context=ssl_context, timeout=60) as response:
                    return response.read(), label
    return b"", ""


def download_document_pdf_content(document_metadata_url: str, api_key: str) -> bytes:
    metadata = get_document_metadata(document_metadata_url, api_key)
    resources = metadata.get("resources", {})
    if "application/pdf" not in resources:
        return b""

    content_path = urllib.parse.urlparse(metadata.get("links", {}).get("document", "")).path
    if not content_path:
        content_path = urllib.parse.urlparse(document_metadata_url).path + "/content"

    request = _build_document_request(content_path, api_key, accept="application/pdf")
    ssl_context = ssl.create_default_context()

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        response = opener.open(request, timeout=60)
        return response.read()
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            raise
        redirect_url = error.headers.get("Location")
        if not redirect_url:
            raise
        redirected = urllib.request.Request(
            redirect_url,
            headers={"User-Agent": "private-wire-workflow/1.0"},
        )
        with urllib.request.urlopen(redirected, context=ssl_context, timeout=60) as response:
            return response.read()


def find_best_match(company_name: str, api_key: str) -> Optional[CompanyMatch]:
    best_item = None
    best_score = -1.0
    best_query = company_name

    for variant in _query_variants(company_name):
        items = search_companies(variant, api_key)
        if not items:
            continue
        ranked = sorted(items, key=lambda item: _score_candidate(variant, item), reverse=True)
        candidate = ranked[0]
        score = _score_candidate(variant, candidate)
        if score > best_score:
            best_score = score
            best_item = candidate
            best_query = variant

    if not best_item:
        return None

    strict_threshold = 0.78
    fallback_threshold = 0.72
    threshold = strict_threshold if _normalize_name(best_query) == _normalize_name(company_name) else fallback_threshold
    if best_score < threshold:
        return None

    profile = get_company_profile(best_item["company_number"], api_key)
    accounts = profile.get("accounts", {})
    next_accounts = accounts.get("next_accounts", {})
    last_accounts = accounts.get("last_accounts", {})

    return CompanyMatch(
        company_name=profile.get("company_name", best_item.get("title", company_name)),
        company_number=profile.get("company_number", best_item["company_number"]),
        status=profile.get("company_status", ""),
        company_type=profile.get("type", ""),
        sic_codes=profile.get("sic_codes", []),
        date_of_creation=profile.get("date_of_creation", ""),
        accounts_next_due=next_accounts.get("due_on", ""),
        accounts_last_made_up_to=last_accounts.get("made_up_to", ""),
        query_score=best_score,
        source_url=f"{API_BASE_URL}/company/{best_item['company_number']}",
    )


def get_api_key(env_var: str = "COMPANIES_HOUSE_API_KEY") -> str:
    api_key = os.getenv(env_var, "").strip()
    if not api_key:
        raise RuntimeError(
            f"Missing {env_var}. Export your Companies House key before running this script."
        )
    return api_key
