import re, time
from playwright.sync_api import Page
from .config import WORKFLOW_URL
from .helpers import _log, _try_click_first_match, _scroll_list

def open_workflows(page: Page) -> None:
    page.goto(WORKFLOW_URL, wait_until="domcontentloaded")
    _log("on workflows page")

def search_and_open_client(page: Page, name: str, wait_ms: int = 15000) -> None:
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
        page.locator('h1:has-text("Workflow"), h2:has-text("Workflow")').first.wait_for(timeout=4000)
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
                continue

    if search:
        try:
            search.click()
            try:
                search.fill("")
                search.type(name, delay=0)
            except Exception:
                page.keyboard.down("Control"); page.keyboard.press("KeyA"); page.keyboard.up("Control")
                page.keyboard.type(name, delay=0)
            try:
                search.press("Enter")
            except Exception:
                pass
            page.wait_for_timeout(400)
        except Exception:
            pass

    deadline = time.time() + (wait_ms / 1000.0)
    pat_exact = re.compile(rf"^{re.escape(name)}$", re.I)
    pat_loose = re.compile(name, re.I)

    while time.time() < deadline:
        if _try_click_first_match(page, pat_exact) or _try_click_first_match(page, pat_loose):
            _log(f"opened client: {name}")
            return
        _scroll_list(page)
        page.wait_for_timeout(250)

    raise RuntimeError(f"No clickable result found for '{name}' within {wait_ms} ms.")

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
        try:
            page.locator(sel).first.click(timeout=2000)
            break
        except Exception:
            pass

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
        except Exception:
            pass
    raise RuntimeError("Could not open Documents tab.")
