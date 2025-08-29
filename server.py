import sys, asyncio
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import os
import sys
import traceback

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright

from dotenv import load_dotenv
load_dotenv()  # ensure .env is loaded (GLADE_USERNAME / GLADE_PASSWORD, etc.)

from glade.auth import fast_login
from glade.navigation import (
    open_workflows,
    search_and_open_client_by_email,
    open_documents_and_discussion_then_documents,
)
from glade.documents import (
    enter_documents_passcode_1111,
    open_initial_documents_checklist,   # always use Initial checklist now
    add_document_and_upload,            # (page, title, upload_payload)
)
from glade.classify import classify_for_checklist  # checklist ignored; title used

HEADLESS  = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO   = int(os.getenv("SLOW_MO", "0"))
ZAP_SHARED_SECRET = os.getenv("ZAP_SHARED_SECRET", "")
DEBUG_TRACES = os.getenv("DEBUG_TRACES", "true").lower() == "true"

def _exc_details() -> str:
    if DEBUG_TRACES:
        return "".join(traceback.format_exception(*sys.exc_info()))
    etype, e, _ = sys.exc_info()
    return f"{etype.__name__}: {e}" if e else (etype.__name__ if etype else "UnknownError")

app = FastAPI()

@app.get("/")
def health():
    return {"ok": True}

# NOTE: this is a SYNC endpoint now (def, not async def)
@app.post("/upload-from-zap-email")
def upload_from_zap_email(
    client_email: str = Form(...),
    doc_name: str = Form(...),            # AI filename from Zapier
    file: UploadFile = File(...),         # Gmail attachment (binary)
    x_zap_secret: str | None = Header(None),
):
    # Optional shared-secret guard
    if ZAP_SHARED_SECRET and x_zap_secret != ZAP_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    # Ensure Glade creds are present
    if not os.getenv("GLADE_USERNAME") or not os.getenv("GLADE_PASSWORD"):
        return JSONResponse(
            {
                "ok": False,
                "matched_in_glade": False,
                "fallback_to_drive": True,
                "error": "Missing GLADE_USERNAME or GLADE_PASSWORD in environment (.env not loaded?)",
                "routed_checklist": "initial",
                "item_title": None,
                "source": None,
                "used_url": None,
            },
            status_code=500,
        )

    # We always route to Initial checklist; we only need the display title/category
    _ignored_checklist, doc_title = classify_for_checklist(doc_name)
    routed_checklist = "initial"

    # Read file bytes synchronously (we're in a sync endpoint)
    file_bytes = file.file.read()
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

            # Navigate and upload
            fast_login(page)
            open_workflows(page)
            # 🔎 search by EMAIL (not name)
            search_and_open_client_by_email(page, client_email)
            open_documents_and_discussion_then_documents(page)
            enter_documents_passcode_1111(page)

            # Always open Initial Document Checklist
            open_initial_documents_checklist(page)

            # Add the item (classified title) and upload the Gmail attachment
            add_document_and_upload(page, doc_title, upload_payload)

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
        print("\n[server] ERROR during upload-from-zap-email:\n", err, file=sys.stderr)
        return JSONResponse({
            "ok": False,
            "matched_in_glade": False,
            "fallback_to_drive": True,
            "error": err,
            "routed_checklist": routed_checklist,
            "item_title": doc_title,
            "source": "file:binary",
            "used_url": None,
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




