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
    Search by email. After typing, click the first button/card immediately below the search bar.
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
                search.type(email, delay=80)  # slow typing for reliability
            except Exception:
                page.keyboard.down("Control"); page.keyboard.press("KeyA"); page.keyboard.up("Control")
                page.keyboard.type(email, delay=80)
            try:
                search.press("Enter")
            except Exception:
                pass
            page.wait_for_timeout(800)  # give time for results to load
        except Exception:
            pass

    # Click the second button/card immediately below the search bar
    deadline = time.time() + (wait_ms / 1000.0)
    while time.time() < deadline:
        try:
            if search:
                # Find the second clickable element after the search bar in the DOM
                next_buttons = search.locator(
                    'xpath=following::*[(self::button or self::a or (self::div and @role="button")) and not(@disabled)]'
                )
                if next_buttons.count() >= 2:
                    target_button = next_buttons.nth(1)
                else:
                    # Fallback: get the second visible button or card on the page
                    all_buttons = page.locator('button, a, [role="button"]')
                    target_button = all_buttons.nth(1) if all_buttons.count() >= 2 else all_buttons.first
                if target_button.count():
                    target_button.scroll_into_view_if_needed(timeout=800)
                    with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                        target_button.click(timeout=2000)
                    _log(f"clicked second button/card below search bar for email: {email}")
                    return
        except Exception:
            pass

        _scroll_list(page)
        page.wait_for_timeout(250)

    raise RuntimeError(f"No client card/button found below search bar for email: {email}")

def open_documents_and_discussion_then_documents(page: Page) -> None:
    """
    Skip 'Documents & Discussion' and go straight to opening the 'Documents' tab.
    """
    for sel in (
        '[role="tab"]:has-text("Documents")',
        'a:has-text("Documents")',
        'button:has-text("Documents")',
        'nav >> text=Documents',
        'text=Documents',
    ):
        try:
            page.locator(sel).first.click(timeout=3000)
            page.wait_for_load_state("domcontentloaded")
            _log("opened Documents tab")
            return
        except Exception:
            pass
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
