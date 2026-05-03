#!/usr/bin/env python3
"""
Study Buddy Task Generator
--------------------------
Reads a school iCal feed + Bruins NHL schedule, generates a week of study
tasks and pushes them to a TickTick project via JSON output.

Usage:
    python3 study_buddy.py              # generates for next 7 days from tomorrow
    python3 study_buddy.py 2026-04-13   # generates starting from a specific date

Output: JSON array of TickTick task dicts (to stdout)
Logs:   Progress messages (to stderr)
"""

import json, sys, re, urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


# ─── Configuration ────────────────────────────────────────────────────────────
#
# Personal values (iCal URL, TickTick project ID, subjects, teachers) are loaded
# from config_local.py, which is gitignored. Safe placeholder defaults are used
# if that file is not present (e.g., in a fresh clone).
#
# To configure for your student: copy config_local.py.example to config_local.py
# and fill in your values. See docs/setup-guide.md for instructions.

try:
    from config_local import (
        ICAL_URL, TIMEZONE, TICKTICK_PROJECT_ID,
        SUBJECT_TAGS, SUBJECT_SHORT, TEACHERS,
        NO_SCHOOL_KEYWORDS, TIMES, SKIP_PATTERNS,
    )
except ImportError:
    ICAL_URL              = "https://yourschool.example.com/feed/iCal.aspx?z=YOUR_TOKEN_HERE"
    TIMEZONE              = "America/New_York"
    TICKTICK_PROJECT_ID   = "YOUR_TICKTICK_PROJECT_ID"
    SUBJECT_TAGS          = {"Course Name": "TagName"}
    SUBJECT_SHORT         = {"Course Name": "Short"}
    TEACHERS              = {"Course Name": "Teacher Name"}
    NO_SCHOOL_KEYWORDS    = ["No School", "Holiday", "Winter Break", "Spring Break",
                             "Thanksgiving", "Summer", "Offices Closed"]
    TIMES                 = {
        "school_light": "18:00", "school_heavy": "19:30", "school_review": "21:00",
        "friday_light": "15:00", "friday_heavy": "16:30",
        "sunday_light": "18:00", "sunday_heavy": "19:30", "sunday_review": "21:00",
        "game_light":   "20:00", "weekly_debrief": "15:30",
    }
    SKIP_PATTERNS         = ["Block)", "Lunch", "Advisory", "Assembly",
                             "Community Service", "Holiday"]

CONFIG = {
    "ical_url":            ICAL_URL,
    "timezone":            TIMEZONE,
    "ticktick_project_id": TICKTICK_PROJECT_ID,
    "subject_tags":        SUBJECT_TAGS,   # TickTick tag names (must match exactly)
    "subject_short":       SUBJECT_SHORT,  # Short display names for task titles
    "teachers":            TEACHERS,       # Teacher names (for office hours tasks)
    "no_school_keywords":  NO_SCHOOL_KEYWORDS,
    "times":               TIMES,
}


# ─── Time-slot resolver ───────────────────────────────────────────────────────

def resolve_slots(task_date, lacrosse_practices, lacrosse_games, bruins_games, no_school_dates):
    """
    Returns (light_slot, heavy_slot, review_slot, bruins_note) for a date.
    Any slot may be None if tasks shouldn't be scheduled in that window.
    """
    T = CONFIG["times"]
    wday = task_date.weekday()

    if wday == 5:                          # Saturday — no tasks
        return None, None, None, None
    if task_date in no_school_dates:       # School holiday — no tasks
        return None, None, None, None

    lacrosse_end  = lacrosse_practices.get(task_date)
    is_lax_game   = task_date in lacrosse_games
    bruins_time   = bruins_games.get(task_date)

    bruins_note = None
    if bruins_time:
        h = int(bruins_time[:2])
        ampm = "PM" if h >= 12 else "AM"
        h12 = h if h <= 12 else h - 12
        bruins_note = (
            f"🏒 Bruins game tonight at {h12}:{bruins_time[3:]} {ampm} — "
            f"tasks shifted early so you can catch the puck drop!"
        )

    # ── Base slots by day ──
    if wday == 4:       # Friday
        light, heavy, review = T["friday_light"], T["friday_heavy"], None
    elif wday == 6:     # Sunday
        light, heavy, review = T["sunday_light"], T["sunday_heavy"], T["sunday_review"]
    elif is_lax_game:   # Lacrosse game evening
        light, heavy, review = T["game_light"], None, None
    elif lacrosse_end:  # Lacrosse practice evening
        # Schedule light tasks 1 h after practice, floor 19:00; no heavy tasks
        end_h, end_m = int(lacrosse_end[:2]), int(lacrosse_end[3:])
        start_min = max(end_h * 60 + end_m + 60, 19 * 60)
        light  = f"{start_min // 60:02d}:{start_min % 60:02d}"
        heavy  = None
        review = "21:00" if start_min <= 20 * 60 else None
    else:               # Regular school day
        light, heavy, review = T["school_light"], T["school_heavy"], T["school_review"]

    # ── Shift for Bruins game (≤ 7 PM start) ──
    if bruins_time:
        b_hour = int(bruins_time[:2])
        if b_hour <= 19:
            def shift(slot, delta=-90):
                if not slot: return None
                h, m = int(slot[:2]), int(slot[3:])
                total = h * 60 + m + delta
                return f"{total // 60:02d}:{total % 60:02d}"
            light  = shift(light)
            heavy  = shift(heavy)
            # Keep review at its usual time (post-game habit)

    return light, heavy, review, bruins_note


# ─── iCal fetcher / parser ────────────────────────────────────────────────────

def fetch_ical():
    req = urllib.request.Request(
        CONFIG["ical_url"], headers={"User-Agent": "StudyBuddy/1.0"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def clean(s):
    s = re.sub(r"\r?\n[ \t]", "", s)           # unfold lines
    s = re.sub(r"&#160;", " ", s)
    s = re.sub(r"&#\d+;", "", s)
    s = re.sub(r"&amp;", "&", s)
    return s.strip()


def parse_ical(data):
    events = []
    for block in re.split(r"BEGIN:VEVENT", data)[1:]:
        sm = re.search(r"SUMMARY:(.+?)(?:\r?\n[A-Z])", block, re.DOTALL)
        ds = re.search(r"DTSTART(?:;[^:]+)?:(\d{8}(?:T\d{6}Z?)?)", block)
        de = re.search(r"DTEND(?:;[^:]+)?:(\d{8}(?:T\d{6}Z?)?)", block)
        dm = re.search(r"DESCRIPTION:(.+?)(?:\r?\n[A-Z]|END:VEVENT)", block, re.DOTALL)
        tz_m = re.search(r"DTSTART;TZID=([^:]+):(\d{8}T\d{6})", block)

        if not sm or not ds:
            continue

        summary     = clean(sm.group(1))
        dtstart_raw = ds.group(1)
        dtend_raw   = de.group(1) if de else dtstart_raw
        description = clean(dm.group(1)) if dm else ""
        has_time    = "T" in dtstart_raw

        try:
            if has_time:
                dtstart = datetime.strptime(dtstart_raw[:15], "%Y%m%dT%H%M%S")
                dtend   = datetime.strptime(dtend_raw[:15],   "%Y%m%dT%H%M%S") \
                          if "T" in dtend_raw else dtstart
                # Apply TZID offset for local-time events
                if tz_m:
                    tz = ZoneInfo(tz_m.group(1))
                    dtstart = dtstart.replace(tzinfo=tz)
                    dtend   = dtend.replace(tzinfo=tz)
            else:
                dtstart = datetime.strptime(dtstart_raw[:8], "%Y%m%d")
                dtend   = datetime.strptime(dtend_raw[:8],   "%Y%m%d")
        except ValueError:
            continue

        events.append({
            "summary":     summary,
            "dtstart":     dtstart,
            "dtend":       dtend,
            "description": description,
            "has_time":    has_time,
        })
    return events


# ─── NHL Bruins schedule ──────────────────────────────────────────────────────

def fetch_bruins_games():
    """Returns dict of {date: 'HH:MM'} in ET for remaining Bruins games."""
    games = {}
    try:
        url = "https://api-web.nhle.com/v1/club-schedule-season/BOS/20252026"
        req = urllib.request.Request(url, headers={"User-Agent": "StudyBuddy/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for g in data.get("games", []):
            gdate_str  = g.get("gameDate", "")
            start_utc  = g.get("startTimeUTC", "")
            if gdate_str and start_utc:
                gdate    = datetime.strptime(gdate_str, "%Y-%m-%d").date()
                hour_et  = int(start_utc[11:13]) - 4   # EDT = UTC-4
                min_et   = int(start_utc[14:16])
                games[gdate] = f"{hour_et:02d}:{min_et:02d}"
        print(f"  Bruins: {len(games)} games fetched", file=sys.stderr)
    except Exception as e:
        print(f"  Bruins fetch failed: {e}", file=sys.stderr)
    return games


# ─── Course helpers ───────────────────────────────────────────────────────────

def get_course_and_assignment(summary):
    m = re.match(r"^(.+?)\s*-\s*[A-Z]\s*-\s*\w+\s*:\s*(.+)$", summary)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m2 = re.match(r"^(.+?):\s*(.+)$", summary)
    if m2:
        return m2.group(1).strip(), m2.group(2).strip()
    return None, None


def get_tag(course):
    for key, tag in CONFIG["subject_tags"].items():
        if key.lower() in course.lower():
            return tag
    return None


def get_short(course):
    for full, short in CONFIG["subject_short"].items():
        if full.lower() in course.lower() or course.lower() in full.lower():
            return short
    return " ".join(course.split()[:2])


def get_teacher(course):
    for key, name in CONFIG["teachers"].items():
        if key.lower() in course.lower():
            return name
    return "your teacher"


# ─── Assignment classifier ────────────────────────────────────────────────────

def classify(text, span_days):
    # Year-long or semester-long tracking events are not tasks
    if span_days > 90:
        return "skip"
    t = text.lower()
    if any(w in t for w in ["quiz", "quiz -", "quiz:"]):
        return "quiz"
    if re.search(r'\btest\b', t) or any(w in t for w in ["exam", "assessment", "midterm"]):
        return "test"
    if any(w in t for w in ["essay", "paper --", "paper:", "dbq", "written response"]):
        if any(s in t for s in ["collect evidence", "free write", "thesis", "topic sentence",
                                 "intro", "body paragraph", "draft", "revise", "outline", "claim"]):
            return "essay_stage"
        return "essay"
    if any(w in t for w in ["project", "museum project", "museum"]):
        return "project"
    if any(w in t for w in ["read and annotate", "annotate", "finish reading",
                             "bring ", "read ", "reading", "prologue", "chapter"]):
        return "reading"
    if any(w in t for w in ["hw ", "hw:", "homework", "handout", "page ", "problems #",
                             "mylab", "graphing", "solving", "choosing a method",
                             "systems", "next steps", "research", "finish ", "letter to"]):
        return "homework"
    if span_days > 7:
        return "project"
    return "other"


# ─── Help text & debrief content ─────────────────────────────────────────────

CONTENT = {
    "reading": {
        "help": (
            "📌 TIPS FOR THIS READING\n"
            "• Before you start: glance at any section headings to prime your brain\n"
            "• While reading: mark moments that surprise, confuse, or connect to other things you know — questions count more than highlights\n"
            "• A good annotation = a question, a connection, or \"this matters because...\" — not just underlines\n"
            "• After: write one sentence summarizing the main idea before you close the book"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "How'd that reading land? Rate your understanding 1–5.\n"
            "If it's a 3 or below, jot down what felt murky — that's your question for next class 📚\n"
            "Score: __/5\nNotes:"
        ),
    },
    "homework": {
        "help": (
            "📌 TIPS FOR THIS HOMEWORK\n"
            "• Try each problem without looking at notes first — know where you actually get stuck\n"
            "• Show every step, even obvious ones. Your teacher can only give partial credit for work they can see\n"
            "• Stuck somewhere? Write down exactly where — that's your question for next class\n"
            "• Check: does your answer make sense? For algebra, plug it back in"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Done! How confident are you feeling? 1 = totally lost, 5 = could teach it. Anything trip you up? ✏️\n"
            "Score: __/5\nNotes:"
        ),
    },
    "quiz_prep": {
        "help": (
            "📌 QUIZ PREP TIPS\n"
            "• Quizzes test cold recall — practice retrieving, not re-reading\n"
            "• Cover your notes and write down everything you know from memory. Then check\n"
            "• For Hebrew: both directions — Hebrew → English AND English → Hebrew, out loud\n"
            "• 20 focused minutes beats an hour of passive re-reading, every time"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "How's your confidence? 1 (not ready) to 5 (bring it on).\n"
            "Below a 3? Book office hours before this one 🎯\n"
            "Score: __/5\nNotes:"
        ),
    },
    "test_phase1": {
        "help": (
            "📌 TEST PREP — DAY 1: SURVEY YOUR GAPS\n"
            "• Go through every topic covered since the last test. Sort into: \"solid,\" \"shaky,\" \"blank\"\n"
            "• Don't study yet — just map the terrain. 20 minutes max\n"
            "• Write your top 3 gaps specifically — vague gaps aren't useful\n"
            "• More than 2 \"blank\" items? Book office hours now — there's still time to use it"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "How many gaps did you find? Rate your readiness: 1–5.\n"
            "At a 3 or below? Reach out to your teacher now — you've got time to actually use that help 📋\n"
            "Score: __/5\nNotes:"
        ),
    },
    "test_phase2": {
        "help": (
            "📌 TEST PREP — DAY 2: TARGETED REVIEW\n"
            "• Today: shaky and blank stuff only — skip what's already solid\n"
            "• Work practice problems on your gap areas. Wrong answers show you exactly what to fix\n"
            "• If you booked office hours, go in with a specific gap list — not \"I don't get it\"\n"
            "• Update your gap list — anything still blank?"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "How are the gaps closing? 1–5. Anything still blank?\n"
            "If you haven't seen your teacher yet and the test is close, send them a message tonight 📚\n"
            "Score: __/5\nNotes:"
        ),
    },
    "test_phase3": {
        "help": (
            "📌 TEST PREP — DAY 3: FINAL RUN\n"
            "• No new topics today — only reinforce what you've already worked on\n"
            "• Do at least 3 practice problems from scratch, no notes\n"
            "• Check your gap list from Day 1 — how many are closed?\n"
            "• Get real sleep tonight. Memory consolidates overnight. Not optional"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Feeling ready? 1–5. You've done the work — trust it. Get to bed 🌟\n"
            "Score: __/5\nNotes:"
        ),
    },
    "essay_evidence": {
        "help": (
            "📌 GATHER EVIDENCE\n"
            "• Don't look for your argument yet — cast a wide net first\n"
            "• Pull every quote or moment from your annotations that could be relevant\n"
            "• Format: Quote → What it shows → Possible argument it supports\n"
            "• The more you collect now, the less painful the drafting will be"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "How much material did you gather? Any quotes that feel especially powerful?\n"
            "Not sure you have enough? Quick check-in with your teacher 🔍\n"
            "Score: __/5\nNotes:"
        ),
    },
    "essay_thesis": {
        "help": (
            "📌 THESIS + OUTLINE\n"
            "• A thesis makes a specific, arguable claim — not just a topic\n"
            "• Topic sentences each prove one part of the thesis — think of them as mini-theses\n"
            "• Test your outline: could someone predict your argument just from reading it?\n"
            "• Stuck? Try \"I think X because...\" in plain language first, then shape it\n"
            "• THIS is the perfect thing to bring to office hours before you start drafting"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Does your thesis feel specific and arguable? Rate your outline 1–5.\n"
            "Below a 3? Bring it to office hours before you start drafting 📝\n"
            "Score: __/5\nNotes:"
        ),
    },
    "essay_draft": {
        "help": (
            "📌 WRITE YOUR DRAFT\n"
            "• Start with body paragraphs, not the intro — intro is easier once you know what you argued\n"
            "• Each body paragraph: topic sentence → quote (with context) → analysis → connect to thesis\n"
            "• Don't edit as you go. Get it all out first — perfectionism kills drafts\n"
            "• A rough complete draft beats a polished incomplete one. Finish it"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Is your draft complete — every section, every paragraph? Rate quality 1–5.\n"
            "Below a 4 and the due date is close? Bring it to office hours 📬\n"
            "Score: __/5\nNotes:"
        ),
    },
    "essay_revise": {
        "help": (
            "📌 REVISE + SUBMIT\n"
            "• Read your essay OUT LOUD — your ear catches what your eye misses\n"
            "• Check each body paragraph: evidence present? Analysis after the quote (not just summary)?\n"
            "• Proofread last: read sentence by sentence, slowly. Check for fragments and run-ons\n"
            "• Before submitting: re-read the prompt. Did you answer what was actually asked?"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Submitted! ✅ Quick 2-min reflection: what would you do differently next time?\n"
            "Write one sentence 🙌\n"
            "Score: __/5\nNotes:"
        ),
    },
    "project_define": {
        "help": (
            "📌 STEP 1: MAKE THIS PLAN YOURS\n"
            "• Read the full assignment now — these milestone tasks are placeholders\n"
            "• Rewrite tasks 2–5 below to match what this project actually requires\n"
            "• Write down what \"done\" looks like for the final submission before you do anything else\n"
            "• Not sure about the stages? A 5-min conversation with your teacher this week saves a lot of pain later\n"
            "• Update the due dates on each milestone so they're evenly spaced before the deadline"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Did you update these milestones to match the actual project?\n"
            "If they're still generic, they won't help you. Take 5 minutes now 🗺️\n"
            "Score: __/5\nNotes:"
        ),
    },
    "project_research": {
        "help": (
            "📌 RESEARCH / GATHER MATERIALS\n"
            "• Define what you're looking for before you start — unfocused research wastes time\n"
            "• Take notes in a format that makes the next step (building/drafting) easier\n"
            "• Flag anything unclear — those are your teacher questions"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Do you have what you need for the next milestone? What's the next concrete step? 🔍\n"
            "Score: __/5\nNotes:"
        ),
    },
    "project_build": {
        "help": (
            "📌 FIRST DRAFT / BUILD\n"
            "• Define what \"done\" looks like for today before you start\n"
            "• Get a complete rough version first, then improve it\n"
            "• Projects punish procrastination harder than anything else"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Did you hit today's milestone? Rate completion 1–5.\n"
            "If you're behind, flag it now — much easier to catch up early 🏗️\n"
            "Score: __/5\nNotes:"
        ),
    },
    "project_review": {
        "help": (
            "📌 REVIEW + REVISE\n"
            "• Check the assignment rubric or requirements again before revising\n"
            "• Get a second set of eyes if possible\n"
            "• Specific feedback beats vague: \"this section needs more evidence\" > \"it needs work\""
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "What's the quality level right now, honestly? 1–5. What specifically still needs work? 👀\n"
            "Score: __/5\nNotes:"
        ),
    },
    "project_submit": {
        "help": (
            "📌 FINAL CHECK + SUBMIT\n"
            "• Re-read the full assignment directions — check every requirement\n"
            "• Proofread for spelling, grammar, and sentence clarity\n"
            "• Submit and screenshot or confirm the submission went through"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Submitted! ✅ What would you do differently on the next project? One sentence 🙌\n"
            "Score: __/5\nNotes:"
        ),
    },
    "hebrew_vocab": {
        "help": (
            "📌 HEBREW PRACTICE (15 min)\n"
            "• Practice 3 verbs — one from each binyan in all 3 tenses\n"
            "• Read for 5–10 minutes\n"
            "• Review any new vocab words"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Any words that keep escaping you? Add them to a list for your teacher 💬\n"
            "Score: __/5\nNotes:"
        ),
    },
    "algebra_review": {
        "help": (
            "📌 PRE-CLASS ALGEBRA REVIEW (10 min)\n"
            "• Do 2–3 problems from the current unit — actual problems, not re-reading\n"
            "• Check your answers. Wrong ones? Those are your questions for class tomorrow\n"
            "• Showing your steps is half the grade"
        ),
        "debrief": (
            "🔔 DEBRIEF\n"
            "Any problems that didn't go right? Those are your questions for tomorrow ✏️\n"
            "Score: __/5\nNotes:"
        ),
    },
    "weekly_debrief": {
        "help": (
            "📌 WEEKLY DEBRIEF (10 min)\n"
            "Work through these three questions:\n"
            "1. What did I actually finish this week vs. what did I skip or rush?\n"
            "2. Where did I score 3 or below — and did I follow up?\n"
            "3. What's one thing I'd do differently next week?\n\n"
            "Write 2–3 sentences below. Not an essay — just enough to make the reflection real."
        ),
        "debrief": "🔔 DONE!\nWeek logged. See you Sunday for the next plan 🙌\nNotes:",
    },
}


# ─── Task builder ─────────────────────────────────────────────────────────────

def to_iso(d, time_str):
    """Convert date + 'HH:MM' string to ISO 8601 with ET offset."""
    if not time_str:
        return None
    tz = ZoneInfo(CONFIG["timezone"])
    h, m = int(time_str[:2]), int(time_str[3:])
    dt = datetime(d.year, d.month, d.day, h, m, 0, tzinfo=tz)
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def offset_time(time_str, minutes):
    """Return a new 'HH:MM' string shifted forward by `minutes`."""
    if not time_str:
        return None
    h, m = int(time_str[:2]), int(time_str[3:])
    total = h * 60 + m + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


def build_task(title, content_key, task_date, time_slot,
               tags=None, priority=1, subtasks=None, bruins_note=None):
    c = CONTENT.get(content_key, {})
    body = c.get("help", "") + "\n\n" + c.get("debrief", "")
    if bruins_note:
        body = bruins_note + "\n\n" + body

    task = {
        "title":     title,
        "content":   body,
        "projectId": CONFIG["ticktick_project_id"],
        "priority":  priority,
        "tags":      tags or [],
    }
    due_iso = to_iso(task_date, time_slot)
    if due_iso:
        task["dueDate"]   = due_iso
        task["startDate"] = due_iso

    if subtasks:
        task["items"] = [{"title": s, "status": 0} for s in subtasks]

    return task


# ─── Main generator ───────────────────────────────────────────────────────────

def generate(start_date=None):
    tz      = ZoneInfo(CONFIG["timezone"])
    today   = datetime.now(tz).date()
    if start_date is None:
        start_date = today + timedelta(days=1)
    end_date = start_date + timedelta(days=9)

    print(f"Generating tasks {start_date} → {end_date}", file=sys.stderr)

    # ── Fetch data ──
    print("  Fetching iCal…", file=sys.stderr)
    ical_raw = fetch_ical()
    events   = parse_ical(ical_raw)
    print(f"  Parsed {len(events)} events", file=sys.stderr)

    print("  Fetching Bruins schedule…", file=sys.stderr)
    bruins_games = fetch_bruins_games()

    # ── Build no-school set ──
    no_school = set()
    for ev in events:
        if any(kw.lower() in ev["summary"].lower() for kw in CONFIG["no_school_keywords"]):
            d = ev["dtstart"].date()
            end = ev["dtend"].date()
            while d < end:
                no_school.add(d)
                d += timedelta(days=1)

    # ── Build lacrosse maps ──
    lax_practices = {}  # date → end_time HH:MM
    lax_games     = set()
    for ev in events:
        if "Lacrosse" in ev["summary"] and ev["has_time"]:
            d = ev["dtstart"].date()
            et = ev["dtend"]
            end_str = f"{et.hour:02d}:{et.minute:02d}"
            if "Game" in ev["summary"]:
                lax_games.add(d)
            else:
                lax_practices[d] = end_str

    tasks = []

    # ── Helper: resolve slots + add task ──
    def add(title, content_key, task_date, slot_type,
            tags=None, priority=1, subtasks=None):
        if task_date < start_date or task_date > end_date:
            return
        light, heavy, review, bn = resolve_slots(
            task_date, lax_practices, lax_games, bruins_games, no_school
        )
        slot = {"light": light, "heavy": heavy, "review": review}.get(slot_type, light)
        if slot is None:
            # Heavy on lacrosse day → fall back to light slot
            if slot_type == "heavy" and light:
                slot = light
            else:
                return
        tasks.append(build_task(title, content_key, task_date, slot,
                                tags, priority, subtasks, bn))

    # ── Process academic assignments ──
    # Customize this list for your school. These are calendar event titles
    # (or substrings) that should NOT be treated as assignments. Examples:
    # class period blocks, lunch, religious services, advisory, holidays,
    # sports practice, school assemblies, community service, etc.
    skip_patterns = SKIP_PATTERNS

    for ev in events:
        summ = ev["summary"]
        if any(p in summ for p in skip_patterns):
            continue

        course, assignment = get_course_and_assignment(summ)
        if not course or not assignment:
            continue

        # Due date: iCal DTEND is exclusive for all-day events → subtract 1 day
        due_date     = (ev["dtend"].date() - timedelta(days=1)) if not ev["has_time"] \
                       else ev["dtend"].date()
        assigned     = ev["dtstart"].date()
        span_days    = max((due_date - assigned).days, 0)
        task_type    = classify(assignment, span_days)

        # Skip if entirely outside window
        if due_date < start_date and (due_date - timedelta(days=3)) < start_date:
            continue
        if assigned > end_date:
            continue

        tag          = get_tag(course)
        tags         = [tag] if tag else []
        short        = get_short(course)
        teacher      = get_teacher(course)
        asgn_clip    = assignment[:55] + "…" if len(assignment) > 55 else assignment
        due_label    = due_date.strftime("%a %b %-d")

        if task_type == "skip":
            continue

        if task_type == "reading":
            d = max(assigned, start_date)
            if d <= due_date:
                add(f"📖 {short}: {asgn_clip}", "reading", d, "light", tags)

        elif task_type == "homework":
            d = max(assigned, start_date)
            if d <= due_date:
                add(f"✏️ {short}: {asgn_clip}", "homework", d, "light", tags)

        elif task_type == "quiz":
            d = max(due_date - timedelta(days=1), start_date)
            if d <= due_date:
                add(f"🧠 Quiz prep: {short} — due {due_label}",
                    "quiz_prep", d, "light", tags)

        elif task_type == "test":
            phases = [
                (3, "📋", "Day 1: survey gaps",      "test_phase1", 3),
                (2, "📚", "Day 2: targeted review",  "test_phase2", 3),
                (1, "🔥", "Day 3: final run",         "test_phase3", 5),
            ]
            for days_before, emoji, label, key, pri in phases:
                d = due_date - timedelta(days=days_before)
                if d >= start_date:
                    add(f"{emoji} {short} test prep — {label} (test: {due_label})",
                        key, d, "heavy", tags, priority=pri)

        elif task_type in ("essay", "essay_stage"):
            a = assignment.lower()
            if "collect evidence" in a or "gather" in a:
                add(f"🔍 {short}: gather evidence", "essay_evidence",
                    max(assigned, start_date), "heavy", tags)
            elif any(w in a for w in ["thesis", "topic sentence", "outline", "claim"]):
                add(f"💡 {short}: thesis + outline — {asgn_clip}", "essay_thesis",
                    max(assigned, start_date), "heavy", tags, priority=3)
            elif any(w in a for w in ["draft", "intro", "body paragraph", "free write"]):
                add(f"✍️ {short}: write draft — {asgn_clip}", "essay_draft",
                    max(assigned, start_date), "heavy", tags, priority=3)
            elif any(w in a for w in ["revise", "final", "submit"]):
                add(f"✅ {short}: revise + submit — {asgn_clip}", "essay_revise",
                    max(due_date - timedelta(days=1), start_date), "heavy", tags, priority=5)
            else:
                # Single essay event — auto-generate all phases
                base = max(assigned, start_date)
                span = max((due_date - base).days, 4)
                for frac, emoji, label, key in [
                    (0,    "🔍", "gather evidence",   "essay_evidence"),
                    (0.25, "💡", "thesis + outline",  "essay_thesis"),
                    (0.5,  "✍️", "write draft",       "essay_draft"),
                    (0.9,  "✅", "revise + submit",    "essay_revise"),
                ]:
                    d = base + timedelta(days=int(span * frac))
                    d = min(d, due_date - timedelta(days=1))
                    if d >= start_date:
                        add(f"{emoji} {short} essay: {label}",
                            key, d, "heavy", tags, priority=3)

        elif task_type == "project":
            base = max(assigned, start_date)
            span = max((due_date - base).days, 4)
            milestones = [
                (base,                                        "🗺️", "define milestones",    "project_define",
                 ["🔍 Research / gather materials",
                  "🏗️ First draft / build",
                  "👀 Review and revise",
                  "✅ Final check and submit"]),
                (base + timedelta(days=max(1, span // 4)),   "🔍", "research / gather",    "project_research",  None),
                (base + timedelta(days=max(2, span // 2)),   "🏗️", "first draft / build",  "project_build",     None),
                (base + timedelta(days=max(3, 3*span // 4)), "👀", "review and revise",     "project_review",    None),
                (due_date - timedelta(days=1),                "✅", "final check + submit",  "project_submit",    None),
            ]
            seen_milestone_dates = set()
            for md, emoji, label, key, sub in milestones:
                if start_date <= md <= end_date and md <= due_date:
                    if md in seen_milestone_dates:
                        continue  # skip duplicate-date milestones (compressed window)
                    seen_milestone_dates.add(md)
                    add(f"{emoji} {short} project: {label} (due {due_date.strftime('%b %-d')})",
                        key, md, "heavy", tags, priority=3, subtasks=sub)

    # ── Standing weekly tasks ──
    d = start_date
    while d <= end_date:
        wday  = d.weekday()
        light, heavy, review, bn = resolve_slots(
            d, lax_practices, lax_games, bruins_games, no_school
        )

        if wday != 5 and d not in no_school:  # skip Saturday and no-school days
            # Friday debrief
            if wday == 4:
                tasks.append(build_task(
                    "🔁 Weekly debrief (10 min)", "weekly_debrief",
                    d, CONFIG["times"]["weekly_debrief"], [], priority=1
                ))

        if wday != 5:  # standing practice tasks run every day except Saturday (incl. holidays)
            # On no-school days resolve_slots returns None — fall back to default review slot
            T = CONFIG["times"]
            practice_review = review or (T["sunday_review"] if wday == 6 else T["school_review"])

            # Hebrew practice: Mon–Thu (0–3) and Sunday (6)
            if wday in (0, 1, 2, 3, 6):
                tasks.append(build_task(
                    "🇮🇱 Hebrew practice (15 min)", "hebrew_vocab",
                    d, practice_review, ["Hebrew"], priority=1, bruins_note=bn
                ))

            # Algebra pre-class review: Mon–Thu (15 min after Hebrew to avoid overlap)
            if wday in (0, 1, 2, 3):
                tasks.append(build_task(
                    "📐 Algebra: pre-class review (10 min)", "algebra_review",
                    d, offset_time(practice_review, 15), ["Algebra"], priority=1
                ))

        d += timedelta(days=1)

    print(f"  Generated {len(tasks)} tasks", file=sys.stderr)
    return tasks


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    start = None
    if len(sys.argv) > 1:
        try:
            start = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            print(f"Invalid date: {sys.argv[1]}. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

    result = generate(start)
    print(json.dumps(result, indent=2, default=str))
