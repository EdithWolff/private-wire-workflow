import unittest

from private_wire_workflow.filing_bankability import assess_filing_bankability, calculate_bankability_ratios
from private_wire_workflow.models import FilingCandidate, FilingFinancials


class FilingBankabilityTests(unittest.TestCase):
    def test_calculates_ratios(self):
        margin, cover, leverage = calculate_bankability_ratios(1000, 150, -30, 200)
        self.assertAlmostEqual(margin, 0.15)
        self.assertAlmostEqual(cover, 5.0)
        self.assertAlmostEqual(leverage, 1.3333333333333333)

    def test_passes_all_thresholds(self):
        result = assess_filing_bankability(
            account_name="Example",
            company_number="123",
            entity_name="Example Ltd",
            filing=FilingCandidate(
                transaction_id="tx",
                category="accounts",
                description="accounts-with-accounts-type-full",
                description_values={},
                date="2025-12-31",
                type="AA",
                document_metadata_url="/document/abc",
            ),
            financials=FilingFinancials(
                turnover=1000,
                ebitda=150,
                interest_expense=-30,
                net_debt=200,
                source_format="xhtml",
            ),
            document_url="/document/abc",
        )
        self.assertEqual(result.verdict, "Bankable")

    def test_missing_values_go_to_review(self):
        result = assess_filing_bankability(
            account_name="Example",
            company_number="123",
            entity_name="Example Ltd",
            filing=FilingCandidate(
                transaction_id="tx",
                category="accounts",
                description="accounts-with-accounts-type-full",
                description_values={},
                date="2025-12-31",
                type="AA",
                document_metadata_url="/document/abc",
            ),
            financials=FilingFinancials(
                turnover=1000,
                ebitda=None,
                interest_expense=-30,
                net_debt=200,
                source_format="xhtml",
            ),
            document_url="/document/abc",
        )
        self.assertEqual(result.verdict, "Needs review")


if __name__ == "__main__":
    unittest.main()
