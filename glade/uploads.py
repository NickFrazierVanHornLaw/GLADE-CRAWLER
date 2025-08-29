from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PWTimeout
from .helpers import _log

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

def upload_sample_pdf_and_confirm(page: Page, filename: str = "sample_upload.pdf") -> None:
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
                page.wait_for_timeout(500)  # Wait for file chooser to appear
            chooser = fc.value
            pdf = ensure_sample_pdf(Path(filename)).resolve()
            chooser.set_files(str(pdf))
            page.wait_for_timeout(1000)  # Wait after setting file to allow upload to start
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
        page.wait_for_timeout(1000)  # Wait after setting file to allow upload to start


    # Wait for upload to finish: look for a pending/progress indicator, then wait for it to disappear or for a success indicator
    # Try to detect a progress bar, spinner, or 'pending' text
    pending_selectors = [
        'text=Pending',
        '[aria-label*="progress"]',
        '[role="progressbar"]',
        '.ant-spin',
        '.MuiCircularProgress-root',
        '.spinner',
        '.loading',
    ]
    found_pending = False
    for sel in pending_selectors:
        try:
            if page.locator(sel).first.is_visible():
                found_pending = True
                # Wait for it to disappear (max 30s)
                page.locator(sel).first.wait_for(state="detached", timeout=30000)
                break
        except Exception:
            continue

    # After pending/progress, wait for a success indicator or the uploaded file to appear
    for sig in (
        f'text="{Path(filename).name}"',
        'text=Uploaded', 'text=Success', 'text=completed'
    ):
        try:
            page.locator(sig).first.wait_for(timeout=12000)
            break
        except PWTimeout:
            continue

    # Wait for any spinner/progress near the uploaded file name to disappear (final processing)
    file_row = page.locator(f'text="{Path(filename).name}"').first
    if file_row.count():
        for sel in pending_selectors:
            try:
                spinner = file_row.locator(f'.. >> {sel}').first
                if spinner.is_visible():
                    spinner.wait_for(state="detached", timeout=15000)
            except Exception:
                continue

    # As a fallback, always wait a little longer to ensure upload is complete
    page.wait_for_timeout(2500)

    page.screenshot(path="upload_success.png", full_page=True)
    _log("uploaded sample PDF and saved upload_success.png")


def wait_for_upload_processing_complete(page: Page, filename: str = "sample_upload.pdf") -> None:
    """Block until the UI shows the given file is fully processed/uploaded.
    Looks for generic progress indicators and waits for them to disappear,
    then confirms via success text or the file name being present, and adds a final grace delay.
    """
    # Detect any global progress indicators
    pending_selectors = [
        'text=Pending',
        '[aria-label*="progress"]',
        '[role="progressbar"]',
        '.ant-spin',
        '.MuiCircularProgress-root',
        '.spinner',
        '.loading',
    ]

    for sel in pending_selectors:
        try:
            if page.locator(sel).first.is_visible():
                page.locator(sel).first.wait_for(state="detached", timeout=30000)
                break
        except Exception:
            continue

    # Check success signals or file name appears
    for sig in (
        f'text="{Path(filename).name}"',
        'text=Uploaded', 'text=Success', 'text=completed'
    ):
        try:
            page.locator(sig).first.wait_for(timeout=12000)
            break
        except PWTimeout:
            continue

    # Ensure no spinner next to the file entry
    file_row = page.locator(f'text="{Path(filename).name}"').first
    if file_row.count():
        for sel in pending_selectors:
            try:
                spinner = file_row.locator(f'.. >> {sel}').first
                if spinner.is_visible():
                    spinner.wait_for(state="detached", timeout=15000)
            except Exception:
                continue

    page.wait_for_timeout(2000)
