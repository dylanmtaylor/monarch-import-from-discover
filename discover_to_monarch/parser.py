"""Parser for Discover credit card statements, raw transaction JSON, and PDF files."""

import base64
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


@dataclass
class DiscoverTransaction:
    """Represents a normalized Discover credit card transaction."""
    date: str  # YYYY-MM-DD
    merchant: str
    category: str
    account: str
    original_statement: str
    notes: str
    amount: float  # Signed decimal: negative for purchases/fees, positive for payments/credits
    running_balance: Optional[float] = None
    transaction_id: Optional[str] = None


@dataclass
class StatementPeriod:
    """Represents a Discover monthly billing statement period."""
    statement_date: str  # YYYY-MM-DD
    start_date: str      # YYYY-MM-DD
    end_date: str        # YYYY-MM-DD
    previous_balance: float
    closing_balance: float
    purchases: float = 0.0
    payments_and_credits: float = 0.0
    transactions: List[DiscoverTransaction] = field(default_factory=list)


@dataclass
class DiscoverAccount:
    """Represents a Discover credit card account and its activity."""
    card_name: str
    account_number: str
    cardholder: str = ""
    current_balance: float = 0.0
    credit_limit: float = 0.0
    available_credit: float = 0.0
    statements: List[StatementPeriod] = field(default_factory=list)
    recent_transactions: List[DiscoverTransaction] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """User-friendly display name for Monarch account mapping."""
        return f"{self.card_name} ({self.account_number})"

    @property
    def slug(self) -> str:
        """Filesystem safe slug."""
        clean_name = re.sub(r"[^a-zA-Z0-9]+", "_", self.card_name.lower()).strip("_")
        return f"{clean_name}_{self.account_number}"

    def get_all_transactions(self) -> List[DiscoverTransaction]:
        """
        Return a single deduplicated, chronologically sorted list of all transactions
        across historical statements and recent activity.
        """
        seen = set()
        all_txns: List[DiscoverTransaction] = []

        # 1. Statement transactions (oldest to newest)
        for stmt in sorted(self.statements, key=lambda s: s.end_date):
            for t in stmt.transactions:
                # Key by date, amount, original statement
                key = (t.date, f"{t.amount:.2f}", t.original_statement.strip())
                if key not in seen:
                    seen.add(key)
                    all_txns.append(t)

        # 2. Recent unbilled transactions
        for t in self.recent_transactions:
            key = (t.date, f"{t.amount:.2f}", t.original_statement.strip())
            if key not in seen:
                seen.add(key)
                all_txns.append(t)

        all_txns.sort(key=lambda t: (t.date, t.original_statement))
        return all_txns

    def compute_daily_balances(self, invert_liability: bool = True) -> List[Dict[str, Any]]:
        """
        Reconstruct continuous daily balance history from account opening to today.
        
        Args:
            invert_liability: If True (default for Monarch liabilities), debt balance is
                             expressed as negative (e.g. -11.45) so that Assets - Liabilities = Net Worth.
                             
        Returns:
            List of dicts: [{"date": "YYYY-MM-DD", "balance": float}, ...]
        """
        sorted_stmts = sorted(self.statements, key=lambda s: s.end_date)
        if not sorted_stmts:
            today_str = datetime.now().strftime("%Y-%m-%d")
            bal = -self.current_balance if invert_liability else self.current_balance
            return [{"date": today_str, "balance": round(bal, 2)}]

        # Start date is the start date of the first available statement
        start_dt = datetime.strptime(sorted_stmts[0].start_date, "%Y-%m-%d")
        today_dt = datetime.now().date()
        today_dt_full = datetime(today_dt.year, today_dt.month, today_dt.day)

        # Index transactions by date for fast lookup
        txns_by_date: Dict[str, List[DiscoverTransaction]] = {}
        for t in self.get_all_transactions():
            txns_by_date.setdefault(t.date, []).append(t)

        # Map statement closing checkpoints: date -> closing_balance
        statement_checkpoints: Dict[str, float] = {}
        statement_start_points: Dict[str, float] = {}
        for s in sorted_stmts:
            statement_checkpoints[s.end_date] = s.closing_balance
            statement_start_points[s.start_date] = s.previous_balance

        daily_points: List[Dict[str, Any]] = []
        curr_dt = start_dt
        curr_balance = sorted_stmts[0].previous_balance

        # Track the latest statement close date
        latest_stmt_end = datetime.strptime(sorted_stmts[-1].end_date, "%Y-%m-%d")

        while curr_dt <= today_dt_full:
            d_str = curr_dt.strftime("%Y-%m-%d")

            # Check if this day is a statement start date
            if d_str in statement_start_points:
                # Align starting balance if we were at 0 or entering period
                curr_balance = statement_start_points[d_str]

            # Apply any transactions on this day
            if d_str in txns_by_date:
                for tx in txns_by_date[d_str]:
                    # In Monarch, purchase is negative, payment is positive.
                    # On the card balance owed: purchase increases debt (+), payment reduces debt (-)
                    # So card_balance_owed += -tx.amount
                    curr_balance -= tx.amount

            # If today is a statement closing date checkpoint, align exactly with official statement
            if d_str in statement_checkpoints:
                curr_balance = statement_checkpoints[d_str]

            # If we are on or after the latest statement and reach today, align with current balance
            if curr_dt == today_dt_full:
                curr_balance = self.current_balance

            # Format balance: in Monarch, credit card liability debt is negative
            reported_bal = -curr_balance if invert_liability else curr_balance
            # Ensure -0.0 is normalized to 0.0
            if abs(reported_bal) < 0.001:
                reported_bal = 0.0

            daily_points.append({
                "date": d_str,
                "balance": round(reported_bal, 2)
            })

            curr_dt += timedelta(days=1)

        return daily_points


def parse_date(date_raw: str, default_year: Optional[int] = None) -> str:
    """Parse raw date string into ISO format (YYYY-MM-DD)."""
    s = date_raw.strip()
    if not s:
        return datetime.now().strftime("%Y-%m-%d")

    # Already YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    # YYYYMMDD
    if re.match(r"^\d{8}$", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    # MM/DD/YYYY
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", s):
        parts = s.split("/")
        return f"{int(parts[2]):04d}-{int(parts[0]):02d}-{int(parts[1]):02d}"

    # MM/DD with default year
    if re.match(r"^\d{1,2}/\d{1,2}$", s):
        yr = default_year or datetime.now().year
        parts = s.split("/")
        return f"{yr:04d}-{int(parts[0]):02d}-{int(parts[1]):02d}"

    # Month Day, Year (e.g. Sep 5, 2019)
    try:
        dt = datetime.strptime(s, "%b %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    try:
        dt = datetime.strptime(s, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    return s


def clean_merchant_name(desc: str) -> str:
    """Clean and normalize Discover statement transaction descriptions into concise merchant names."""
    if not desc:
        return "Discover"

    desc = desc.replace("\r", " ").replace("\n", " ").strip()
    desc_upper = desc.upper()

    # Exact standard overrides
    if "AUTOMATIC STATEMENT CREDIT" in desc_upper:
        return "Automatic Statement Credit"
    if any(k in desc_upper for k in ["PAYMENT - THANK YOU", "INTERNET PAYMENT", "DIRECTPAY"]):
        return "Payment - Thank You"
    if "CASHBACK BONUS" in desc_upper:
        return "Cashback Bonus Redemption"
    if "PATREON" in desc_upper:
        return "Patreon"
    if "YOUTUBE" in desc_upper:
        return "YouTube Premium"
    if "GOOGLE MUSIC" in desc_upper or "GOOGLE *GOOGLE MUSIC" in desc_upper:
        return "Google Play Music"
    if any(k in desc_upper for k in ["AMAZON", "AMZN"]):
        return "Amazon"
    if "TARGET" in desc_upper:
        return "Target"
    if "WALMART" in desc_upper:
        return "Walmart"
    if "COSTCO" in desc_upper:
        return "Costco"
    if "STARBUCKS" in desc_upper:
        return "Starbucks"
    if "NETFLIX" in desc_upper:
        return "Netflix"
    if "SPOTIFY" in desc_upper:
        return "Spotify"
    if "APPLE.COM/BILL" in desc_upper or "ITUNES" in desc_upper:
        return "Apple"

    # Regex cleaning
    cleaned = desc
    # Remove alphanumeric order/transaction IDs (8+ chars)
    cleaned = re.sub(r"\b[A-Z0-9]{8,}\b", "", cleaned)
    # Remove phone numbers
    cleaned = re.sub(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{4}\b", "", cleaned)
    # Remove common URL patterns
    cleaned = re.sub(r"\b(?:G\.CO|AMZN\.COM|WWW\.)\S+", "", cleaned, flags=re.IGNORECASE)
    # Remove trailing 2-letter state codes (e.g. CA, WA, NC, NY)
    cleaned = re.sub(r"\s+[A-Z]{2}$", "", cleaned.strip())
    # Remove asterisks and extra spaces
    cleaned = cleaned.replace("*", " ")
    cleaned = " ".join(cleaned.split())

    return cleaned.title() if cleaned else desc[:40].strip()


def infer_category(desc: str, amount: float, raw_category: Optional[str] = None) -> str:
    """Map Discover merchant descriptions and raw categories to standard Monarch categories."""
    desc_upper = desc.upper()
    cat_upper = (raw_category or "").upper()

    if any(k in desc_upper for k in ["PAYMENT - THANK YOU", "INTERNET PAYMENT", "DIRECTPAY"]):
        return "Credit Card Payment"

    if any(k in desc_upper or k in cat_upper for k in ["AWARDS AND REBATE CREDITS", "AUTOMATIC STATEMENT CREDIT", "CASHBACK BONUS"]):
        return "Cash Flow / Credit"

    if any(k in desc_upper for k in ["PATREON", "YOUTUBE", "GOOGLE MUSIC", "NETFLIX", "SPOTIFY"]):
        return "Subscriptions"

    if any(k in desc_upper for k in ["AMAZON", "TARGET", "WALMART"]):
        return "Shopping"

    if "MERCHANDISE" in cat_upper:
        return "Shopping"

    if "SERVICES" in cat_upper:
        return "Subscriptions"

    if any(k in cat_upper for k in ["RESTAURANTS", "DINING"]):
        return "Restaurants"

    if any(k in cat_upper for k in ["SUPERMARKETS", "GROCERIES"]):
        return "Groceries"

    if any(k in cat_upper for k in ["GASOLINE", "AUTOMOTIVE"]):
        return "Gas / Fuel"

    # Fallback based on sign
    return "Credit Card Payment" if amount > 0 else "Shopping"


def parse_pdf_statement(pdf_bytes: bytes) -> StatementPeriod:
    """
    Parse a Discover statement PDF binary into a structured StatementPeriod object.
    Uses pdftotext layout if available, falling back to PyMuPDF.
    """
    text = ""
    # Try pdftotext -layout first for exact tabular alignment
    try:
        proc = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf_bytes, capture_output=True)
        if proc.returncode == 0 and proc.stdout:
            text = proc.stdout.decode("utf-8", errors="ignore")
    except Exception:
        pass

    # Fallback to PyMuPDF (fitz)
    if not text:
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
        except Exception:
            pass

    # Extract dates
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None

    m_dates = re.search(r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})", text)
    if m_dates:
        start_dt = datetime.strptime(m_dates.group(1), "%m/%d/%Y")
        end_dt = datetime.strptime(m_dates.group(2), "%m/%d/%Y")
    else:
        m_dates2 = re.search(r"Open Date:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s*-\s*Close Date:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})", text)
        if m_dates2:
            start_dt = datetime.strptime(m_dates2.group(1), "%b %d, %Y")
            end_dt = datetime.strptime(m_dates2.group(2), "%b %d, %Y")

    start_date_str = start_dt.strftime("%Y-%m-%d") if start_dt else ""
    end_date_str = end_dt.strftime("%Y-%m-%d") if end_dt else ""

    # Closing balance (New Balance)
    m_bal = re.search(r"New Balance:?\s*\n\s*\$([0-9,]+\.[0-9]{2})", text)
    if not m_bal:
        m_bal = re.search(r"New Balance\s+\$([0-9,]+\.[0-9]{2})", text)
    closing_bal = float(m_bal.group(1).replace(",", "")) if m_bal else 0.0

    # Previous balance
    m_prev = re.search(r"Previous Balance\s*\n\s*\$([0-9,]+\.[0-9]{2})", text)
    if not m_prev:
        m_prev = re.search(r"Previous Balance\s+\$([0-9,]+\.[0-9]{2})", text)
    prev_bal = float(m_prev.group(1).replace(",", "")) if m_prev else 0.0

    # Extract transactions
    transactions: List[DiscoverTransaction] = []
    if end_dt and start_dt:
        for line in text.splitlines():
            line = line.strip()
            if not line or "PAGE" in line.upper() or "TOTAL" in line.upper() or "PREVIOUS BALANCE" in line.upper():
                continue

            # Format 1: 09/06 INTERNET PAYMENT - THANK YOU -$16.58
            m1 = re.match(r"^(\d{2}/\d{2})\s{2,}(.+?)\s{2,}(-?\$?[0-9,]+\.[0-9]{2})$", line)
            if m1:
                md, desc_raw, amt_str = m1.groups()
                m_month, m_day = int(md[:2]), int(md[3:])
                yr = end_dt.year if (start_dt.year != end_dt.year and m_month == 1) or (m_month <= end_dt.month and start_dt.year == end_dt.year) else start_dt.year
                date_str = f"{yr:04d}-{m_month:02d}-{m_day:02d}"
                raw_amt = float(amt_str.replace("$", "").replace(",", ""))
                # Discover PDF shows payments as negative (-$16.58) and purchases as positive ($13.00).
                # Monarch convention: purchases are negative (-13.00), payments are positive (+16.58).
                monarch_amount = -raw_amt
                merchant = clean_merchant_name(desc_raw)
                category = infer_category(desc_raw, monarch_amount)
                transactions.append(DiscoverTransaction(
                    date=date_str,
                    merchant=merchant,
                    category=category,
                    account="Discover it",
                    original_statement=desc_raw.strip(),
                    notes=f"Statement Date: {end_date_str}",
                    amount=monarch_amount,
                ))
                continue

            # Format 2: Payments and Credits Sep 12 Sep 12 PAYMENT - THANK YOU $ -10.71
            m2 = re.search(r"([A-Za-z]{3}\s+\d{1,2})\s+(?:[A-Za-z]{3}\s+\d{1,2}\s+)?(.+?)\s+\$\s*(-?[0-9,]+\.[0-9]{2})$", line)
            if m2:
                md, desc_raw, amt_str = m2.groups()
                try:
                    d_parsed = datetime.strptime(md, "%b %d")
                    yr = end_dt.year if (start_dt.year != end_dt.year and d_parsed.month == 1) or (d_parsed.month <= end_dt.month and start_dt.year == end_dt.year) else start_dt.year
                    date_str = f"{yr:04d}-{d_parsed.month:02d}-{d_parsed.day:02d}"
                    raw_amt = float(amt_str.replace(",", ""))
                    monarch_amount = -raw_amt
                    merchant = clean_merchant_name(desc_raw)
                    category = infer_category(desc_raw, monarch_amount)
                    transactions.append(DiscoverTransaction(
                        date=date_str,
                        merchant=merchant,
                        category=category,
                        account="Discover it",
                        original_statement=desc_raw.strip(),
                        notes=f"Statement Date: {end_date_str}",
                        amount=monarch_amount,
                    ))
                except Exception:
                    pass

    return StatementPeriod(
        statement_date=end_date_str,
        start_date=start_date_str,
        end_date=end_date_str,
        previous_balance=prev_bal,
        closing_balance=closing_bal,
        transactions=transactions,
    )


def parse_discover_dataset(raw_data: Dict[str, Any]) -> DiscoverAccount:
    """
    Parse complete captured dataset into structured DiscoverAccount object.
    
    Args:
        raw_data: Dict output from CDPSession.capture_all_data().
        
    Returns:
        DiscoverAccount populated with statements and transactions.
    """
    overview = raw_data.get("account_overview", {})
    recent_activity = raw_data.get("recent_activity", {})
    json_statements = raw_data.get("json_statements", [])
    pdf_statements = raw_data.get("pdf_statements", [])

    card_name = overview.get("card_name", "Discover it")
    account_number = str(overview.get("card_ending", "0000"))
    current_balance = float(overview.get("current_balance") or recent_activity.get("summaryData", {}).get("currentBalance") or 0.0)
    credit_limit = float(overview.get("credit_limit") or 0.0)
    available_credit = float(overview.get("available_credit") or 0.0)

    account = DiscoverAccount(
        card_name=card_name,
        account_number=account_number,
        cardholder=overview.get("cardholder", "Cardholder"),
        current_balance=current_balance,
        credit_limit=credit_limit,
        available_credit=available_credit,
    )

    # 1. Parse JSON Statements
    for j_stmt in json_statements:
        meta = j_stmt.get("metadata", {})
        data = j_stmt.get("data", {})
        summary = data.get("summaryData", {})
        posted = data.get("postedTransactionData", {})

        from_date_raw = meta.get("fromDate") or posted.get("activityStartDate") or ""
        to_date_raw = meta.get("toDate") or ""
        stmt_date = parse_date(to_date_raw)
        start_date = parse_date(from_date_raw)

        closing_bal = float(summary.get("statementBalance") or 0.0)
        prev_bal = float(posted.get("previousBalance") or 0.0)
        purchases = float(summary.get("purchases") or 0.0)
        pymts = float(summary.get("pymtsAndCredits") or 0.0)

        txns: List[DiscoverTransaction] = []
        for raw_tx in posted.get("postedTransactions", []):
            tx_date_raw = raw_tx.get("date") or raw_tx.get("postDate") or ""
            iso_date = parse_date(tx_date_raw)
            desc = raw_tx.get("description", "").strip()
            raw_amt = float(raw_tx.get("amount", 0.0))
            # In Discover JSON API:
            # Purchases are positive strings (e.g. "16.33")
            # Payments are negative strings (e.g. "-16.58")
            # In Monarch personal finance:
            # Purchases are negative (-16.33), Payments/credits are positive (+16.58)
            monarch_amt = -raw_amt

            merchant = clean_merchant_name(desc)
            category = infer_category(desc, monarch_amt, raw_tx.get("category"))
            running_bal = float(raw_tx["runningBalance"]) if raw_tx.get("runningBalance") else None

            txns.append(DiscoverTransaction(
                date=iso_date,
                merchant=merchant,
                category=category,
                account=account.display_name,
                original_statement=desc,
                notes=f"Statement Date: {stmt_date}",
                amount=monarch_amt,
                running_balance=running_bal,
                transaction_id=raw_tx.get("transactionId"),
            ))

        account.statements.append(StatementPeriod(
            statement_date=stmt_date,
            start_date=start_date,
            end_date=stmt_date,
            previous_balance=prev_bal,
            closing_balance=closing_bal,
            purchases=purchases,
            payments_and_credits=pymts,
            transactions=txns,
        ))

    # 2. Parse PDF Statements (for statements older than 24 months)
    for p_stmt in pdf_statements:
        b64 = p_stmt.get("pdf_base64")
        if b64:
            pdf_bytes = base64.b64decode(b64)
            stmt_obj = parse_pdf_statement(pdf_bytes)
            # Ensure account name on transactions matches account display name
            for t in stmt_obj.transactions:
                t.account = account.display_name
            account.statements.append(stmt_obj)

    # 3. Parse Recent / Unbilled Transactions
    recent_txns = recent_activity.get("combinedTransactionData", {}).get("combinedTransactions", [])
    for r_tx in recent_txns:
        tx_date_raw = r_tx.get("date") or r_tx.get("postDate") or ""
        iso_date = parse_date(tx_date_raw)
        desc = r_tx.get("description", "").strip()
        raw_amt = float(r_tx.get("amount", 0.0))
        # In recent activity, credits are negative (e.g. "-0.22"), purchases are positive
        # Monarch: credits positive (+0.22), purchases negative
        monarch_amt = -raw_amt
        merchant = clean_merchant_name(desc)
        category = infer_category(desc, monarch_amt, r_tx.get("category"))
        running_bal = float(r_tx["runningBalance"]) if r_tx.get("runningBalance") else None

        account.recent_transactions.append(DiscoverTransaction(
            date=iso_date,
            merchant=merchant,
            category=category,
            account=account.display_name,
            original_statement=desc,
            notes="Unbilled Recent Activity",
            amount=monarch_amt,
            running_balance=running_bal,
            transaction_id=r_tx.get("transactionId"),
        ))

    # Sort statements chronologically
    account.statements.sort(key=lambda s: s.end_date)
    return account
