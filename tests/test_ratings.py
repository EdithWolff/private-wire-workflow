import unittest

from private_wire_workflow.ratings import assess_official_rating, rating_strictly_above_bbb_minus


class RatingsTests(unittest.TestCase):
    def test_strictly_above_bbb_minus(self):
        self.assertTrue(rating_strictly_above_bbb_minus("BBB"))
        self.assertFalse(rating_strictly_above_bbb_minus("BBB-"))

    def test_assess_sp_rating(self):
        result = assess_official_rating("A- (S&P) / A2 (Moody's)")
        self.assertEqual(result.verdict, "Qualified")
        self.assertEqual(result.best_sp_equivalent, "A-")

    def test_assess_unrated(self):
        result = assess_official_rating("Unrated (Private)")
        self.assertEqual(result.verdict, "TBD")


if __name__ == "__main__":
    unittest.main()
