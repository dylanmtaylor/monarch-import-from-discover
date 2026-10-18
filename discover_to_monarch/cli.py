"""Command Line Interface for Discover to Monarch Money export."""

import argparse
import json
import os
import sys
from typing import Optional

from discover_to_monarch.cdp import CDPSession, CDPError
from discover_to_monarch.parser import parse_discover_dataset
from discover_to_monarch.exporter import Exporter


def run_pipeline(
    port: int = 9222,
    tab_id: Optional[str] = None,
    output_dir: str = "output",
    cache_file: Optional[str] = "discover_raw_data.json",
    cache_dir: str = "raw_statements",
    include_pdfs: bool = True,
    max_pdf_statements: Optional[int] = None,
    invert_liability: bool = True,
    input_file: Optional[str] = None,
):
    """Run full automated capture and export pipeline."""
    os.makedirs(output_dir, exist_ok=True)
    raw_data = None

    if input_file and os.path.exists(input_file):
        print(f"Loading raw Discover dataset from '{input_file}'...")
        with open(input_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    else:
        print(f"Connecting to Chrome DevTools Protocol on port {port}...")
        try:
            with CDPSession(port=port, tab_id=tab_id) as session:
                tab_title = session.tab_info.get("title", "") if session.tab_info else ""
                print(f"Connected to Discover tab: {tab_title}")
                print("Starting automated extraction of recent activity and statement periods...")
                raw_data = session.capture_all_data(
                    cache_dir=cache_dir,
                    include_pdfs=include_pdfs,
                    max_pdf_statements=max_pdf_statements,
                    progress_callback=print,
                )
        except CDPError as e:
            print(f"CDP Error: {e}", file=sys.stderr)
            sys.exit(1)

        # Cache raw data if requested
        if cache_file:
            print(f"Saving raw dataset to '{cache_file}'...")
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, indent=2)
            except Exception as e:
                print(f"Warning: Failed to save raw cache file: {e}")

    print("Parsing statements and transactions...")
    account = parse_discover_dataset(raw_data)

    print("Exporting continuous daily balances and transactions to Monarch CSVs...")
    exporter = Exporter(output_dir=output_dir)
    exporter.export_account(account, invert_liability=invert_liability)


def run_capture(
    port: int = 9222,
    tab_id: Optional[str] = None,
    output_file: str = "discover_raw_data.json",
    cache_dir: str = "raw_statements",
    include_pdfs: bool = True,
    max_pdf_statements: Optional[int] = None,
):
    """Capture raw data from Chrome CDP and write to JSON file."""
    print(f"Connecting to Chrome on port {port}...")
    try:
        with CDPSession(port=port, tab_id=tab_id) as session:
            tab_title = session.tab_info.get("title", "") if session.tab_info else ""
            print(f"Connected to Discover tab: {tab_title}")
            raw_data = session.capture_all_data(
                cache_dir=cache_dir,
                include_pdfs=include_pdfs,
                max_pdf_statements=max_pdf_statements,
                progress_callback=print,
            )
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2)
            print(f"Raw Discover data captured successfully to '{output_file}'.")
    except CDPError as e:
        print(f"CDP Error: {e}", file=sys.stderr)
        sys.exit(1)


def run_convert(
    input_file: str,
    output_dir: str = "output",
    invert_liability: bool = True,
):
    """Convert an existing JSON cache file to Monarch CSVs."""
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Reading Discover dataset from '{input_file}'...")
    with open(input_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    account = parse_discover_dataset(raw_data)
    exporter = Exporter(output_dir=output_dir)
    exporter.export_account(account, invert_liability=invert_liability)


def main():
    """Main CLI entry point for discover-to-monarch."""
    parser = argparse.ArgumentParser(
        prog="discover-to-monarch",
        description="Extract Discover credit card transactions and continuous daily balance history into Monarch Money CSV format.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: all
    p_all = subparsers.add_parser("all", help="Full automated capture and export pipeline")
    p_all.add_argument("--port", type=int, default=9222, help="Chrome debugging port (default: 9222)")
    p_all.add_argument("--tab-id", type=str, default="6EF711CA72264941AADA4117D9F8667E", help="Specific Discover tab ID")
    p_all.add_argument("--output-dir", type=str, default="output", help="Directory for Monarch CSVs (default: output)")
    p_all.add_argument("--cache-file", type=str, default="discover_raw_data.json", help="Path to cache raw captured data")
    p_all.add_argument("--cache-dir", type=str, default="raw_statements", help="Directory for raw statement PDFs")
    p_all.add_argument("--no-pdfs", action="store_true", help="Skip historical statement PDFs older than 24 months")
    p_all.add_argument("--max-pdfs", type=int, default=None, help="Maximum number of historical PDFs to fetch")
    p_all.add_argument("--positive-balances", action="store_true", help="Do not invert credit card liability balances")
    p_all.add_argument("--input-file", type=str, default=None, help="Path to existing JSON dataset (skip CDP)")

    # Command: capture
    p_capture = subparsers.add_parser("capture", help="Capture raw data from Chrome CDP into JSON cache")
    p_capture.add_argument("--port", type=int, default=9222, help="Chrome debugging port (default: 9222)")
    p_capture.add_argument("--tab-id", type=str, default="6EF711CA72264941AADA4117D9F8667E", help="Specific Discover tab ID")
    p_capture.add_argument("--output-file", type=str, default="discover_raw_data.json", help="Path for captured JSON")
    p_capture.add_argument("--cache-dir", type=str, default="raw_statements", help="Directory for raw statement PDFs")
    p_capture.add_argument("--no-pdfs", action="store_true", help="Skip historical statement PDFs older than 24 months")
    p_capture.add_argument("--max-pdfs", type=int, default=None, help="Maximum number of historical PDFs to fetch")

    # Command: convert
    p_convert = subparsers.add_parser("convert", help="Convert an existing JSON dataset to Monarch CSVs")
    p_convert.add_argument("input_file", type=str, help="Path to raw JSON dataset")
    p_convert.add_argument("--output-dir", type=str, default="output", help="Directory for Monarch CSVs (default: output)")
    p_convert.add_argument("--positive-balances", action="store_true", help="Do not invert credit card liability balances")

    args = parser.parse_args()

    if args.command in (None, "all"):
        run_pipeline(
            port=getattr(args, "port", 9222),
            tab_id=getattr(args, "tab_id", "6EF711CA72264941AADA4117D9F8667E"),
            output_dir=getattr(args, "output_dir", "output"),
            cache_file=getattr(args, "cache_file", "discover_raw_data.json"),
            cache_dir=getattr(args, "cache_dir", "raw_statements"),
            include_pdfs=not getattr(args, "no_pdfs", False),
            max_pdf_statements=getattr(args, "max_pdfs", None),
            invert_liability=not getattr(args, "positive_balances", False),
            input_file=getattr(args, "input_file", None),
        )
    elif args.command == "capture":
        run_capture(
            port=args.port,
            tab_id=args.tab_id,
            output_file=args.output_file,
            cache_dir=args.cache_dir,
            include_pdfs=not args.no_pdfs,
            max_pdf_statements=args.max_pdfs,
        )
    elif args.command == "convert":
        run_convert(
            input_file=args.input_file,
            output_dir=args.output_dir,
            invert_liability=not args.positive_balances,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
