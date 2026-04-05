import unittest
from unittest.mock import patch

from private_wire_workflow.filing_text_assessment import (
    assess_electricity_consumption,
    assess_filing_text_quality,
    assess_investment_grade_from_filing_text,
    assess_previous_ppa,
    assess_ratio_thresholds,
    assess_sustainability_targets,
    build_no_information_flags,
    compute_ratio_assessment_from_text,
    normalize_company_name,
    select_accounts_filing_automated,
    select_and_extract_best_filing_text,
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

    def test_select_accounts_filing_automated_falls_back_when_needed(self):
        filings = [
            FilingCandidate(
                transaction_id="1",
                category="accounts",
                description="accounts-with-accounts-type-small",
                description_values={},
                date="2025-06-01",
                type="AA",
                document_metadata_url="doc1",
            ),
            FilingCandidate(
                transaction_id="2",
                category="accounts",
                description="accounts-with-accounts-type-dormant",
                description_values={},
                date="2025-07-01",
                type="AA",
                document_metadata_url="doc2",
            ),
        ]
        selection = select_accounts_filing_automated(filings)
        self.assertIsNotNone(selection.filing)
        self.assertEqual(selection.filing.transaction_id, "1")
        self.assertEqual(selection.filing_type, "small_or_abridged")

    def test_assess_filing_text_quality_detects_partial_limited_accounts(self):
        text = """
        Balance sheet
        Creditors
        Cash at bank
        In accordance with Section 444 of the Companies Act 2006, the Profit & Loss Account has not been delivered.
        """
        quality = assess_filing_text_quality(text)
        self.assertEqual(quality.status, "partial")
        self.assertTrue(quality.limited_accounts)

    def test_assess_filing_text_quality_detects_usable_statement(self):
        text = "\n".join(
            [
                "Balance sheet",
                "Statement of comprehensive income",
                "Turnover 1000",
                "Operating profit 200",
                "Cash at bank and in hand 80",
                "Creditors 300",
            ]
            + [f"Line {index}" for index in range(30)]
        )
        quality = assess_filing_text_quality(text)
        self.assertEqual(quality.status, "usable")

    @patch("private_wire_workflow.filing_text_assessment.extract_best_filing_text")
    @patch("private_wire_workflow.companies_house.download_document_pdf_content")
    def test_select_and_extract_best_filing_text_retries_next_best_filing(self, mock_download, mock_extract):
        filings = [
            FilingCandidate(
                transaction_id="1",
                category="accounts",
                description="accounts-with-accounts-type-full",
                description_values={},
                date="2025-06-01",
                type="AA",
                document_metadata_url="doc1",
            ),
            FilingCandidate(
                transaction_id="2",
                category="accounts",
                description="accounts-with-accounts-type-small",
                description_values={},
                date="2025-07-01",
                type="AA",
                document_metadata_url="doc2",
            ),
        ]
        mock_download.side_effect = [b"pdf1", b"pdf2"]
        mock_extract.side_effect = [
            type("Result", (), {"text": "noise", "page_count": 1, "runtime_sec": 0.1, "engine": "native", "notes": []})(),
            type(
                "Result",
                (),
                {
                    "text": "\n".join([
                        "Balance sheet",
                        "Profit and loss",
                        "Turnover 1000",
                        "Cash at bank 20",
                        "Creditors 50",
                    ] + [f"Line {index}" for index in range(30)]),
                    "page_count": 2,
                    "runtime_sec": 0.2,
                    "engine": "native",
                    "notes": [],
                },
            )(),
        ]
        result = select_and_extract_best_filing_text(filings, api_key="dummy", max_attempts=2)

        self.assertIsNotNone(result)
        self.assertEqual(result.selection.filing.transaction_id, "2")
        self.assertEqual(result.quality.status, "usable")
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.attempts[0].txt_quality_status, "poor")
        self.assertEqual(result.attempts[1].txt_quality_status, "usable")

    def test_rank_accounts_filings_prefers_financial_information_candidates(self):
        filings = [
            FilingCandidate(
                transaction_id="1",
                category="accounts",
                description="accounts-with-accounts-type-dormant",
                description_values={},
                date="2025-06-01",
                type="AA",
                document_metadata_url="doc1",
            ),
            FilingCandidate(
                transaction_id="2",
                category="accounts",
                description="accounts-with-accounts-type-full",
                description_values={},
                date="2025-05-01",
                type="AA",
                document_metadata_url="doc2",
            ),
        ]
        ranked = select_accounts_filing_automated(filings)
        self.assertIsNotNone(ranked.filing)
        self.assertEqual(ranked.filing.transaction_id, "2")

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
