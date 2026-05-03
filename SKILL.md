---
name: study-buddy
description: Weekly study task generator. Reads a student's school iCal calendar and sports schedule, generates backward-planned study tasks for the week, and pushes them to a shared TickTick list. Run manually or on a Sunday 6 PM schedule.
triggers:
  - "run study buddy"
  - "generate this week's tasks"
  - "push study tasks"
  - "study buddy"
---

# Study Buddy — Skill Instructions

## What This Skill Does

1. Finds and runs `study_buddy.py` from the configured workspace
2. Parses the output JSON array of TickTick task objects
3. Pushes all tasks to the student's TickTick list via `batch_add_tasks`
4. Scans recently completed tasks for low debrief scores (≤ 3) and creates "Book office hours" follow-up tasks

## Step 1: Find the Script

Set `SCRIPT_PATH` to wherever you cloned this repo. The Python script lives at `<REPO_PATH>/study_buddy.py`.

If you are unsure where the repo lives, search for it:

```bash
find ~ -name "study_buddy.py" 2>/dev/null | head -1
```

## Step 2: Install Dependencies (if needed)

```bash
pip install icalendar pytz --break-system-packages -q 2>/dev/null
```

## Step 3: Run the Script

```bash
cd "$(dirname SCRIPT_PATH)"
python3 study_buddy.py 2>/dev/null
```

This outputs a JSON array of task objects to stdout. The script defaults to the current week (Sunday = today). To generate for a specific date: `python3 study_buddy.py 2026-04-13`

## Step 4: Push Tasks to TickTick

Parse the JSON output and call `batch_add_tasks` with the full array. The `projectId` is already embedded in each task object — do not change it.

Verify success: `id2error` in the response should be empty. If any tasks failed, report which ones and why.

## Step 5: Carry-Forward Check

Query TickTick for completed tasks from the past 7 days in the configured project:

```
Call: list_completed_tasks_by_date (project_id = [from CONFIG])
```

For each completed task whose `content` field contains `Score: 1/`, `Score: 2/`, or `Score: 3/`:

Create a new task:
- **Title:** `📅 Book office hours: [extract teacher/subject from original task title]`
- **Content:** `Low score flagged on: [original task title]\nSchedule 10–15 min with your teacher this week.`
- **projectId:** same as original task
- **dueDate:** next Friday at 15:00 local time (use America/New_York unless CONFIG says otherwise)
- **priority:** 3
- **tags:** same tags as original task

## Step 6: Report

Tell the user:
- How many tasks were generated and pushed
- Which days have tasks and which are empty (and why — game day, holiday, etc.)
- How many carry-forward office hours tasks were created, if any

---

## Configuration

All school-specific settings live in the `CONFIG` dict near the top of `study_buddy.py`. Key fields:

| Field | What to change |
|-------|---------------|
| `ical_url` | Student's school iCal feed URL |
| `ticktick_project_id` | TickTick list ID (24-char hex) |
| `timezone` | Student's local timezone string |
| `subject_tags` | iCal course name prefixes → TickTick tag names |
| `teachers` | Subject → teacher full name |
| `no_school_keywords` | Keywords that mark a calendar day as no-school |

See `docs/setup-guide.md` for full configuration instructions.

---

## Troubleshooting

**"Fewer tasks than expected"** — Run with stderr visible: `python3 study_buddy.py` (without `2>/dev/null`) to see debug output. Check that `ical_url` is still valid.

**Duplicate tasks in TickTick** — The script does not check for existing tasks. If run twice for the same week, manually delete duplicates in TickTick.

**iCal URL expired** — Some schools rotate the auth token. Regenerate from the school portal and update `ical_url` in CONFIG.
