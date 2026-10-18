"""Chrome DevTools Protocol (CDP) client for Discover credit card extraction."""

import json
import os
import time
import urllib.request
import websocket
from typing import Dict, Any, List, Optional


class CDPError(Exception):
    """Raised when CDP connection or data extraction fails."""
    pass


def find_discover_tab(port: int = 9222, tab_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Locate the Discover Account Center tab in Chrome DevTools Protocol.
    
    Args:
        port: Chrome remote debugging port.
        tab_id: Optional specific tab ID to look for.
        
    Returns:
        Dict representing tab metadata from /json.
    """
    url = f"http://127.0.0.1:{port}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            tabs = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise CDPError(
            f"Could not connect to Chrome debugging port {port}: {e}. "
            f"Ensure Chrome is running with --remote-debugging-port={port}"
        )

    if tab_id:
        for tab in tabs:
            if tab.get("id") == tab_id:
                return tab

    # Search by URL or Title
    for tab in tabs:
        tab_url = tab.get("url", "")
        tab_title = tab.get("title", "")
        if "card.discover.com" in tab_url and tab.get("type") == "page":
            return tab
        if "discover" in tab_title.lower() and tab.get("type") == "page":
            return tab

    raise CDPError(
        "No open Discover tab found. Please log in to https://card.discover.com in Chrome."
    )


class CDPSession:
    """Manages WebSocket connection to Chrome CDP tab for Discover data extraction."""

    def __init__(self, port: int = 9222, tab_id: Optional[str] = None, timeout: float = 30.0):
        self.port = port
        self.tab_id = tab_id
        self.timeout = timeout
        self.ws: Optional[websocket.WebSocket] = None
        self.tab_info: Optional[Dict[str, Any]] = None
        self._msg_id = 0

    def connect(self) -> None:
        """Establish WebSocket connection to Chrome CDP tab."""
        self.tab_info = find_discover_tab(port=self.port, tab_id=self.tab_id)
        ws_url = self.tab_info.get("webSocketDebuggerUrl")
        if not ws_url:
            raise CDPError(f"Tab {self.tab_info.get('id')} has no webSocketDebuggerUrl available.")

        try:
            self.ws = websocket.create_connection(
                ws_url,
                suppress_origin=True,
                timeout=self.timeout
            )
        except Exception as e:
            raise CDPError(f"Failed to connect to WebSocket {ws_url}: {e}")

    def close(self) -> None:
        """Close WebSocket connection."""
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def evaluate(self, expression: str, await_promise: bool = True) -> Any:
        """Evaluate a JavaScript expression inside the Discover page context."""
        if not self.ws:
            raise CDPError("WebSocket connection is not open.")

        self._msg_id += 1
        msg = {
            "id": self._msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        }
        self.ws.send(json.dumps(msg))

        start_time = time.time()
        while time.time() - start_time < self.timeout:
            try:
                raw = self.ws.recv()
                data = json.loads(raw)
                if data.get("id") == self._msg_id:
                    result = data.get("result", {})
                    if "exceptionDetails" in result:
                        exc = result["exceptionDetails"]
                        raise CDPError(f"JavaScript evaluation failed: {exc}")
                    return result.get("result", {}).get("value")
            except websocket.WebSocketTimeoutException:
                pass

        raise CDPError(f"Timed out waiting for Runtime.evaluate response for msg id {self._msg_id}")

    def get_account_overview(self) -> Dict[str, Any]:
        """Extract basic account metadata and balances from page context."""
        js_code = r"""
        (() => {
            const cardEndingMatch = document.body.innerText.match(/(?:Card Details|Account|CARD ENDING IN)\s*(?:\(Account ending in\s*|ending in\s*)?(\d{4})/i);
            const cardEnding = cardEndingMatch ? cardEndingMatch[1] : '0000';
            
            let currentBal = null;
            const balMatch = document.body.innerText.match(/Current Balance:?\s*\n?\s*\$([0-9,]+\.[0-9]{2})/i);
            if (balMatch) {
                currentBal = parseFloat(balMatch[1].replace(/,/g, ''));
            } else if (window.globalData?.summaryData?.currentBalance) {
                currentBal = parseFloat(window.globalData.summaryData.currentBalance);
            }

            let creditLimit = null;
            const limitMatch = document.body.innerText.match(/Total Credit Line:?\s*\$([0-9,]+(?:\.[0-9]{2})?)/i);
            if (limitMatch) {
                creditLimit = parseFloat(limitMatch[1].replace(/,/g, ''));
            }

            let availCredit = null;
            const availMatch = document.body.innerText.match(/Available Credit:?\s*\$([0-9,]+(?:\.[0-9]{2})?)/i);
            if (availMatch) {
                availCredit = parseFloat(availMatch[1].replace(/,/g, ''));
            }

            return {
                card_name: "Discover it",
                card_ending: cardEnding,
                current_balance: currentBal,
                credit_limit: creditLimit,
                available_credit: availCredit,
                url: window.location.href,
                title: document.title
            };
        })()
        """
        return self.evaluate(js_code)

    def fetch_recent_activity(self) -> Dict[str, Any]:
        """Fetch recent transactions and statements catalog."""
        js_code = """
        (async () => {
            const resp = await fetch('/cardissuer/statements/transactions/v1/recent?source=stmt');
            if (!resp.ok) {
                throw new Error(`Failed to fetch recent transactions: HTTP ${resp.status}`);
            }
            return await resp.json();
        })()
        """
        return self.evaluate(js_code)

    def fetch_statement_json(self, stmt_uri: str) -> Dict[str, Any]:
        """Fetch online JSON statement details."""
        js_code = f"""
        (async () => {{
            const resp = await fetch({json.dumps(stmt_uri)});
            if (!resp.ok) {{
                throw new Error(`Failed to fetch statement {stmt_uri}: HTTP ${{resp.status}}`);
            }}
            return await resp.json();
        }})()
        """
        return self.evaluate(js_code)

    def fetch_pdf_base64(self, pdf_uri: str) -> str:
        """Fetch PDF binary content as base64 string."""
        js_code = f"""
        (async () => {{
            const resp = await fetch({json.dumps(pdf_uri)});
            if (!resp.ok) {{
                throw new Error(`Failed to fetch PDF {pdf_uri}: HTTP ${{resp.status}}`);
            }}
            const blob = await resp.blob();
            return new Promise((resolve, reject) => {{
                const reader = new FileReader();
                reader.onloadend = () => {{
                    const res = reader.result;
                    const b64 = res.split(',')[1];
                    resolve(b64);
                }};
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            }});
        }})()
        """
        return self.evaluate(js_code)

    def capture_all_data(
        self,
        cache_dir: str = "raw_statements",
        include_pdfs: bool = True,
        max_pdf_statements: Optional[int] = None,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Perform complete extraction of account data, JSON statements, and statement PDFs.
        
        Args:
            cache_dir: Directory where raw PDFs and JSON can be cached.
            include_pdfs: Whether to fetch historical PDF statements older than 24 months.
            max_pdf_statements: Limit number of historical PDFs to fetch (None for all).
            progress_callback: Optional callable(status_str) for progress updates.
            
        Returns:
            Dict containing complete raw captured dataset.
        """
        os.makedirs(cache_dir, exist_ok=True)

        if progress_callback:
            progress_callback("Extracting card overview and recent activity...")

        overview = self.get_account_overview()
        recent = self.fetch_recent_activity()

        statements_catalog = recent.get("statements", [])
        if progress_callback:
            progress_callback(f"Found {len(statements_catalog)} total statement periods in Discover archive.")

        # 1. Fetch all available JSON statements (past ~24 months)
        json_statements = []
        json_stmts_to_fetch = [s for s in statements_catalog if s.get("stmtUri")]
        for idx, s in enumerate(json_stmts_to_fetch, start=1):
            date_label = s.get("toDate", "")
            uri = s.get("stmtUri")
            if progress_callback:
                progress_callback(f"Fetching JSON statement {idx}/{len(json_stmts_to_fetch)} ({date_label})...")
            try:
                stmt_data = self.fetch_statement_json(uri)
                json_statements.append({
                    "metadata": s,
                    "data": stmt_data
                })
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Warning: Failed to fetch JSON statement for {date_label}: {e}")

        # 2. Fetch older PDF statements (beyond 24 months)
        pdf_statements = []
        if include_pdfs:
            # Statements without stmtUri (older than 24 months)
            pdf_stmts_to_fetch = [s for s in statements_catalog if not s.get("stmtUri") and s.get("pdfUri")]
            if max_pdf_statements:
                pdf_stmts_to_fetch = pdf_stmts_to_fetch[:max_pdf_statements]

            total_pdfs = len(pdf_stmts_to_fetch)
            for idx, s in enumerate(pdf_stmts_to_fetch, start=1):
                date_label = s.get("toDate", "")
                pdf_uri = s.get("pdfUri")
                clean_date = date_label.replace("/", "")
                cached_pdf_path = os.path.join(cache_dir, f"discover_statement_{clean_date}.pdf")

                if os.path.exists(cached_pdf_path) and os.path.getsize(cached_pdf_path) > 1000:
                    if progress_callback:
                        progress_callback(f"Loaded cached PDF {idx}/{total_pdfs} ({date_label})...")
                    with open(cached_pdf_path, "rb") as f:
                        import base64
                        b64 = base64.b64encode(f.read()).decode("ascii")
                    pdf_statements.append({
                        "metadata": s,
                        "pdf_base64": b64,
                        "file_path": cached_pdf_path
                    })
                else:
                    if progress_callback:
                        progress_callback(f"Downloading statement PDF {idx}/{total_pdfs} ({date_label})...")
                    try:
                        b64 = self.fetch_pdf_base64(pdf_uri)
                        import base64
                        with open(cached_pdf_path, "wb") as f:
                            f.write(base64.b64decode(b64))
                        pdf_statements.append({
                            "metadata": s,
                            "pdf_base64": b64,
                            "file_path": cached_pdf_path
                        })
                    except Exception as e:
                        if progress_callback:
                            progress_callback(f"Warning: Failed to fetch PDF for {date_label}: {e}")

        return {
            "account_overview": overview,
            "recent_activity": recent,
            "json_statements": json_statements,
            "pdf_statements": pdf_statements
        }
