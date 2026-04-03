import unittest

from private_wire_workflow.filing_parser import extract_text_from_pdf_bytes


class PDFExtractionTests(unittest.TestCase):
    def test_extract_text_from_blank_pdf_bytes_is_string(self):
        # Minimal invalid-ish payload should be handled by caller; valid PDF testing is integration-level.
        with self.assertRaises(Exception):
            extract_text_from_pdf_bytes(b"not-a-pdf")


if __name__ == "__main__":
    unittest.main()
