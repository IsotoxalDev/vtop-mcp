"""
Pure HTML parsers for the HTML fragments VTOP's internal AJAX endpoints return.

The parsing logic (which column holds what, how rows are grouped) is ported from
https://github.com/therealsujitk/android-vtop-chennai, which scrapes the same
vtopcc.vit.ac.in endpoints from inside an Android WebView. That app's column-index
math is reused here verbatim since it was reverse-engineered against the real portal.
"""

import re
from typing import Any

from bs4 import BeautifulSoup

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def to_float(text: str | None, default: float | None = 0.0) -> float | None:
    if not text:
        return default
    m = _NUM_RE.search(text)
    if not m:
        return default
    try:
        return float(m.group())
    except ValueError:
        return default


def to_int(text: str | None, default: int | None = 0) -> int | None:
    val = to_float(text, None)
    return default if val is None else int(val)


def parse_semesters(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find(id="semesterSubId")
    if not select:
        return []
    out = []
    for option in select.find_all("option"):
        value = option.get("value")
        if not value:
            continue
        out.append({"name": option.get_text(strip=True), "id": value})
    return out


def parse_profile(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    cells = soup.find_all("td")

    name = None
    for i, cell in enumerate(cells):
        key = cell.get_text(strip=True).lower()
        if "student" in key and "name" in key and i + 1 < len(cells):
            name = cells[i + 1].get_text(strip=True)
            break

    fields: dict[str, str] = {}
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            tds = row.find_all("td")
            if len(tds) == 2:
                label = tds[0].get_text(strip=True)
                value = tds[1].get_text(strip=True)
                if label and value and label.lower() not in fields:
                    fields[label] = value

    return {"name": name, "fields": fields}


def parse_cgpa(html: str) -> dict[str, float | None]:
    soup = BeautifulSoup(html, "html.parser")
    for table in reversed(soup.find_all("table")):
        rows = table.find_all("tr")
        if not rows:
            continue
        headings = rows[0].find_all("td")
        if not headings or "credits" not in headings[0].get_text(strip=True).lower():
            continue

        credits_index = cgpa_index = None
        for j, h in enumerate(headings):
            text = h.get_text(strip=True).lower()
            if "earned" in text:
                credits_index = j + len(headings)
            elif "cgpa" in text:
                cgpa_index = j + len(headings)

        cells = table.find_all("td")
        if credits_index is None or cgpa_index is None:
            continue
        if credits_index >= len(cells) or cgpa_index >= len(cells):
            continue

        return {
            "cgpa": to_float(cells[cgpa_index].get_text(strip=True)),
            "total_credits": to_float(cells[credits_index].get_text(strip=True)),
        }
    return {"cgpa": None, "total_credits": None}


def parse_courses(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="studentDetailsList")
    if not container:
        return []
    table = container.find("table")
    if not table:
        return []

    headings = table.find_all("th")
    course_i = credits_i = slot_venue_i = faculty_i = None
    for i, h in enumerate(headings):
        text = h.get_text(strip=True).lower()
        if text == "course":
            course_i = i
        elif text == "l t p j c":
            credits_i = i
        elif "slot" in text:
            slot_venue_i = i
        elif "faculty" in text:
            faculty_i = i

    cells = table.find_all("td")
    if not cells or None in (course_i, credits_i, slot_venue_i, faculty_i):
        return []

    heading_offset = -1 if "invoice" in headings[0].get_text(strip=True).lower() else 0
    cell_offset = 1 if "invoice" in cells[0].get_text(strip=True).lower() else 0
    offset = heading_offset + cell_offset
    stride = len(headings) + heading_offset

    courses = []
    ci, cr, sv, fa = course_i, credits_i, slot_venue_i, faculty_i
    while (
        ci + offset < len(cells)
        and cr + offset < len(cells)
        and sv + offset < len(cells)
        and fa + offset < len(cells)
    ):
        raw_course = re.sub(r"\s+", " ", cells[ci + offset].get_text(" ")).strip()
        raw_course_type = raw_course.split("(")[-1].lower()
        raw_credits = re.sub(r"\s+", " ", cells[cr + offset].get_text(" ")).strip().split(" ")
        raw_slot_venue = re.sub(r"\s+", " ", cells[sv + offset].get_text(" ")).strip().split("-")
        raw_faculty = re.sub(r"\s+", " ", cells[fa + offset].get_text(" ")).strip().split("-")

        parts = raw_course.split("-")
        course = {
            "code": parts[0].strip(),
            "title": "-".join(parts[1:]).split("(")[0].strip(),
            "type": (
                "lab" if "lab" in raw_course_type else "project" if "project" in raw_course_type else "theory"
            ),
            "credits": to_int(raw_credits[-1] if raw_credits else None),
            "slots": [s.strip() for s in raw_slot_venue[0].strip().split("+")] if raw_slot_venue else [],
            "venue": " - ".join(p.strip() for p in raw_slot_venue[1:]).strip(),
            "faculty": raw_faculty[0].strip() if raw_faculty else "",
        }
        courses.append(course)

        ci += stride
        cr += stride
        sv += stride
        fa += stride

    return courses


def parse_timetable_grid(html: str) -> list[list[str]]:
    """Raw weekly timetable grid as rows of cell text. Pair with parse_courses to map
    slot codes (e.g. "A1") found in the grid to course names via each course's "slots"."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(id="timeTableStyle")
    if not table:
        return []
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    return rows


def parse_attendance(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(id="getStudentDetails")
    if not table:
        return []
    headings = table.find_all("th")
    if not headings:
        return []

    idx: dict[str, int] = {}
    for i, h in enumerate(headings):
        text = h.get_text(strip=True).lower()
        if "course" in text and "type" in text:
            idx["course_type"] = i
        elif "slot" in text:
            idx["slot"] = i
        elif "attended" in text:
            idx["attended"] = i
        elif "total" in text:
            idx["total"] = i
        elif "percentage" in text:
            idx["percentage"] = i

    required = ("course_type", "slot", "attended", "total", "percentage")
    if not all(k in idx for k in required):
        return []

    cells = table.find_all("td")
    stride = len(headings)
    cur = dict(idx)
    out = []
    while all(cur[k] < len(cells) for k in required):
        out.append(
            {
                "course_type": cells[cur["course_type"]].get_text(strip=True),
                "slot": cells[cur["slot"]].get_text(strip=True).split("+")[0].strip(),
                "attended": to_int(cells[cur["attended"]].get_text(strip=True)),
                "total": to_int(cells[cur["total"]].get_text(strip=True)),
                "percentage": to_int(cells[cur["percentage"]].get_text(strip=True)),
            }
        )
        for k in required:
            cur[k] += stride
    return out


def parse_marks(html: str) -> list[dict[str, Any]]:
    if "no data found" in html.lower():
        return []
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="fixedTableContainer")
    if not container:
        return []

    rows = container.find_all("tr")
    if not rows:
        return []
    headings = rows[0].find_all("td")
    course_type_i = slot_i = None
    for i, h in enumerate(headings):
        text = h.get_text(strip=True).lower()
        if "course" in text and "type" in text:
            course_type_i = i
        elif "slot" in text:
            slot_i = i
    if course_type_i is None or slot_i is None:
        return []

    marks: list[dict[str, Any]] = []
    i = 1
    while i < len(rows):
        row_tds = rows[i].find_all("td")
        if course_type_i >= len(row_tds) or slot_i >= len(row_tds):
            break

        raw_course_type = row_tds[course_type_i].get_text(strip=True).lower()
        course_type = "lab" if "lab" in raw_course_type else "project" if "project" in raw_course_type else "theory"
        slot = row_tds[slot_i].get_text(strip=True).split("+")[0].strip()

        i += 1
        if i >= len(rows):
            break
        inner_table = rows[i].find("table")
        if inner_table is None:
            i += 1
            continue
        inner_rows = inner_table.find_all("tr")
        if inner_rows:
            inner_headings = inner_rows[0].find_all("td")
            n = len(inner_headings)
            fidx: dict[str, int] = {}
            for j, h in enumerate(inner_headings):
                text = h.get_text(strip=True).lower()
                if "title" in text:
                    fidx["title"] = j + n
                elif "max" in text:
                    fidx["max_score"] = j + n
                elif "%" in text:
                    fidx["max_weightage"] = j + n
                elif "status" in text:
                    fidx["status"] = j + n
                elif "scored" in text:
                    fidx["score"] = j + n
                elif "weightage" in text and "mark" in text:
                    fidx["weightage"] = j + n
                elif "average" in text:
                    fidx["average"] = j + n

            required = ("title", "score", "max_score", "weightage", "max_weightage", "average", "status")
            inner_cells = inner_table.find_all("td")
            if all(k in fidx for k in required):
                cur = dict(fidx)
                while all(cur[k] < len(inner_cells) for k in required):
                    marks.append(
                        {
                            "slot": slot,
                            "course_type": course_type,
                            "title": inner_cells[cur["title"]].get_text(strip=True),
                            "score": to_float(inner_cells[cur["score"]].get_text(strip=True)),
                            "max_score": to_float(inner_cells[cur["max_score"]].get_text(strip=True), None),
                            "weightage": to_float(inner_cells[cur["weightage"]].get_text(strip=True)),
                            "max_weightage": to_float(inner_cells[cur["max_weightage"]].get_text(strip=True), None),
                            "average": to_float(inner_cells[cur["average"]].get_text(strip=True), None),
                            "status": inner_cells[cur["status"]].get_text(strip=True),
                        }
                    )
                    for k in required:
                        cur[k] += n
        i += len(inner_rows)
    return marks


def parse_grades(html: str) -> dict[str, Any]:
    if "no records" in html.lower():
        return {"grades": [], "gpa": None}
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return {"grades": [], "gpa": None}

    headings = table.find_all("th")
    course_code_i = grade_i = credits_i = None
    credits_span = 1
    for i, h in enumerate(headings):
        text = h.get_text(strip=True).lower()
        if "code" in text:
            course_code_i = i
        elif "credits" in text:
            credits_i = i
            try:
                credits_span = int(h.get("colspan", 1))
            except (TypeError, ValueError):
                credits_span = 1
        elif "grade" in text:
            grade_i = i

    if course_code_i is None or grade_i is None or credits_i is None:
        return {"grades": [], "gpa": None}

    if course_code_i > credits_i:
        course_code_i += credits_span - 1
    if grade_i > credits_i:
        grade_i += credits_span - 1

    cells = table.find_all("td")
    stride = len(headings) - 1
    grades = []
    ci, gi = course_code_i, grade_i
    while ci < len(cells) and gi < len(cells):
        grades.append({"course_code": cells[ci].get_text(strip=True), "grade": cells[gi].get_text(strip=True)})
        ci += stride
        gi += stride

    gpa = None
    if cells:
        last_text = cells[-1].get_text(strip=True)
        if ":" in last_text:
            gpa = last_text.split(":", 1)[1].strip()

    return {"grades": grades, "gpa": gpa}


def parse_exam_schedule(html: str) -> dict[str, list[dict[str, Any]]]:
    if "not found" in html.lower():
        return {}
    soup = BeautifulSoup(html, "html.parser")
    all_trs = soup.find_all("tr")
    if not all_trs:
        return {}

    columns = all_trs[0].find_all("td")
    n_cols = len(columns)
    if n_cols == 0:
        return {}

    idx: dict[str, int] = {}
    for i, c in enumerate(columns):
        text = c.get_text(strip=True).lower()
        if "slot" in text:
            idx["slot"] = i
        elif "date" in text:
            idx["date"] = i
        elif "exam" in text and "time" in text:
            idx["timing"] = i
        elif "venue" in text:
            idx["venue"] = i
        elif "location" in text:
            idx["location"] = i
        elif "seat" in text and "no." in text:
            idx["number"] = i

    cells = soup.find_all("td")
    response: dict[str, list[dict[str, Any]]] = {}
    exam_title = ""
    exam: dict[str, Any] = {}

    for i in range(n_cols, len(cells)):
        cell = cells[i]
        try:
            colspan = int(cell.get("colspan", 1))
        except (TypeError, ValueError):
            colspan = 1

        if colspan > 1:
            exam_title = cell.get_text(strip=True)
            response[exam_title] = []
            continue

        index = (i - len(response)) % n_cols
        text = cell.get_text(strip=True)

        if index == idx.get("slot"):
            exam["slot"] = text.split("+")[0]
        elif index == idx.get("date"):
            date = text.upper()
            exam["date"] = date or None
        elif index == idx.get("timing"):
            parts = text.split("-")
            if len(parts) == 2:
                exam["start_time"] = parts[0].strip()
                exam["end_time"] = parts[1].strip()
            else:
                exam["start_time"] = None
                exam["end_time"] = None
        elif index == idx.get("venue"):
            exam["venue"] = None if text.replace("-", "") == "" else text
        elif index == idx.get("location"):
            exam["seat_location"] = None if text.replace("-", "") == "" else text
        elif index == idx.get("number"):
            stripped = text.replace("-", "")
            exam["seat_number"] = None if stripped == "" else to_int(stripped, None)

        if len(exam) == 7:
            response.setdefault(exam_title, []).append(exam)
            exam = {}

    return response
