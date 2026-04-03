import unittest

from private_wire_workflow.models import SiteCandidate
from private_wire_workflow.site_screening import rank_sites


class SiteScreeningTests(unittest.TestCase):
    def test_viable_large_site_is_selected(self):
        sites = [
            SiteCandidate(
                site_name="Large Rural Site",
                site_size_sqm=15_000,
                grade="3b",
                urban_flag=False,
                adjacent_land_flag=True,
            )
        ]
        ranked = rank_sites(sites)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].site_name, "Large Rural Site")

    def test_site_below_threshold_is_rejected(self):
        sites = [
            SiteCandidate(
                site_name="Small Site",
                site_size_sqm=8_000,
                grade="3b",
                urban_flag=False,
                adjacent_land_flag=True,
            )
        ]
        self.assertEqual(rank_sites(sites), [])

    def test_urban_site_is_rejected(self):
        sites = [
            SiteCandidate(
                site_name="Urban Site",
                site_size_sqm=12_000,
                grade="3b",
                urban_flag=True,
            )
        ]
        self.assertEqual(rank_sites(sites), [])

    def test_grade_above_3b_is_rejected(self):
        sites = [
            SiteCandidate(
                site_name="Bad Grade Site",
                site_size_sqm=12_000,
                grade="4",
                urban_flag=False,
            )
        ]
        self.assertEqual(rank_sites(sites), [])

    def test_top_three_sites_only(self):
        sites = [
            SiteCandidate(site_name=f"Site {index}", site_size_sqm=20_000 + index, grade="3b")
            for index in range(5)
        ]
        ranked = rank_sites(sites)
        self.assertEqual(len(ranked), 3)


if __name__ == "__main__":
    unittest.main()
