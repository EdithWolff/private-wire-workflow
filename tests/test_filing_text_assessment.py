import unittest

from private_wire_workflow.filing_text_assessment import (
    assess_electricity_consumption,
    assess_investment_grade_from_filing_text,
    assess_previous_ppa,
    assess_ratio_thresholds,
    assess_sustainability_targets,
    build_no_information_flags,
    compute_ratio_assessment_from_text,
    normalize_company_name,
    select_latest_non_dormant_full_accounts,
)
from private_wire_workflow.models import FilingCandidate


class FilingTextAssessmentTests(unittest.TestCase):
    def test_normalize_company_name(self):
        self.assertEqual(normalize_company_name("A.B. Company Ltd!"), "a_b_company_ltd")

    def test_select_latest_non_dormant_full_accounts(self):
        filings = [
            FilingCandidate(
                transaction_id="1",
                category="accounts",
                description="accounts-with-accounts-type-dormant",
                description_values={},
                date="2025-01-01",
                type="AA",
                document_metadata_url="doc1",
            ),
            FilingCandidate(
                transaction_id="2",
                category="accounts",
                description="accounts-with-accounts-type-full",
                description_values={},
                date="2024-01-01",
                type="AA",
                document_metadata_url="doc2",
            ),
            FilingCandidate(
                transaction_id="3",
                category="accounts",
                description="accounts-with-accounts-type-full-group",
                description_values={},
                date="2025-06-01",
                type="AA",
                document_metadata_url="doc3",
            ),
        ]
        selected = select_latest_non_dormant_full_accounts(filings)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.transaction_id, "3")

    def test_assess_investment_grade(self):
        yes, _ = assess_investment_grade_from_filing_text("Issuer credit rating: BBB")
        no, _ = assess_investment_grade_from_filing_text("Issuer credit rating: BB+")
        no_info, _ = assess_investment_grade_from_filing_text("No rating in this report.")
        self.assertEqual(yes, "Yes")
        self.assertEqual(no, "No")
        self.assertEqual(no_info, "No information found")

    def test_ratio_assessment(self):
        metrics_yes = {
            "ebitda_margin": 0.2,
            "interest_coverage": 4.0,
            "net_debt_to_ebitda": 1.1,
        }
        metrics_no = {
            "ebitda_margin": 0.08,
            "interest_coverage": 2.1,
            "net_debt_to_ebitda": 2.5,
        }
        metrics_missing = {
            "ebitda_margin": None,
            "interest_coverage": 3.5,
            "net_debt_to_ebitda": 1.2,
        }
        self.assertEqual(assess_ratio_thresholds(metrics_yes), "Yes")
        self.assertEqual(assess_ratio_thresholds(metrics_no), "No")
        self.assertEqual(assess_ratio_thresholds(metrics_missing), "No information found")

    def test_compute_ratios_from_text(self):
        text = """
        Turnover 1000
        EBITDA 200
        Interest expense (50)
        Debt 500
        Cash 100
        """
        metrics = compute_ratio_assessment_from_text(text)
        self.assertEqual(metrics["turnover"], 1000)
        self.assertEqual(metrics["ebitda"], 200)
        self.assertEqual(metrics["interest_expense"], -50)
        self.assertEqual(metrics["debt"], 500)
        self.assertEqual(metrics["cash"], 100)
        self.assertEqual(metrics["net_debt"], 400)

    def test_signal_questions(self):
        self.assertEqual(
            assess_electricity_consumption("Total 35 GWh and site demand 9 GWh."),
            "Yes",
        )
        self.assertEqual(
            assess_sustainability_targets("Net zero by 2040 and Scope 2 reduction target."),
            "Yes",
        )
        self.assertEqual(
            assess_previous_ppa("The business signed a wind PPA in 2023."),
            "Yes",
        )
        self.assertEqual(assess_previous_ppa("No statement about procurement."), "No information found")

    def test_no_information_flags(self):
        metrics = {
            "turnover": None,
            "ebitda": None,
            "interest_expense": None,
            "debt": None,
            "cash": None,
            "net_debt": None,
        }
        flags = build_no_information_flags(
            q1="No information found",
            q2="No information found",
            q3="No information found",
            q4="No information found",
            q5="No information found",
            metrics=metrics,
        )
        self.assertIn("q1", flags)
        self.assertIn("missing_turnover", flags)


if __name__ == "__main__":
    unittest.main()
