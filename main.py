import os, re, time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

load_dotenv()

USERNAME  = os.getenv("GLADE_USERNAME")
PASSWORD  = os.getenv("GLADE_PASSWORD")
HEADLESS  = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO   = int(os.getenv("SLOW_MO", "0"))
START_AT_HOME = os.getenv("START_AT_HOME", "false").lower() == "true"

HOME_URL     = "https://www.glade.ai/"
LOGIN_URL    = "https://app.glade.ai/creator/sign-in"
WORKFLOW_URL = "https://app.glade.ai/dashboard/workflows/user-workflow"

def _log(msg: str): print(f"[glade] {msg}")

# ------------------ FAST LOGIN ------------------ #
def fast_login(page: Page):
    page.set_default_timeout(6000)

    if START_AT_HOME:
        page.goto(HOME_URL, wait_until="domcontentloaded")
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=4000):
                page.get_by_role("link", name=re.compile("log.?in|sign.?in", re.I)).click()
        except PWTimeout:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
    else:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

    # Email textbox (avoid the 'Email' radio)
    email = page.get_by_role("textbox", name="Email")
    if not email.count():
        email = page.locator(
            '#identifier, input[name="identifier"][type="email"], input[placeholder="Enter your email"]'
        ).first
    email.fill(USERNAME)

    # Password textbox
    pw = page.get_by_role("textbox", name="Password")
    if not pw.count():
        pw = page.get_by_label("Password", exact=True)
    if not pw.count():
        pw = page.get_by_placeholder("Password")
    if not pw.count():
        pw = page.locator('input[type="password"]').first
    pw.fill(PASSWORD)

    # Submit
    signin = page.locator('button:has-text("Sign In"):not([disabled]), button[type="submit"]:not([disabled])').first
    try:
        signin.click()
    except Exception:
        page.get_by_role("button", name=re.compile(r"^sign\s*in$", re.I)).click()

    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except PWTimeout:
        page.wait_for_load_state("domcontentloaded")

    _log("logged in")

# ------------------ Workflows + Client → Documents ------------------ #
def open_workflows(page: Page):
    page.goto(WORKFLOW_URL, wait_until="domcontentloaded")
    _log("on workflows page")

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

def _scroll_list(page: Page):
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

def search_and_open_client(page: Page, name: str, wait_ms: int = 15000):
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

def open_documents_and_discussion_then_documents(page: Page):
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

# ------------------ Passcode (fill THEN submit) ------------------ #
def enter_documents_passcode_1111(page: Page):
    try:
        for _ in range(40):
            gate = page.get_by_text(re.compile("Enter passcode to access case documents", re.I)).first
            inputs = page.locator(
                'input[maxlength="1"], input[autocomplete="one-time-code"], input[type="tel"], input[type="password"]'
            )
            if gate.count() or inputs.count():
                break
            page.wait_for_timeout(250)
        else:
            return

        inputs = page.locator(
            'input[maxlength="1"], input[autocomplete="one-time-code"], input[type="tel"], input[type="password"]'
        )
        count = inputs.count()

        if count >= 4:
            for i in range(4):
                box = inputs.nth(i)
                try:
                    box.click(timeout=800)
                    box.fill("1")
                except Exception:
                    try: box.type("1", delay=0)
                    except Exception: pass
        else:
            first = inputs.first if count else page.locator("input").first
            first.click(timeout=800)
            first.fill("1111")

        try:
            total_len = 0
            for i in range(min(count, 4)):
                v = inputs.nth(i).evaluate("el => (el.value || '').length")
                total_len += int(v or 0)
            if count < 4:
                v = (inputs.first.evaluate("el => el.value") if count else "") or ""
                total_len = len(v)
        except Exception:
            total_len = 4

        if total_len < 4:
            page.keyboard.type("1" * (4 - total_len), delay=0)

        submit = page.get_by_role("button", name=re.compile("^submit$", re.I)).first
        if submit.count():
            submit.click(timeout=2000)
        else:
            page.locator('button:has-text("Submit"), button[type="submit"]').first.click(timeout=2000)

        page.wait_for_timeout(400)
        _log("entered passcode 1111 (fill then submit)")
    except Exception:
        try:
            page.locator('input').first.fill("1111")
            page.get_by_role("button", name=re.compile("^submit$", re.I)).click()
        except Exception:
            pass

def open_initial_documents_checklist(page: Page):
    for sel in (
        'text="Initial Document Checklist"',
        'text="Initial Documents Checklist"',
        'a:has-text("Initial Document Checklist")',
        'a:has-text("Initial Documents Checklist")',
        '[role="link"]:has-text("Initial Document Checklist")',
        'text=/Initial\\s+Document(s)?\\s+Checklist/i',
        'button:has-text("Initial Document Checklist")',
    ):
        try:
            page.locator(sel).first.click(timeout=2500)
            page.wait_for_timeout(500)
            _log("opened Initial Document Checklist tab")
            return
        except Exception:
            pass
    raise RuntimeError("Could not open 'Initial Document(s) Checklist'.")

# ------------------ Find checklist row & click OPEN / menu ------------------ #
def _row_container_for_text(page: Page, text_regex: re.Pattern):
    """
    Find a visible checklist row whose text matches text_regex and return its container.
    We climb to the nearest ancestor that contains an 'Open' button (the row).
    """
    nodes = page.get_by_text(text_regex)
    for i in range(min(nodes.count(), 8)):
        node = nodes.nth(i)
        try:
            # climb to the first ancestor that also has an Open button inside
            container = node.locator(
                'xpath=ancestor::*[.//button[normalize-space()="Open" or contains(translate(.,"OPEN","open"),"open")]][1]'
            )
            if not container.count():
                # fallback: closest div/section/li
                container = node.locator('xpath=ancestor::*[self::div or self::section or self::li][1]')
            if container.count():
                try: container.scroll_into_view_if_needed(timeout=800)
                except Exception: pass
                if container.is_visible():
                    return container
        except Exception:
            continue
    return None

def open_photo_holding_ids(page: Page, doc_name: str = "Selfie Holding DL & SS"):
    """
    Add a new checklist item, set toggles (Required OFF, Private ON),
    submit, then upload a sample document via the 'Upload' button.
    """

    # 1) Click "Add an item"
    add_btn = page.get_by_role("button", name=re.compile(r"^add\s+an\s+item$", re.I)).first
    if not add_btn.count():
        add_btn = page.locator(
            'button:has-text("Add an item"), button:has-text("Add Item"), text=/^Add an item$/i'
        ).first
    if not add_btn.count():
        raise RuntimeError("Could not find the 'Add an item' button.")
    add_btn.click(timeout=5000)
    page.wait_for_timeout(300)

    # 2) Scope to the drawer/dialog if one opened
    panel = None
    for sel in (
        '[role="dialog"]', '[aria-modal="true"]', '.modal:visible',
        '.Dialog:visible', '[class*="drawer"]:visible', '[class*="side"][class*="panel"]:visible',
    ):
        loc = page.locator(sel).last
        if loc.count():
            panel = loc
            break
    if panel is None:
        panel = page  # fallback

    # 3) Enter document name
    name_field = None
    for sel in (
        'input[placeholder*="document name" i]',
        'input[aria-label*="document name" i]',
        'input[name*="name" i]',
        'input[placeholder*="name" i]',
        'input[type="text"]',
        'textarea',
    ):
        loc = panel.locator(sel).first
        if loc.count():
            name_field = loc
            break
    if not name_field or not name_field.count():
        tb = panel.get_by_role("textbox").first
        if tb.count(): name_field = tb
    if not name_field or not name_field.count():
        raise RuntimeError("Could not find the document name field after clicking 'Add an item'.")
    name_field.click(timeout=2000)
    try:
        name_field.fill(doc_name)
    except Exception:
        try: name_field.press("Control+A")
        except Exception: pass
        name_field.type(doc_name, delay=0)

    # 4) Helper to set a labeled switch/checkbox to ON/OFF
    def _set_toggle(label_regex: re.Pattern, want_on: bool):
        # Try role="switch" then checkbox by accessible name
        tgt = panel.get_by_role("switch", name=label_regex).first
        if not tgt.count():
            tgt = panel.get_by_role("checkbox", name=label_regex).first
        if not tgt.count():
            # Fallback: find label text and click nearest switch/checkbox/button in same row
            lbl = panel.get_by_text(label_regex).first
            if lbl.count():
                container = lbl.locator(
                    'xpath=ancestor::*[.//input[@type="checkbox"] or .//*[@role="switch"] or .//button[@role="switch"] or .//button[contains(@class,"toggle") or contains(@class,"switch")]][1]'
                )
                if container.count():
                    tgt = container.locator(
                        'input[type="checkbox"], [role="switch"], button[role="switch"], button:has([aria-checked]), button:has([data-state])'
                    ).first
        if not tgt.count():
            return False

        # Determine current state
        state = None
        try:
            state = tgt.is_checked()
        except Exception:
            try:
                attr = (tgt.get_attribute("aria-checked") or tgt.get_attribute("data-state") or "").lower()
                if attr in ("true", "on", "checked"): state = True
                if attr in ("false", "off", "unchecked"): state = False
            except Exception:
                pass
        if state is None:
            cls = (tgt.get_attribute("class") or "").lower()
            state = any(k in cls for k in ("on", "checked", "active", "enabled"))

        if state != want_on:
            try:
                tgt.click(timeout=2000, force=True)
                page.wait_for_timeout(150)
            except Exception:
                # last resort: try space/enter
                try: tgt.press("Space")
                except Exception:
                    try: tgt.press("Enter")
                    except Exception: pass
        return True

    # 5) Toggle switches
    _set_toggle(re.compile(r"^required$", re.I), False)
    _set_toggle(re.compile(r"document will only be visible to your team and whoever uploads this document", re.I), True)

    # 6) Click "Add document"
    add_doc_btn = panel.get_by_role("button", name=re.compile(r"^add\s+document$", re.I)).first
    if not add_doc_btn.count():
        add_doc_btn = page.locator('button:has-text("Add document"), button:has-text("Add Document")').first
    if not add_doc_btn.count():
        raise RuntimeError("Could not find the 'Add document' button.")
    add_doc_btn.click(timeout=4000)

    # Let it render the new row
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass

    # 7) Find the new item row by its name and click "Upload", then upload a sample PDF
    row = None
    name_pat = re.compile(re.escape(doc_name), re.I)
    # reuse existing helper if present in the module
    try:
        row = _row_container_for_text(page, name_pat)  # type: ignore[name-defined]
    except Exception:
        pass
    if row is None:
        # fallback: locate by text, then climb to row container
        node = page.get_by_text(name_pat).first
        if node.count():
            row = node.locator('xpath=ancestor::*[self::div or self::section or self::li][1]')

    if not row or not row.count():
        raise RuntimeError("Added document, but could not find its row to upload a file.")

    upload_btn = row.get_by_role("button", name=re.compile(r"^upload$", re.I)).first
    if not upload_btn.count():
        upload_btn = row.locator('button:has-text("Upload")').first
    if not upload_btn.count():
        raise RuntimeError("Could not find the 'Upload' button in the new document row.")

    with page.expect_file_chooser(timeout=5000) as fc:
        upload_btn.click()
    chooser = fc.value
    pdf = ensure_sample_pdf(Path("sample_upload.pdf")).resolve()  # uses your existing helper
    chooser.set_files(str(pdf))

    # Optional: brief confirmation wait
    try:
        row.get_by_text(re.compile(r"uploaded|complete|success", re.I)).first.wait_for(timeout=4000)
    except Exception:
        pass

    _log(f"Added '{doc_name}', set toggles, and uploaded sample document.")


def _nearest_card_container(node_locator):
    candidates = ["DocumentFileCard", "Document", "Card", "card", "Checklist", "Item", "Row"]
    xpath_any_card = " | ".join([f"ancestor::*[contains(@class,'{c}')]" for c in candidates])
    loc = node_locator.locator(f"xpath=({xpath_any_card})[1]")
    if not loc.count():
        loc = node_locator.locator("xpath=ancestor::*[self::div or self::section or self::li][1]")
    return loc

def open_card_menu_by_text(page: Page, card_text: str):
    """
    If you want the little 'tail' menu instead of Open:
    find the row by text and click the right-most non-Open, non-Download button.
    """
    # Find all visible 'Open' buttons on the page
    open_buttons = page.get_by_role("button", name=re.compile("^open$", re.I))
    if not open_buttons.count():
        open_buttons = page.locator('button:has-text("Open")')
    if not open_buttons.count():
        raise RuntimeError("No 'Open' buttons found on the page.")

    for i in range(open_buttons.count()):
        btn = open_buttons.nth(i)
        try:
            btn.scroll_into_view_if_needed(timeout=800)
        except Exception:
            pass
        try:
            box = btn.bounding_box()
        except Exception:
            continue
        if not box:
            continue
        offsets = [
            (box["x"] + box["width"] - 5, box["y"] - 10),
            (box["x"] + box["width"] + 5, box["y"] - 10),
            (box["x"] + box["width"] + 10, box["y"] - 5),
            (box["x"] + box["width"] + 15, box["y"]),
        ]
        for idx, (x, y) in enumerate(offsets):
            try:
                page.mouse.move(x, y)
                page.wait_for_timeout(100)
                page.mouse.click(x, y, delay=30)
                _log(f"Tried clicking at offset {idx} ({x}, {y}) above/right of Open button {i}.")
                page.wait_for_timeout(300)
            except Exception as e:
                _log(f"[debug] Failed to click at offset {idx} ({x}, {y}): {e}")
        # Optionally, break after first button if only one is needed
        # break
    return

# ------------------ Optional upload helpers ------------------ #
def ensure_sample_pdf(path: Path) -> Path:
    if not path.exists():
        pdf_bytes = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 24 Tf 72 96 Td (Test PDF) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f 
0000000010 00000 n 
0000000060 00000 n 
0000000118 00000 n 
0000000281 00000 n 
0000000391 00000 n 
trailer<</Size 6/Root 1 0 R>>
startxref
466
%%EOF
"""
        path.write_bytes(pdf_bytes)
    return path

def upload_sample_pdf_and_confirm(page: Page, filename: str = "sample_upload.pdf"):
    clicked = False
    for sel in (
        'button:has-text("Upload more files")',
        'a:has-text("Upload more files")',
        'button:has-text("Upload files")',
        'text=/Upload\\s+more\\s+files/i',
        '[data-testid*="upload"]',
    ):
        try:
            with page.expect_file_chooser(timeout=1500) as fc:
                page.locator(sel).first.click()
            chooser = fc.value
            pdf = ensure_sample_pdf(Path(filename)).resolve()
            chooser.set_files(str(pdf))
            clicked = True
            break
        except PWTimeout:
            continue
        except Exception:
            continue

    if not clicked:
        inp = page.locator('input[type="file"]').first
        if not inp.count():
            raise RuntimeError("Could not find file upload control.")
        pdf = ensure_sample_pdf(Path(filename)).resolve()
        inp.set_input_files(str(pdf))

    for sig in (
        f'text="{Path(filename).name}"',
        'text=Uploaded', 'text=Success', 'text=completed'
    ):
        try:
            page.locator(sig).first.wait_for(timeout=4000)
            break
        except PWTimeout:
            continue

    page.screenshot(path="upload_success.png", full_page=True)
    _log("uploaded sample PDF and saved upload_success.png")

# ------------------ Runner ------------------ #
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

            # Click the row’s Open button (robust vs hidden span[title])
            open_photo_holding_ids(page)

            # If you instead want the little circle / tail menu on the DL-only row:
            # open_card_menu_by_text(page, "A Photo of your Driver's License")

            _log("Done. Opened the 'Photo holding DL & SS' row.")
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


