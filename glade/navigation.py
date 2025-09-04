# glade/navigation.py
import re, time
from playwright.sync_api import Page
from .config import WORKFLOW_URL
from .helpers import _log, _scroll_list


def open_workflows(page: Page) -> None:
    page.goto(WORKFLOW_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    _log("on workflows page")


def _wait_for_client_view(page: Page, timeout_ms: int = 10000) -> None:
    """
    Wait until the client profile view is loaded. We consider it loaded if we can
    see a Documents(-related) tab or a common case header in the page.
    """
    deadline = time.time() + (timeout_ms / 1000.0)
    patterns = [
        re.compile(r"\bDocuments\b", re.I),
        re.compile(r"\bOverview\b", re.I),
        re.compile(r"\bCase\b", re.I),
    ]
    while time.time() < deadline:
        try:
            nav_like = page.locator('[role="tab"], nav *, header *, button, a, [role="button"]')
            for pat in patterns:
                nodes = nav_like.filter(has_text=pat)
                if nodes.count():
                    _log(f"client view detected by pattern: {pat.pattern}")
                    return
        except Exception:
            pass
        page.wait_for_timeout(200)
    _log("client view markers not detected within timeout; proceeding anyway")


def _type_in_search(page: Page, text: str, delay: int = 12):
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
    search = None
    for s in search_sels:
        loc = page.locator(s).first
        if loc.count():
            search = loc
            break
    if not search:
        return None
    try:
        search.click()
        try:
            search.fill("")
        except Exception:
            pass
        try:
            search.type(text, delay=delay)
        except Exception:
            page.keyboard.type(text, delay=delay)
        try:
            search.press("Enter")
        except Exception:
            pass
        return search
    except Exception:
        return search


def _click_second_clickable_below_search(page: Page, search) -> bool:
    """
    Click the *second* clickable element (button/link/role=button) that is visually below the search bar.
    Mirrors "press TAB twice then click".
    """
    if not search:
        return False

    page.wait_for_timeout(2000)  # let results populate

    candidates = []
    try:
        btns = page.get_by_role("button").below(search)
        for i in range(min(btns.count(), 8)):
            candidates.append(btns.nth(i))
    except Exception:
        pass
    try:
        links = page.get_by_role("link").below(search)
        for i in range(min(links.count(), 8)):
            candidates.append(links.nth(i))
    except Exception:
        pass
    try:
        roles = page.locator('[role="button"]').below(search)
        for i in range(min(roles.count(), 8)):
            candidates.append(roles.nth(i))
    except Exception:
        pass

    filtered = []
    for c in candidates:
        try:
            if c.count() and c.is_visible():
                filtered.append(c)
        except Exception:
            continue

    if len(filtered) >= 2:
        target = filtered[1]
        try:
            try:
                target.scroll_into_view_if_needed(timeout=800)
            except Exception:
                pass
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=5000):
                    target.click(timeout=2500, force=True)
            except Exception:
                target.click(timeout=2500, force=True)
            page.wait_for_timeout(1500)
            _log("clicked second clickable below the search field (email flow)")
            return True
        except Exception:
            return False
    return False


def _activate_focused(page: Page) -> bool:
    """
    Click/activate currently :focus element robustly.
    """
    try:
        focused = page.locator(":focus").first
        if focused.count() and focused.is_visible():
            try:
                focused.press("Enter")
                page.wait_for_timeout(400)
            except Exception:
                pass
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                    focused.click(timeout=2000, force=True)
            except Exception:
                try:
                    focused.click(timeout=2000, force=True)
                except Exception:
                    return False
            page.wait_for_timeout(1000)
            return True
    except Exception:
        pass
    return False


def search_and_open_client_by_email(page: Page, email: str, wait_ms: int = 15000) -> None:
    """
    New behavior:
      1) Type the email into search.
      2) Wait ~2s.
      3) Press TAB twice to focus the client card directly under the search.
      4) Activate/click the focused element.
      5) If that fails, click the second clickable below search.
      6) If that also fails, fallback to strict text-match approach.
    """
    _log(f"searching by email: {email}")
    search = _type_in_search(page, email, delay=12)

    page.wait_for_timeout(2000)  # results settle

    # Primary: TAB×2 then activate
    try:
        for _ in range(2):
            page.keyboard.press("Tab")
            page.wait_for_timeout(120)
        if _activate_focused(page):
            _wait_for_client_view(page, timeout_ms=7000)
            _log("clicked client card via TAB×2 from search")
            return
        # Try a couple more tabs just in case focus landed on a wrapper
        for _ in range(2):
            page.keyboard.press("Tab")
            page.wait_for_timeout(120)
        if _activate_focused(page):
            _wait_for_client_view(page, timeout_ms=7000)
            _log("clicked client card via TAB×4 fallback")
            return
    except Exception:
        pass

    # Fallback #1: second clickable below search
    if _click_second_clickable_below_search(page, search):
        _wait_for_client_view(page, timeout_ms=7000)
        return

    # Fallback #2: strict text match around email and click nearest card
    deadline = time.time() + (wait_ms / 1000.0)
    email_pat = re.compile(re.escape(email), re.I)
    candidates = (
        'xpath=ancestor::a[1]',
        'xpath=ancestor::button[1]',
        'xpath=ancestor::*[@role="button"][1]',
        'xpath=ancestor::*[contains(@class,"card") or contains(@class,"row") or contains(@class,"item")][1]',
        'xpath=ancestor::li[1]',
        'xpath=ancestor::div[1]',
    )

    def _click_nearest(label_for_log: str) -> bool:
        try:
            hits = page.get_by_text(email_pat)
            for i in range(min(hits.count(), 12)):
                node = hits.nth(i)
                for xp in candidates:
                    try:
                        container = node.locator(xp)
                        if not container.count():
                            continue
                        try:
                            container.scroll_into_view_if_needed(timeout=800)
                        except Exception:
                            pass
                        if not container.is_visible():
                            continue
                        try:
                            with page.expect_navigation(wait_until="domcontentloaded", timeout=5000):
                                container.click(timeout=2500, force=True)
                        except Exception:
                            container.click(timeout=2500, force=True)
                        page.wait_for_timeout(1500)
                        _log(f"clicked client card containing: {label_for_log}")
                        return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    while time.time() < deadline:
        if _click_nearest(email):
            _wait_for_client_view(page, timeout_ms=7000)
            return
        _scroll_list(page)
        page.wait_for_timeout(300)

    raise RuntimeError(f"No client card/button found for email: {email}")


def open_documents_and_discussion_then_documents(page: Page) -> None:
    """
    Click the single 'Documents' tab by TAB-cycling through focusable controls until we hit it.
    No selector scanning; this matches the requested interaction.
    """
    _wait_for_client_view(page, timeout_ms=9000)

    # Ensure the document area has focusable context
    try:
        page.locator("body").click()
    except Exception:
        pass

    # Up to 200 tabs to reach "Documents"
    for i in range(200):
        try:
            focused = page.locator(":focus").first
            label = ""
            try:
                # Try to read accessible name or text
                label = (focused.get_attribute("aria-label") or "").strip()
                if not label:
                    label = (focused.inner_text(timeout=300) or "").strip()
            except Exception:
                pass

            if label and re.search(r"\bDocuments\b", label, re.I):
                if _activate_focused(page):
                    try:
                        page.wait_for_load_state("networkidle", timeout=3500)
                    except Exception:
                        pass
                    _log("opened 'Documents' via tabbing")
                    return

            page.keyboard.press("Tab")
            page.wait_for_timeout(80)
        except Exception:
            # keep tabbing anyway
            try:
                page.keyboard.press("Tab")
            except Exception:
                pass
            page.wait_for_timeout(80)

    raise RuntimeError("Could not open Documents tab via tabbing.")


def _press_continue_uploading_if_present(page: Page) -> bool:
    """
    If a blocking 'Continue Uploading' button is present on the Initial/Additional
    Documents Checklist view (overlay, modal, or inline), click it to clear the screen.
    Returns True if clicked.
    """
    for _ in range(6):  # retry briefly to allow late render
        try:
            btn = page.get_by_role("button", name=re.compile(r"^continue\s+uploading$", re.I)).first
            if not btn.count():
                btn = page.locator('button:has-text("Continue Uploading"), a:has-text("Continue Uploading")').first
            if btn.count() and btn.is_visible():
                try:
                    btn.scroll_into_view_if_needed(timeout=800)
                except Exception:
                    pass
                try:
                    btn.click(timeout=2500, force=True)
                except Exception:
                    try:
                        btn.press("Enter")
                    except Exception:
                        pass
                page.wait_for_timeout(400)
                _log('dismissed "Continue Uploading" overlay')
                return True
        except Exception:
            pass
        page.wait_for_timeout(300)
    return False


def open_documents_checklist(page: Page, which: str) -> None:
    labels = {
        "initial": ("Initial Document Checklist", "Initial Documents Checklist"),
        "additional": ("Additional Document Checklist", "Additional Documents Checklist"),
    }
    targets = labels[which.lower().strip()]
    for text in targets:
        for sel in (f'text="{text}"', f'a:has-text("{text}")', f'button:has-text("{text}")'):
            try:
                page.locator(sel).first.click(timeout=3500, force=True)
                page.wait_for_timeout(900)
                # Immediately clear any blocking overlay if present
                _press_continue_uploading_if_present(page)
                _log(f"opened {text}")
                return
            except Exception:
                continue

    # If we might already be on the checklist view, still try clearing overlay once
    if _press_continue_uploading_if_present(page):
        _log(f"{targets[0]} assumed open; overlay cleared")
        return

    raise RuntimeError(f"Could not open '{targets[0]}'")


def search_and_open_client_by_name(page: Page, name: str, wait_ms: int = 15000) -> None:
    _log(f"searching by name: {name}")
    search = _type_in_search(page, name, delay=12)

    page.wait_for_timeout(2000)

    deadline = time.time() + (wait_ms / 1000.0)
    name_pat = re.compile(re.escape(name), re.I)
    candidates = (
        'xpath=ancestor::a[1]',
        'xpath=ancestor::button[1]',
        'xpath=ancestor::*[@role="button"][1]',
        'xpath=ancestor::*[contains(@class,"card") or contains(@class,"row") or contains(@class,"item")][1]',
        'xpath=ancestor::li[1]',
        'xpath=ancestor::div[1]',
    )

    def _click_nearest(label_for_log: str) -> bool:
        try:
            hits = page.get_by_text(name_pat)
            count = hits.count()
            for i in range(min(count, 12)):
                node = hits.nth(i)
                for xp in candidates:
                    try:
                        container = node.locator(xp)
                        if not container.count():
                            continue
                        try:
                            container.scroll_into_view_if_needed(timeout=800)
                        except Exception:
                            pass
                        if not container.is_visible():
                            continue
                        try:
                            with page.expect_navigation(wait_until="domcontentloaded", timeout=5000):
                                container.click(timeout=2500, force=True)
                        except Exception:
                            container.click(timeout=2500, force=True)
                        page.wait_for_timeout(1500)
                        _log(f"clicked client card for name: {label_for_log}")
                        return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    while time.time() < deadline:
        if _click_nearest(name):
            page.wait_for_timeout(2000)
            _wait_for_client_view(page, timeout_ms=7000)
            return
        _scroll_list(page)
        page.wait_for_timeout(300)

    raise RuntimeError(f"No client card/button found for name: {name}")

