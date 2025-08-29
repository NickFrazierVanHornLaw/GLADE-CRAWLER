from playwright.sync_api import sync_playwright
from glade.config import USERNAME, PASSWORD, HEADLESS, SLOW_MO
from glade.auth import fast_login
from glade.workflows import open_workflows, search_and_open_client, open_documents_and_discussion_then_documents
from glade.documents import enter_documents_passcode_1111, open_initial_documents_checklist, open_photo_holding_ids
from glade.helpers import _log

def main():
    if not USERNAME or not PASSWORD:
        raise SystemExit("Missing GLADE_USERNAME or GLADE_PASSWORD in .env")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        try:
            fast_login(page)
            open_workflows(page)
            search_and_open_client(page, "Carlos Rodriguez")
            open_documents_and_discussion_then_documents(page)
            enter_documents_passcode_1111(page)
            open_initial_documents_checklist(page)

            # Add new checklist item (set toggles as requested) and upload sample doc
            open_photo_holding_ids(page)  # default name: "Selfie Holding DL & SS"

            _log("Done. New document added and sample uploaded.")
            # Stall briefly to ensure any async UI updates complete before closing
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
                context.close(); browser.close()

if __name__ == "__main__":
    main()



