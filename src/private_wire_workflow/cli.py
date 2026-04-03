import csv
from pathlib import Path

from .bankability import assess_bankability
from .contacts import select_target_contacts
from .models import AccountScreeningInput, ContactCandidate, SiteCandidate
from .outreach import build_outreach_package
from .site_screening import rank_sites


ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_TEMPLATE = ROOT / "data" / "templates" / "account_screening_template.csv"


def _sample_contacts():
    return [
        ContactCandidate(
            full_name="Alex Green",
            title="Energy Director",
            source="LinkedIn",
            email="alex.green@example.com",
            confidence=0.9,
        ),
        ContactCandidate(
            full_name="Pat Woods",
            title="Procurement Manager",
            source="Lusha",
            email="pat.woods@example.com",
            confidence=0.8,
        ),
    ]


def _sample_sites():
    return [
        SiteCandidate(
            site_name="North Plant",
            parcel_id="PID-001",
            site_size_sqm=18_500,
            grade="3b",
            urban_flag=False,
            adjacent_land_flag=True,
            energy_intensity_hint=True,
        ),
        SiteCandidate(
            site_name="City Depot",
            parcel_id="PID-002",
            site_size_sqm=9_000,
            grade="3b",
            urban_flag=True,
            adjacent_land_flag=False,
        ),
    ]


def main() -> None:
    with ACCOUNT_TEMPLATE.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))

    account = AccountScreeningInput(
        account_name=row["account_name"],
        revenue_gbp=float(row["revenue_gbp"]),
        uk_presence=row["uk_presence"].strip().lower() == "yes",
        notes=row["next_action"],
    )
    bankability = assess_bankability(account)
    sites = rank_sites(_sample_sites())
    contacts = select_target_contacts(_sample_contacts())
    package = build_outreach_package(account.account_name, bankability, sites, contacts)

    print(f"Account: {package.account_name}")
    print(f"Bankability: {package.bankability_verdict}")
    print(f"Selected sites: {', '.join(site.site_name for site in package.top_sites) or 'None'}")
    print(f"Selected contacts: {', '.join(contact.full_name for contact in package.contacts) or 'None'}")
    print(f"Slack message: {package.slack_message}")


if __name__ == "__main__":
    main()
