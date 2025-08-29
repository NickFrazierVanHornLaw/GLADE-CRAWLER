import os
import re
import mimetypes
from urllib.parse import urlparse
from typing import Optional, Tuple

import httpx
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright

from glade.auth import fast_login
from glade.navigation import (
    open_workflows,
    search_and_open_client_by_email,
    open_documents_and_discussion_then_documents,
)
from glade.documents import (
    enter_documents_passcode_1111,
    open_initial_documents_checklist,   # always Initial
    add_document_and_upload,            # expects (page, title, upload_payload)
)
from glade.classify import classify_for_checklist  # we ignore its checklist value

HEADLESS  = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO   = int(os.getenv("SLOW_MO", "0"))
ZAP_SHARED_SECRET = os.getenv("ZAP_SHARED_SECRET", "")

app = FastAPI()


@app.get("/")
def health():
    return {"ok": True}


async def _download_url(url: str) -> Tuple[bytes, str, str]:
    """
    Download a file from a signed CloudConvert/S3 URL.
    Returns (content_bytes, filename, content_type).
    """
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        content = r.content
        content_type = (r.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()

        # Try to extract filename from Content-Disposition
        fname = ""
        cd = r.headers.get("content-disposition") or ""
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
        if m:
            fname = m.group(1)

        # Fallback to URL path
        if not fname:
            path = urlparse(str(r.url)).path
            base = os.path.basename(path)
            if base:
                fname = base

        # Final fallback
        if not fname:
            ext = mimetypes.guess_extension(content_type) or ".bin"
            fname = f"upload{ext}"

        return content, fname, content_type


@app.post("/upload-from-zap-email")
async def upload_from_zap_email(
    client_email: str = Form(...),
    doc_name: str = Form(...),                 # AI filename from Zapier
    file: Optional[UploadFile] = File(None),   # Gmail attachment (binary OR text/uri-list)
    file_url: Optional[str] = Form(None),      # If you send the CloudConvert URL in a separate field
    x_zap_secret: Optional[str] = Header(None),
):
    # Optional shared-secret
    if ZAP_SHARED_SECRET and x_zap_secret != ZAP_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    # Classify just to get the document title; we force 'initial' checklist below
    _ignored_checklist, doc_title = classify_for_checklist(doc_name)
    routed_checklist = "initial"

    # Normalize file input:
    #  - If Zap sent a real uploaded file → use it
    #  - If Zap used "File" but content_type is text/uri-list → download the URL inside
    #  - If Zap sent file_url as a text field → download it
    source = "unknown"
    used_url = None
    content_bytes: Optional[bytes] = None
    filename: Optional[str] = None
    content_type: Optional[str] = None

    if file is not None:
        if (file.content_type or "").startswith("text/uri-list"):
            # The file field actually contains a URL string
            text = (await file.read()).decode(errors="ignore").strip()
            url_candidate = text.splitlines()[0].strip()
            if not (url_candidate.startswith("http://") or url_candidate.startswith("https://")):
                raise HTTPException(status_code=422, detail="file field contained text/uri-list but no URL")
            content_bytes, filename, content_type = await _download_url(url_candidate)
            source = "file:text/uri-list"
            used_url = url_candidate
        else:
            # Real binary upload
            content_bytes = await file.read()
            filename = file.filename or "upload.bin"
            content_type = file.content_type or "application/octet-stream"
            source = "file:binary"
    elif file_url:
        content_bytes, filename, content_type = await _download_url(file_url)
        source = "form:file_url"
        used_url = file_url
    else:
        raise HTTPException(status_code=422, detail="No file provided (binary upload, text/uri-list, or file_url).")

    # Prepare payload for the Playwright uploader
    upload_payload = {
        "name": filename or "upload.bin",
        "mimeType": content_type or "application/octet-stream",
        "buffer": content_bytes or b"",
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
            context = browser.new_context(viewport={"width": 1400, "height": 900})
            page = context.new_page()

            # Navigate to the client's documents by EMAIL
            fast_login(page)
            open_workflows(page)
            search_and_open_client_by_email(page, client_email)
            open_documents_and_discussion_then_documents(page)
            enter_documents_passcode_1111(page)

            # Always Initial checklist
            open_initial_documents_checklist(page)

            # Add item with classified title and upload the Gmail/CloudConvert file
            add_document_and_upload(page, doc_title, upload_payload)

            context.close()
            browser.close()

        return JSONResponse({
            "ok": True,
            "matched_in_glade": True,
            "routed_checklist": routed_checklist,
            "item_title": doc_title,
            "source": source,
            "used_url": used_url,
            "received_filename": filename,
            "received_content_type": content_type,
        })
    except Exception as e:
        return JSONResponse({
            "ok": False,
            "matched_in_glade": False,
            "fallback_to_drive": True,
            "error": str(e),
            "routed_checklist": routed_checklist,
            "item_title": doc_title,
            "source": source,
            "used_url": used_url,
        }, status_code=404)


