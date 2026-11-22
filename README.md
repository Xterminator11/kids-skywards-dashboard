# Kids Gradebook Tracker

Logs in to Skyward Family Access every day at **3:00 PM Central**, reads every child's
gradebook, and saves the grades to CSV files. Runs in Docker.

## Quick start

1. Copy the settings file and add your Skyward login:
   ```bash
   cp .env.example .env
   # edit .env: set SKYWARD_USERNAME and SKYWARD_PASSWORD
   ```
   `.env` is git-ignored. Credentials are never stored in code.

### Run locally (easiest for debugging)

Needs [uv](https://docs.astral.sh/uv/) (`brew install uv` or
`curl -LsSf https://astral.sh/uv/install.sh | sh`). `start.sh` installs the Python
dependencies and Chromium on first use, and writes to `./data`.

```bash
./start.sh                  # scrape once now
HEADLESS=false ./start.sh   # same, but watch the browser
./start.sh schedule         # run every day on SCHEDULE_CRON until Ctrl+C
./start.sh dashboard        # rebuild the family dashboard and open it, no login
./start.sh parse data/raw/<file>.html   # re-parse a saved page, no login
./start.sh parse-assignments data/raw/assignments_*.html data/raw/gradebook_*.html
./start.sh test             # run the tests
```

A one-off `./start.sh` run does not retry on failure (`MAX_RETRIES=0`) so problems show
up right away; set `MAX_RETRIES=2` to change that.

### Host it at home (Mac mini, or test on a laptop first)

**Step-by-step guide: [docs/MAC_MINI_SETUP.md](docs/MAC_MINI_SETUP.md)** (setup, daily
family text alert, Docker commands, troubleshooting).

One script sets everything up on a Mac with Docker Desktop:

```bash
./deploy/macmini-setup.sh
```

It asks for your Skyward login (saved only in `.env`), sets the daily scrape to
**3:00 PM Central**, builds and starts two containers, and announces
**http://kids-dashboard.local** on your home network:

| Container | What it does |
|---|---|
| `scraper` | Checks Skyward once a day on `SCHEDULE_CRON`, then rebuilds the dashboard |
| `dashboard` | Always on. Serves the page on `HTTP_PORT` (default 80) |

The `.local` name works on iPhone, iPad, Mac, Windows and recent Android (Pixel) while on
your home Wi-Fi. It comes from a small LaunchAgent (`deploy/mdns-advertise.sh`, using
macOS's built-in Bonjour), so the computer's own name doesn't change. Devices that can't
find `.local` names can use the Mac's IP address instead; the script prints both.

On the Mac mini (no battery) the script also keeps it awake and restarting after a power
cut. Also turn on Docker Desktop's "Start Docker Desktop when you sign in", automatic
login, and keep the Mac mini's IP fixed (a DHCP reservation, or a manual IP).

After testing on a laptop, run `./deploy/macmini-setup.sh --remove` there, so the laptop
stops scraping and stops claiming the `kids-dashboard.local` name.

```bash
docker compose ps                                                      # what's running
docker compose logs -f scraper                                         # watch a scrape
docker compose run --rm -e MAX_RETRIES=0 scraper python -m gradebook run   # scrape right now
git pull && ./deploy/macmini-setup.sh                                  # update
```

Port 80 busy? `HTTP_PORT=8787 ./deploy/macmini-setup.sh`, then the address is
`http://kids-dashboard.local:8787`.

If your district has more than one child on the account, the gradebook is read for each
child in turn (Skyward hides it while "All Students" is selected).

## What you get (in `./data`)

| File | What it is |
|---|---|
| `grades_latest.csv` | The most recent run |
| `snapshots/grades_YYYY-MM-DD.csv` | One file per day |
| `grades_history.csv` | Every run appended, for tracking changes over time |
| `assignments_latest.csv` (and snapshot / history) | Assignments, see below |
| `raw/gradebook_*.html` | Copy of each child's gradebook page (turn off with `SAVE_RAW_HTML=false`) |
| `raw/assignments_*.html` | Copy of each term-grade popup |
| `site/index.html` | The family dashboard, rebuilt after every run |
| `../state/writeoffs.json` | Items you wrote off (kept separate, never overwritten by a scrape) |
| `debug/failure_*` | Screenshot + HTML when a run fails |

Columns: `scraped_at, student, student_id, course, course_id, period, teacher, term, grade, source`.
One row per student, course and grading term (e.g. PR1, Q1, S1).

### Assignments

With `FETCH_ASSIGNMENTS=true` (the default) each run also saves assignments, in the same
three forms: `assignments_latest.csv`, `snapshots/assignments_YYYY-MM-DD.csv` and
`assignments_history.csv`.

For each course the run clicks the **latest grading term that has a grade** (skipping
semester, exam and final columns), which opens Skyward's term-grade popup listing every
assignment in that term. It pauses `ASSIGNMENT_DELAY_SECONDS` (default 1.5) between
courses. Older assignments that Skyward shows on the main gradebook page are added too
(`detail_source` = `gradebook`; these have no category or points).

Columns: `scraped_at, student, student_id, course, course_id, term, category, assignment,
assignment_id, due_date, score, points_earned, points_possible, flags, status,
detail_source, notes, source`.

`status` is worked out like this:

| status | meaning |
|---|---|
| `missing` | Skyward marks it Missing (popup column, or the page's Missing Assignments box) |
| `exempt` | marked No Count / exempt and has no score, or the teacher marked it Excused |
| `done` | has a score (including 0) |
| `not_yet_due` | no score, due today or later |
| `not_turned_in` | no score and the due date has passed, but Skyward has not marked it missing. Often it just has not been graded yet |

`flags` lists what Skyward marked: `missing`, `no count`, `absent`, `late`, `exempt`,
and `excused` when a teacher's special code or comment says Excused. `notes` holds those
special codes and comments as text. (Adding a column rewrites `assignments_history.csv`
once with the new header; old rows get a blank.)
Each popup is saved as `raw/assignments_<date>_<student>_<course>_<section>_<term>.html`.

## Family dashboard

After every run the app writes **`data/site/index.html`**, one page for the whole family:

- **Tonight's focus** (for the kids): a badge on each child's avatar. Green ✓ means all
  clear, amber means something is due by tomorrow, red means something is past due, with
  their top 3 things to do first.
- **This week at a glance**, and an **open work** list across all classes with
  Past due / Today / 1D / 2D / 1W / 2W filters.
- **Where they're lagging** (for parents): plain-language alerts and a table per class
  (grade, change from last quarter, progress-report trend, test vs daily-work average,
  zeros, past due).
- **On time vs missed** by week.

It costs nothing to run: there are no AI or model calls. The alerts are fixed rules in
`gradebook/dashboard/rules.py`:

| Alert | Rule (default) | Setting |
|---|---|---|
| Failing (red) | class grade below 70 | `DASH_FAILING_BELOW` |
| Dropped (amber) | 2nd quarter 10+ points below the 1st | `DASH_DROP_POINTS` |
| Below a B (amber) | class grade below 80 | `DASH_WATCH_BELOW` |
| Doing well (green) | class grade 90 or more | `DASH_STRONG_AT` |
| "Understanding" vs "effort" | test average and daily-work average 10+ points apart | `DASH_GAP_POINTS` |

Weekly items the teacher scores (participation, good character, rehearsal) are hidden from
the lists by default; change the pattern with `DASH_TEACHER_SCORED`.

**Excused work.** When a teacher marks an assignment "Excused" (the small info icon in
Skyward), it's saved with flag `excused`, status `exempt`, and never counts as a zero or as
past due. Teacher comments ("Turned in late.", "Missing- complete for homework") are kept in
the `notes` column and shown under each item.

**Writing items off.** Some old work can't be made up. Press **Write off** on a past-due or
zero item, pick why (Turned in, Excused, Cannot be completed, Other) and add an optional
comment. It drops out of Tonight's focus, every count, the averages and the alerts.
Write-offs are saved in `state/writeoffs.json` (outside `data/`), so a new scrape never
brings them back. The **Written off** filter lists them with a **Restore** button.
Skyward's own class grade can't change, so the "Now" column still shows Skyward's number.

**See it:**

```bash
./start.sh serve            # http://localhost:8787 with write-off buttons
./start.sh dashboard        # read-only copy in data/site/index.html (no buttons), opens it
./deploy/macmini-setup.sh   # serves it at http://kids-dashboard.local for phones on your Wi-Fi
```

In Docker, `./state` is mounted as a volume, so write-offs survive restarts and rebuilds.
Anyone on your Wi-Fi who opens the page can write items off; don't expose that port to
the internet.

**Ports.** Docker uses `HTTP_PORT` (default 80). `./start.sh serve` uses
`DASHBOARD_PORT` (default 8787) or `--port 9000`.

The page shows when Skyward was last checked, and turns amber if that was 2+ days ago.
Skyward can't tell "not turned in" from "turned in, not graded yet", so "past due"
can include work the teacher hasn't graded.

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `SKYWARD_URL` | — | Family Access login page |
| `SKYWARD_USERNAME` / `SKYWARD_PASSWORD` | — | Your login |
| `SCHEDULE_CRON` | `0 15 * * *` | When to run (cron format) |
| `TZ` | `America/Chicago` | Time zone for the schedule (handles daylight saving) |
| `RUN_ON_START` | `false` | Also run as soon as the container starts |
| `FETCH_ASSIGNMENTS` | `true` | Also read assignments (one popup per course) |
| `ASSIGNMENT_DELAY_SECONDS` | `1.5` | Pause between popups, to go easy on Skyward |
| `MAX_RETRIES` / `RETRY_DELAY_MINUTES` | `2` / `10` | Retries if Skyward is down. A rejected password is never retried, to avoid locking your account |

## If a run finds no grades

Skyward pages vary a little by district. If a run logs in but finds no grades, look at
`data/debug/` and `data/raw/`. The page selectors live at the top of
`gradebook/sources/skyward.py`, and you can re-test the parser on a saved page without
logging in again:

```bash
./start.sh parse data/raw/<file>.html
# or: docker compose run --rm scraper python -m gradebook parse data/raw/<file>.html
```

## Project layout (built to extend)

```
gradebook/
  config.py            settings from env / .env
  models.py            GradeRecord: the one shape every part shares
  pipeline.py          one run: sources -> stores, with retries
  scheduler.py         daily cron schedule (APScheduler)
  sources/             where grades come from
    base.py            GradeSource interface
    skyward.py         browser login + navigation (Playwright)
    skyward_parser.py  HTML -> GradeRecords (unit tested)
    skyward_assignments_parser.py  HTML -> AssignmentRecords (unit tested)
  dashboard/           family dashboard (data/site/index.html)
    rules.py           the alert rules and thresholds (plain Python, no AI)
    build.py           CSVs -> metrics -> page
    template.html      the page itself
    writeoffs.py       write-off list (state/writeoffs.json)
    server.py          small web server: the page + write-off API (standard library only)
  storage/             where grades go
    base.py            GradeStore interface
    csv_store.py       CSV files (grades and assignments)
tests/                 parser and CSV tests with a made-up sample page
```

To add something new, write a class that implements `GradeSource` (e.g. assignments,
attendance) or `GradeStore` (e.g. SQLite, Google Sheets, email alerts) and register it in
`pipeline.py`.

## Development

This is a [uv](https://docs.astral.sh/uv/) project: dependencies are pinned in
`pyproject.toml` and locked in `uv.lock`.

```bash
uv sync                          # create .venv with app + dev dependencies
uv run playwright install chromium
uv run pytest
uv add <package>                 # add a dependency (updates uv.lock)
```

Keep the `playwright` version in `pyproject.toml` the same as the Playwright image tag in
the `Dockerfile`. The Docker image installs with `uv sync --frozen --no-dev`.
