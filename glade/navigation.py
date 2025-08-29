# glade/navigation.py
import re, time
from playwright.sync_api import Page, TimeoutError
from .config import WORKFLOW_URL
from .helpers import _log, _try_click_first_match, _scroll_list

def open_workflows(page: Page) -> None:
    page.goto(WORKFLOW_URL, wait_until="domcontentloaded")
    _log("on workflows page")

def search_and_open_client_by_email(page: Page, email: str, wait_ms: int = 15000) -> None:
    """
    Search by email. If a direct link isn't obvious, click the result card that
    contains the word 'Workflows' (prefer the one that also contains the email).
    """
    # 1) Focus the search box and type the email
    search_sels = (
        'input[type="search"]',
        'input[role="searchbox"]',
        'input[placeholder*="search" i]',
        'input[placeholder*="client" i]',
        'input[placeholder*="workflow" i]',
        '[data-testid*="search"] input',
        '[contenteditable="true"][role="combobox"]',
        '[contenteditable="true"]',
    )

    try:
        page.locator('h1:has-text("Chapter"), h2:has-text("Chapter")').first.wait_for(timeout=4000)
    except Exception:
        pass

    search = None
    for s in search_sels:
        loc = page.locator(s).first
        if loc.count():
            try:
                loc.wait_for(state="visible", timeout=2000)
                search = loc
                break
            except Exception:
                pass

    if search:
        try:
            search.click()
            try:
                search.fill("")
                search.type(email, delay=0)
            except Exception:
                page.keyboard.down("Control"); page.keyboard.press("KeyA"); page.keyboard.up("Control")
                page.keyboard.type(email, delay=0)
            try:
                search.press("Enter")
            except Exception:
                pass
            page.wait_for_timeout(500)
        except Exception:
            pass

    # 2) Try direct link click first
    pat_email = re.compile(re.escape(email), re.I)
    deadline = time.time() + (wait_ms / 1000.0)

    while time.time() < deadline:
        # A. If a link itself matches, click it
        if _try_click_first_match(page, pat_email):
            _log(f"opened client by email (direct link): {email}")
            return

        # B. Prefer a card that contains BOTH the email and the word 'Workflows'
        try:
            email_nodes = page.get_by_text(pat_email)
            for i in range(min(email_nodes.count(), 6)):
                n = email_nodes.nth(i)
                try:
                    # Find nearest ancestor card that also contains 'Workflows' text
                    container = n.locator(
                        'xpath=ancestor::*[self::article or self::section or self::li or self::div]'
                        '[.//text()[contains(translate(., "Chapter", "Chapters"), "Chapter")]]'
                        '[.//a or .//button][1]'
                    )
                    if container.count():
                        try:
                            container.scroll_into_view_if_needed(timeout=800)
                        except Exception:
                            pass

                        # Prefer a link inside the card
                        link = container.locator("a[href]").first
                        click_target = link if link.count() else container.locator("button").first
                        if not click_target.count():
                            click_target = container

                        try:
                            with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                                click_target.click(timeout=2000)
                            _log(f"opened client by email (card with Workflows + email): {email}")
                            return
                        except TimeoutError:
                            # Try a force click without expecting nav (sometimes SPA updates)
                            try:
                                click_target.click(timeout=2000, force=True)
                                page.wait_for_load_state("domcontentloaded")
                                _log(f"opened client by email (card forced): {email}")
                                return
                            except Exception:
                                pass
                except Exception:
                    continue
        except Exception:
            pass

        # C. Fallback: any visible 'Workflows' card — click first clickable within
        try:
            wf_nodes = page.get_by_text(re.compile(r"\bWorkflows\b", re.I))
            for i in range(min(wf_nodes.count(), 6)):
                w = wf_nodes.nth(i)
                try:
                    container = w.locator(
                        'xpath=ancestor::*[self::article or self::section or self::li or self::div][.//a or .//button][1]'
                    )
                    if container.count():
                        try:
                            container.scroll_into_view_if_needed(timeout=800)
                        except Exception:
                            pass

                        link = container.locator("a[href]").first
                        click_target = link if link.count() else container.locator("button").first
                        if not click_target.count():
                            click_target = container

                        try:
                            with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                                click_target.click(timeout=2000)
                            _log(f"opened client by email (generic Workflows card): {email}")
                            return
                        except TimeoutError:
                            try:
                                click_target.click(timeout=2000, force=True)
                                page.wait_for_load_state("domcontentloaded")
                                _log(f"opened client by email (generic Workflows card forced): {email}")
                                return
                            except Exception:
                                pass
                except Exception:
                    continue
        except Exception:
            pass

        # D. As a last resort: find a row containing the email, click the first link in that row
        try:
            nodes = page.get_by_text(pat_email)
            for i in range(min(nodes.count(), 6)):
                n = nodes.nth(i)
                try:
                    row = n.locator('xpath=ancestor::*[self::tr or self::li or self::div][.//a][1]')
                    if row.count():
                        try:
                            row.scroll_into_view_if_needed(timeout=800)
                        except Exception:
                            pass
                        link = row.locator("a").first
                        if link.count():
                            with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                                link.click()
                            _log(f"opened client (row link) by email: {email}")
                            return
                except Exception:
                    continue
        except Exception:
            pass

        _scroll_list(page)
        page.wait_for_timeout(250)

    raise RuntimeError(f"No client row/card found for email: {email}")

    """
    Types the email in the search box, then clicks the first visible result:
    - Prefers dropdown/listbox option right under the search
    - Otherwise clicks the first 'card' / link row that contains the email
    - Falls back to the previous row-scanning and scrolling
    """
    search_sels = (
        'input[type="search"]',
        'input[role="searchbox"]',
        'input[placeholder*="search" i]',
        'input[placeholder*="client" i]',
        'input[placeholder*="workflow" i]',
        '[data-testid*="search"] input',
        '[contenteditable="true"][role="combobox"]',
        '[contenteditable="true"]',
    )

    # 1) Focus the search box and type the email
    search = None
    for s in search_sels:
        loc = page.locator(s).first
        if loc.count():
            try:
                loc.wait_for(state="visible", timeout=2000)
                search = loc
                break
            except Exception:
                pass

    if search:
        try:
            search.click()
            try:
                search.fill("")
                search.type(email, delay=0)
            except Exception:
                page.keyboard.down("Control"); page.keyboard.press("KeyA"); page.keyboard.up("Control")
                page.keyboard.type(email, delay=0)
            # Try to trigger suggestions/results
            try:
                search.press("Enter")
            except Exception:
                pass
            page.wait_for_timeout(300)
        except Exception:
            pass

    pat_email = re.compile(re.escape(email), re.I)
    deadline = time.time() + (wait_ms / 1000.0)

    def _click_with_nav(loc) -> bool:
        """Click loc and wait for navigation; fall back to force click."""
        if not loc or not loc.count():
            return False
        try:
            try:
                loc.scroll_into_view_if_needed(timeout=800)
            except Exception:
                pass
            with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                loc.click()
            _log(f"opened client by email: {email}")
            return True
        except TimeoutError:
            try:
                loc.click(timeout=2000, force=True)
                page.wait_for_load_state("domcontentloaded")
                _log(f"opened client by email (force click): {email}")
                return True
            except Exception:
                return False
        except Exception:
            return False

    while time.time() < deadline:
        # A) Dropdown/Listbox options directly under search
        try:
            opt = page.get_by_role("option", name=pat_email).first
            if opt.count() and _click_with_nav(opt):
                return
        except Exception:
            pass
        try:
            listbox_opt = page.locator(
                '[role="listbox"] [role="option"], [role="listbox"] li, ul[role="listbox"] li'
            ).filter(has_text=pat_email).first
            if listbox_opt.count() and _click_with_nav(listbox_opt):
                return
        except Exception:
            pass
        # As a nudge, try ArrowDown + Enter once results exist
        try:
            if search and page.locator('[role="listbox"]').count():
                search.press("ArrowDown"); search.press("Enter")
                page.wait_for_load_state("domcontentloaded", timeout=2000)
                _log(f"opened client by email (ArrowDown+Enter): {email}")
                return
        except Exception:
            pass

        # B) The “card just below the search bar” or any clickable card/link containing the email
        candidates = [
            page.locator('[data-testid*="card"]').filter(has_text=pat_email).first,
            page.locator('[class*="card"]').filter(has_text=pat_email).first,
            page.locator('[role="link"]').filter(has_text=pat_email).first,
            page.locator('a').filter(has_text=pat_email).first,
        ]
        for cand in candidates:
            if cand.count() and _click_with_nav(cand):
                return

        # C) Row fallback (original behavior)
        nodes = page.get_by_text(pat_email)
        for i in range(min(nodes.count(), 6)):
            n = nodes.nth(i)
            try:
                # Prefer a link/button inside the same row/card
                row = n.locator('xpath=ancestor::*[self::tr or self::li or self::div][.//a or .//*[@role="link"] or .//button][1]')
                if row.count():
                    linkish = row.locator('a, [role="link"], button').first
                    if linkish.count() and _click_with_nav(linkish):
                        return
                    # If no child link, try clicking the row itself
                    if _click_with_nav(row):
                        return
            except Exception:
                continue

        _scroll_list(page)
        page.wait_for_timeout(250)

    raise RuntimeError(f"No client row found for email: {email}")

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
