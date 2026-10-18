"""Unit tests for discover_to_monarch.cli."""

import json
import os
import subprocess
import sys
import tempfile
import unittest


class TestCLI(unittest.TestCase):
    """Test CLI argument parsing and conversion workflow."""

    def test_cli_help(self):
        """Test that CLI displays help and subcommands."""
        res = subprocess.run(
            [sys.executable, "-m", "discover_to_monarch.cli", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("discover-to-monarch", res.stdout)
        self.assertIn("all", res.stdout)
        self.assertIn("capture", res.stdout)
        self.assertIn("convert", res.stdout)

    def test_cli_convert_command(self):
        """Test convert subcommand using synthetic JSON dataset."""
        synthetic_data = {
            "account_overview": {
                "card_name": "Discover it Test",
                "card_ending": "8888",
                "current_balance": 50.00,
                "credit_limit": 3000.0,
            },
            "recent_activity": {
                "summaryData": {"currentBalance": "50.00"},
                "combinedTransactionData": {"combinedTransactions": []},
            },
            "json_statements": [
                {
                    "metadata": {
                        "fromDate": "08/05/2026",
                        "toDate": "09/04/2026",
                    },
                    "data": {
                        "summaryData": {"statementBalance": "50.00"},
                        "postedTransactionData": {
                            "previousBalance": "0.00",
                            "postedTransactions": [
                                {
                                    "date": "08/15/2026",
                                    "description": "SAMPLE BOOKSTORE",
                                    "amount": "50.00",
                                    "category": "Merchandise",
                                }
                            ],
                        },
                    },
                }
            ],
            "pdf_statements": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "synthetic_discover.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(synthetic_data, f)

            output_dir = os.path.join(tmpdir, "output")
            res = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "discover_to_monarch.cli",
                    "convert",
                    json_path,
                    "--output-dir",
                    output_dir,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, f"CLI error: {res.stderr}")
            self.assertIn("Export completed", res.stdout)

            bal_file = os.path.join(output_dir, "discover_balances_discover_it_test_8888.csv")
            txn_file = os.path.join(output_dir, "discover_transactions_discover_it_test_8888.csv")

            self.assertTrue(os.path.exists(bal_file))
            self.assertTrue(os.path.exists(txn_file))


if __name__ == "__main__":
    unittest.main()
