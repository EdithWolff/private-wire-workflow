import unittest

from private_wire_workflow.models import BankabilityResult, ContactCandidate, SiteCandidate
from private_wire_workflow.outreach import build_outreach_package
from private_wire_workflow.qa import validate_account_row, validate_site_row


class OutreachAndQATests(unittest.TestCase):
    def test_outreach_package_contains_slack_message(self):
        package = build_outreach_package(
            account_name="Example Co",
            bankability=BankabilityResult(
                verdict="Bankable",
                confidence="High",
                reason="Pass",
                entity_used="Example Co",
                rating_status="Rated pass",
                accounts_source="Ratings",
            ),
            sites=[SiteCandidate(site_name="North Plant", site_size_sqm=15_000, grade="3b")],
            contacts=[ContactCandidate("Alex Green", "Energy Director", "LinkedIn", confidence=0.9)],
        )
        self.assertIn("Meeting booked", package.slack_message)
        self.assertIn("North Plant", package.slack_message)

    def test_account_validation_catches_missing_fields(self):
        errors = validate_account_row({"account_name": "Example Co"})
        self.assertTrue(errors)

    def test_site_validation_catches_small_site(self):
        errors = validate_site_row(
            {
                "account_name": "Example Co",
                "site_name": "Small Site",
                "site_size_sqm": "5000",
                "grade": "3b",
                "jonathan_qualification": "Pending",
            }
        )
        self.assertIn("Site size is below the 10,000 sqm threshold.", errors)


if __name__ == "__main__":
    unittest.main()
