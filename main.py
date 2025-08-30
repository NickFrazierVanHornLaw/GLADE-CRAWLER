# main.py
import asyncio
from playwright.sync_api import sync_playwright
from glade.config import USERNAME, PASSWORD, HEADLESS, SLOW_MO
from glade.auth import fast_login
from glade.workflows import (
    open_workflows,
    search_and_open_client,
    open_documents_and_discussion_then_documents,
)
from glade.documents import (
    enter_documents_passcode_1111,
    open_initial_documents_checklist,
    open_photo_holding_ids,
)
from glade.helpers import _log

HEADLESS=False

def _run_sync_flow() -> None:
    """Your existing sync Playwright flow (with step-by-step screenshots for debugging)."""
    if not USERNAME or not PASSWORD:
        raise SystemExit("Missing GLADE_USERNAME or GLADE_PASSWORD in .env")

    with sync_playwright() as p:
        # Use WebKit for Safari-like automation
        browser = p.webkit.launch(headless=HEADLESS, slow_mo=SLOW_MO)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        try:
            fast_login(page)
            page.screenshot(path="step1_after_login.png", full_page=True)
            open_workflows(page)
            page.screenshot(path="step2_after_open_workflows.png", full_page=True)
            search_and_open_client(page, "Carlos Rodriguez")
            page.screenshot(path="step3_after_search_client.png", full_page=True)
            open_documents_and_discussion_then_documents(page)
            page.screenshot(path="step4_after_open_documents_tab.png", full_page=True)
            enter_documents_passcode_1111(page)
            page.screenshot(path="step5_after_passcode.png", full_page=True)
            open_initial_documents_checklist(page)
            page.screenshot(path="step6_after_initial_checklist.png", full_page=True)

            # Add new checklist item (set toggles) and upload sample doc
            open_photo_holding_ids(page)  # default: "Selfie Holding DL & SS"
            page.screenshot(path="step7_after_photo_holding_ids.png", full_page=True)

            _log("Done. New document added and sample uploaded.")
            page.wait_for_timeout(1500)
        except Exception as e:
            _log(f"ERROR: {e}")
            try:
                page.screenshot(path="error.png", full_page=True)
                _log("Saved error.png")
            except Exception:
                pass
            raise
        finally:
            if HEADLESS:
                context.close()
                browser.close()

async def main() -> None:
    # Run the sync Playwright flow in a worker thread so your entrypoint is async.
    await asyncio.to_thread(_run_sync_flow)

if __name__ == "__main__":
    asyncio.run(main())



