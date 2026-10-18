"""Unit tests for discover_to_monarch.parser."""

import unittest
from datetime import datetime
from discover_to_monarch.parser import (
    parse_date,
    clean_merchant_name,
    infer_category,
    parse_discover_dataset,
    DiscoverTransaction,
    StatementPeriod,
    DiscoverAccount,
)


class TestParser(unittest.TestCase):
    """Test parser functionality with 100% synthetic test fixtures."""

    def test_parse_date_formats(self):
        """Test parsing diverse date formats into standard ISO YYYY-MM-DD."""
        self.assertEqual(parse_date("2026-10-01"), "2026-10-01")
        self.assertEqual(parse_date("20261004"), "2026-10-04")
        self.assertEqual(parse_date("10/04/2026"), "2026-10-04")
        self.assertEqual(parse_date("01/05/2025"), "2025-01-05")
        self.assertEqual(parse_date("Oct 4, 2024"), "2024-10-04")
        self.assertEqual(parse_date("September 5, 2023"), "2023-09-05")
        self.assertEqual(parse_date("10/01", default_year=2026), "2026-10-01")

    def test_clean_merchant_name(self):
        """Test merchant cleaning rules for synthetic test descriptions."""
        cases = [
            ("PATREON* MEMBERSHIP SAN FRANCISCOCA", "Patreon"),
            ("AMAZON MKTPL*5L26Q0VB0 AMZN.COM/BILLWA\n6NSRFRQIT76", "Amazon"),
            ("GOOGLE *YOUTUBEPREMIUM\nG.CO/HELPPAY#CA", "YouTube Premium"),
            ("GOOGLE *GOOGLE MUSIC 855-836-3987 CA", "Google Play Music"),
            ("INTERNET PAYMENT - THANK YOU", "Payment - Thank You"),
            ("AUTOMATIC STATEMENT CREDIT", "Automatic Statement Credit"),
            ("DIRECTPAY FULL - THANK YOU", "Payment - Thank You"),
            ("CASHBACK BONUS REDEMPTION", "Cashback Bonus Redemption"),
            ("SPOTIFY USA NEW YORK NY", "Spotify"),
            ("NETFLIX.COM LOS GATOS CA", "Netflix"),
            ("TARGET STORE #1234 RALEIGH NC", "Target"),
        ]
        for raw, expected in cases:
            self.assertEqual(clean_merchant_name(raw), expected)

    def test_infer_category(self):
        """Test category inference rules."""
        self.assertEqual(infer_category("INTERNET PAYMENT - THANK YOU", 50.0), "Credit Card Payment")
        self.assertEqual(infer_category("AUTOMATIC STATEMENT CREDIT", 10.0), "Cash Flow / Credit")
        self.assertEqual(infer_category("PATREON* MEMBERSHIP", -15.0), "Subscriptions")
        self.assertEqual(infer_category("AMAZON.COM", -25.0), "Shopping")
        self.assertEqual(infer_category("WHOLE FOODS MARKET", -40.0, raw_category="Groceries"), "Groceries")
        self.assertEqual(infer_category("SHELL OIL", -35.0, raw_category="Gasoline"), "Gas / Fuel")
        self.assertEqual(infer_category("CHIPOTLE ONLINE", -12.50, raw_category="Restaurants"), "Restaurants")

    def test_parse_synthetic_dataset(self):
        """Test parsing synthetic JSON dataset structure."""
        synthetic_payload = {
            "account_overview": {
                "card_name": "Discover it Test",
                "card_ending": "9999",
                "current_balance": 125.50,
                "credit_limit": 5000.0,
                "available_credit": 4874.50,
            },
            "recent_activity": {
                "summaryData": {
                    "currentBalance": "125.50",
                    "lastStmtBal": "150.00",
                    "lastStmtDate": "10/04/2026",
                },
                "combinedTransactionData": {
                    "combinedTransactions": [
                        {
                            "transactionId": "rec-1",
                            "date": "10/05/2026",
                            "description": "AUTOMATIC STATEMENT CREDIT",
                            "amount": "-24.50",
                            "category": "Awards and Rebate Credits",
                        }
                    ]
                },
            },
            "json_statements": [
                {
                    "metadata": {
                        "fromDate": "09/05/2026",
                        "toDate": "10/04/2026",
                        "stmtUri": "/cardmembersvcs/statements/app/v2/current",
                    },
                    "data": {
                        "summaryData": {
                            "statementBalance": "150.00",
                            "purchases": "150.00",
                        },
                        "postedTransactionData": {
                            "previousBalance": "0.00",
                            "postedTransactions": [
                                {
                                    "transactionId": "tx-1",
                                    "date": "09/10/2026",
                                    "description": "AMAZON.COM TEST PURCHASE",
                                    "amount": "100.00",
                                    "category": "Merchandise",
                                },
                                {
                                    "transactionId": "tx-2",
                                    "date": "09/20/2026",
                                    "description": "PATREON* MEMBERSHIP",
                                    "amount": "50.00",
                                    "category": "Services",
                                },
                            ],
                        },
                    },
                }
            ],
            "pdf_statements": [],
        }

        account = parse_discover_dataset(synthetic_payload)
        self.assertEqual(account.card_name, "Discover it Test")
        self.assertEqual(account.account_number, "9999")
        self.assertEqual(account.current_balance, 125.50)
        self.assertEqual(account.display_name, "Discover it Test (9999)")
        self.assertEqual(len(account.statements), 1)
        self.assertEqual(len(account.recent_transactions), 1)

        all_txns = account.get_all_transactions()
        self.assertEqual(len(all_txns), 3)

        # Check transaction sign convention: purchases are negative, credits are positive
        amazon_tx = [t for t in all_txns if "Amazon" in t.merchant][0]
        self.assertEqual(amazon_tx.amount, -100.00)

        credit_tx = [t for t in all_txns if "Credit" in t.merchant][0]
        self.assertEqual(credit_tx.amount, 24.50)


if __name__ == "__main__":
    unittest.main()
