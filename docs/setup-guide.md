# Study Buddy — Setup Guide

*How to configure this system for a different student*

---

## What You're Setting Up

Study Buddy is a Python script that runs automatically every Sunday at 6 PM. It reads the student's school iCal calendar, applies scheduling rules, and pushes a structured task list to a shared TickTick list. The student only ever sees TickTick. They do not interact with any of the automation.

Setup takes about 30 to 45 minutes the first time. After that, it runs without any ongoing maintenance.

You will need somewhere to run the script on a schedule. Options:
- Claude Code on a machine that's awake at the scheduled time, with a cron job or launchd entry
- Any hosted Claude environment that supports scheduled tasks
- A plain Linux server with cron and the TickTick API

These instructions assume you are using Claude (Code or hosted) so the TickTick MCP is available. If you are running pure cron, you'll need to call the TickTick HTTP API directly instead of the steps that say "ask Claude".

---

## Prerequisites

Before you start, you'll need:

- A Claude environment that can run Python and call the TickTick MCP (Claude Code, or a hosted Claude environment)
- A **TickTick account** for the student. The free tier is sufficient.
- The student's **school iCal feed URL** (see Step 2 below)
- Python 3.8 or later

---

## Step 1: Get the Script

Clone this repo, or copy `study_buddy.py` to wherever you want it to live. Anywhere your Claude environment can read and execute it is fine.

Verify the file is accessible from your Claude session:

```bash
ls <REPO_PATH>/study_buddy.py
```

---

## Step 2: Get the School iCal URL

Every school that uses a platform like MySchoolApp, Blackbaud, Veracross, or Google Calendar publishes an iCal feed. The process varies by platform:

**Blackbaud / MySchoolApp:**
1. Log into the student's school portal
2. Go to Calendar or Schedule
3. Look for "Subscribe" or "Export" — this gives you a `webcal://` or `https://` URL
4. Copy the full URL including any authentication token in the query string

**Google Calendar (school-issued):**
1. Open the student's Google Calendar
2. Click the three-dot menu next to the calendar name → Settings
3. Scroll to "Integrate calendar" → copy the "Secret address in iCal format"

The URL typically contains a long authentication token. Keep this private — it provides read access to the student's calendar.

**Test the URL** before configuring the script:

```bash
curl -s "YOUR_ICAL_URL_HERE" | head -20
```

You should see lines starting with `BEGIN:VCALENDAR`. If you get an error or empty response, the URL is wrong.

---

## Step 3: Set Up TickTick

1. Create a TickTick account for the student (or use an existing one)
2. Create a new list — name it something the student will recognize (e.g., "📚 Schoolwork")
3. Create tags for each subject the student takes — these must match exactly what you'll configure in the script. For example: `English`, `Algebra`, `Biology`, `History`
4. Share the list with the student as a collaborator so they can see and complete tasks

**Get the project ID** for the list:

The easiest way is to use the TickTick MCP in a Claude session:

```
Ask Claude: "List my TickTick projects and show me the IDs"
```

The project ID is a 24-character hex string (looks like `aaaaaaaaaaaaaaaaaaaaaaaa`).

---

## Step 4: Configure the Script

Open `study_buddy.py` and edit the `CONFIG` block near the top of the file. Every value in this block is school-specific. Do not skip any of them.

```python
CONFIG = {
    # The iCal URL from Step 2
    "ical_url": "https://yourschool.example.com/feed/iCal.aspx?z=YOUR_TOKEN",

    # Student's local timezone
    "timezone": "America/New_York",

    # TickTick project ID from Step 3
    "ticktick_project_id": "YOUR_PROJECT_ID_HERE",

    # Maps iCal subject name prefixes to TickTick tag names.
    # The key must be a prefix of the course name as it appears in the iCal feed.
    # The value must exactly match the tag name in TickTick (case-sensitive).
    "subject_tags": {
        "English 10": "English",
        "Algebra II": "Algebra",
        "AP Biology": "Biology",
        "US History": "History",
    },

    # Short display names used in task titles
    "subject_short": {
        "English 10": "English",
        "Algebra II": "Algebra",
        "AP Biology": "Biology",
        "US History": "History",
    },

    # Teacher full names, used in "Book office hours" tasks
    "teachers": {
        "English 10": "Ms. Smith",
        "Algebra II": "Mr. Johnson",
        "AP Biology": "Dr. Patel",
        "US History": "Ms. Williams",
    },

    # Keywords in calendar events that indicate no school that day
    "no_school_keywords": [
        "No School", "Holiday", "Winter Break", "Spring Break",
        "Thanksgiving", "Summer", "Offices Closed",
    ],

    # Time slots used for task scheduling (24-hour format, local time)
    # Adjust these to match the student's after-school schedule
    "times": {
        "school_light": "18:00",    # light task on a school day
        "school_heavy": "19:30",    # heavy task on a school day
        "school_review": "21:00",   # standing review tasks
        "friday_light": "15:00",    # light task on Friday
        "friday_heavy": "16:30",    # heavy task on Friday
        "sunday_light": "18:00",
        "sunday_heavy": "19:30",
        "sunday_review": "21:00",
        "game_light": "20:00",      # tasks on sports game nights
        "weekly_debrief": "15:30",  # Friday debrief time
    },
}
```

**Key things to get right:**

- `subject_tags` keys must be prefixes of the actual course names in the iCal feed. Run a quick fetch to see exactly how courses are named:

```bash
python3 -c "
import urllib.request
from icalendar import Calendar
req = urllib.request.Request('YOUR_ICAL_URL', headers={'User-Agent': 'StudyBuddy/1.0'})
raw = urllib.request.urlopen(req, timeout=30).read()
cal = Calendar.from_ical(raw)
names = set()
for c in cal.walk():
    if c.name == 'VEVENT':
        s = str(c.get('SUMMARY',''))
        if ' - ' in s and not any(w in s for w in ['Block', 'Lunch']):
            names.add(s.split(' - ')[0])
for n in sorted(names): print(n)
"
```

This prints all unique course name prefixes in the calendar — use these as your `subject_tags` keys.

---

## Step 5: Identify Sports Events

The script reads lacrosse (or other sports) events from the same iCal calendar to adjust task times. You need to tell the script what string to look for in sports event titles.

In `study_buddy.py`, find the section that parses lacrosse events (search for `lax_practices` and `lax_games`). The default filter looks for events containing `"Boys Varsity Lacrosse"`. Change this string to match however sports events appear in your school's calendar.

Also add the sport name to `SKIP_PATTERNS` in your `config_local.py` so those events aren't classified as assignments. SKIP_PATTERNS is a list of strings that get filtered out of the calendar before task generation. Customize it for your school's specific events. Typical entries include class period blocks, lunch, advisory, religious services, school assemblies, sports practice, and any tag your school adds to events.

```python
SKIP_PATTERNS = [
    "Block)", "Lunch", "Advisory", "Assembly",
    "YOUR SPORT NAME",  # add the sport here
    "YOUR SCHOOL TAG",  # whatever your school appends to events, if anything
    # add anything else from your school's calendar that is not homework
]
```

If the student doesn't play a sport or you don't want schedule-aware timing, you can skip this step. It will have no effect if no matching events are found.

---

## Step 6: Configure the NHL / Sports League Schedule (Optional)

By default, the script fetches the Boston Bruins schedule to shift task times on game nights. To change this to a different team or league:

- **Different NHL team:** Change the team code in the API URL (e.g., `NYR` for Rangers, `TOR` for Leafs)
- **Different league / sport:** Replace the Bruins API call with any API that returns game dates and start times, and update the `bruins_games` set accordingly
- **Not applicable:** Remove or comment out the Bruins block — tasks will be scheduled at default times on all evenings

---

## Step 7: Test the Script

Install dependencies:

```bash
pip install icalendar pytz --break-system-packages
```

Run a test for the current week:

```bash
python3 study_buddy.py 2>/dev/null | python3 -c "
import json, sys
tasks = json.load(sys.stdin)
print(f'Total tasks: {len(tasks)}')
for t in tasks:
    print(t['dueDate'][:16], t['title'][:65])
"
```

Check the output:

- Do the subject names in task titles match what you expected?
- Are no-school days and weekends empty?
- Do assignment tasks appear with appropriate lead time before due dates?
- Are standing tasks (vocab, review) appearing on the right days?

If you see tasks for events that should be filtered (like class schedule blocks), add their keywords to `skip_patterns`.

**Do not push to TickTick yet** until the output looks correct.

---

## Step 8: Push the First Week

Once the output looks right, push the tasks:

In a Claude session with the TickTick MCP enabled, ask Claude:

> "Run the study buddy script for this week and push the output to TickTick"

Or do it manually:

```bash
python3 study_buddy.py 2>/dev/null > /tmp/tasks.json
```

Then pass the JSON to the TickTick `batch_add_tasks` MCP call with the full array.

Check TickTick to confirm the tasks landed in the right list with the right dates, times, and tags.

---

## Step 9: Set Up the Scheduled Run

Pick whichever option fits your environment:

**Option A: Hosted Claude environment with scheduled tasks.** Ask Claude:

> "Create a scheduled task that runs every Sunday at 6 PM. It should find study_buddy.py at `<REPO_PATH>`, run it, and push the JSON output to TickTick project [YOUR_PROJECT_ID]."

The scheduled task prompt should include:
- The path to the script (`<REPO_PATH>/study_buddy.py`)
- How to run it and capture JSON output
- How to call `batch_add_tasks` with the output
- The carry-forward logic (scan completed tasks for Score: 1/2/3, create office hours tasks)

After creating the task, trigger a manual run once to pre-approve all tool permissions. This way future unattended runs don't pause for approval prompts.

**Option B: Plain cron on a Mac or Linux box.** The TickTick MCP only runs inside a Claude session, so for a pure-cron setup you'll need to either (a) keep the script running inside `claude --headless` and call `batch_add_tasks`, or (b) replace the MCP call with a direct TickTick API request. Option (a) is closer to what this skill was designed for.

---

## Ongoing Maintenance

The system runs without maintenance in most cases. A few situations may require attention:

**New subject added mid-year:** Add the course name prefix, tag, short name, and teacher to CONFIG. The tag must exist in TickTick before tasks are pushed.

**Teacher change:** Update the `teachers` dict in CONFIG.

**Schedule change** (e.g., school day ends at different time): Update the `times` dict.

**Duplicate tasks after a manual re-run:** The script doesn't check for existing tasks before pushing. If you run it twice for the same week, you'll need to manually delete the duplicates in TickTick.

**iCal URL expired:** Some schools rotate the authentication token in the iCal URL periodically. If tasks stop appearing, regenerate the URL from the school portal and update `ical_url` in CONFIG.

---

## Troubleshooting

**"No tasks generated" or fewer tasks than expected:**
Run with stderr visible to see what's happening:
```bash
python3 study_buddy.py 2>&1 | head -20
```
Check that the iCal URL is still valid and that course names in `subject_tags` still match.

**Task titles contain garbled subject names:**
The `subject_tags` prefixes don't match the iCal feed. Re-run the course name extraction in Step 4 to see current names.

**Tasks appearing on holidays:**
Add the holiday keyword (exactly as it appears in the calendar event summary) to `no_school_keywords` in CONFIG.

**Standing tasks missing on certain days:**
These are suppressed on game days and no-school days — check whether those days are correctly detected. Also check that `review` slot is not None for the day in question.
