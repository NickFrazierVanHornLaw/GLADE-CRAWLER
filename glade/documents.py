# glade/documents.py
import re
import time
from pathlib import Path
from typing import Union, Optional

from playwright.sync_api import Page, TimeoutError as PWTimeout
from .helpers import _log
from .uploads import ensure_sample_pdf, wait_for_upload_processing_complete


# --------------------------
# Gate: enter documents code
# --------------------------
def enter_documents_passcode_1111(page: Page) -> None:
    """
    Robustly enter a 4-digit passcode '1111' on either segmented (4 inputs) or single input forms.
    Includes patient waits so UI has time to render the gate after Documents loads.
    """
    try:
        # Wait up to ~10s for the passcode gate to appear
        for _ in range(50):
            gate = page.get_by_text(
                re.compile(r"Enter\s+passcode\s+to\s+access\s+case\s+documents", re.I)
            ).first
            inputs = page.locator(
                'input[maxlength="1"], input[autocomplete="one-time-code"], input[type="tel"], input[type="password"]'
            )
            if gate.count() or inputs.count():
                break
            page.wait_for_timeout(200)
        else:
            # No passcode gate; nothing to do
            _log("no documents passcode gate detected")
            return

        # Give a small extra pause for scripts binding
        page.wait_for_timeout(350)

        inputs = page.locator(
            'input[maxlength="1"], input[autocomplete="one-time-code"], input[type="tel"], input[type="password"]'
        )
        count = inputs.count()

        if count >= 4:
            for i in range(4):
                box = inputs.nth(i)
                try:
                    box.click(timeout=1000)
                    box.fill("1")
                except Exception:
                    try:
                        box.type("1", delay=10)
                    except Exception:
                        pass
            page.wait_for_timeout(150)
        else:
            first = inputs.first if count else page.locator("input").first
            first.click(timeout=1200)
            try:
                first.fill("1111")
            except Exception:
                first.type("1111", delay=10)

        # Ensure total length == 4
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
            page.keyboard.type("1" * (4 - total_len), delay=10)

        # Click submit
        submit = page.get_by_role("button", name=re.compile(r"^submit$", re.I)).first
        if submit.count():
            submit.click(timeout=2500)
        else:
            alt = page.locator('button:has-text("Submit"), button[type="submit"]').first
            if alt.count():
                alt.click(timeout=2500)

        page.wait_for_timeout(500)
        _log("entered passcode 1111 (fill then submit)")
    except Exception:
        try:
            page.locator("input").first.fill("1111")
            page.get_by_role("button", name=re.compile(r"^submit$", re.I)).click()
        except Exception:
            pass


def open_initial_documents_checklist(page: Page) -> None:
    """
    Click the 'Initial Document(s) Checklist' tab.
    """
    for sel in (
        'text="Initial Document Checklist"',
        'text="Initial Documents Checklist"',
        'a:has-text("Initial Document Checklist")',
        'a:has-text("Initial Documents Checklist")',
        '[role="link"]:has-text("Initial Document Checklist")',
        "text=/Initial\\s+Document(s)?\\s+Checklist/i",
        'button:has-text("Initial Document Checklist")',
    ):
        try:
            page.locator(sel).first.click(timeout=3000, force=True)
            page.wait_for_timeout(700)
            _log("opened Initial Document Checklist tab")
            return
        except Exception:
            pass
    raise RuntimeError("Could not open 'Initial Document(s) Checklist'.")


# --------------------------
# Helpers for checklist flow
# --------------------------
_ALLOWED_LABELS = [
    "Bank Statements",
    "Vehicle Info",
    "Income",
    "Tax Returns",
    "Lawsuits",
    "Lease",
    "Credit Cards",
    "Utility",
    "Credit Counseling Certificate",
    "Home/Rent Information",
    "Identification",
    "Retirement & Insurance",
    "Medical Bills",
    "Client Forms",
    "UnrecognizedDocs",
]


def _match_label_regex(label: str) -> re.Pattern:
    # exact, but tolerant to extra whitespace and case
    # also handle optional trailing colon or pluralization quirks
    safe = re.escape(label).replace(r"\ ", r"\s+")
    return re.compile(rf"^\s*{safe}\s*:?\s*$", re.I)


def _infer_label_from_text(text: str) -> Optional[str]:
    """
    Guess a checklist bucket from a filename or line of text.
    Mirrors the synonyms used elsewhere so we can match 'similar category' items.
    """
    t = (text or "").lower()

    def has(*words):
        return any(w in t for w in words)

    if has("mortgage", "deed", "escrow", "landlord", "rent", "rental", "lease"):
        return "Home/Rent Information" if "mortgage" in t else ("Lease" if "lease" in t else "Home/Rent Information")
    if has("pay stub", "paystub", "payroll", "earnings", "w-2", "w2"):
        return "Income"
    if has("tax return", "return transcript", "1040", "irs", "1099", "k-1", "k1", "schedule a", "schedule c"):
        return "Tax Returns"
    if has("bank of", "chase", "wells", "boa", "bofa", "usbank", "nfcu", "statement") and not has("credit card", "mortgage", "lease", "rent"):
        return "Bank Statements"
    if has("credit card", "visa", "mastercard", "discover", "american express", "amex"):
        return "Credit Cards"
    if has("electric", "water", "gas", "internet", "phone", "cable", "utility", "xfinity", "verizon", "t-mobile", "spectrum", "comcast", "att", "at&t"):
        return "Utility"
    if has("title", "registration", "vin", "insurance card") and has("insurance"):
        return "Vehicle Info"
    if has("401k", "401(k)", "ira", "annuity", "life insurance", "pension", "retirement"):
        return "Retirement & Insurance"
    if has("driver", "license", "dl") or has("social security", "ssn", "ss card", "passport", "id card"):
        return "Identification"
    if has("medical", "hospital", "clinic", "er", "emergency", "doctor", "dental") and has("bill", "invoice", "statement"):
        return "Medical Bills"
    if has("complaint", "summons", "subpoena", "plaintiff v.", "vs.", "v. "):
        return "Lawsuits"
    if has("client information worksheet", "questionnaire", "rights & responsibilities", "lf90", "debtors 341", "341 questionnaire"):
        return "Client Forms"
    if has("credit counseling", "certificate of counseling"):
        return "Credit Counseling Certificate"

    # When in doubt, return None (caller decides).
    return None


def _focus_label_then_tab_to_button_and_open(page: Page, label: str, tabs: int = 8, total_wait_ms: int = 15000) -> bool:
    """
    Find the checklist label node, focus it (or its nearest container), then TAB N times and activate.
    Retries with gentle scrolling for up to total_wait_ms.

    Extra fallback:
      • A Ctrl+F-style DOM search to locate the first container containing the label text.
      • If no explicit button is found, synthesize a click on the center of that container row.
    """
    deadline = time.monotonic() + (total_wait_ms / 1000.0)
    pat_exact = _match_label_regex(label)
    pat_contains = re.compile(re.escape(label), re.I)

    def _attempt_once() -> bool:
        # ---- Normal Playwright text/role-based strategies ----
        candidates = [
            page.get_by_text(pat_exact).first,
            page.get_by_text(pat_contains).first,
            page.get_by_role("heading", name=pat_contains).first,
            page.get_by_role("link", name=pat_contains).first,
            page.get_by_role("button", name=pat_contains).first,
        ]
        for cand in candidates:
            try:
                if not cand.count():
                    continue
                try:
                    cand.scroll_into_view_if_needed(timeout=1200)
                except Exception:
                    pass

                # Try clicking/focusing the label
                try:
                    cand.click(timeout=1500, force=True)
                except Exception:
                    try:
                        cand.focus()
                    except Exception:
                        pass

                page.wait_for_timeout(180)

                # TAB → Enter/Click the control that follows the label
                for _ in range(tabs):
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(75)

                focused = page.locator(":focus").first
                if focused.count() and focused.is_visible():
                    try:
                        with page.expect_load_state("domcontentloaded", timeout=4500):
                            focused.press("Enter")
                    except Exception:
                        try:
                            focused.click(timeout=1800, force=True)
                        except Exception:
                            pass

                    try:
                        page.wait_for_load_state("networkidle", timeout=4000)
                    except Exception:
                        page.wait_for_timeout(800)

                    _log(f"opened checklist section via label '{label}' (TAB x{tabs})")
                    return True
            except Exception:
                continue

        # ---- Ctrl+F-style DOM search fallback + row click ----
        try:
            needle = re.sub(r"\s+", " ", label or "").strip().lower()
            if not needle:
                return False

            # Mark container, scroll it into view, and compute a click point.
            pt = page.evaluate(
                """(needle) => {
                    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const n = norm(needle);
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
                    let hitEl = null;
                    while (walker.nextNode()) {
                        const txt = norm(walker.currentNode.nodeValue);
                        if (txt && txt.includes(n)) {
                            hitEl = walker.currentNode.parentElement;
                            break;
                        }
                    }
                    if (!hitEl) return null;
                    const container = hitEl.closest(
                        '[data-testid*="checklist"], [role="row"], [role="region"], [role="group"], section, article, li, .Row, .row, .Checklist, .Document, .Item, div'
                    ) || hitEl;
                    container.setAttribute('data-ctrlf-hit', '1');
                    try { container.scrollIntoView({block: 'center', inline: 'nearest'}); } catch(e) {}
                    const rect = container.getBoundingClientRect();
                    const x = rect.left + Math.min(rect.width * 0.65, rect.width - 5);
                    const y = rect.top + Math.min(rect.height * 0.5, rect.height - 5);
                    return { x, y };
                }""",
                needle,
            )

            if pt:
                # First try to click a nearby explicit button inside the marked container.
                container = page.locator("[data-ctrlf-hit='1']").first
                try:
                    if container.count():
                        try:
                            container.hover(timeout=500)
                        except Exception:
                            pass

                        btn = container.get_by_role("button").filter(
                            has_text=re.compile(r"\b(Open|View|Manage|Upload|Add\s+Files?)\b", re.I)
                        ).first
                        if not btn.count():
                            btn = container.locator(
                                'button:has-text("Open"), a:has-text("Open"), '
                                'button:has-text("View"), a:has-text("View"), '
                                'button:has-text("Manage"), a:has-text("Manage"), '
                                'button:has-text("Upload"), a:has-text("Upload"), '
                                'button:has-text("Add files"), a:has-text("Add files")'
                            ).first

                        if btn.count():
                            try:
                                with page.expect_load_state("domcontentloaded", timeout=4500):
                                    btn.click(timeout=2200, force=True)
                            except Exception:
                                btn.click(timeout=2200, force=True)
                        else:
                            # No explicit button: synthesize a row click at computed coords
                            page.mouse.click(float(pt["x"]), float(pt["y"]))
                            page.wait_for_timeout(120)
                            try:
                                # Some UIs require a double-click to open details
                                page.mouse.dblclick(float(pt["x"]), float(pt["y"]))
                            except Exception:
                                pass

                        try:
                            page.wait_for_load_state("networkidle", timeout=3500)
                        except Exception:
                            page.wait_for_timeout(700)

                        _log(f"opened checklist section via Ctrl+F-style row click for '{label}'")
                        return True
                finally:
                    # Clean up the temporary attribute
                    try:
                        page.evaluate("""() => {
                            document.querySelectorAll('[data-ctrlf-hit]').forEach(el => el.removeAttribute('data-ctrlf-hit'));
                        }""")
                    except Exception:
                        pass
        except Exception:
            pass

        return False

    # Retry loop with gentle scrolling to coax lazy-rendered content
    while time.monotonic() < deadline:
        if _attempt_once():
            return True
        try:
            page.keyboard.press("Home")
            page.wait_for_timeout(220)
            page.keyboard.press("End")
        except Exception:
            pass
        page.wait_for_timeout(350)

    return False


def _open_checklist_section(page: Page, checklist_label: str) -> None:
    """
    Open the target checklist section (bucket) identified by `checklist_label`.

    Strategy:
      1) Try the existing TAB×8 flow (best-effort; swallow its errors).
      2) Fallback: find the text node for the label, resolve its nearest container,
         then aggressively try to click the *container itself* (not a button):
           - wait for visible → scroll → normal click
           - force click
           - mouse click at container center (via bounding box)
           - JS element.click()
         If a nearby explicit button exists, we still try it first.
    """
    if checklist_label not in _ALLOWED_LABELS:
        _log(f"label '{checklist_label}' not in allowed list; attempting best-effort open")

    # 1) Primary flow: focus → TAB×8 → Enter (ignore internal errors)
    try:
        if _focus_label_then_tab_to_button_and_open(page, checklist_label, tabs=8, total_wait_ms=15000):
            return
    except Exception as e:
        _log(f"primary TAB flow errored for '{checklist_label}': {e}")

    # 2) Fallback: explicit clickable near the label, or click the container itself
    pat_contains = re.compile(re.escape(checklist_label), re.I)

    def _try_open_via_container(container) -> bool:
        # Prefer explicit buttons inside the container if present
        try:
            btn = container.get_by_role("button").filter(
                has_text=re.compile(r"\b(Open|View|Manage|Upload|Add\s+Files?)\b", re.I)
            ).first
            if not btn.count():
                btn = container.locator(
                    'button:has-text("Open"), a:has-text("Open"), '
                    'button:has-text("View"), a:has-text("View"), '
                    'button:has-text("Manage"), a:has-text("Manage"), '
                    'button:has-text("Upload"), a:has-text("Upload"), '
                    'button:has-text("Add files"), a:has-text("Add files")'
                ).first
            if btn.count():
                try:
                    with page.expect_load_state("domcontentloaded", timeout=4500):
                        btn.click(timeout=2500, force=True)
                except Exception:
                    btn.click(timeout=2500, force=True)
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                _log(f"opened checklist section via fallback button for '{checklist_label}'")
                return True
        except Exception:
            pass

        # No obvious button → click the container itself (several strategies)
        try:
            container.wait_for(state="visible", timeout=2000)
        except Exception:
            pass
        try:
            container.scroll_into_view_if_needed(timeout=900)
        except Exception:
            pass

        # a) Normal click
        try:
            container.click(timeout=2000)
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                page.wait_for_timeout(400)
            _log(f"opened checklist section by clicking container for '{checklist_label}'")
            return True
        except Exception:
            pass

        # b) Force click
        try:
            container.click(timeout=2000, force=True)
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                page.wait_for_timeout(400)
            _log(f"opened checklist section by force-clicking container for '{checklist_label}'")
            return True
        except Exception:
            pass

        # c) Mouse click at center via bounding box
        try:
            box = container.bounding_box()
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                page.mouse.click(x, y)
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    page.wait_for_timeout(400)
                _log(f"opened checklist section via center-point mouse click for '{checklist_label}'")
                return True
        except Exception:
            pass

        # d) JS element.click()
        try:
            handle = container.element_handle(timeout=1000)
            if handle:
                page.evaluate(
                    """el => { try { el.scrollIntoView({block:'center', inline:'nearest'}); } catch(e) {} el.click(); }""",
                    handle,
                )
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    page.wait_for_timeout(400)
                _log(f"opened checklist section via JS click() for '{checklist_label}'")
                return True
        except Exception:
            pass

        return False

    # Try a few passes, gently scrolling between attempts to coax lazy-rendered content
    for _ in range(4):
        hits = page.get_by_text(pat_contains)
        count = hits.count()
        for i in range(min(count, 12)):
            node = hits.nth(i)
            try:
                container = node.locator('xpath=ancestor::*[self::section or self::article or self::li or self::div][1]')
                if not container.count():
                    container = node
                if _try_open_via_container(container):
                    return
            except Exception:
                continue
        try:
            page.keyboard.press("End")
            page.wait_for_timeout(250)
            page.keyboard.press("Home")
        except Exception:
            pass
        page.wait_for_timeout(350)

    raise RuntimeError(f"Could not open checklist section for label: '{checklist_label}'")


def _click_upload_more_files(page: Page):
    """
    Enforce the 'Tab ×2 → Enter → choose "Upload more"' flow.

    This tries (in order):
      1) Keyboard-only: Tab twice from current focus, press Enter to open the menu,
         then click a visible "Upload more" / "Upload more files" / "Add files" item.
      2) Explicitly click a kebab/overflow button in view to open the menu, then the same menu item.
      3) Fallback to any visible 'Upload' button inside the section.
    NOTE: add_document_and_upload() wraps this call in page.expect_file_chooser(), so this
    function MUST only trigger the chooser, not handle it.
    """
    def _click_menu_item():
        item = page.get_by_role("menuitem", name=re.compile(r"^upload\s+more(\s+files)?$", re.I)).first
        if not item.count():
            item = page.locator(
                'text=/^Upload\\s+more(\\s+files)?$/i, '
                'text=/^Add\\s+files$/i, '
                'text=/^Add\\s+Documents?$/i'
            ).first
        if item.count():
            item.click(timeout=2500, force=True)
            return True
        return False

    # 1) Keyboard-only path: Tab ×2, Enter, then pick menu item
    try:
        # ensure focus somewhere sensible
        try:
            page.locator(":focus").first.click(timeout=600)
        except Exception:
            try:
                page.locator("body").click(timeout=600)
            except Exception:
                pass

        page.wait_for_timeout(120)
        page.keyboard.press("Tab")
        page.wait_for_timeout(90)
        page.keyboard.press("Tab")
        page.wait_for_timeout(120)
        try:
            # try to open the overflow/menu
            with page.expect_load_state("domcontentloaded", timeout=2500):
                page.keyboard.press("Enter")
        except Exception:
            page.keyboard.press("Enter")
        page.wait_for_timeout(180)

        if _click_menu_item():
            _log("opened menu via Tab×2→Enter and clicked 'Upload more'")
            return
    except Exception:
        pass

    # 2) Explicit overflow/kebab button
    try:
        menu_btn = page.locator(
            'button[aria-label*="more" i], button[aria-haspopup="menu"], '
            'button:has-text("…"), button:has-text("..."), [role="button"]:has([data-icon="more"])'
        ).first
        if menu_btn.count():
            try:
                with page.expect_load_state("domcontentloaded", timeout=2500):
                    menu_btn.click(timeout=2000, force=True)
            except Exception:
                menu_btn.click(timeout=2000, force=True)
            page.wait_for_timeout(150)
            if _click_menu_item():
                _log("opened menu via kebab button and clicked 'Upload more'")
                return
    except Exception:
        pass

    # 3) Fallback: direct visible 'Upload' style buttons inside the section
    try:
        btn = page.get_by_role("button", name=re.compile(r"\bupload\b", re.I)).first
        if not btn.count():
            btn = page.locator(
                'button:has-text("Upload more files"), '
                'a:has-text("Upload more files"), '
                'button:has-text("Upload More"), '
                'button:has-text("Add files"), '
                'button:has-text("Add Documents"), '
                '[data-testid*="upload"]'
            ).first
        if btn.count():
            btn.scroll_into_view_if_needed(timeout=800)
            btn.click(timeout=3000, force=True)
            _log("clicked visible 'Upload' style button as fallback")
            return
    except Exception:
        pass

    raise RuntimeError('Could not trigger "Upload more" (menu or button) in the opened section.')

def _open_menu_and_select_upload_more(page: Page, container) -> bool:
    """
    From a specific checklist/file card container:
      - Focus/click it, Tab ×2, Enter to open the overflow,
      - Click 'Upload more...' style item.
    Falls back to explicitly clicking a kebab button, then to a visible 'Upload' button.
    Returns a FileChooser object (truthy) when it successfully triggers the chooser,
    otherwise returns False.
    """
    # --- Keyboard-first: Tab ×2 + Enter ---
    try:
        try:
            container.click(timeout=1500)
        except Exception:
            container.focus()
        page.wait_for_timeout(120)
        page.keyboard.press("Tab")
        page.wait_for_timeout(90)
        page.keyboard.press("Tab")
        page.wait_for_timeout(120)

        with page.expect_file_chooser(timeout=4000) as fc:
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass
            page.wait_for_timeout(200)
            item = page.get_by_role("menuitem", name=re.compile(r"^upload\s+more(\s+files)?$", re.I)).first
            if not item.count():
                item = page.locator(
                    'text=/^Upload\\s+more(\\s+files)?$/i, '
                    'text=/^Add\\s+files$/i, '
                    'text=/^Add\\s+Documents?$/i'
                ).first
            if item.count():
                item.click(timeout=2500, force=True)
        return fc.value
    except Exception:
        pass

    # --- Explicit kebab/overflow button inside the container ---
    try:
        menu_btn = container.locator(
            'button[aria-label*="more" i], button[aria-haspopup="menu"], '
            'button:has-text("…"), button:has-text("..."), [role="button"]:has([data-icon="more"])'
        ).first
        if menu_btn.count():
            with page.expect_load_state("domcontentloaded", timeout=2500):
                menu_btn.click(timeout=2000, force=True)
            page.wait_for_timeout(150)
            with page.expect_file_chooser(timeout=4000) as fc:
                item = page.get_by_role("menuitem", name=re.compile(r"^upload\s+more(\s+files)?$", re.I)).first
                if not item.count():
                    item = page.locator(
                        'text=/^Upload\\s+more(\\s+files)?$/i, '
                        'text=/^Add\\s+files$/i, '
                        'text=/^Add\\s+Documents?$/i'
                    ).first
                if item.count():
                    item.click(timeout=2500, force=True)
            return fc.value
    except Exception:
        pass

    # --- Last resort: visible 'Upload' button inside this container ---
    try:
        with page.expect_file_chooser(timeout=2500) as fc:
            btn = container.get_by_role("button", name=re.compile(r"\bupload\b", re.I)).first
            if btn.count():
                btn.click(timeout=2000, force=True)
        return fc.value
    except Exception:
        return False

def _try_upload_via_similar_category(page: Page, target_label: str, upload: Union[str, Path, dict]) -> bool:
    """
    Scan visible file cards; if a file's text implies the same checklist category as `target_label`,
    open that section's small menu (TAB×2 flow), choose 'Upload more', and upload the file.
    """
    # Any text node that looks like a filename
    name_pat = re.compile(r"\.(pdf|jpg|jpeg|png|gif|tif|tiff|webp|heic)\b", re.I)
    nodes = page.get_by_text(name_pat)
    total = nodes.count()
    for i in range(min(total, 40)):  # guard
        node = nodes.nth(i)
        try:
            # Bind to a sensible file card container
            container = _nearest_card_container(node)
            if not container.count():
                continue

            # Extract filename-ish text
            try:
                txt = node.evaluate("el => (el.innerText || el.textContent || '').trim()") or ""
            except Exception:
                txt = ""
            if not txt or not name_pat.search(txt):
                continue

            inferred = _infer_label_from_text(txt) or "UnrecognizedDocs"
            if inferred != target_label:
                continue

            # Found a similar category – open the section menu and choose Upload More
            try:
                chooser = _open_menu_and_select_upload_more(page, container)
                if chooser:
                    chooser.set_files(upload)
                    try:
                        if isinstance(upload, dict) and "name" in upload:
                            fname = upload["name"]
                        else:
                            fname = Path(str(upload)).name
                        wait_for_upload_processing_complete(page, filename=fname)
                    except Exception:
                        pass
                    _log(f'Uploaded file into matched section via existing item "{txt}" for bucket "{target_label}".')
                    return True
            except Exception:
                continue
        except Exception:
            continue

    return False


def _fallback_add_item_and_upload(page: Page, item_title: str, upload: Union[str, Path, dict]) -> None:
    """
    Fallback when we can't find/open a labeled checklist section:
      - Click "Add an item"
      - Fill item title
      - (Best-effort) toggle Required OFF, Private ON
      - Click "Add document"
      - Upload file
    """
    page.wait_for_timeout(500)

    # 1) Click "Add an item"
    add_btn = page.get_by_role("button", name=re.compile(r"^add\s+an\s+item$", re.I)).first
    if not add_btn.count():
        for sel in ('button:has-text("Add an item")', 'button:has-text("Add Item")'):
            try:
                cand = page.locator(sel).first
                if cand.count():
                    add_btn = cand
                    break
            except Exception:
                pass
    if not add_btn.count():
        txt = page.get_by_text(re.compile(r"^Add\s+an\s+item$", re.I)).first
        if txt.count():
            add_btn = txt.locator('xpath=ancestor::button[1]')
    if not add_btn.count():
        raise RuntimeError("Could not find the 'Add an item' button.")
    add_btn.click(timeout=5000)
    page.wait_for_timeout(350)

    # 2) Scope to dialog/drawer if present
    panel = None
    for sel in (
        '[role="dialog"]',
        '[aria-modal="true"]',
        ".modal:visible",
        ".Dialog:visible",
        '[class*="drawer"]:visible',
        '[class*="side"][class*="panel"]:visible',
    ):
        loc = page.locator(sel).last
        if loc.count():
            panel = loc
            break
    if panel is None:
        panel = page

    # 3) Enter item title
    name_field = panel.locator(
        'input[placeholder*="document name" i], '
        'input[aria-label*="document name" i], '
        'input[name*="name" i], '
        'input[placeholder*="name" i], '
        'input[type="text"], '
        "textarea"
    ).first
    if not name_field.count():
        name_field = panel.get_by_role("textbox").first
    if not name_field.count():
        raise RuntimeError("Could not find the document name field after clicking 'Add an item'.")

    name_field.click(timeout=2000)
    try:
        name_field.fill(item_title)
    except Exception:
        try:
            name_field.press("Control+A")
        except Exception:
            pass
        name_field.type(item_title, delay=10)

    # 4) Toggle switches (best-effort)
    def _set_toggle(label_regex: re.Pattern, want_on: bool):
        tgt = panel.get_by_role("switch", name=label_regex).first
        if not tgt.count():
            tgt = panel.get_by_role("checkbox", name=label_regex).first
        if not tgt.count():
            lbl = panel.get_by_text(label_regex).first
            if lbl.count():
                container = lbl.locator(
                    'xpath=ancestor::*[.//input[@type="checkbox"] or .//*[@role="switch"] or '
                    './/button[@role="switch"] or .//button[contains(@class,"toggle") or contains(@class,"switch")]][1]'
                )
                if container.count():
                    tgt = container.locator(
                        'input[type="checkbox"], [role="switch"], button[role="switch"], '
                        "button:has([aria-checked]), button:has([data-state])"
                    ).first
        if not tgt.count():
            return False
        state = None
        try:
            state = tgt.is_checked()
        except Exception:
            try:
                attr = (tgt.get_attribute("aria-checked") or tgt.get_attribute("data-state") or "").lower()
                if attr in ("true", "on", "checked"):
                    state = True
                elif attr in ("false", "off", "unchecked"):
                    state = False
            except Exception:
                pass
        if state != want_on:
            try:
                tgt.click(timeout=2000, force=True)
            except Exception:
                try:
                    tgt.press("Space")
                except Exception:
                    try:
                        tgt.press("Enter")
                    except Exception:
                        pass
            page.wait_for_timeout(150)
        return True

    _set_toggle(re.compile(r"^required$", re.I), False)
    _set_toggle(
        re.compile(r"document will only be visible to your team and whoever uploads this document", re.I),
        True,
    )

    # 5) Click "Add document"
    add_doc_btn = panel.get_by_role("button", name=re.compile(r"^add\s+document$", re.I)).first
    if not add_doc_btn.count():
        for sel in ('button:has-text("Add document")', 'button:has-text("Add Document")'):
            try:
                cand = page.locator(sel).first
                if cand.count():
                    add_doc_btn = cand
                    break
            except Exception:
                pass
    if not add_doc_btn.count():
        raise RuntimeError("Could not find the 'Add document' button.")
    add_doc_btn.click(timeout=4000)

    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        page.wait_for_timeout(350)

    # 6) Upload file
    try:
        with page.expect_file_chooser(timeout=5000) as fc:
            # some UIs require clicking an 'Upload' button in the detail view
            up = panel.get_by_role("button", name=re.compile(r"\bupload\b", re.I)).first
            if not up.count():
                up = page.get_by_role("button", name=re.compile(r"\bupload\b", re.I)).first
            if up.count():
                up.click()
        chooser = fc.value
        chooser.set_files(upload)
    except PWTimeout:
        file_input = page.locator('input[type="file"]').first
        if not file_input.count():
            raise RuntimeError("Upload file chooser did not appear and no direct file input was found.")
        file_input.set_input_files(upload)

    try:
        if isinstance(upload, dict) and "name" in upload:
            fname = upload["name"]
        else:
            fname = Path(str(upload)).name
        wait_for_upload_processing_complete(page, filename=fname)
    except Exception:
        pass

    _log(f"Fallback: added new item '{item_title}' and uploaded file.")


def add_document_and_upload(
    page: Page,
    doc_title: str,           # Here, this is the *checklist label* to target.
    upload: Union[str, Path, dict],
) -> None:
    """
    Preferred flow:
      1) Try to open an existing checklist label section (with extra patience).
      2) Click 'Upload more files' (or equivalent) and upload.

    Smart fallback (NEW):
      - If the label section can't be opened, scan existing file cards for a filename that
        looks like the same category; when found, TAB×2 to open that section's menu,
        click 'Upload more', and upload there.

    Final fallback:
      - If none of the above works, use the 'Add an item' flow.
    """
    checklist_label = doc_title

    # Try labeled-bucket flow first
    try:
        _open_checklist_section(page, checklist_label)
        try:
            with page.expect_file_chooser(timeout=6000) as fc:
                _click_upload_more_files(page)
            chooser = fc.value
            chooser.set_files(upload)
            try:
                if isinstance(upload, dict) and "name" in upload:
                    fname = upload["name"]
                else:
                    fname = Path(str(upload)).name
                wait_for_upload_processing_complete(page, filename=fname)
            except Exception:
                pass
            _log(f'Uploaded file into checklist bucket "{checklist_label}" via Upload button.')
            return
        except Exception as e:
            _log(f'upload button path failed in bucket "{checklist_label}" ({e}); trying similar-category flow.')
            # Try the new similar-category path before giving up
            try:
                if _try_upload_via_similar_category(page, checklist_label, upload):
                    return
            except Exception as e2:
                _log(f'similar-category flow failed ({e2}); will fall back to Add an item.')
    except Exception as e:
        _log(f'could not open checklist bucket "{checklist_label}" ({e}); trying similar-category flow.')
        try:
            if _try_upload_via_similar_category(page, checklist_label, upload):
                return
        except Exception as e2:
            _log(f'similar-category flow failed ({e2}); will fall back to Add an item.')

    # Final fallback: add an item and upload
    _fallback_add_item_and_upload(page, checklist_label, upload)


# --------------------------
# (utility/legacy helpers)
# --------------------------
def _nearest_card_container(node_locator):
    candidates = ["DocumentFileCard", "Document", "Card", "card", "Checklist", "Item", "Row"]
    xpath_any_card = " | ".join([f"ancestor::*[contains(@class,'{c}')]" for c in candidates])
    loc = node_locator.locator(f"xpath=({xpath_any_card})[1]")
    if not loc.count():
        loc = node_locator.locator("xpath=ancestor::*[self::div or self::section or self::li][1]")
    return loc


def open_photo_holding_ids(page: Page, doc_name: str = "Selfie Holding DL & SS") -> None:
    sample_path = ensure_sample_pdf(Path("sample_upload.pdf")).resolve()
    add_document_and_upload(page, doc_name, str(sample_path))


def open_card_menu_by_text(page: Page, card_text: str) -> None:
    patt = re.compile(re.escape(card_text), re.I)
    nodes = page.get_by_text(patt)
    if not nodes.count():
        raise RuntimeError(f"No element contains the text {card_text!r}.")

    for i in range(min(nodes.count(), 8)):
        node = nodes.nth(i)
        try:
            container = _nearest_card_container(node)
            if not container.count():
                continue

            try:
                container.scroll_into_view_if_needed(timeout=800)
            except Exception:
                pass

            menu = container.locator(
                'button[aria-label*="more" i], button[aria-label*="menu" i], '
                'button[aria-haspopup="menu"], button:has-text("…"), button:has-text("...")'
            ).first
            if not menu.count():
                cand = container.locator(":scope button").filter(
                    has_not_text=re.compile(r"(?:^|\b)(Open|Download)\b", re.I)
                )
                if cand.count():
                    menu = cand.nth(cand.count() - 1)

            if menu.count():
                try:
                    container.hover(timeout=300)
                except Exception:
                    pass
                menu.click(timeout=2000)
                _log(f"Opened menu for card: {card_text!r}")
                return
        except Exception:
            continue

    raise RuntimeError(
        f"Could not find a visible card with text {card_text!r} and a clickable tail menu."
    )

