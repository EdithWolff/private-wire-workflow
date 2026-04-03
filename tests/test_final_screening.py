import unittest

from private_wire_workflow.final_screening import combine_rating_and_filing
from private_wire_workflow.models import FilingCandidate, FilingFinancials


class FinalScreeningTests(unittest.TestCase):
    def test_rating_overrides_filing(self):
        result = combine_rating_and_filing(
            company_name="Example Co",
            official_rating_text="A (S&P)",
            matched_entity="Example Ltd",
            company_number="123",
            filing=None,
            financials=None,
            document_url="",
            source_format="",
        )
        self.assertEqual(result.final_status, "Qualified")
        self.assertEqual(result.decision_basis, "Official rating")

    def test_filing_used_when_unrated(self):
        result = combine_rating_and_filing(
            company_name="Example Co",
            official_rating_text="Unrated",
            matched_entity="Example Ltd",
            company_number="123",
            filing=FilingCandidate(
                transaction_id="tx",
                category="accounts",
                description="accounts-with-accounts-type-full",
                description_values={},
                date="2025-12-31",
                type="AA",
                document_metadata_url="/doc",
            ),
            financials=FilingFinancials(
                turnover=1000,
                ebitda=150,
                interest_expense=-30,
                net_debt=200,
                source_format="pdf",
            ),
            document_url="/doc",
            source_format="pdf",
        )
        self.assertEqual(result.final_status, "Qualified")
        self.assertEqual(result.decision_basis, "Filing ratios")


if __name__ == "__main__":
    unittest.main()
