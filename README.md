# vtop-mcp

An MCP server for VIT Chennai's VTOP portal (`vtopcc.vit.ac.in`). It drives a real
Chromium browser (Playwright) against the live site instead of talking to private
APIs, so it works the same way a human in a browser would.

Column/endpoint logic for the "solid" tools below is ported from
[therealsujitk/android-vtop-chennai](https://github.com/therealsujitk/android-vtop-chennai),
an open-source Android client that scrapes the same portal from a WebView.

## Logging in

VTOP's login form has a captcha: either a plain distorted-text image, or a Google
reCAPTCHA.

- **Plain image captcha + credentials configured** (see Setup below): `vtop_login`
  solves it with local OCR (`pytesseract`/`tesseract`, retried a few times against
  fresh captcha images) and logs in fully headlessly. No browser window appears.
- **Google reCAPTCHA, or OCR can't crack it, or no credentials configured**:
  `vtop_login` falls back to opening a real, visible Chromium window (pre-filled with
  your username/password if known) for you to finish by hand. reCAPTCHA is
  specifically designed to resist automated solving, and defeating it generally means
  paying a third-party captcha-solving service — that's a line this project doesn't
  cross, so that case always needs a human.

Either way, the resulting session is saved to a local browser profile
(`~/.local/share/vtop-mcp/browser-profile`) and every other tool reuses it headlessly
until it expires.

## Tools

Solid (ported from the reference app's reverse-engineered endpoints):

- `vtop_login`, `vtop_logout`, `vtop_status`
- `vtop_get_semesters` — semester name -> id, needed by the tools below
- `vtop_get_profile`, `vtop_get_cgpa`
- `vtop_get_courses(semester_id)`
- `vtop_get_timetable_grid(semester_id)` — raw grid; cross-reference slot codes against `vtop_get_courses`
- `vtop_get_attendance(semester_id)`
- `vtop_get_marks(semester_id)`
- `vtop_get_grades(semester_id)`
- `vtop_get_exam_schedule(semester_id)`

Best-effort / generic (VTOP's academic calendar and leave/outing application aren't
implemented by the reference app, so there's no reverse-engineered endpoint to port —
these drive the real page generically instead):

- `vtop_get_academic_calendar` — finds a PDF link and/or tables on the Academic Calendar page
- `vtop_list_menu` — lists every menu link's visible text, to find e.g. the leave/outing page
- `vtop_open_menu(link_text)` — opens a menu item, reports its tables and form fields
- `vtop_fill_and_submit(link_text, field_values, confirm)` — fills a form; only submits
  when called again with `confirm=True` (it previews first, since this performs a real
  action on your VTOP account)

### Applying for leave/outing

1. `vtop_list_menu` to find the exact link text (e.g. "Hostel" submenu, or "Outing/Leave").
2. `vtop_open_menu("...")` to see the form's fields (names/labels/options).
3. `vtop_fill_and_submit("...", {"fieldName": "value", ...})` with `confirm=False` (default) to preview.
4. Once the preview looks right, call it again with `confirm=True` to actually submit.

## Setup

1. Copy `config.example.toml` to `config.toml` and fill in your VTOP username/password
   (this file is gitignored). This enables headless auto-login (OCR captcha solving);
   without it, `vtop_login` always opens a visible browser for you to log in by hand.

   ```toml
   username = "21BCE1234"
   password = "your-vtop-password"
   ```

2. Enter the dev shell (requires Nix with flakes):

   ```sh
   nix develop
   ```

   This provides Python with `mcp`, `playwright`, `beautifulsoup4`, `pytesseract` and
   `pillow`, plus the `tesseract` OCR engine. For the browser, it reuses Chromium
   already on your `PATH` (see `VTOP_MCP_CHROMIUM_PATH` below) instead of having
   Playwright fetch its own pinned copy.

Run directly:

```sh
python -m vtop_mcp
```

Or via the flake app:

```sh
nix run .
```

### Registering with an MCP client (e.g. Claude Code)

```sh
claude mcp add vtop -- nix run /path/to/mcp/folder
```

or, if you'd rather point at an already-entered dev shell:

```sh
claude mcp add vtop -- python -m vtop_mcp
```

## Config

Every setting can go in `config.toml` (gitignored, copy from `config.example.toml`) or
as an env var of the same name in `VTOP_<UPPERCASE>` form; an env var wins if both are
set.

- `username` / `VTOP_USERNAME`, `password` / `VTOP_PASSWORD` — your VTOP login.
  Without these, `vtop_login` always uses the manual, visible-browser flow.
- `base_url` / `VTOP_BASE_URL` — defaults to `https://vtopcc.vit.ac.in/vtop`. Override
  for other VIT campuses (e.g. `https://vtop.vit.ac.in/vtop` for Vellore) — the generic
  tools should still work there; the "solid" tools are Chennai-specific and may need
  endpoint-name tweaks.
- `login_timeout_s` / `VTOP_LOGIN_TIMEOUT_S` — how long the manual login flow waits
  for a human to finish (default 300s).
- `VTOP_MCP_CHROMIUM_PATH` — path to a Chromium/Chrome binary to reuse instead of
  Playwright's own pinned copy. The dev shell auto-detects one already on `PATH`
  (`chromium`, `chromium-browser`, `google-chrome(-stable)`) and exports this for you,
  so most NixOS setups with Chromium already installed need no extra browser download.
  If none is found and this is left unset, Playwright will look for its own
  bundled browser (add `pkgs.playwright-driver.browsers` back to `flake.nix`, with
  `PLAYWRIGHT_BROWSERS_PATH` set to it, if you want that instead).

## Notes / limitations

- Only one tool call should run at a time: the browser profile is locked by Chromium
  while in use.
- Sessions expire like any normal VTOP session; when a tool reports you're logged out,
  just run `vtop_login` again.
- `vtop_get_timetable_grid` intentionally returns the raw grid rather than a parsed
  per-day structure — the source app's own per-cell parsing logic for this specific
  table had internal inconsistencies, so a flat, inspectable grid was safer to port
  than to guess at a "fixed" version of it.
