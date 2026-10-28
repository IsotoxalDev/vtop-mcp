import asyncio
import re
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import Page

from . import captcha, parsers
from .config import LOGIN_TIMEOUT_S, VTOP_BASE_URL
from .errors import NotLoggedInError, VtopError

CONTENT_URL = f"{VTOP_BASE_URL}/content"
LOGIN_URL = f"{VTOP_BASE_URL}/login"

MAX_CAPTCHA_ATTEMPTS = 20


async def goto_login_form(page: Page) -> None:
    """Navigate to the login flow's entry point and get to the actual username/password/
    captcha form. VTOP's /login is a role-selector landing page (Student/Employee/Parent/
    Alumni); picking "Student" POSTs a hidden form (#stdForm) to /prelogin/setup, which is
    what actually renders #vtopLoginForm (with either the plain image captcha or
    reCAPTCHA)."""
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    if await page.locator("#vtopLoginForm").count() > 0:
        return
    if await page.locator("#stdForm").count() > 0:
        await page.evaluate("document.getElementById('stdForm').submit()")
        await page.wait_for_load_state("domcontentloaded")


async def is_logged_in(page: Page) -> bool:
    """Authoritative check: always (re)navigates to /content, so it reflects the real,
    current server-side session state. Used by vtop_status, whose whole job is to report
    that accurately. For the repeated "are we still logged in" guard that every data tool
    runs before its own request, see ensure_home below -- that one deliberately trades a
    little staleness for not re-navigating on every single call."""
    try:
        await page.goto(CONTENT_URL, wait_until="domcontentloaded")
    except Exception:
        return False
    try:
        await page.wait_for_selector("#authorizedIDX, #vtopLoginForm", timeout=10_000)
    except Exception:
        pass
    return await page.locator("#authorizedIDX").count() > 0


async def _prefill_credentials(page: Page, username: str | None, password: str | None) -> None:
    if username:
        try:
            await page.fill('#vtopLoginForm [name="username"]', username, timeout=2000)
        except Exception:
            pass
    if password:
        try:
            await page.fill('#vtopLoginForm [name="password"]', password, timeout=2000)
        except Exception:
            pass


async def _captcha_kind(page: Page) -> str:
    """"grecaptcha" (Google reCAPTCHA) or "default" (plain image captcha)."""
    has_grecaptcha = await page.locator("#gResponse").count() > 0
    return "grecaptcha" if has_grecaptcha else "default"


async def _submit_login_form(page: Page, username: str, password: str, captcha_str: str) -> dict[str, Any]:
    """Port of the reference app's signIn(): POST /vtop/login and classify the response."""
    return await page.evaluate(
        """
        async ({ username, password, captchaStr }) => {
            const csrf = document.querySelector('#vtopLoginForm input[name="_csrf"]');
            const body = new URLSearchParams({
                _csrf: csrf ? csrf.value : '',
                username, password, captchaStr,
            });
            const res = await fetch('/vtop/login', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: body.toString(),
            });
            const text = await res.text();
            const lower = text.toLowerCase();
            if (text.includes('authorizedIDX')) {
                return { authorised: true };
            }
            if (/invalid\\s*captcha/.test(lower)) {
                return { authorised: false, error_code: 1, error_message: 'Invalid captcha' };
            }
            if (/invalid\\s*(user\\s*name|login\\s*id|user\\s*id)\\s*\\/\\s*password/.test(lower)) {
                return { authorised: false, error_code: 2, error_message: 'Invalid username/password' };
            }
            if (/account\\s*is\\s*locked/.test(lower)) {
                return { authorised: false, error_code: 3, error_message: 'Account is locked' };
            }
            if (/maximum\\s*fail\\s*attempts\\s*reached/.test(lower)) {
                return { authorised: false, error_code: 4, error_message: 'Maximum fail attempts reached' };
            }
            return { authorised: false, error_code: 5, error_message: 'Unknown error' };
        }
        """,
        {"username": username, "password": password, "captchaStr": captcha_str},
    )


async def try_auto_login(page: Page, username: str, password: str) -> bool:
    """Attempt fully headless login by OCR-solving VTOP's plain image captcha.

    If VTOP initially serves a Google reCAPTCHA, this just reloads the login page a
    few times first: VTOP's own login flow intermittently flips between reCAPTCHA and
    the plain captcha (or no captcha) on a fresh page load, a quirk documented by
    https://github.com/NotSooShariff/vtop-captcha-kill-extension. That's a plain page
    reload, not an attempt to defeat reCAPTCHA itself -- if it keeps serving
    reCAPTCHA, this gives up and lets the caller fall back to a visible browser (see
    captcha.py's module docstring for why reCAPTCHA itself is never auto-solved).

    Returns False (never raises for ordinary captcha misreads) if it can't get in.
    """
    for _ in range(MAX_CAPTCHA_ATTEMPTS):
        if await _captcha_kind(page) != "default":
            await goto_login_form(page)
            continue

        try:
            captcha_src = await page.eval_on_selector("#captchaBlock img", "img => img.src")
        except Exception:
            return False

        guess = captcha.solve_default_captcha(captcha_src)
        if not guess:
            await goto_login_form(page)
            continue

        result = await _submit_login_form(page, username, password, guess)
        if result.get("authorised"):
            await page.goto(CONTENT_URL, wait_until="domcontentloaded")
            return True

        if result.get("error_code") == 1:  # invalid captcha -- retry with a fresh one
            await goto_login_form(page)
            continue

        # Wrong credentials / locked / rate-limited: no point retrying automatically.
        raise VtopError(f"VTOP login failed: {result.get('error_message', 'unknown error')}")

    return False


async def wait_for_manual_login(
    page: Page,
    timeout_s: int = LOGIN_TIMEOUT_S,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Navigate to the login page and poll until the user has finished logging in
    by hand in the visible browser window. Pre-fills username/password if given, so
    the human only has to deal with the captcha."""
    await goto_login_form(page)
    await _prefill_credentials(page, username, password)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if await page.locator("#authorizedIDX").count() > 0:
            return
        await page.wait_for_timeout(1500)
    raise TimeoutError(
        "Timed out waiting for manual VTOP login. Run vtop_login again and finish "
        "entering your credentials/captcha in the browser window within the timeout."
    )


async def ensure_home(page: Page) -> None:
    """Cheap guard run before every data-fetching call. The shared page/context (see
    browser.py) persists across tool calls, so if the current DOM already has
    #authorizedIDX (the authenticated shell's marker, present on every VTOP page reached
    via its internal AJAX nav, not just /content) we're still on an authenticated page
    from a previous call and skip the full page.goto round trip that is_logged_in does.
    This can go stale if the server-side session expired without the DOM changing, but
    vtop_post() independently detects that case ("not authorized" in its AJAX response)
    and raises telling the caller to log in again -- so this is just a fast path to a
    nicer error message up front, not the actual security boundary."""
    try:
        if await page.locator("#authorizedIDX").count() > 0:
            return
    except Exception:
        pass
    if not await is_logged_in(page):
        raise NotLoggedInError("Not logged in to VTOP (or the session expired). Call vtop_login first.")


def _check_selector(name: str) -> None:
    if '"' in name or "'" in name:
        raise VtopError(f"Invalid field name/id: {name!r}")


async def vtop_post(page: Page, path: str, params: dict[str, str]) -> str:
    """Replay VTOP's own internal AJAX call (same endpoint, same CSRF/session cookie the
    page already has) and return the raw HTML fragment it responds with."""
    html = await page.evaluate(
        """
        async ({ path, params }) => {
            const csrf = document.querySelector('input[name="_csrf"]');
            const authorizedID = document.querySelector('#authorizedIDX');
            const body = new URLSearchParams({
                _csrf: csrf ? csrf.value : '',
                authorizedID: authorizedID ? authorizedID.value : '',
                ...params,
            });
            const res = await fetch(path, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: body.toString(),
            });
            return await res.text();
        }
        """,
        {"path": path, "params": params},
    )
    if "not authorized" in html.lower():
        raise VtopError("VTOP rejected the request as unauthorized (session likely expired). Call vtop_login again.")
    return html


async def get_semesters(page: Page) -> list[dict[str, str]]:
    await ensure_home(page)
    html = await vtop_post(page, "academics/common/StudentTimeTableChn", {"verifyMenu": "true"})
    return parsers.parse_semesters(html)


async def get_profile(page: Page) -> dict[str, Any]:
    await ensure_home(page)
    html = await vtop_post(page, "studentsRecord/StudentProfileAllView", {"verifyMenu": "true"})
    return parsers.parse_profile(html)


async def get_cgpa(page: Page) -> dict[str, float | None]:
    await ensure_home(page)
    html = await vtop_post(page, "examinations/examGradeView/StudentGradeHistory", {})
    return parsers.parse_cgpa(html)


async def get_courses(page: Page, semester_id: str) -> list[dict[str, Any]]:
    await ensure_home(page)
    html = await vtop_post(page, "processViewTimeTable", {"semesterSubId": semester_id})
    return parsers.parse_courses(html)


async def get_timetable_grid(page: Page, semester_id: str) -> list[list[str]]:
    await ensure_home(page)
    html = await vtop_post(page, "processViewTimeTable", {"semesterSubId": semester_id})
    return parsers.parse_timetable_grid(html)


async def get_attendance(page: Page, semester_id: str) -> list[dict[str, Any]]:
    await ensure_home(page)
    html = await vtop_post(page, "processViewStudentAttendance", {"semesterSubId": semester_id})
    return parsers.parse_attendance(html)


async def get_marks(page: Page, semester_id: str) -> list[dict[str, Any]]:
    await ensure_home(page)
    html = await vtop_post(page, "examinations/doStudentMarkView", {"semesterSubId": semester_id})
    return parsers.parse_marks(html)


async def get_grades(page: Page, semester_id: str) -> dict[str, Any]:
    await ensure_home(page)
    html = await vtop_post(page, "examinations/examGradeView/doStudentGradeView", {"semesterSubId": semester_id})
    return parsers.parse_grades(html)


async def get_exam_schedule(page: Page, semester_id: str) -> dict[str, Any]:
    await ensure_home(page)
    html = await vtop_post(page, "examinations/doSearchExamScheduleForStudent", {"semesterSubId": semester_id})
    return parsers.parse_exam_schedule(html)


# --- Generic navigation, for anything without a dedicated parser above
# (Academic Calendar, Leave/Outing application, or any other VTOP module). ---


async def list_menu(page: Page) -> list[dict[str, str | None]]:
    await ensure_home(page)
    links = await page.eval_on_selector_all(
        "a",
        """els => els.map(e => ({
            text: (e.innerText || '').trim(),
            href: e.getAttribute('href'),
        })).filter(l => l.text)""",
    )
    seen: set[tuple[str, str | None]] = set()
    out = []
    for link in links:
        key = (link["text"], link["href"])
        if key in seen:
            continue
        seen.add(key)
        out.append(link)
    return out


async def open_menu_item(page: Page, link_text: str, timeout_ms: int = 15_000) -> None:
    await ensure_home(page)
    locator = page.get_by_text(link_text, exact=False).first
    await locator.click(timeout=timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def _scrape_tables_from_soup(soup: BeautifulSoup) -> list[list[list[str]]]:
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


async def scrape_tables(page: Page) -> list[list[list[str]]]:
    html = await page.content()
    return _scrape_tables_from_soup(BeautifulSoup(html, "html.parser"))


async def get_form_fields(page: Page) -> list[dict[str, Any]]:
    return await page.eval_on_selector_all(
        "form",
        """
        forms => forms.map(form => ({
            action: form.getAttribute('action'),
            fields: Array.from(form.querySelectorAll('input, select, textarea')).map(el => {
                let label = '';
                if (el.id) {
                    const lab = form.querySelector(`label[for="${el.id}"]`);
                    if (lab) label = lab.innerText.trim();
                }
                if (!label && el.closest('label')) {
                    label = el.closest('label').innerText.trim();
                }
                const field = {
                    name: el.getAttribute('name'),
                    id: el.id || null,
                    type: el.tagName.toLowerCase() === 'select' ? 'select' : (el.getAttribute('type') || 'text'),
                    label: label || null,
                    value: el.value || null,
                };
                if (el.tagName.toLowerCase() === 'select') {
                    field.options = Array.from(el.options).map(o => ({ value: o.value, text: o.text }));
                }
                return field;
            }).filter(f => f.name),
        }))
        """,
    )


async def fill_form_fields(page: Page, values: dict[str, str]) -> None:
    await ensure_home(page)
    for key, value in values.items():
        _check_selector(key)
        locator = page.locator(f'[name="{key}"]')
        if await locator.count() == 0:
            locator = page.locator(f"#{key}")
        if await locator.count() == 0:
            raise VtopError(f"No form field found matching '{key}'.")

        el = locator.first
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            try:
                await el.select_option(label=str(value))
            except Exception:
                await el.select_option(value=str(value))
        else:
            input_type = (await el.get_attribute("type")) or "text"
            if input_type in ("checkbox", "radio"):
                if str(value).strip().lower() in ("true", "1", "yes", "on"):
                    await el.check()
                else:
                    await el.uncheck()
            else:
                await el.fill(str(value))


async def submit_form(page: Page, timeout_ms: int = 15_000) -> None:
    candidates = page.locator('button[type="submit"], input[type="submit"]')
    if await candidates.count() == 0:
        raise VtopError("Could not find a submit button on the current form.")
    await candidates.first.click(timeout=timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


async def get_academic_calendar(page: Page, semester_id: str | None = None) -> dict[str, Any]:
    """Fetch the Academic Calendar for a semester (current semester if semester_id isn't
    given) directly via VTOP's own AJAX endpoints -- same pattern as vtop_post's other
    callers -- rather than through the sidebar menu's UI (that menu lives behind a
    Bootstrap dropdown flyout that proved unreliable to drive via a scripted click).

    VTOP serves this as a day-by-day calendar, one month at a time: picking a semester
    returns a row of month buttons, and each one is a separate AJAX call returning that
    month's day grid (date -> working day / holiday / LID, etc.)."""
    await ensure_home(page)
    if semester_id is None:
        semesters = await get_semesters(page)
        if not semesters:
            raise VtopError("Could not determine the current semester for the academic calendar.")
        semester_id = semesters[0]["id"]

    months_html = await vtop_post(
        page,
        "getDateForSemesterPreview",
        {"semSubId": semester_id, "paramReturnId": "getDateForSemesterPreview"},
    )
    months_soup = BeautifulSoup(months_html, "html.parser")

    month_dates = []
    for a in months_soup.find_all("a", onclick=True):
        m = re.search(r"processViewCalendar\('([^']+)'\)", a["onclick"])
        if m:
            month_dates.append(m.group(1))

    months: dict[str, list[list[str]]] = {}
    for cal_date in month_dates:
        month_html = await vtop_post(
            page,
            "processViewCalendar",
            {"calDate": cal_date, "semSubId": semester_id, "classGroupId": "COMB"},
        )
        label = cal_date[3:]  # "01-NOV-2026" -> "NOV-2026"
        months[label] = _scrape_tables_from_soup(BeautifulSoup(month_html, "html.parser"))

    return {"semester_id": semester_id, "months": months}
