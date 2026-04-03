import os
import unittest

from private_wire_workflow.companies_house import _score_candidate, get_api_key


class CompaniesHouseTests(unittest.TestCase):
    def test_exact_active_match_scores_higher(self):
        exact = {
            "title": "Example Manufacturing Limited",
            "company_status": "active",
        }
        weak = {
            "title": "Example Services Holdings",
            "company_status": "dissolved",
        }
        self.assertGreater(
            _score_candidate("Example Manufacturing Limited", exact),
            _score_candidate("Example Manufacturing Limited", weak),
        )

    def test_missing_api_key_raises(self):
        original = os.environ.pop("COMPANIES_HOUSE_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                get_api_key()
        finally:
            if original is not None:
                os.environ["COMPANIES_HOUSE_API_KEY"] = original


if __name__ == "__main__":
    unittest.main()
