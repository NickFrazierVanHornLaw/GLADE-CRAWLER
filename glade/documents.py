# glade/documents.py
import re
import time
from pathlib import Path
from typing import Any, Union, Optional

from playwright.sync_api import Page, TimeoutError as PWTimeout
from .helpers import _log
from .uploads import ensure_sample_pdf, wait_for_upload_processing_complete


def enter_documents_passcode_1111(page: Page) -> None:
    try:
        for _ in range(40):
            gate = page.get_by_text(
                re.compile("Enter passcode to access case documents", re.I)
            ).first
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
                    try:
                        box.type("1", delay=0)
                    except Exception:
                        pass
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
            page.locator("input").first.fill("1111")
            page.get_by_role("button", name=re.compile("^submit$", re.I)).click()
        except Exception:
            pass


def open_initial_documents_checklist(page: Page) -> None:
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
            page.locator(sel).first.click(timeout=2500)
            page.wait_for_timeout(500)
            _log("opened Initial Document Checklist tab")
            return
        except Exception:
            pass
    raise RuntimeError("Could not open 'Initial Document(s) Checklist'.")


# ---- helpers for rows/cards (scoped to this module) ---- #
def _row_container_for_text(page: Page, text_regex: re.Pattern):
    nodes = page.get_by_text(text_regex)
    for i in range(min(nodes.count(), 8)):
        node = nodes.nth(i)
        try:
            container = node.locator(
                'xpath=ancestor::*[.//button[normalize-space()="Open" or '
                'contains(translate(.,"OPEN","open"),"open")]][1]'
            )
            if not container.count():
                container = node.locator('xpath=ancestor::*[self::div or self::section or self::li][1]')
            if container.count():
                try:
                    container.scroll_into_view_if_needed(timeout=800)
                except Exception:
                    pass
                if container.is_visible():
                    return container
        except Exception:
            continue
    return None


def _nearest_card_container(node_locator):
    candidates = ["DocumentFileCard", "Document", "Card", "card", "Checklist", "Item", "Row"]
    xpath_any_card = " | ".join([f"ancestor::*[contains(@class,'{c}')]" for c in candidates])
    loc = node_locator.locator(f"xpath=({xpath_any_card})[1]")
    if not loc.count():
        loc = node_locator.locator("xpath=ancestor::*[self::div or self::section or self::li][1]")
    return loc


# ---- new: generic add item + upload (supports path or bytes) ---- #
def add_document_and_upload(
    page: Page,
    doc_title: str,
    upload: Union[str, Path, dict],
) -> None:
    """
    Add a new checklist item titled `doc_title`, set toggles (Required OFF, Private ON),
    click 'Add document', then upload the given file.

    `upload` can be:
      - a filesystem path (str or Path)
      - a Playwright FilePayload dict: {"name": "...", "mimeType": "...", "buffer": bytes}
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

    # 3) Enter document title
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
        name_field.fill(doc_title)
    except Exception:
        try:
            name_field.press("Control+A")
        except Exception:
            pass
        name_field.type(doc_title, delay=0)

    # 4) helper to set a labeled switch/checkbox to ON/OFF
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

        # Determine current state (checked → ON)
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
            if state is None:
                cls = (tgt.get_attribute("class") or "").lower()
                state = any(k in cls for k in ("on", "checked", "active", "enabled"))

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

    # 5) Toggle switches (Required OFF, Private ON)
    _set_toggle(re.compile(r"^required$", re.I), False)
    _set_toggle(
        re.compile(r"document will only be visible to your team and whoever uploads this document", re.I),
        True,
    )

    # 6) Click "Add document"
    add_doc_btn = panel.get_by_role("button", name=re.compile(r"^add\s+document$", re.I)).first
    if not add_doc_btn.count():
        add_doc_btn = page.locator('button:has-text("Add document"), button:has-text("Add Document")').first
    if not add_doc_btn.count():
        raise RuntimeError("Could not find the 'Add document' button.")
    add_doc_btn.click(timeout=4000)

    # Let transitions/DOM settle
    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        page.wait_for_timeout(300)

    # helper: find an Upload button in a given scope
    def _find_upload(scope):
        cand = scope.get_by_role("button", name=re.compile(r"^upload$", re.I)).first
        if cand.count():
            return cand
        cand = scope.locator('button:has-text("Upload")').first
        if cand.count():
            return cand
        cand = scope.locator('[data-testid*="upload"]').first
        if cand.count():
            return cand
        return None

    # 7) Try immediate "Upload" (detail view)
    upload_btn = _find_upload(page)
    if not upload_btn:
        # 8) Fallback: go back to row, click Open, then Upload
        name_pat = re.compile(re.escape(doc_title), re.I)
        row = None
        try:
            row = _row_container_for_text(page, name_pat)
        except Exception:
            pass
        if row is None:
            node = page.get_by_text(name_pat).first
            if node.count():
                row = node.locator('xpath=ancestor::*[self::div or self::section or self::li][1]')
        if not row or not row.count():
            raise RuntimeError("Added document, but could not find its row to open it and upload a file.")

        open_btn = row.get_by_role("button", name=re.compile(r"^open$", re.I)).first
        if not open_btn.count():
            open_btn = row.locator('button:has-text("Open")').first
        if not open_btn.count():
            raise RuntimeError("New document row found, but no 'Open' button present.")
        open_btn.click(timeout=4000)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            page.wait_for_timeout(300)

        upload_btn = _find_upload(page)

    if not upload_btn or not upload_btn.count():
        raise RuntimeError("Could not find the 'Upload' button after adding the document.")

    # 9) Click Upload and send file (path or FilePayload)
    try:
        with page.expect_file_chooser(timeout=4000) as fc:
            upload_btn.click()
        chooser = fc.value
        chooser.set_files(upload)
    except PWTimeout:
        # fallback: direct file input
        file_input = page.locator('input[type="file"]').first
        if not file_input.count():
            raise RuntimeError("Upload file chooser did not appear and no direct file input was found.")
        file_input.set_input_files(upload)

    # 10) Wait until upload fully processed
    try:
        # Use filename when possible for better “done” signal
        if isinstance(upload, dict) and "name" in upload:
            fname = upload["name"]
        else:
            fname = Path(str(upload)).name
        wait_for_upload_processing_complete(page, filename=fname)
    except Exception:
        pass

    _log(f"Added '{doc_title}', set toggles, and uploaded file.")


# ---- backward-compat wrapper (keeps older calls working) ---- #
def open_photo_holding_ids(page: Page, doc_name: str = "Selfie Holding DL & SS") -> None:
    """
    Legacy function preserved for compatibility.
    Uses a local sample PDF and delegates to add_document_and_upload.
    """
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
