from typing import Iterable

from .models import BankabilityResult, ContactCandidate, OutreachPackage, SiteCandidate


def build_slack_message(
    account_name: str,
    meeting_date: str,
    person_name: str,
    person_role: str,
    site_name: str,
) -> str:
    return (
        "Meeting booked | "
        f"Account: {account_name} | "
        f"Date: {meeting_date} | "
        f"Name: {person_name} | "
        f"Role: {person_role} | "
        f"Site pitched: {site_name}"
    )


def build_outreach_package(
    account_name: str,
    bankability: BankabilityResult,
    sites: Iterable[SiteCandidate],
    contacts: Iterable[ContactCandidate],
) -> OutreachPackage:
    site_list = list(sites)
    contact_list = list(contacts)
    return OutreachPackage(
        account_name=account_name,
        bankability_verdict=bankability.verdict,
        top_sites=site_list,
        contacts=contact_list,
        slack_message=build_slack_message(
            account_name=account_name,
            meeting_date="TBD",
            person_name=contact_list[0].full_name if contact_list else "TBD",
            person_role=contact_list[0].title if contact_list else "TBD",
            site_name=site_list[0].site_name if site_list else "TBD",
        ),
    )
