# glade/navigation.py
import re, time
from playwright.sync_api import Page
from .config import WORKFLOW_URL
from .helpers import _log, _try_click_first_match, _scroll_list

def open_workflows(page: Page) -> None:
    page.goto(WORKFLOW_URL, wait_until="domcontentloaded")
    _log("on workflows page")

def search_and_open_client_by_email(page: Page, email: str, wait_ms: int = 15000) -> None:
    """
    Types the email into the global search. If there isn't a direct
    link match, it clicks the first client link inside the row that contains the email.
    """
    # 1) Try the same search boxes
    search_sels = (
        'input[type="search"]',
        'input[role="searchbox"]',
        'input[placeholder*="search" i]',
        '[data-testid*="search"] input',
        '[contenteditable="true"][role="combobox"]',
        '[contenteditable="true"]',
    )

    search = None
    for s in search_sels:
        loc = page.locator(s).first
        if loc.count():
            try:
                loc.wait_for(state="visible", timeout=2000)
                search = loc; break
            except Exception: pass

    if search:
        try:
            search.click()
            try:
                search.fill(""); search.type(email, delay=0)
            except Exception:
                page.keyboard.down("Control"); page.keyboard.press("KeyA"); page.keyboard.up("Control")
                page.keyboard.type(email, delay=0)
            try: search.press("Enter")
            except Exception: pass
            page.wait_for_timeout(400)
        except Exception:
            pass

    # 2) If a link itself matches, click it
    pat_email = re.compile(re.escape(email), re.I)
    deadline = time.time() + (wait_ms / 1000.0)
    while time.time() < deadline:
        # If the client link happens to include the email as accessible name
        if _try_click_first_match(page, pat_email):
            _log(f"opened client by email: {email}")
            return

        # Otherwise: find a row containing the email, then click the first link in that row
        nodes = page.get_by_text(pat_email)
        for i in range(min(nodes.count(), 6)):
            n = nodes.nth(i)
            try:
                row = n.locator('xpath=ancestor::*[self::tr or self::li or self::div][.//a][1]')
                if row.count():
                    try: row.scroll_into_view_if_needed(timeout=800)
                    except Exception: pass
                    link = row.locator("a").first
                    if link.count():
                        with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                            link.click()
                        _log(f"opened client (row click) by email: {email}")
                        return
            except Exception:
                continue

        _scroll_list(page)
        page.wait_for_timeout(250)

    raise RuntimeError(f"No client row found for email: {email}")

def open_documents_and_discussion_then_documents(page: Page) -> None:
    for sel in (
        '[role="tab"]:has-text("Documents & Discussion")',
        '[role="tab"]:has-text("Documents and Discussion")',
        'a:has-text("Documents & Discussion")',
        'a:has-text("Documents and Discussion")',
        'button:has-text("Documents & Discussion")',
        'button:has-text("Documents and Discussion")',
        'text=/Documents\\s*(&|and)\\s*Discussion/i',
    ):
        try: page.locator(sel).first.click(timeout=2000); break
        except Exception: pass

    for sel in (
        '[role="tab"]:has-text("Documents")',
        'a:has-text("Documents")',
        'button:has-text("Documents")',
        'nav >> text=Documents',
    ):
        try:
            page.locator(sel).first.click(timeout=3000)
            page.wait_for_load_state("domcontentloaded")
            _log("opened Documents tab")
            return
        except Exception: pass
    raise RuntimeError("Could not open Documents tab.")

def open_documents_checklist(page: Page, which: str) -> None:
    """
    which: "initial" or "additional"
    """
    labels = (
        ("initial", ("Initial Document Checklist", "Initial Documents Checklist")),
        ("additional", ("Additional Document Checklist", "Additional Documents Checklist")),
    )
    targets = dict(labels)[which.lower().strip()]

    for text in targets:
        for sel in (
            f'text="{text}"',
            f'a:has-text("{text}")',
            f'button:has-text("{text}")',
            f'[role="link"]:has-text("{text}")',
        ):
            try:
                page.locator(sel).first.click(timeout=2500)
                page.wait_for_timeout(500)
                _log(f"opened {text}")
                return
            except Exception:
                pass
    raise RuntimeError(f"Could not open '{targets[0]}'")
