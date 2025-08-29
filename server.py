# server.py
import os
import sys
import traceback

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright

from dotenv import load_dotenv
load_dotenv()  # <-- make sure .env is loaded for GLADE_USERNAME/PASSWORD, etc.

from glade.auth import fast_login
from glade.navigation import (
    open_workflows,
    search_and_open_client_by_email,
    open_documents_and_discussion_then_documents,
)
from glade.documents import (
    enter_documents_passcode_1111,
    open_initial_documents_checklist,
    add_document_and_upload,
)
from glade.classify import classify_for_checklist  # checklist ignored; we always use Initial

HEADLESS  = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO   = int(os.getenv("SLOW_MO", "0"))
ZAP_SHARED_SECRET = os.getenv("ZAP_SHARED_SECRET", "")

# Optional: flip to 'true' to include full tracebacks in JSON
DEBUG_TRACES = os.getenv("DEBUG_TRACES", "true").lower() == "true"

def _exc_details() -> str:
    if DEBUG_TRACES:
        return "".join(traceback.format_exception(*sys.exc_info()))
    # fallback to just the exception string
    etype, e, _ = sys.exc_info()
    return f"{etype.__name__}: {e}" if e else (etype.__name__ if etype else "UnknownError")

app = FastAPI()

@app.get("/")
def health():
    return {"ok": True}

@app.post("/upload-from-zap-email")
async def upload_from_zap_email(
    client_email: str = Form(...),
    doc_name: str   = Form(...),            # AI filename from Zapier
    file: UploadFile = File(...),           # Gmail attachment (binary)
    x_zap_secret: str | None = Header(None),
):
    # Shared-secret guard (optional)
    if ZAP_SHARED_SECRET and x_zap_secret != ZAP_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    # Make sure creds exist before we spin up a browser
    u = os.getenv("GLADE_USERNAME")
    p = os.getenv("GLADE_PASSWORD")
    if not u or not p:
        return JSONResponse(
            {
                "ok": False,
                "matched_in_glade": False,
                "fallback_to_drive": True,
                "error": "Missing GLADE_USERNAME or GLADE_PASSWORD in environment (.env not loaded?)",
                "routed_checklist": "initial",
                "item_title": None,
            },
            status_code=500,
        )

    # We only want the *title/category* from the AI; checklist is always "initial" now
    _unused_checklist, doc_title = classify_for_checklist(doc_name)
    routed_checklist = "initial"

    # Read file bytes for Playwright upload
    file_bytes = await file.read()
    upload_payload = {
        "name": file.filename or "upload.pdf",
        "mimeType": file.content_type or "application/pdf",
        "buffer": file_bytes,
    }

    browser = None
    context = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
            context = browser.new_context(viewport={"width": 1400, "height": 900})
            page = context.new_page()

            # Navigate & upload
            fast_login(page)
            open_workflows(page)
            # 🔎 email-based search (not name)
            search_and_open_client_by_email(page, client_email)
            open_documents_and_discussion_then_documents(page)
            enter_documents_passcode_1111(page)

            # Always Initial
            open_initial_documents_checklist(page)

            # Add classified title + upload the Gmail attachment
            add_document_and_upload(page, doc_title, upload_payload)

        # success
        return JSONResponse({
            "ok": True,
            "matched_in_glade": True,
            "routed_checklist": routed_checklist,
            "item_title": doc_title,
            "received_filename": file.filename,
            "received_content_type": file.content_type,
        })
    except Exception:
        err = _exc_details()
        # Print to server logs as well for easy debugging
        print("\n[server] ERROR during upload-from-zap-email:\n", err, file=sys.stderr)
        return JSONResponse({
            "ok": False,
            "matched_in_glade": False,
            "fallback_to_drive": True,
            "error": err,
            "routed_checklist": routed_checklist,
            "item_title": doc_title,
        }, status_code=404)
    finally:
        try:
            if context: context.close()
        except Exception:
            pass
        try:
            if browser: browser.close()
        except Exception:
            pass




