from typing import Iterable, List

from .models import SiteCandidate


def _grade_allowed(grade: str) -> bool:
    normalized = grade.strip().lower()
    allowed = {"1", "2", "3a", "3b", ""}
    return normalized in allowed


def score_site(site: SiteCandidate) -> float:
    score = 0.0
    if site.site_size_sqm >= 10_000:
        score += 50
    elif site.site_size_sqm >= 8_000:
        score += 20
    else:
        score -= 50

    if site.adjacent_land_flag:
        score += 20
    if not site.urban_flag:
        score += 15
    else:
        score -= 20
    if _grade_allowed(site.grade):
        score += 10
    else:
        score -= 40
    if site.energy_intensity_hint:
        score += 15
    return score


def is_viable_site(site: SiteCandidate) -> bool:
    if site.site_size_sqm < 10_000:
        return False
    if site.urban_flag:
        return False
    if not _grade_allowed(site.grade):
        return False
    return True


def rank_sites(sites: Iterable[SiteCandidate], limit: int = 3) -> List[SiteCandidate]:
    scored = []
    for site in sites:
        site.score = score_site(site)
        if is_viable_site(site):
            scored.append(site)
    return sorted(scored, key=lambda site: site.score, reverse=True)[:limit]
