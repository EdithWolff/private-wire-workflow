import unittest

from private_wire_workflow.contacts import select_target_contacts
from private_wire_workflow.models import ContactCandidate


class ContactSelectionTests(unittest.TestCase):
    def test_role_priority_and_limit(self):
        contacts = [
            ContactCandidate("A", "Energy Director", "LinkedIn", confidence=0.9),
            ContactCandidate("B", "Sustainability Director", "LinkedIn", confidence=0.8),
            ContactCandidate("C", "Procurement Manager", "Lusha", confidence=0.7),
            ContactCandidate("D", "Indirect Sourcing Lead", "Lusha", confidence=0.6),
            ContactCandidate("E", "Site Manager", "LinkedIn", confidence=0.9),
            ContactCandidate("F", "Operations Analyst", "LinkedIn", confidence=0.9),
        ]
        selected = select_target_contacts(contacts)
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected[0].title, "Energy Director")

    def test_duplicate_contacts_are_deduped(self):
        contacts = [
            ContactCandidate("Alex Green", "Procurement Manager", "Lusha", email="alex@example.com", confidence=0.7),
            ContactCandidate("Alex Green", "Energy Director", "LinkedIn", email="alex@example.com", confidence=0.9),
        ]
        selected = select_target_contacts(contacts)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].title, "Energy Director")

    def test_low_confidence_contacts_are_excluded(self):
        contacts = [
            ContactCandidate("A", "Energy Director", "LinkedIn", confidence=0.2),
        ]
        selected = select_target_contacts(contacts)
        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
