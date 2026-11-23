# Kids Gradebook Tracker

Reads each child's Skyward Family Access gradebook once a day, saves grades and
assignments to CSV, and serves a family dashboard on your home Wi-Fi: **kids mode**
(Creature Island) for the kids and a PIN-locked view for grown-ups. Runs in Docker on a
Mac. Everything is plain rules: no AI calls, no running cost.

## Quick start

```bash
cp .env.example .env    # add SKYWARD_USERNAME, SKYWARD_PASSWORD and a 4-digit DASH_PARENT_PIN
```

`.env` is git-ignored; credentials never go in code.

**Run locally** (needs [uv](https://docs.astral.sh/uv/): `brew install uv`). `start.sh`
installs dependencies and Chromium on first use and writes to `./data` and `./state`.

```bash
./start.sh                  # scrape once now (HEADLESS=false to watch the browser)
./start.sh serve            # dashboard at http://localhost:8787
./start.sh schedule         # scrape daily on SCHEDULE_CRON until Ctrl+C
./start.sh test             # run the tests
./start.sh dashboard        # rebuild the read-only classic page and open it
./start.sh parse data/raw/<file>.html                    # re-parse a saved page, no login
./start.sh parse-assignments data/raw/assignments_*.html data/raw/gradebook_*.html
```

A one-off `./start.sh` doesn't retry on failure (`MAX_RETRIES=0`), so problems show up
right away.

**Host it at home**: follow **[docs/MAC_MINI_SETUP.md](docs/MAC_MINI_SETUP.md)** (setup,
HTTPS, daily text alert, troubleshooting). In short:

```bash
./deploy/macmini-setup.sh   # builds and starts the containers, serves https://kids-dashboard.local
```

| Container | What it does |
|---|---|
| `scraper` | Checks Skyward daily on `SCHEDULE_CRON` (3:00 PM Central), then rebuilds the classic page |
| `dashboard` | Always on, through the shared home server (Caddy, ports 80/443); also directly on `HTTP_PORT` (8787) |

```bash
docker compose ps                                                          # what's running
docker compose logs -f scraper                                             # watch a scrape
docker compose run --rm -e MAX_RETRIES=0 scraper python -m gradebook run   # scrape right now
git pull && ./deploy/macmini-setup.sh                                      # update
```

With more than one child on the account, the scraper selects each child in turn
(Skyward hides the gradebook under "All Students").

## The dashboard

### Kids mode (`/`)

Each child taps their picture on the opening screen.

- **Tonight's quests**: this term's missing work plus anything due today or tomorrow.
  **I did it!** marks it done (it turns gold when Skyward shows a score).
  **Can't do this?** asks a grown-up to write it off.
- **The island**: one creature per class showing the grade now and the change since the
  last check (`DASH_TREND_DAYS`, default 7). Missing work makes a creature *hungry* or
  *sleepy* (`KIDS_MOODS`), never sad. Creatures hatch and grow with stars.
- **New grades**, **Top subjects** with a Comeback Kid, **My progress** charts per class,
  an **I'm done for tonight** recap, and a weekly **Friday Show**.
- **Team star bank**: one golden bar both kids fill (1 star per graded item, +1 for 90+).
  Grown-ups set the rewards (default 100 = Pizza night, 200 = Netflix House).
- **Profiles**: name, character or photo, and color; kids can swap and name creatures.

The kids are never compared with each other.

### Grown-up view (PIN)

Tap **Grown-ups** on the opening screen and enter `DASH_PARENT_PIN` (4 digits; 1234 if
unset). Five wrong tries lock the keypad for 5 minutes; a session lasts 12 hours.

- Write-off requests to approve, and "I did it!" taps still waiting for a score
- **Written off** log with undo, so nothing gets lost
- Rewards: edit levels, cash in, start a new season
- Per child: where they're lagging, every class with drill-down to each assignment, and
  grade charts across progress reports and quarters
- The older dashboard at **`/classic`**

Lagging alerts are fixed rules in `gradebook/dashboard/rules.py`:

| Alert | Default rule | Setting |
|---|---|---|
| Failing | class grade below 70 | `DASH_FAILING_BELOW` |
| Below a B | class grade below 80 | `DASH_WATCH_BELOW` |
| Doing well | class grade 90+ | `DASH_STRONG_AT` |
| Dropped | 10+ points below last quarter | `DASH_DROP_POINTS` |
| Tests vs daily work | averages 10+ points apart | `DASH_GAP_POINTS` |

**Write-offs** remove an item from quests, counts, averages and alerts (Skyward's own
grade doesn't change). Teacher-marked "Excused" items are treated the same way
automatically. Weekly teacher-scored items (participation and the like) are hidden;
change the pattern with `DASH_TEACHER_SCORED`.

**Daily family text**: `deploy/send-alerts.sh` sends it from the Mac through Messages,
in the creatures' voices ("Bruno 🐻 is snoozing 💤 Mile (PE) is past due. Turn it in and
Bruno wakes up!"). It skips quiet days and items already tapped or asked about. Preview
with `bash deploy/send-alerts.sh --dry-run`.

Skyward can't tell "not turned in" from "not graded yet", so past due can include work
the teacher hasn't graded. The page notes when data is 2+ days old. Don't expose the
dashboard to the internet.

## Data

| Path | What it is |
|---|---|
| `data/grades_latest.csv`, `grades_history.csv`, `snapshots/grades_<date>.csv` | Grades: latest run, every run, one file per day |
| `data/assignments_*` | Assignments, same three forms |
| `data/raw/*.html` | Saved Skyward pages, for re-parsing (`SAVE_RAW_HTML`) |
| `data/site/index.html` | Read-only classic dashboard |
| `data/debug/failure_*` | Screenshot and HTML when a run fails |
| `state/family.json` | Kids' taps, requests, profiles, creatures, rewards |
| `state/writeoffs.json` | Written-off items |

`state/` is never touched by a scrape and survives Docker rebuilds.

**Grades**: one row per student, course and term (PR1, Q1, S1...):
`scraped_at, student, student_id, course, course_id, period, teacher, term, grade, source`.

**Assignments** (`FETCH_ASSIGNMENTS=true`): for each course the scraper opens the latest
graded term's popup, pausing `ASSIGNMENT_DELAY_SECONDS` between courses. Older items from
the main page are added with `detail_source=gradebook`.
`scraped_at, student, student_id, course, course_id, term, category, assignment,
assignment_id, due_date, score, points_earned, points_possible, flags, status,
detail_source, notes, source`.

| `status` | Meaning |
|---|---|
| `done` | Has a score (including 0) |
| `missing` | Skyward marks it Missing |
| `not_turned_in` | No score, past due, not marked missing (often just not graded yet) |
| `not_yet_due` | No score, due today or later |
| `exempt` | No Count with no score, or Excused |

`flags` lists Skyward's marks (`missing`, `no count`, `absent`, `late`, `exempt`,
`excused`); `notes` keeps teacher comments.

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `SKYWARD_URL`, `SKYWARD_USERNAME`, `SKYWARD_PASSWORD` | | Family Access login |
| `SCHEDULE_CRON` / `TZ` | `0 15 * * *` / `America/Chicago` | When to scrape |
| `RUN_ON_START` | `false` | Also scrape when the container starts |
| `FETCH_ASSIGNMENTS` / `ASSIGNMENT_DELAY_SECONDS` | `true` / `1.5` | Read assignments, gently |
| `SAVE_RAW_HTML` | `true` | Keep copies of Skyward pages |
| `MAX_RETRIES` / `RETRY_DELAY_MINUTES` | `2` / `10` | Retries when Skyward is down. A rejected password is never retried, to avoid lockout |
| `DASH_PARENT_PIN` | `1234` | 4-digit grown-up PIN |
| `KIDS_MOODS` | by grade | e.g. `Dithya=hungry,Manya=sleepy` (default: hungry for 5th grade and below) |
| `DASH_TREND_DAYS` | `7` | How far back the creature arrows compare |
| `DASH_*` thresholds | see table above | Lagging alert rules |
| `HTTP_PORT` / `DASHBOARD_PORT` | `8787` | Direct port in Docker / for `./start.sh serve` |
| `ALERT_DUE_DAYS` / `ALERT_LINK` | `2` / `https://kids-dashboard.local` | Daily text: days ahead, link at the end |
| `LOG_LEVEL` | `INFO` | Logging |

## If a run finds no grades

Check `data/debug/` and `data/raw/`. Page selectors are at the top of
`gradebook/sources/skyward.py`; re-test the parser on a saved page with
`./start.sh parse data/raw/<file>.html` (no login).

## Project layout

```
gradebook/
  config.py, models.py   settings; the shared record shapes
  pipeline.py            one run: sources -> stores (with retries) -> classic page
  scheduler.py           daily schedule
  sources/               Skyward login, navigation and HTML parsers (Playwright)
  storage/               CSV files
  dashboard/
    server.py            web server and API (standard library only)
    kids.py, kids.html   kids mode data and page (also the grown-up view)
    family.py            state/family.json
    writeoffs.py         state/writeoffs.json
    rules.py             alert rules and thresholds
    alerts.py            daily family text
    build.py, template.html   classic dashboard
deploy/                  Mac mini setup and the Messages alert
tests/                   pytest, with made-up sample data
```

To add a source (attendance) or store (SQLite, Sheets), implement `GradeSource` or
`GradeStore` and register it in `pipeline.py`.

## Development

```bash
uv sync && uv run playwright install chromium
uv run pytest
uv add <package>          # updates uv.lock
```

Keep the `playwright` version in `pyproject.toml` equal to the Playwright image tag in
the `Dockerfile`.
