# monarch-import-from-discover

Automated extraction and conversion tool for **Discover** credit card accounts (Discover it, Miles, etc.) into **Monarch Money**-compatible CSV imports.

Connects to an authenticated Discover Card session in Google Chrome via Chrome DevTools Protocol (CDP), captures online recent activity and full historical statements (both JSON and PDF statements), parses transactions and statement closing balances, and exports:
1. **Continuous Daily Balance History** (`Date,Balance`) across all calendar days back to account inception, integrating verified statement checkpoints.
2. **Standard Transactions** (`Date,Merchant,Category,Account,Original Statement,Notes,Amount`) with automatic merchant cleaning and category inference.
3. **Full Statement Archive Coverage**: Seamlessly combines modern online JSON statements with older PDF archive statements to reconstruct complete card history.

---

## Features

- **Automated Statement History Extraction**:
  - Automatically fetches all available statement periods from Discover's statement archive.
  - Taps online JSON statement endpoints for fast, accurate structured extraction.
  - Automatically downloads and parses older statement PDFs via PyMuPDF (`fitz`) when online JSON statements are unavailable.
- **Continuous Daily Balance Interpolation**:
  - Reconstructs uninterrupted daily balances forward-filled from account open date up to the present day, perfectly aligning with statement checkpoints.
  - Supports standard liability representation (negative decimal balance or inverted depending on Monarch preferences).
- **Chrome CDP Session Extraction**:
  - Reuses your active, authenticated Chrome browser session via CDP (port `9222`) without requiring credential storage or password exposure.
- **Monarch Money Import Ready**:
  - Strict compliance with Monarch's CSV specifications for Balances (`Date,Balance`) and Transactions (`Date,Merchant,Category,Account,Original Statement,Notes,Amount`).
- **Zero PII Committed**:
  - All account numbers, financial amounts, raw JSON captures, PDF statements, and CSV exports are safely excluded via `.gitignore`.

---

## Installation

```bash
git clone https://github.com/dylanmtaylor/monarch-import-from-discover.git
cd monarch-import-from-discover
pip install -e .
```

### Dependencies
- Python 3.9+
- `pymupdf>=1.20.0`
- `websocket-client>=1.6.0`

---

## Quickstart

### 1. Launch Chrome with Remote Debugging
Ensure Chrome is running with `--remote-debugging-port=9222` and log into [Discover](https://card.discover.com):

```bash
google-chrome --remote-debugging-port=9222
# or on Flatpak:
flatpak run com.google.Chrome --remote-debugging-port=9222
```

### 2. Run Capture & Convert
Run the automated pipeline to capture statement data and generate Monarch CSVs:

```bash
discover-to-monarch all
```

Or specify a custom output directory:

```bash
discover-to-monarch all --output-dir ./output
```

---

## Testing

Run the full synthetic test suite (100% synthetic fixtures, zero network calls):

```bash
python3 -m unittest discover tests -v
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
