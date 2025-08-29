import re, time
from playwright.sync_api import Page, TimeoutError as PWTimeout

def _log(msg: str) -> None:
    print(f"[glade] {msg}")

def _try_click_first_match(page: Page, name_pat: re.Pattern) -> bool:
    candidates = [
        page.get_by_role("link", name=name_pat),
        page.locator("aside").get_by_role("link", name=name_pat),
        page.locator("main").get_by_role("link", name=name_pat),
        page.locator("a").filter(has_text=name_pat),
    ]
    for loc in candidates:
        if loc.count():
            el = loc.first
            try:
                el.scroll_into_view_if_needed(timeout=500)
            except Exception:
                pass
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=3000):
                    el.click(timeout=3000)
                return True
            except PWTimeout:
                try:
                    el.click(timeout=3000, force=True)
                    page.wait_for_load_state("domcontentloaded")
                    return True
                except Exception:
                    continue
            except Exception:
                continue
    return False

def _scroll_list(page: Page) -> None:
    scrollers = [
        page.locator("aside").first,
        page.locator('[data-testid*="sidebar"]').first,
        page.locator('[class*="sidebar"]').first,
    ]
    did = False
    for sc in scrollers:
        if sc.count():
            try:
                sc.evaluate("el => el.scrollBy(0, 900)")
                did = True
            except Exception:
                pass
    try:
        page.mouse.wheel(0, 900)
        did = True
    except Exception:
        pass
    if not did:
        page.evaluate("window.scrollBy(0, 900)")
