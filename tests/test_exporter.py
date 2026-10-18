"""Unit tests for discover_to_monarch.exporter."""

import os
import tempfile
import unittest
from discover_to_monarch.parser import DiscoverAccount, StatementPeriod, DiscoverTransaction
from discover_to_monarch.exporter import Exporter


class TestExporter(unittest.TestCase):
    """Test exporting CSV files to disk."""

    def test_export_account(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            account = DiscoverAccount(
                card_name="Discover it Synthetic",
                account_number="4321",
                current_balance=10.00,
                credit_limit=1500.00,
            )
            stmt = StatementPeriod(
                statement_date="2026-05-31",
                start_date="2026-05-01",
                end_date="2026-05-31",
                previous_balance=0.00,
                closing_balance=10.00,
                transactions=[
                    DiscoverTransaction(
                        date="2026-05-15",
                        merchant="Test Store",
                        category="Shopping",
                        account="Discover it Synthetic (4321)",
                        original_statement="TEST STORE",
                        notes="",
                        amount=-10.00,
                    )
                ],
            )
            account.statements = [stmt]

            exporter = Exporter(output_dir=tmpdir)
            metrics = exporter.export_account(account)

            bal_file = metrics["balance_file"]
            txn_file = metrics["transaction_file"]

            self.assertTrue(os.path.exists(bal_file))
            self.assertTrue(os.path.exists(txn_file))

            with open(bal_file, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("Date,Balance", content)
                self.assertIn("2026-05-31,-10.00", content)

            with open(txn_file, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("Date,Merchant,Category,Account,Original Statement,Notes,Amount", content)
                self.assertIn("Test Store,Shopping,Discover it Synthetic (4321),TEST STORE,,-10.00", content)


if __name__ == "__main__":
    unittest.main()
