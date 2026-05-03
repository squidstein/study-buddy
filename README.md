## Study Buddy

> A weekly study scaffolding system for a high school student. Reads their school iCal, applies backward planning rules, and pushes structured tasks to a shared TickTick list every Sunday at 6 PM.

Study Buddy turns a school calendar into a week of specific, time-boxed study tasks. Tests get distributed prep starting four days before the due date. Essays get outline → draft → revise → submit, one stage per evening. Standing tasks (vocab review, math warmup, weekly debrief) repeat on the right days. Game nights and practice nights shift task times automatically. Holidays and weekends are skipped.

The student never interacts with the automation. They open TickTick, see the tasks, and check them off.

This is a snapshot of the version I run for my own kid. It works against any iCal feed, any TickTick list, and any NHL team's schedule. You set the values once and it runs without maintenance.

## Prerequisites

- **A Claude environment with the TickTick MCP.** Claude Code on your machine, or any hosted Claude environment. The skill calls TickTick via MCP. If you want to run this on plain cron without Claude, you'll need to swap the MCP call for a direct TickTick API request.
- **TickTick account** for the student ([sign up](https://ticktick.com)). The free tier is sufficient.
- **School iCal feed URL.** Most school portals (Blackbaud, MySchoolApp, Veracross, Google Calendar) publish one. See `docs/setup-guide.md` Step 2.
- **Python 3.8 or later** with `icalendar` and `pytz` (`pip install icalendar pytz`).

## Install

1. Clone this repo somewhere on your machine.
2. Copy the skill folder into your Claude skills directory:
   ```bash
   cp -r . ~/.claude/skills/study-buddy/
   ```
   (Or symlink it if you want to keep developing in place.)
3. Reload Claude Code. You can now invoke `/study-buddy` or just say "run study buddy" in a Claude session.

## Make it your own

The script ships with placeholder defaults so it loads cleanly on a fresh clone. To actually generate real tasks, copy the example config and fill in your values:

```bash
cp config_local.py.example config_local.py
```

Then edit `config_local.py`. `config_local.py` is gitignored. It will not be committed. Never commit your iCal URL or TickTick project ID.

### Required (skill won't work without these)

- `ICAL_URL`. Your student's school iCal feed URL. Found in the school portal under Calendar → Subscribe or Export. Often contains an auth token in the query string. Keep this private.
- `TICKTICK_PROJECT_ID`. The 24-character hex ID of the student's TickTick list. Easiest way: ask Claude in a session with the TickTick MCP, "List my TickTick projects and show me the IDs."
- `SUBJECT_TAGS`. Maps how courses appear in the iCal feed (the prefix of the SUMMARY field) to the TickTick tag names you've created. Tag names must match exactly, case-sensitive. The tags must already exist in TickTick before tasks get pushed.
- `SUBJECT_SHORT`. Short display names used in task titles. Can be the same strings as `SUBJECT_TAGS` values.
- `TEACHERS`. Full teacher name for each subject. Used when the script creates "📅 Book office hours: [teacher]" follow-up tasks.

### Optional (defaults work, tune to taste)

- `TIMEZONE` (default: `America/New_York`). Student's local timezone, as a pytz string.
- `NO_SCHOOL_KEYWORDS` (default: common US holiday names). Strings that, when found in a calendar event title, mark the whole day as no-school.
- `TIMES`. When tasks should be scheduled on different day types. Defaults assume school ends mid-afternoon and the student does heavy work after dinner. Adjust to match your student's actual rhythm.
- `SKIP_PATTERNS`. Calendar event titles to ignore (class period blocks, lunch, advisory, religious services, school assemblies, sports practice, etc.). Customize for your school.

### NHL / sports schedule integration (optional)

By default the script fetches the Boston Bruins schedule and shifts task times on game nights so the student can watch. To change teams or sports:

- **Different NHL team.** Find `fetch_bruins_games` in `study_buddy.py` and change the team code in the API URL (`NYR`, `TOR`, etc.).
- **Different league or sport.** Replace the function with a call to any API that returns game dates and start times.
- **Don't want this at all.** Comment out the call. Tasks will be scheduled at default times every evening.

### Sports practice / game schedule integration (optional)

The script also reads the student's own sports schedule from the same iCal feed, so it can push study tasks later on practice days and shift them earlier or skip them on game days. Find `lax_practices` and `lax_games` in `study_buddy.py` and change the filter string (default: `"Boys Varsity Lacrosse"`) to match how your student's sport appears in the calendar. Add the sport name to `SKIP_PATTERNS` so practice events aren't classified as homework.

If your student doesn't play a sport, leave this alone. With no matching events, it has no effect.

### First-run checklist

- [ ] `config_local.py` exists and all required fields are filled
- [ ] iCal URL fetches successfully: `curl -s "$ICAL_URL" | head -3` shows `BEGIN:VCALENDAR`
- [ ] TickTick list exists, tags exist, list is shared with the student
- [ ] `python3 study_buddy.py 2>/dev/null | python3 -m json.tool | head -50` produces sensible-looking task JSON
- [ ] First push to TickTick lands in the right list with the right dates and tags
- [ ] (Optional) Scheduled run is set up. See `docs/setup-guide.md` Step 9.

## What it does

In detail:

**Backward planning.** Every test, essay, quiz, and project gets prep tasks that count back from the due date. Test in 4 days → "study unit review" tonight, "focused review of weak areas" tomorrow, "day-of scan" the morning of. Essays get outline → evidence → draft → revise → proofread, one stage per evening.

**Standing tasks.** Recurring weekly work (vocab review, math warmup, a Friday debrief) appears on configured days. These are short on purpose. The point is consistency.

**Schedule-aware timing.** Tasks shift earlier on hockey game nights so the student can watch. Tasks shift later (or skip) on game days. Friday tasks happen in the afternoon because school dismisses early. Tasks aren't scheduled on weekends or holidays.

**Score-driven follow-up.** Each task ends with a `Score: __/5` line. The student rates how the work went. The script scans completed tasks and, for any score of 1, 2, or 3, creates a "📅 Book office hours: [teacher]" task due the next Friday.

**JSON output, pushed via MCP.** The script outputs JSON to stdout. The skill reads it and calls TickTick's `batch_add_tasks`. No API keys live in this repo. TickTick auth is handled by your Claude environment's MCP setup.

The full setup walkthrough is in `docs/setup-guide.md`. The student-facing version of how to use the system is in `docs/user-guide.md` (which you'll want to rewrite for your own kid since mine has specific subjects and a hockey team he likes).

## Status

This is a **snapshot** of a skill I use day-to-day for my actual kid, published here as a portfolio showcase. I'm not syncing updates from my private version, so bug reports and PRs may not get a response. Fork freely.

Last snapshot: May 2026.

## Origin

- Portfolio page: https://lauranh.netlify.app/skills/study-buddy
- Blog post: https://lauranh.netlify.app/blog/study-buddy
- Built by Lauran Hazan ([@squidstein](https://github.com/squidstein))

## License

MIT. See [LICENSE](./LICENSE).
