from typing import Iterable, List

from .models import ContactCandidate


ROLE_PRIORITY = {
    "energy director": 5,
    "sustainability director": 4,
    "indirect sourcing": 3,
    "procurement manager": 3,
    "site manager": 1,
}


def _role_score(title: str) -> int:
    normalized = title.strip().lower()
    for key, value in ROLE_PRIORITY.items():
        if key in normalized:
            return value
    return 0


def _dedupe_key(contact: ContactCandidate) -> str:
    if contact.email:
        return contact.email.strip().lower()
    return f"{contact.full_name.strip().lower()}::{contact.title.strip().lower()}"


def select_target_contacts(
    contacts: Iterable[ContactCandidate],
    limit: int = 5,
    min_confidence: float = 0.45,
) -> List[ContactCandidate]:
    deduped = {}
    for contact in contacts:
        if contact.confidence < min_confidence:
            continue
        if _role_score(contact.title) == 0:
            continue
        key = _dedupe_key(contact)
        current = deduped.get(key)
        if current is None or (
            _role_score(contact.title),
            contact.confidence,
        ) > (_role_score(current.title), current.confidence):
            deduped[key] = contact

    ranked = sorted(
        deduped.values(),
        key=lambda contact: (_role_score(contact.title), contact.confidence),
        reverse=True,
    )
    return ranked[:limit]
