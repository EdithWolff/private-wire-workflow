import os
import unittest

from private_wire_workflow.companies_house import (
    NoMatchResult,
    _confidence_tier,
    _is_substantive_entity,
    _query_variants,
    _rescore_with_profile,
    _score_candidate,
    _verify_original_overlap,
    get_api_key,
)


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

    def test_query_variants_include_normalized_and_reduced_forms(self):
        variants = _query_variants("A.B. Example Holdings & Services Limited")
        self.assertIn("A.B. Example Holdings and Services Limited", variants)
        self.assertIn("ab example holdings services limited", variants)
        self.assertTrue(any("example" in variant for variant in variants))


class SubstantiveEntityTests(unittest.TestCase):
    def test_active_full_accounts_passes(self):
        profile = {
            "company_status": "active",
            "sic_codes": ["21100"],
            "accounts": {
                "last_accounts": {
                    "type": "full",
                    "made_up_to": "2024-12-31",
                }
            },
        }
        passes, reasons = _is_substantive_entity(profile)
        self.assertTrue(passes)
        self.assertEqual(reasons, [])

    def test_dormant_account_type_rejected(self):
        profile = {
            "company_status": "active",
            "sic_codes": ["99999"],
            "accounts": {
                "last_accounts": {
                    "type": "dormant",
                    "made_up_to": "2024-12-31",
                }
            },
        }
        passes, reasons = _is_substantive_entity(profile)
        self.assertFalse(passes)
        self.assertIn("last_accounts_type=dormant", reasons)
        self.assertIn("sic_codes=99999_only", reasons)

    def test_dissolved_status_rejected(self):
        profile = {
            "company_status": "dissolved",
            "sic_codes": ["21100"],
            "accounts": {
                "last_accounts": {
                    "type": "full",
                    "made_up_to": "2024-01-01",
                }
            },
        }
        passes, reasons = _is_substantive_entity(profile)
        self.assertFalse(passes)
        self.assertIn("company_status=dissolved", reasons)

    def test_micro_entity_rejected(self):
        profile = {
            "company_status": "active",
            "sic_codes": ["47110"],
            "accounts": {
                "last_accounts": {
                    "type": "micro-entity",
                    "made_up_to": "2024-06-30",
                }
            },
        }
        passes, reasons = _is_substantive_entity(profile)
        self.assertFalse(passes)
        self.assertIn("last_accounts_type=micro-entity", reasons)

    def test_no_accounts_filed_rejected(self):
        profile = {
            "company_status": "active",
            "sic_codes": ["21100"],
            "accounts": {"last_accounts": {}},
        }
        passes, reasons = _is_substantive_entity(profile)
        self.assertFalse(passes)
        self.assertIn("no_accounts_filed", reasons)

    def test_stale_accounts_rejected(self):
        profile = {
            "company_status": "active",
            "sic_codes": ["21100"],
            "accounts": {
                "last_accounts": {
                    "type": "full",
                    "made_up_to": "2018-01-01",
                }
            },
        }
        passes, reasons = _is_substantive_entity(profile)
        self.assertFalse(passes)
        self.assertTrue(any("accounts_stale" in r for r in reasons))


class VerifyOriginalOverlapTests(unittest.TestCase):
    def test_alnylam_vs_aquarium_rejected(self):
        self.assertFalse(
            _verify_original_overlap("Alnylam Pharmaceuticals Inc", "AQUARIUM PHARMACEUTICALS INC")
        )

    def test_amgen_vs_amgent_rejected(self):
        self.assertFalse(
            _verify_original_overlap("Amgen Inc", "Amgent Limited")
        )

    def test_exact_match_passes(self):
        self.assertTrue(
            _verify_original_overlap("Abbott Laboratories", "ABBOTT LABORATORIES LIMITED")
        )

    def test_partial_match_passes(self):
        self.assertTrue(
            _verify_original_overlap("Hikma Pharmaceuticals PLC", "HIKMA PHARMACEUTICALS PLC")
        )

    def test_empty_tokens_passes(self):
        # If the name is entirely filler/legal tokens, allow any match.
        self.assertTrue(_verify_original_overlap("The UK Limited", "Something Else Ltd"))


class MajorityOverlapTests(unittest.TestCase):
    def test_leica_biosystems_vs_geosystems_rejected(self):
        """Leica Biosystems should NOT match Leica Geosystems (1/2 overlap)."""
        self.assertFalse(
            _verify_original_overlap("Leica Biosystems", "LEICA GEOSYSTEMS LIMITED")
        )

    def test_eli_lilly_full_match_passes(self):
        """Eli Lilly And Company should match Eli Lilly And Company Limited."""
        self.assertTrue(
            _verify_original_overlap("Eli Lilly And Company", "ELI LILLY AND COMPANY LIMITED")
        )

    def test_single_distinctive_token_still_works(self):
        """With only 1 distinctive token, the old 'at least one' rule applies."""
        self.assertTrue(
            _verify_original_overlap("Pfizer Inc.", "PFIZER LIMITED")
        )

    def test_two_tokens_both_present_passes(self):
        """Both distinctive tokens present → passes majority check."""
        self.assertTrue(
            _verify_original_overlap("Jazz Pharmaceuticals", "JAZZ PHARMACEUTICALS UK LIMITED")
        )


class PLCBonusTests(unittest.TestCase):
    def test_plc_scores_higher_than_ltd(self):
        plc_item = {
            "title": "GSK PLC",
            "company_status": "active",
            "company_type": "plc",
        }
        ltd_item = {
            "title": "GSK LIMITED",
            "company_status": "active",
            "company_type": "ltd",
        }
        self.assertGreater(
            _score_candidate("GSK", plc_item),
            _score_candidate("GSK", ltd_item),
        )


class RescoreWithProfileTests(unittest.TestCase):
    def test_full_accounts_gets_bonus(self):
        profile = {
            "accounts": {"last_accounts": {"type": "full"}},
        }
        self.assertGreater(_rescore_with_profile(1.0, profile), 1.0)

    def test_group_accounts_gets_bonus(self):
        profile = {
            "accounts": {"last_accounts": {"type": "group"}},
        }
        self.assertGreater(_rescore_with_profile(1.0, profile), 1.0)

    def test_micro_accounts_no_bonus(self):
        profile = {
            "accounts": {"last_accounts": {"type": "micro-entity"}},
        }
        self.assertEqual(_rescore_with_profile(1.0, profile), 1.0)

    def test_missing_accounts_no_bonus(self):
        self.assertEqual(_rescore_with_profile(1.0, {}), 1.0)


class ConfidenceTierTests(unittest.TestCase):
    def test_high_confidence(self):
        self.assertEqual(_confidence_tier(1.0, 0.10, "active"), "high")

    def test_medium_confidence(self):
        self.assertEqual(_confidence_tier(0.90, 0.05, "active"), "medium")

    def test_low_confidence(self):
        self.assertEqual(_confidence_tier(0.70, 0.01, "active"), "low")

    def test_high_requires_active(self):
        self.assertNotEqual(_confidence_tier(1.0, 0.10, "dissolved"), "high")

    def test_borderline_high_rejected(self):
        """Old threshold (0.93/0.05) would pass, new (0.95/0.08) should not."""
        self.assertNotEqual(_confidence_tier(0.94, 0.06, "active"), "high")


class NoMatchResultTests(unittest.TestCase):
    def test_dataclass_fields(self):
        result = NoMatchResult(
            company_name="Test Corp",
            reason="all_rejected_non_substantive",
            candidates_found=3,
            candidates_rejected=2,
            rejection_details=["ENTITY A (12345): dormant", "ENTITY B (67890): micro-entity"],
        )
        self.assertEqual(result.company_name, "Test Corp")
        self.assertEqual(result.reason, "all_rejected_non_substantive")
        self.assertEqual(result.candidates_found, 3)
        self.assertEqual(result.candidates_rejected, 2)
        self.assertEqual(len(result.rejection_details), 2)
        self.assertEqual(result.best_rejected_name, "")
        self.assertEqual(result.best_rejected_score, 0.0)


if __name__ == "__main__":
    unittest.main()
