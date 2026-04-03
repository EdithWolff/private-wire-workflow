import unittest

from private_wire_workflow.filing_parser import extract_financials_from_text, html_to_text


class FilingParserTests(unittest.TestCase):
    def test_extracts_direct_financial_fields(self):
        text = """
        Turnover 1000
        EBITDA 150
        Interest payable (30)
        Net debt 200
        """
        financials = extract_financials_from_text(text)
        self.assertEqual(financials.turnover, 1000)
        self.assertEqual(financials.ebitda, 150)
        self.assertEqual(financials.interest_expense, -30)
        self.assertEqual(financials.net_debt, 200)

    def test_derives_ebitda_and_net_debt(self):
        text = """
        Revenue 2000
        Operating profit 180
        Depreciation 20
        Amortisation 10
        Finance costs (40)
        Borrowings 500
        Cash at bank and in hand 150
        """
        financials = extract_financials_from_text(text)
        self.assertEqual(financials.ebitda, 210)
        self.assertEqual(financials.net_debt, 350)

    def test_html_to_text_strips_tags(self):
        content = "<html><body><p>Turnover</p><p>1000</p></body></html>"
        self.assertEqual(html_to_text(content), "Turnover 1000")


if __name__ == "__main__":
    unittest.main()
