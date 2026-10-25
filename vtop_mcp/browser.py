import asyncio
import json
from contextlib import asynccontextmanager

from playwright.async_api import Page, async_playwright

from .config import CHROMIUM_PATH, NAV_TIMEOUT_MS, PROFILE_DIR

# A single Chromium persistent context, kept alive for the life of the MCP server process
# and reused by every tool call, rather than relaunched per call. Two reasons:
#  1. Chromium only restores session-only cookies (no Max-Age/Expires -- which is how
#     VTOP's auth cookie is set) on a NEXT launch if it thinks the previous run crashed.
#     A clean context.close() makes it drop them, so a fresh launch per call meant the
#     login never actually survived past the call that created it.
#  2. Launching Chromium fresh takes several seconds; reusing one avoids that per call.
_lock = asyncio.Lock()
_state: dict = {}


def _mark_profile_as_crash_recovery() -> None:
    """Rewrite the profile's exit_type to "Crashed" after we close it.

    This is what makes Chromium restore session-only cookies (VTOP's auth cookie has no
    Max-Age/Expires) on the *next* launch -- on a real clean exit it drops them, treating
    that as the user intentionally ending their session. We always want VTOP's login to
    survive a server restart/reconnect, so every close is made to look like a crash.
    """
    prefs_path = PROFILE_DIR / "Default" / "Preferences"
    if not prefs_path.is_file():
        return
    try:
        data = json.loads(prefs_path.read_text())
        data.setdefault("profile", {})["exit_type"] = "Crashed"
        data["profile"]["exited_cleanly"] = False
        prefs_path.write_text(json.dumps(data))
    except Exception:
        pass


async def _close_state() -> None:
    context = _state.pop("context", None)
    pw = _state.pop("playwright", None)
    _state.pop("page", None)
    _state.pop("headless", None)
    if context is not None:
        await context.close()
        _mark_profile_as_crash_recovery()
    if pw is not None:
        await pw.stop()


async def _ensure_page(headless: bool) -> Page:
    if _state.get("context") is not None and _state.get("headless") == headless:
        return _state["page"]

    # Switching between headless and headed (or recovering from a broken context) needs
    # a fresh launch -- Chromium can't change headless mode on a running context.
    await _close_state()

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        executable_path=CHROMIUM_PATH,
        # Chromium's sandbox (user namespaces + seccomp) is extremely slow to set up
        # under this host's container/namespace restrictions -- it roughly doubles
        # page-load latency and was causing spurious navigation timeouts. Disabling
        # it is safe here since this only ever browses VTOP's own site.
        args=["--no-sandbox"],
    )
    page: Page = context.pages[0] if context.pages else await context.new_page()
    page.set_default_timeout(NAV_TIMEOUT_MS)
    _state.update(playwright=pw, context=context, page=page, headless=headless)
    return page


@asynccontextmanager
async def open_page(headless: bool = True):
    """Get the shared VTOP browser page, launching it on first use and reusing it (and its
    logged-in session) on every call after that.

    Serialized with a lock: only one tool call drives the shared page at a time.
    """
    async with _lock:
        page = await _ensure_page(headless)
        try:
            yield page
        except Exception:
            # Leave a possibly-broken page/context around to debug from is worse than just
            # dropping it -- the next call gets a fresh one.
            await _close_state()
            raise


async def reset() -> None:
    """Close the shared browser/context, e.g. after clearing the on-disk profile."""
    async with _lock:
        await _close_state()
