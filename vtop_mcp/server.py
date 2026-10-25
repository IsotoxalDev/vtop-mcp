"""MCP server exposing VIT VTOP (vtopcc.vit.ac.in) as tools over stdio."""

import shutil
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import client
from .browser import open_page, reset as reset_browser
from .config import PROFILE_DIR, VTOP_PASSWORD, VTOP_USERNAME
from .errors import VtopError

mcp = FastMCP(
    "vtop",
    instructions=(
        "Tools for VIT's VTOP student portal (vtopcc.vit.ac.in). Call vtop_login first "
        "(it opens a real, visible browser window for the human to type their username, "
        "password and captcha themselves) before using any other tool. Most data tools "
        "need a semester_id from vtop_get_semesters. For anything without a dedicated "
        "tool (e.g. leave/outing application), use vtop_list_menu to find the right menu "
        "link text, then vtop_open_menu to inspect it, then vtop_fill_and_submit to act on "
        "it -- that last tool previews the submission and only actually submits when "
        "called again with confirm=True, since it performs a real, hard-to-reverse action "
        "on the user's behalf."
    ),
)


@mcp.tool()
async def vtop_login() -> str:
    """Log in to VTOP. If username/password are configured (config.toml or
    VTOP_USERNAME/VTOP_PASSWORD env vars) and VTOP is showing its plain image captcha,
    this solves the captcha with local OCR and logs in fully headlessly -- no browser
    window appears. If VTOP serves a Google reCAPTCHA instead (which this deliberately
    does not try to automate -- see captcha.py), or OCR can't crack the image captcha
    after a few tries, or no credentials are configured, it falls back to opening a
    visible browser window (pre-filled with username/password if known) for a human to
    finish by hand. Either way, the resulting session is saved to a local browser
    profile and reused by every other vtop_* tool. Call this again whenever another
    tool reports the session has expired."""
    if VTOP_USERNAME and VTOP_PASSWORD:
        async with open_page(headless=True) as page:
            await client.goto_login_form(page)
            try:
                if await client.try_auto_login(page, VTOP_USERNAME, VTOP_PASSWORD):
                    return "Login successful (captcha solved automatically). Session saved; other vtop_* tools can now be used."
            except VtopError as e:
                return (
                    f"Automatic login failed: {e}. Fix the credentials in config.toml / "
                    "env vars, or call vtop_login again to try a manual, visible-browser login."
                )

    async with open_page(headless=False) as page:
        await client.wait_for_manual_login(page, username=VTOP_USERNAME, password=VTOP_PASSWORD)
    return "Login successful. The session is saved; other vtop_* tools can now be used."


@mcp.tool()
async def vtop_status() -> dict[str, bool]:
    """Check whether there is currently a valid, logged-in VTOP session."""
    async with open_page(headless=True) as page:
        return {"logged_in": await client.is_logged_in(page)}


@mcp.tool()
async def vtop_logout() -> str:
    """Delete the local saved VTOP browser session/profile, forcing a fresh vtop_login."""
    await reset_browser()
    shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    return "Local VTOP session cleared."


@mcp.tool()
async def vtop_get_semesters() -> list[dict[str, str]]:
    """List semesters (name and internal id). The id is what other tools expect as
    semester_id."""
    async with open_page() as page:
        return await client.get_semesters(page)


@mcp.tool()
async def vtop_get_profile() -> dict[str, Any]:
    """Get the logged-in student's profile (name and other personal/academic fields)."""
    async with open_page() as page:
        return await client.get_profile(page)


@mcp.tool()
async def vtop_get_cgpa() -> dict[str, float | None]:
    """Get overall CGPA and total earned credits across all semesters."""
    async with open_page() as page:
        return await client.get_cgpa(page)


@mcp.tool()
async def vtop_get_courses(semester_id: str) -> list[dict[str, Any]]:
    """List registered courses for a semester: code, title, type (theory/lab/project),
    credits, slot codes, venue and faculty. Get semester_id from vtop_get_semesters."""
    async with open_page() as page:
        return await client.get_courses(page, semester_id)


@mcp.tool()
async def vtop_get_timetable_grid(semester_id: str) -> list[list[str]]:
    """Get the weekly timetable as raw grid rows (cell text left to right). Cross-reference
    slot codes (e.g. "A1") against vtop_get_courses' "slots" field to see which course each
    grid cell belongs to."""
    async with open_page() as page:
        return await client.get_timetable_grid(page, semester_id)


@mcp.tool()
async def vtop_get_attendance(semester_id: str) -> list[dict[str, Any]]:
    """Get attendance per course for a semester: classes attended, total held, percentage."""
    async with open_page() as page:
        return await client.get_attendance(page, semester_id)


@mcp.tool()
async def vtop_get_marks(semester_id: str) -> list[dict[str, Any]]:
    """Get the CAT/assignment/FAT marks breakdown per course for a semester."""
    async with open_page() as page:
        return await client.get_marks(page, semester_id)


@mcp.tool()
async def vtop_get_grades(semester_id: str) -> dict[str, Any]:
    """Get final letter grades per course and the semester GPA, for a completed semester."""
    async with open_page() as page:
        return await client.get_grades(page, semester_id)


@mcp.tool()
async def vtop_get_exam_schedule(semester_id: str) -> dict[str, Any]:
    """Get the exam schedule (CAT1/CAT2/FAT etc.) for a semester: date, timing, venue,
    seat location/number per course, grouped by exam name."""
    async with open_page() as page:
        return await client.get_exam_schedule(page, semester_id)


@mcp.tool()
async def vtop_get_academic_calendar() -> dict[str, Any]:
    """Best-effort fetch of the Academic Calendar: a PDF link if VTOP serves it as a
    download, plus any tables found on the page."""
    async with open_page() as page:
        return await client.get_academic_calendar(page)


@mcp.tool()
async def vtop_list_menu() -> list[dict[str, str | None]]:
    """List every clickable menu link's visible text on the logged-in VTOP home page.
    Use this to find the exact text for a feature (e.g. a leave/outing application)
    before calling vtop_open_menu or vtop_fill_and_submit."""
    async with open_page() as page:
        return await client.list_menu(page)


@mcp.tool()
async def vtop_open_menu(link_text: str) -> dict[str, Any]:
    """Click the first VTOP menu link whose visible text contains link_text
    (case-insensitive), then report any tables and form fields found on the page that
    opens. Use vtop_list_menu first to find the right link_text."""
    async with open_page() as page:
        await client.open_menu_item(page, link_text)
        return {
            "tables": await client.scrape_tables(page),
            "forms": await client.get_form_fields(page),
        }


@mcp.tool()
async def vtop_fill_and_submit(
    link_text: str, field_values: dict[str, str], confirm: bool = False
) -> dict[str, Any]:
    """Open a VTOP menu item (by link_text, as in vtop_open_menu) and fill its form using
    field_values, keyed by each field's "name" (or "id") as reported by vtop_open_menu's
    "forms". This performs a REAL, often hard-to-reverse action on the user's VTOP account
    (e.g. submitting a leave/outing application) -- so by default (confirm=False) it only
    fills the form and returns a preview without submitting. Review the preview with the
    user, then call again with confirm=True to actually submit. Runs in a visible browser
    window so the human can also watch and intervene."""
    async with open_page(headless=False) as page:
        await client.open_menu_item(page, link_text)
        await client.fill_form_fields(page, field_values)
        preview = await client.get_form_fields(page)

        if not confirm:
            return {
                "submitted": False,
                "forms_after_fill": preview,
                "note": "Not submitted. Review the filled-in values, then call again with confirm=True to submit.",
            }

        await client.submit_form(page)
        return {
            "submitted": True,
            "forms_after_fill": preview,
            "resulting_tables": await client.scrape_tables(page),
        }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
