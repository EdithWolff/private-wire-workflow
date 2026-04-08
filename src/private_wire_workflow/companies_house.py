import base64
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date as _date
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

try:
    import certifi
    _CA_FILE = certifi.where()
except ImportError:
    _CA_FILE = None

from .models import FilingCandidate


API_BASE_URL = "https://api.company-information.service.gov.uk"
DOCUMENT_API_BASE_URL = "https://document-api.company-information.service.gov.uk"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Suppress automatic redirects so we can follow them with the right headers."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _RateLimiter:
    """Thread-safe token-bucket rate limiter.

    Allows up to *max_requests* in a rolling *window_sec* window.
    Callers block until a slot is available.
    """

    def __init__(self, max_requests: int = 500, window_sec: float = 300.0):
        self._max_requests = max_requests
        self._window_sec = window_sec
        self._timestamps: List[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - self._window_sec
                self._timestamps = [t for t in self._timestamps if t > cutoff]
                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return
                wait = self._timestamps[0] - cutoff
            time.sleep(max(wait, 0.1))


# Global limiter: 500 req / 5 min leaves headroom below the 600 hard cap.
_rate_limiter = _RateLimiter(max_requests=500, window_sec=300.0)


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
    matched_query: str = ""
    confidence_tier: str = "low"
    score_gap: float = 0.0
    runner_up_company_number: str = ""
    runner_up_score: float = 0.0
    entities_evaluated: int = 1


@dataclass
class NoMatchResult:
    """Diagnostic information when no substantive entity match is found."""
    company_name: str
    reason: str  # "no_candidates", "all_rejected_non_substantive", "score_below_threshold"
    candidates_found: int
    candidates_rejected: int
    rejection_details: List[str]
    best_rejected_name: str = ""
    best_rejected_number: str = ""
    best_rejected_score: float = 0.0


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


def _load_json(request: urllib.request.Request, _max_retries: int = 3) -> Dict:
    _rate_limiter.acquire()
    ssl_context = ssl.create_default_context(cafile=_CA_FILE)
    for attempt in range(1, _max_retries + 1):
        try:
            with urllib.request.urlopen(request, context=ssl_context, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = float(exc.headers.get("Retry-After", 5))
                wait = min(retry_after, 60) * attempt
                print(f"[rate-limit] 429 received, waiting {wait:.0f}s (attempt {attempt}/{_max_retries})", flush=True)
                time.sleep(wait)
                _rate_limiter.acquire()
                # Rebuild the request (urlopen consumes it)
                request = urllib.request.Request(
                    request.full_url,
                    headers=dict(request.headers),
                    method=request.get_method(),
                )
                continue
            raise
    # Final attempt without catching
    with urllib.request.urlopen(request, context=ssl_context, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_name(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or ch.isspace()).strip()


_LEGAL_SUFFIXES = {"ltd", "limited", "plc", "inc", "sa", "ag", "co", "llc", "gmbh", "bv", "nv"}
_FILLER_TOKENS = {
    "the", "of", "and", "uk", "group", "holdings", "holding", "services",
    "international", "company", "companies", "corporation", "corp",
    # Common industry words that appear in many company names but are not
    # distinctive enough to confirm a match on their own.
    "pharmaceuticals", "pharmaceutical", "pharma", "medical", "healthcare",
    "health", "technology", "technologies", "research", "sciences", "science",
    "laboratories", "laboratory", "labs", "industries", "industrial",
    "global", "worldwide", "europe", "emea", "asia", "pacific",
    "animal", "consumer", "products", "solutions", "systems", "stores",
    "beauty", "home", "care", "life", "bio", "nutrition", "food",
    "energy", "power", "chemicals", "chemical", "retail", "wholesale",
    "supply", "distribution", "logistics", "manufacturing",
    # Geographic tokens — city/country names are not distinctive brand words.
    "london", "beijing", "shanghai", "tokyo", "new", "york", "paris",
    "berlin", "munich", "zurich", "dublin", "edinburgh", "manchester",
    "bristol", "cambridge", "oxford", "china", "japan", "india",
    "usa", "america", "british", "english", "european", "nordic",
    "north", "south", "east", "west", "central",
}


def _strip_legal_suffixes(value: str) -> str:
    text = _normalize_name(value)
    tokens = [tok for tok in text.split() if tok not in _LEGAL_SUFFIXES]
    return " ".join(tokens).strip()


def _distinctive_tokens(value: str) -> set:
    """Return the core identifying tokens of a company name, stripped of legal
    suffixes and common filler words.  These are the tokens that *must* appear
    in any candidate match to be credible."""
    text = _normalize_name(value)
    tokens = [
        tok for tok in text.split()
        if tok not in _LEGAL_SUFFIXES and tok not in _FILLER_TOKENS and len(tok) > 2
    ]
    return set(tokens)


_REJECTED_STATUSES = {"dissolved", "liquidation", "converted-closed"}
_REJECTED_ACCOUNT_TYPES = {"dormant", "micro-entity", "unaudited-abridged"}
_DORMANT_SIC = {"99999"}


def _is_substantive_entity(profile: Dict) -> Tuple[bool, List[str]]:
    """Check whether a Companies House entity is substantive enough to have
    useful financial filings.  Returns ``(True, [])`` if acceptable, or
    ``(False, [reasons])`` if the entity should be skipped."""
    reasons: List[str] = []

    status = (profile.get("company_status") or "").lower()
    if status in _REJECTED_STATUSES:
        reasons.append(f"company_status={status}")

    accounts = profile.get("accounts", {})
    last_accounts = accounts.get("last_accounts", {})
    acc_type = (last_accounts.get("type") or "").lower()
    if acc_type in _REJECTED_ACCOUNT_TYPES:
        reasons.append(f"last_accounts_type={acc_type}")

    sic_codes = set(profile.get("sic_codes") or [])
    if sic_codes and sic_codes <= _DORMANT_SIC:
        reasons.append("sic_codes=99999_only")

    made_up_to = last_accounts.get("made_up_to", "")
    if not made_up_to:
        reasons.append("no_accounts_filed")
    else:
        try:
            last_date = _date.fromisoformat(made_up_to)
            if (_date.today() - last_date).days > 1825:
                reasons.append(f"accounts_stale={made_up_to}")
        except ValueError:
            pass

    return (len(reasons) == 0, reasons)


def _verify_original_overlap(original_name: str, candidate_title: str) -> bool:
    """Hard gate: distinctive tokens from the *original* company name must
    appear in the candidate title.  When the original has 2+ distinctive
    tokens, a *majority* (>50%) must overlap — not just one.  This prevents
    matches that only looked good against a broadened search variant (e.g.
    "Leica Biosystems" should not match "Leica Geosystems")."""
    orig_tokens = _distinctive_tokens(original_name)
    title_tokens = _distinctive_tokens(candidate_title)
    if not orig_tokens:
        return True  # No distinctive tokens to check (very generic name).
    overlap = orig_tokens & title_tokens
    if len(orig_tokens) >= 2:
        return len(overlap) / len(orig_tokens) > 0.5
    return bool(overlap)


def _query_variants(company_name: str, attempt: int = 0) -> List[str]:
    """Generate search query variants.  Higher attempt numbers produce
    progressively broader / more creative variants for the retry loop.

    attempt 0 — exact and lightly stripped (default, same as before)
    attempt 1 — add "ltd" / "limited" suffixed versions
    attempt 2 — core distinctive tokens only
    attempt 3 — first two distinctive tokens (catches abbreviated usage)
    attempt 4 — single most distinctive token (last resort)
    """
    base = company_name.strip()
    variants: List[str] = []

    if attempt <= 0:
        variants.append(base)
        stripped = _strip_legal_suffixes(base)
        if stripped and stripped != _normalize_name(base):
            variants.append(stripped)
        if "&" in base:
            variants.append(base.replace("&", "and"))
        normalized = " ".join(_normalize_name(base).split())
        if normalized and normalized not in variants:
            variants.append(normalized)
        reduced_tokens = [
            token
            for token in stripped.split()
            if token not in {"group", "holdings", "holding", "services"}
        ]
        if len(reduced_tokens) > 4:
            variants.append(" ".join(reduced_tokens[:4]))

    elif attempt == 1:
        stripped = _strip_legal_suffixes(base)
        if stripped:
            variants.append(f"{stripped} ltd")
            variants.append(f"{stripped} limited")
            variants.append(f"{stripped} uk")
            variants.append(f"{stripped} uk limited")

    elif attempt == 2:
        distinctive = list(_distinctive_tokens(base))
        if distinctive:
            variants.append(" ".join(distinctive))

    elif attempt == 3:
        distinctive = list(_distinctive_tokens(base))
        if len(distinctive) >= 2:
            variants.append(" ".join(distinctive[:2]))
        elif distinctive:
            variants.append(distinctive[0])

    elif attempt >= 4:
        distinctive = list(_distinctive_tokens(base))
        if distinctive:
            longest = max(distinctive, key=len)
            variants.append(longest)

    return list(dict.fromkeys([v for v in variants if v]))


def _confidence_tier(score: float, score_gap: float, status: str) -> str:
    if status == "active" and score >= 0.95 and score_gap >= 0.08:
        return "high"
    if score >= 0.85 and score_gap >= 0.03:
        return "medium"
    return "low"


def _rescore_with_profile(base_score: float, profile: Dict) -> float:
    """Re-score a candidate using full profile data (accounts type, etc.)."""
    score = base_score
    accounts = profile.get("accounts", {})
    last_accounts = accounts.get("last_accounts", {})
    acc_type = (last_accounts.get("type") or "").lower()
    if acc_type in ("group", "full"):
        score += 0.05
    return score


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

    # PLC entities are typically the main listed/trading entity.
    company_type = (item.get("company_type") or "").lower()
    if company_type == "plc":
        score += 0.05

    # --- Core token overlap gate ---
    # If the distinctive part of the query name shares zero tokens with the
    # candidate title, the match is almost certainly wrong (e.g. "Alnylam" vs
    # "Aquarium").  Cap the score well below any acceptance threshold.
    query_tokens = _distinctive_tokens(query)
    title_tokens = _distinctive_tokens(title)
    if query_tokens and title_tokens:
        overlap = query_tokens & title_tokens
        if not overlap:
            score = min(score, 0.40)

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
            ssl_context = ssl.create_default_context(cafile=_CA_FILE)
            https_handler = urllib.request.HTTPSHandler(context=ssl_context)
            opener = urllib.request.build_opener(_NoRedirect, https_handler)
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
    ssl_context = ssl.create_default_context(cafile=_CA_FILE)
    https_handler = urllib.request.HTTPSHandler(context=ssl_context)
    opener = urllib.request.build_opener(_NoRedirect, https_handler)
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


def _search_and_rank_candidates(
    company_name: str,
    api_key: str,
    max_search_rounds: int = 5,
) -> List[Tuple[float, Dict, str]]:
    """Search Companies House and return scored candidates, filtered by
    original-name token overlap, sorted best-first.  Shared by both
    ``find_best_match`` and ``find_best_match_with_filings``."""
    ranked_candidates: Dict[str, Tuple[float, Dict, str]] = {}
    tried_variants: set = set()

    for attempt in range(min(max_search_rounds, 5)):
        variants = _query_variants(company_name, attempt=attempt)
        new_variants = [v for v in variants if v not in tried_variants]
        if not new_variants:
            continue
        tried_variants.update(new_variants)

        for variant in new_variants:
            items = search_companies(variant, api_key, items_per_page=20)
            if not items:
                continue
            for item in items:
                company_number = item.get("company_number")
                if not company_number:
                    continue
                score = _score_candidate(variant, item)
                existing = ranked_candidates.get(company_number)
                if existing is None or score > existing[0]:
                    ranked_candidates[company_number] = (score, item, variant)

        if ranked_candidates:
            ranked = sorted(ranked_candidates.values(), key=lambda e: e[0], reverse=True)
            best_score, _, best_query = ranked[0]
            is_exact = _normalize_name(best_query) == _normalize_name(company_name)
            if best_score >= (0.78 if is_exact else 0.72):
                break

    if not ranked_candidates:
        return []

    ranked = sorted(ranked_candidates.values(), key=lambda e: e[0], reverse=True)
    return [
        (score, item, query) for score, item, query in ranked
        if _verify_original_overlap(company_name, item.get("title", ""))
    ]


def _build_match(
    company_name: str,
    profile: Dict,
    item: Dict,
    query: str,
    score: float,
    ranked: List[Tuple[float, Dict, str]],
    entities_evaluated: int,
) -> CompanyMatch:
    """Construct a ``CompanyMatch`` from a verified profile."""
    accounts = profile.get("accounts", {})
    next_accounts = accounts.get("next_accounts", {})
    last_accounts = accounts.get("last_accounts", {})
    runner_up_score = ranked[1][0] if len(ranked) > 1 else 0.0
    runner_up_number = ranked[1][1].get("company_number", "") if len(ranked) > 1 else ""

    return CompanyMatch(
        company_name=profile.get("company_name", item.get("title", company_name)),
        company_number=profile.get("company_number", item["company_number"]),
        status=profile.get("company_status", ""),
        company_type=profile.get("type", ""),
        sic_codes=profile.get("sic_codes", []),
        date_of_creation=profile.get("date_of_creation", ""),
        accounts_next_due=next_accounts.get("due_on", ""),
        accounts_last_made_up_to=last_accounts.get("made_up_to", ""),
        query_score=score,
        source_url=f"{API_BASE_URL}/company/{item['company_number']}",
        matched_query=query,
        confidence_tier=_confidence_tier(score, score - runner_up_score, profile.get("company_status", "")),
        score_gap=score - runner_up_score,
        runner_up_company_number=runner_up_number,
        runner_up_score=runner_up_score,
        entities_evaluated=entities_evaluated,
    )


def _build_no_match_result(
    company_name: str,
    ranked: List[Tuple[float, Dict, str]],
    rejected_entities: List[str],
) -> NoMatchResult:
    """Build a ``NoMatchResult`` from rejection tracking data."""
    if not ranked:
        reason = "no_candidates"
    elif not rejected_entities:
        reason = "score_below_threshold"
    else:
        reason = "all_rejected_non_substantive"
    return NoMatchResult(
        company_name=company_name,
        reason=reason,
        candidates_found=len(ranked),
        candidates_rejected=len(rejected_entities),
        rejection_details=rejected_entities,
    )


def find_best_match(
    company_name: str,
    api_key: str,
    max_attempts: int = 5,
    return_diagnostics: bool = False,
) -> "Optional[CompanyMatch] | NoMatchResult":
    """Search Companies House for the best substantive entity match.

    Uses two-pass scoring: initial ranking from search results, then
    re-scoring with full profile data (accounts type, etc.) to pick
    the best candidate from the top 3.

    When *return_diagnostics* is ``True`` and no match is found, returns
    a ``NoMatchResult`` instead of ``None``.
    """
    ranked = _search_and_rank_candidates(company_name, api_key, max_attempts)
    if not ranked:
        if return_diagnostics:
            return _build_no_match_result(company_name, ranked, [])
        return None

    # Two-pass: fetch profiles for candidates above threshold, re-score,
    # pick the best substantive one.  We evaluate up to 10 candidates to
    # handle cases where the top few are dormant/dissolved shells.
    rejected_entities: List[str] = []
    verified: List[Tuple[float, Dict, Dict, str]] = []  # (score, item, profile, query)

    for score, item, query in ranked[:10]:
        is_exact = _normalize_name(query) == _normalize_name(company_name)
        if score < (0.78 if is_exact else 0.72):
            continue

        profile = get_company_profile(item["company_number"], api_key)
        substantive, reasons = _is_substantive_entity(profile)
        if not substantive:
            detail = (
                f"{item.get('title', '?')} ({item['company_number']}): "
                f"{', '.join(reasons)}"
            )
            rejected_entities.append(detail)
            print(f"[skip entity] {detail}", flush=True)
            continue

        rescored = _rescore_with_profile(score, profile)
        verified.append((rescored, item, profile, query))
        # Once we have 3 verified candidates, no need to keep fetching.
        if len(verified) >= 3:
            break

    if not verified:
        if return_diagnostics:
            return _build_no_match_result(company_name, ranked, rejected_entities)
        return None

    verified.sort(key=lambda x: x[0], reverse=True)
    best_score, best_item, best_profile, best_query = verified[0]
    return _build_match(
        company_name, best_profile, best_item, best_query,
        best_score, ranked, len(verified) + len(rejected_entities),
    )


def find_best_match_with_filings(
    company_name: str,
    api_key: str,
    max_entity_attempts: int = 3,
    return_diagnostics: bool = False,
) -> "Optional[Tuple[CompanyMatch, List[FilingCandidate]]] | NoMatchResult":
    """Find a substantive entity *and* verify it has qualifying filings.

    Uses two-pass scoring: profiles are fetched for the top candidates,
    re-scored, and the best one with qualifying filings is selected.

    When *return_diagnostics* is ``True`` and no match is found, returns
    a ``NoMatchResult`` instead of ``None``.
    """
    from .filing_text_assessment import rank_accounts_filings  # lazy to avoid circular

    ranked = _search_and_rank_candidates(company_name, api_key)
    if not ranked:
        if return_diagnostics:
            return _build_no_match_result(company_name, ranked, [])
        return None

    rejected_entities: List[str] = []
    verified: List[Tuple[float, Dict, Dict, str, List[FilingCandidate]]] = []

    # Evaluate up to 10 candidates to handle cases where the top few are
    # dormant/dissolved.  Stop once we have enough verified candidates.
    for score, item, query in ranked[:10]:
        is_exact = _normalize_name(query) == _normalize_name(company_name)
        if score < (0.78 if is_exact else 0.72):
            continue

        profile = get_company_profile(item["company_number"], api_key)

        substantive, reasons = _is_substantive_entity(profile)
        if not substantive:
            detail = (
                f"{item.get('title', '?')} ({item['company_number']}): "
                f"{', '.join(reasons)}"
            )
            rejected_entities.append(detail)
            print(f"[skip entity] {detail}", flush=True)
            continue

        filings = list_accounts_filings(item["company_number"], api_key)
        if not rank_accounts_filings(filings):
            detail = (
                f"{item.get('title', '?')} ({item['company_number']}): "
                f"no qualifying filings"
            )
            rejected_entities.append(detail)
            print(f"[skip entity] {detail}", flush=True)
            continue

        rescored = _rescore_with_profile(score, profile)
        verified.append((rescored, item, profile, query, filings))
        if len(verified) >= max_entity_attempts:
            break

    if not verified:
        if return_diagnostics:
            return _build_no_match_result(company_name, ranked, rejected_entities)
        return None

    verified.sort(key=lambda x: x[0], reverse=True)
    best_score, best_item, best_profile, best_query, best_filings = verified[0]
    match = _build_match(
        company_name, best_profile, best_item, best_query,
        best_score, ranked, len(verified) + len(rejected_entities),
    )
    return (match, best_filings)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
        from pathlib import Path as _Path
        env_file = _Path(__file__).resolve().parents[2] / ".env.local"
        if env_file.exists():
            load_dotenv(env_file, override=False)
    except ImportError:
        pass


def get_api_key(env_var: str = "COMPANIES_HOUSE_API_KEY") -> str:
    _load_dotenv_if_available()
    api_key = os.getenv(env_var, "").strip()
    if not api_key:
        raise RuntimeError(
            f"Missing {env_var}. Set it in .env.local or export it before running."
        )
    return api_key
