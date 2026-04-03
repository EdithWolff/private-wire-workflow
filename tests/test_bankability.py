import unittest

from private_wire_workflow.bankability import assess_bankability
from private_wire_workflow.models import AccountScreeningInput


class BankabilityTests(unittest.TestCase):
    def test_rated_company_passes(self):
        result = assess_bankability(
            AccountScreeningInput(
                account_name="Rated Co",
                revenue_gbp=1_500_000_000,
                uk_presence=True,
                credit_rating="BBB",
            )
        )
        self.assertEqual(result.verdict, "Bankable")

    def test_rated_company_below_threshold_fails(self):
        result = assess_bankability(
            AccountScreeningInput(
                account_name="Weak Rated Co",
                revenue_gbp=1_500_000_000,
                uk_presence=True,
                credit_rating="BB+",
            )
        )
        self.assertEqual(result.verdict, "Not bankable")

    def test_unrated_strong_company_proxy_passes(self):
        result = assess_bankability(
            AccountScreeningInput(
                account_name="Strong Co",
                revenue_gbp=1_300_000_000,
                uk_presence=True,
                latest_accounts_age_months=12,
                profitability_ratio=0.11,
                interest_cover_ratio=4.2,
                leverage_ratio=3.1,
                liquidity_ratio=1.4,
            )
        )
        self.assertEqual(result.verdict, "Bankable")

    def test_group_support_escalates_to_review(self):
        result = assess_bankability(
            AccountScreeningInput(
                account_name="Group Co",
                revenue_gbp=1_300_000_000,
                uk_presence=True,
                latest_accounts_age_months=10,
                profitability_ratio=0.02,
                interest_cover_ratio=1.0,
                leverage_ratio=7.0,
                liquidity_ratio=0.7,
                group_support_available=True,
            )
        )
        self.assertEqual(result.verdict, "Needs review")

    def test_stale_accounts_need_review(self):
        result = assess_bankability(
            AccountScreeningInput(
                account_name="Stale Co",
                revenue_gbp=1_300_000_000,
                uk_presence=True,
                latest_accounts_age_months=24,
            )
        )
        self.assertEqual(result.verdict, "Needs review")


if __name__ == "__main__":
    unittest.main()
