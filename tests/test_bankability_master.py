import unittest

from private_wire_workflow.bankability_master import (
    _parse_rating_columns,
    _ratio_based_status,
    _ratio_flags,
    rating_at_least_bbb_minus,
)


class BankabilityMasterTests(unittest.TestCase):
    def test_rating_threshold_inclusive(self):
        self.assertTrue(rating_at_least_bbb_minus("BBB-"))
        self.assertTrue(rating_at_least_bbb_minus("A-"))
        self.assertFalse(rating_at_least_bbb_minus("BB+"))

    def test_parse_combined_rating_column(self):
        row = {
            "Credit Rating (S&P / Moody's / Fitch)": "A- (S&P) / A2 (Moody's)",
        }
        moodys, sp, fitch = _parse_rating_columns(row)
        self.assertEqual(moodys, "A2")
        self.assertEqual(sp, "A-")
        self.assertEqual(fitch, "")

    def test_ratio_status_and_flags(self):
        status, reason = _ratio_based_status(
            {"ebitda_margin": 0.2, "interest_coverage": 4.0, "net_debt_to_ebitda": 1.5}
        )
        self.assertEqual(status, "Qualified")
        self.assertIn("meet", reason)

        status, reason = _ratio_based_status(
            {"ebitda_margin": 0.05, "interest_coverage": 1.2, "net_debt_to_ebitda": 4.5}
        )
        self.assertEqual(status, "Disqualified")
        self.assertIn("not met", reason)

        status, reason = _ratio_based_status(
            {"ebitda_margin": None, "interest_coverage": 4.0, "net_debt_to_ebitda": 1.0}
        )
        self.assertEqual(status, "Needs review")

        flags = _ratio_flags(
            {"ebitda_margin": 0.2, "interest_coverage": 4.0, "net_debt_to_ebitda": 1.5}
        )
        self.assertEqual(flags["margin_ge_10"], "Yes")
        self.assertEqual(flags["coverage_ge_3x"], "Yes")
        self.assertEqual(flags["netdebt_ebitda_le_2x"], "Yes")


if __name__ == "__main__":
    unittest.main()
