# server.py
import sys, asyncio
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import os
import io
import re
import uuid
import json
import shutil
import traceback
import tempfile
from typing import Optional, Tuple
from urllib.parse import urlparse, unquote

import httpx
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

# ====== CONFIG ======
HEADLESS = os.getenv("HEADLESS", "false").lower() == "false"
SLOW_MO = int(os.getenv("SLOW_MO", "0"))
ZAP_SHARED_SECRET = os.getenv("ZAP_SHARED_SECRET", "")
DEBUG_TRACES = os.getenv("DEBUG_TRACES", "true").lower() == "true"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")

# Prefer Edge on Windows (Chromium channel), user can override
BROWSER_ENGINE = os.getenv("BROWSER_ENGINE", "chromium").lower()  # chromium|webkit|firefox
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "msedge").lower()  # msedge|chrome|msedge-beta|...

OPENAI_NAMING_PROMPT = """You will be given the first page of a document (title + a little text).
Return a VERY short, human-friendly document title used in a law firm's intake checklist.
Do NOT include the person's name or email. Prefer specific labels like "Driver's License", 
"Social Security Card", "Paystub", "Bank Statement", "Photo Holding IDs", "Tax Return 2023", etc.
If unreadable or blank, respond exactly: UnrecognizableDoc.
Return only the title. No punctuation at the end.
"""

# Lazily-initialized globals
_openai_client = None

# ====== UTILITIES ======
def _exc_details() -> str:
    if DEBUG_TRACES:
        return "".join(traceback.format_exception(*sys.exc_info()))
    etype, e, _ = sys.exc_info()
    return f"{etype.__name__}: {e}" if e else (etype.__name__ if etype else "UnknownError")

def parse_name_email_from_subject(subject: str) -> Tuple[Optional[str], Optional[str]]:
    if not subject:
        return None, None
    m = re.search(r"^\s*(.+?)\s*\(\s*([^)@\s]+@[^)\s]+)\s*\)\s*$", subject)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m2 = re.search(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", subject or "")
    name = subject
    email = m2.group(1) if m2 else None
    return name, email

def _download_to_bytes(url: str, timeout: int = 60) -> Tuple[bytes, Optional[str]]:
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content, r.headers.get("content-type")

def _guess_ext_from_mime(mime: Optional[str]) -> str:
    if not mime:
        return ""
    mime = mime.lower().split(";")[0].strip()
    mapping = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/heic": ".heic",
        "image/heif": ".heic",
        "image/tiff": ".tif",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-excel": ".xls",
    }
    return mapping.get(mime, "")

# ---- Conversions (lazy imports inside) ----
def convert_any_to_pdf(tmpdir: str, in_bytes: bytes, filename: str, mime: Optional[str]) -> str:
    print(f"[DEBUG] convert_any_to_pdf: filename={filename}, mime={mime}, size={len(in_bytes)}")
    print(f"[DEBUG] First 16 bytes: {in_bytes[:16].hex()}")

    base_name = os.path.splitext(filename)[0] or f"file_{uuid.uuid4().hex}"
    ext = (os.path.splitext(filename)[1] or _guess_ext_from_mime(mime) or "").lower()

    # Magic sniff if no good ext
    if not ext:
        if in_bytes.startswith(b"%PDF"):
            ext = ".pdf"
            print("[DEBUG] Detected PDF from magic header")
        elif in_bytes[:2] == b"\xff\xd8":
            ext = ".jpg"
            print("[DEBUG] Detected JPEG from magic header")
        elif in_bytes[:4] == b"\x89PNG":
            ext = ".png"
            print("[DEBUG] Detected PNG from magic header")
        elif in_bytes[:2] == b"PK":
            ext = ".docx"
            print("[DEBUG] Detected ZIP container (assuming DOCX)")
        else:
            raise RuntimeError("Unsupported file type (no extension and magic header not recognized)")

    src_path = os.path.join(tmpdir, base_name + ext)
    with open(src_path, "wb") as f:
        f.write(in_bytes)

    if ext == ".pdf":
        print(f"[DEBUG] Saved PDF to {src_path}")
        return src_path

    if ext in (".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".gif", ".bmp", ".webp"):
        from PIL import Image
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        img = Image.open(io.BytesIO(in_bytes)).convert("RGB")
        out_pdf = os.path.join(tmpdir, base_name + ".pdf")
        img.save(out_pdf, "PDF", resolution=200.0)
        print(f"[DEBUG] Converted image -> PDF at {out_pdf}")
        return out_pdf

    if ext in (".doc", ".docx"):
        try:
            from docx2pdf import convert as docx2pdf_convert
        except Exception:
            raise RuntimeError("docx2pdf not available (requires MS Word on Windows).")
        out_pdf = os.path.join(tmpdir, base_name + ".pdf")
        docx2pdf_convert(src_path, out_pdf)
        if not os.path.exists(out_pdf):
            raise RuntimeError("DOC/DOCX convert failed (no output PDF).")
        print(f"[DEBUG] Converted Word -> PDF at {out_pdf}")
        return out_pdf

    raise RuntimeError(f"Unsupported file type for conversion: {ext}")

def pdf_first_page_only(pdf_path: str, tmpdir: str) -> str:
    from PyPDF2 import PdfReader, PdfWriter
    reader = PdfReader(pdf_path)
    if len(reader.pages) == 0:
        raise RuntimeError("Empty PDF.")
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    out_path = os.path.join(tmpdir, f"{uuid.uuid4().hex}_page1.pdf")
    with open(out_path, "wb") as f:
        writer.write(f)
    print(f"[DEBUG] First-page-only PDF at {out_path}")
    return out_path

def extract_text_first_page(pdf_path: str, max_chars: int = 3000) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        if not reader.pages:
            return ""
        text = reader.pages[0].extract_text() or ""
        text = re.sub(r"\s+", " ", text).strip()
        print(f"[DEBUG] Extracted {len(text)} chars from first page")
        return text[:max_chars]
    except Exception as e:
        print(f"[WARN] extract_text_first_page failed: {e}")
        return ""

def _get_openai_client():
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY:
        try:
            from openai import OpenAI
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        except Exception:
            _openai_client = None
    return _openai_client

def openai_name_document_from_first_page(page1_pdf_path: str) -> str:
    client = _get_openai_client()
    if client is None:
        print("[DEBUG] OpenAI disabled or not available; using UnrecognizableDoc")
        return "UnrecognizableDoc"

    text = extract_text_first_page(page1_pdf_path, max_chars=3000) or "(No extractable text)"
    try:
        # Newer models require max_completion_tokens instead of max_tokens
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You name legal intake documents succinctly."},
                {"role": "user", "content": f"{OPENAI_NAMING_PROMPT}\n\nFirst page text:\n{text}\n"}
            ],
            temperature=1.0,
            max_completion_tokens=2000,
        )
        title = (resp.choices[0].message.content or "").strip()
        title = re.sub(r"[\r\n]+", " ", title).strip()
        if not title:
            title = "UnrecognizableDoc"
        title = re.sub(r"[.:\-;,\s]+$", "", title).strip()
        title = title[:120] or "UnrecognizableDoc"
        print(f"[DEBUG] OpenAI proposed title: {title}")
        return title
    except Exception as e:
        print(f"[WARN] OpenAI naming failed: {e}")
        return "UnrecognizableDoc"

def ensure_doc_title(doc_name_from_zap: Optional[str], page1_pdf_path: str) -> str:
    if doc_name_from_zap and doc_name_from_zap.strip():
        print(f"[DEBUG] Using doc_name from Zap: {doc_name_from_zap.strip()}")
        return doc_name_from_zap.strip()
    return openai_name_document_from_first_page(page1_pdf_path)


def _launch_browser(pw):
    """
    Launch the requested Playwright browser. Defaults to Chromium with Edge channel on Windows.
    """
    launch_kwargs = dict(headless=HEADLESS, slow_mo=SLOW_MO)
    engine = BROWSER_ENGINE
    if engine == "chromium":
        # Prefer channel when provided (Edge tends to be more stable with some SPAs)
        if BROWSER_CHANNEL:
            launch_kwargs["channel"] = BROWSER_CHANNEL
        return pw.chromium.launch(**launch_kwargs)
    elif engine == "firefox":
        return pw.firefox.launch(**launch_kwargs)
    else:
        # webkit fallback
        return pw.webkit.launch(**launch_kwargs)


# server.py (only the glade process function)
def attempt_glade_upload(
    client_email: str,
    client_name: str,
    doc_title: str,            # AI-proposed human title (used for FILE name)
    upload_bytes: bytes,
    upload_filename: str,
    upload_mime: str,
):
    """
    Returns (success, error_message). Self-contained Playwright + Glade flow.

    FIX: The checklist ITEM title is the CLASSIFIED BUCKET (e.g., "Bank statements"),
    while the uploaded FILE name uses the AI-proposed title (e.g., "Mortgage Statement.pdf").
    """
    import os, re

    def _safe_pdf_name(title: str) -> str:
        t = re.sub(r"\s+", " ", (title or "").strip())
        t = re.sub(r'[\\/:*?"<>|]+', "", t)
        t = t[:120].rstrip(" .")
        if not t:
            t = "Document"
        if not re.search(r"\.pdf$", t, re.I):
            t = f"{t}.pdf"
        return t

    browser = None
    context = None
    try:
        print("[DEBUG] Starting Playwright + Glade upload sequence...")
        from playwright.sync_api import sync_playwright
        from glade.classify import classify_for_checklist
        from glade.auth import fast_login
        from glade.navigation import (
            open_workflows,
            search_and_open_client_by_email,
            search_and_open_client_by_name,
            open_documents_and_discussion_then_documents,
        )
        from glade.documents import (
            enter_documents_passcode_1111,
            open_initial_documents_checklist,
            add_document_and_upload,
        )

        headless = os.getenv("HEADLESS", "false").lower() in ("1", "true", "yes")
        slow_mo = int(os.getenv("SLOW_MO", "0") or "0")
        engine = os.getenv("BROWSER_ENGINE", "chromium").lower()
        channel = os.getenv("BROWSER_CHANNEL", "msedge")

        with sync_playwright() as p:
            # Launch
            if engine == "chromium":
                try:
                    browser = p.chromium.launch(channel=channel, headless=headless, slow_mo=slow_mo)
                except Exception:
                    browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
            elif engine == "firefox":
                browser = p.firefox.launch(headless=headless, slow_mo=slow_mo)
            else:
                browser = p.webkit.launch(headless=headless, slow_mo=slow_mo)

            context = browser.new_context(viewport={"width": 1400, "height": 900})
            page = context.new_page()

            # Login & land on workflows
            fast_login(page)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            open_workflows(page)

            # Select client: email first (TAB×2 flow), then name fallback
            client_found = False
            try:
                print(f"[DEBUG] Searching client by email: {client_email}")
                search_and_open_client_by_email(page, client_email)
                client_found = True
            except Exception as e:
                print(f"[DEBUG] Email search failed: {e}. Trying by name: {client_name}")
                try:
                    search_and_open_client_by_name(page, client_name)
                    client_found = True
                except Exception as e2:
                    print(f"[DEBUG] Name search failed: {e2}")
                    client_found = False

            if not client_found:
                return False, "Client profile not found"

            # Documents tab
            page.wait_for_timeout(900)
            open_documents_and_discussion_then_documents(page)

            # Passcode (if present) + checklist
            enter_documents_passcode_1111(page)
            open_initial_documents_checklist(page)

            # Map to checklist BUCKET for ITEM title
            _ignored, checklist_bucket = classify_for_checklist(doc_title)
            print(f"[DEBUG] Checklist bucket for '{doc_title}' -> '{checklist_bucket}'")

            # FILE name uses AI-proposed title
            final_upload_name = _safe_pdf_name(doc_title)
            print(f"[DEBUG] Using upload filename: {final_upload_name}")

            payload = {
                "name": final_upload_name,                     # visible file name in Glade
                "mimeType": upload_mime or "application/pdf",
                "buffer": upload_bytes,
            }

            # IMPORTANT: Use the BUCKET as the checklist item's title, not the AI title
            add_document_and_upload(page, checklist_bucket, payload)

            print("[DEBUG] Upload to Glade completed")
            return True, None
    except Exception as e:
        return False, str(e)
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        
# ====== FASTAPI ======
app = FastAPI()

@app.get("/")
def health():
    return {"ok": True}

@app.post("/process-doc")
def process_doc(
    client_email: Optional[str] = Form(None),
    client_name: Optional[str] = Form(None),
    name_email_subject: Optional[str] = Form(None),
    doc_name: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    file_url: Optional[str] = Form(None),
    x_zap_secret: Optional[str] = Header(None),
):
    # Auth
    if ZAP_SHARED_SECRET and x_zap_secret != ZAP_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    # Log inbound
    print("\n[DEBUG] /process-doc request")
    print(json.dumps({
        "client_email": client_email,
        "client_name": client_name,
        "name_email_subject": name_email_subject,
        "doc_name": doc_name,
        "file_present": bool(file),
        "file_url": file_url,
    }, indent=2))

    # Subject parse if needed
    if (not client_email or not client_name) and name_email_subject:
        nm, em = parse_name_email_from_subject(name_email_subject)
        client_name = client_name or nm
        client_email = client_email or em

    if not client_email:
        client_email = ""
        print("[WARN] Missing client_email; will still name but mark as not matched.")

    # Read input bytes
    try:
        if file is not None:
            in_bytes = file.file.read()
            in_name = file.filename or "upload.bin"
            in_mime = file.content_type or "application/octet-stream"
        elif file_url:
            in_bytes, ctype = _download_to_bytes(file_url, timeout=120)
            parsed = urlparse(file_url)
            in_name = unquote(os.path.basename(parsed.path)) or "download.bin"
            in_mime = ctype or "application/octet-stream"
        else:
            return JSONResponse({
                "ok": False, "matched_in_glade": False,
                "error": "Client profile not found",
                "detail": "Missing both file and file_url",
            }, status_code=200)
    except Exception as e:
        print(f"[ERROR] Download/read failed: {e}")
        return JSONResponse({
            "ok": False, "matched_in_glade": False,
            "error": "Client profile not found",
            "detail": f"fetch_failed: {e}",
        }, status_code=200)

    # Convert + name + upload
    tmpdir = tempfile.mkdtemp(prefix="ingest_")
    try:
        pdf_path = convert_any_to_pdf(tmpdir, in_bytes, in_name, in_mime)
        print(f"[DEBUG] PDF ready at {pdf_path} (size={os.path.getsize(pdf_path)} bytes)")
        page1_pdf = pdf_first_page_only(pdf_path, tmpdir)

        from glade.classify import classify_for_checklist
        proposed_title = ensure_doc_title(doc_name, page1_pdf)
        _ignored, checklist_title = classify_for_checklist(proposed_title)
        print(f"[DEBUG] Proposed title: '{proposed_title}', checklist title: '{checklist_title}'")

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        success, err = attempt_glade_upload(
            client_email=client_email or "",
            client_name=client_name or "",
            doc_title=proposed_title,
            upload_bytes=pdf_bytes,
            upload_filename=(os.path.basename(pdf_path) or "upload.pdf"),
            upload_mime="application/pdf",
        )

        if success:
            print(f"[INFO] Uploaded to Glade as '{checklist_title}' for {client_email or client_name}")
            return JSONResponse({
                "ok": True,
                "matched_in_glade": True,
                "item_title": checklist_title,
                "proposed_title": proposed_title,
                "received_filename": os.path.basename(pdf_path),
                "source": ("file:binary" if file is not None else "file:url"),
            }, status_code=200)

        print(f"[WARN] Glade upload failed/not matched. Reason: {err}")
        return JSONResponse({
            "ok": False,
            "matched_in_glade": False,
            "error": "Client profile not found",
            "detail": err or "",
            "item_title": checklist_title,
            "proposed_title": proposed_title,
            "received_filename": os.path.basename(pdf_path),
        }, status_code=200)

    except Exception:
        err = _exc_details()
        print("[ERROR] Pipeline failed:\n", err)
        return JSONResponse({
            "ok": False,
            "matched_in_glade": False,
            "error": "Client profile not found",
            "detail": err,
        }, status_code=200)
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass









