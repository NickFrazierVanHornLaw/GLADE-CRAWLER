import re
from playwright.sync_api import Page, TimeoutError as PWTimeout
from .config import START_AT_HOME, HOME_URL, LOGIN_URL, USERNAME, PASSWORD
from .helpers import _log

def fast_login(page: Page) -> None:
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

    # Tolerate missing networkidle
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except PWTimeout:
        page.wait_for_load_state("domcontentloaded")

    _log("logged in")
