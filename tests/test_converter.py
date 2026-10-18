"""Unit tests for discover_to_monarch.converter."""

import csv
import io
import unittest
from datetime import datetime, timedelta
from discover_to_monarch.parser import DiscoverAccount, StatementPeriod, DiscoverTransaction
from discover_to_monarch.converter import convert_balances_to_csv, convert_transactions_to_csv


class TestConverter(unittest.TestCase):
    """Test Monarch CSV formatting and daily balance calculations with synthetic fixtures."""

    def setUp(self):
        self.account = DiscoverAccount(
            card_name="Discover it Synthetic",
            account_number="1234",
            current_balance=25.00,
            credit_limit=2000.00,
            available_credit=1975.00,
        )

        # Period 1: Jan 1 to Jan 31
        stmt1 = StatementPeriod(
            statement_date="2026-01-31",
            start_date="2026-01-01",
            end_date="2026-01-31",
            previous_balance=0.00,
            closing_balance=50.00,
            transactions=[
                DiscoverTransaction(
                    date="2026-01-15",
                    merchant="Sample Merchant A",
                    category="Shopping",
                    account="Discover it Synthetic (1234)",
                    original_statement="SAMPLE PURCHASE",
                    notes="Statement Date: 2026-01-31",
                    amount=-50.00,
                )
            ],
        )

        # Period 2: Feb 1 to Feb 28
        stmt2 = StatementPeriod(
            statement_date="2026-02-28",
            start_date="2026-02-01",
            end_date="2026-02-28",
            previous_balance=50.00,
            closing_balance=25.00,
            transactions=[
                DiscoverTransaction(
                    date="2026-02-10",
                    merchant="Payment - Thank You",
                    category="Credit Card Payment",
                    account="Discover it Synthetic (1234)",
                    original_statement="ONLINE PAYMENT",
                    notes="Statement Date: 2026-02-28",
                    amount=50.00,
                ),
                DiscoverTransaction(
                    date="2026-02-20",
                    merchant="Sample Merchant B",
                    category="Subscriptions",
                    account="Discover it Synthetic (1234)",
                    original_statement="MONTHLY SUB",
                    notes="Statement Date: 2026-02-28",
                    amount=-25.00,
                ),
            ],
        )

        self.account.statements = [stmt1, stmt2]

    def test_convert_balances_to_csv(self):
        """Test formatting of balance history CSV."""
        daily_balances = [
            {"date": "2026-01-01", "balance": 0.00},
            {"date": "2026-01-02", "balance": -50.25},
        ]
        csv_text = convert_balances_to_csv(daily_balances)
        reader = list(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(reader[0], ["Date", "Balance"])
        self.assertEqual(reader[1], ["2026-01-01", "0.00"])
        self.assertEqual(reader[2], ["2026-01-02", "-50.25"])

    def test_convert_transactions_to_csv(self):
        """Test formatting of transactions CSV."""
        txns = [
            DiscoverTransaction(
                date="2026-01-15",
                merchant="Test Store",
                category="Shopping",
                account="Discover it (1234)",
                original_statement="TEST STORE #1",
                notes="Ref: 12345",
                amount=-19.99,
            )
        ]
        csv_text = convert_transactions_to_csv(txns, "Discover it (1234)")
        reader = list(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(
            reader[0],
            ["Date", "Merchant", "Category", "Account", "Original Statement", "Notes", "Amount"],
        )
        self.assertEqual(
            reader[1],
            ["2026-01-15", "Test Store", "Shopping", "Discover it (1234)", "TEST STORE #1", "Ref: 12345", "-19.99"],
        )

    def test_compute_daily_balances_continuity(self):
        """Test that daily balances are 100% continuous without missing calendar days."""
        daily = self.account.compute_daily_balances(invert_liability=True)
        self.assertTrue(len(daily) > 60)

        # Verify no missing days
        for i in range(len(daily) - 1):
            d1 = datetime.strptime(daily[i]["date"], "%Y-%m-%d")
            d2 = datetime.strptime(daily[i + 1]["date"], "%Y-%m-%d")
            self.assertEqual((d2 - d1).days, 1, f"Gap detected between {daily[i]['date']} and {daily[i+1]['date']}")

        # Verify checkpoints
        jan31 = [d for d in daily if d["date"] == "2026-01-31"][0]
        # Closing balance for stmt1 was 50.00. Invert liability -> -50.00
        self.assertEqual(jan31["balance"], -50.00)

        feb28 = [d for d in daily if d["date"] == "2026-02-28"][0]
        # Closing balance for stmt2 was 25.00. Invert liability -> -25.00
        self.assertEqual(feb28["balance"], -25.00)

    def test_compute_daily_balances_positive_option(self):
        """Test positive balance history output when invert_liability is False."""
        daily = self.account.compute_daily_balances(invert_liability=False)
        jan31 = [d for d in daily if d["date"] == "2026-01-31"][0]
        self.assertEqual(jan31["balance"], 50.00)


if __name__ == "__main__":
    unittest.main()
