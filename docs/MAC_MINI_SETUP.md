# Mac mini setup, step by step

This puts the whole thing on the Mac mini:

- **scraper** container: checks Skyward every day at **3:00 PM**.
- **dashboard** container: always on at **http://kids-dashboard.local** for every phone
  and laptop on your home Wi-Fi.
- **family alert**: at **3:30 PM** the Mac mini texts what's due in the next 2 days and
  what's past due. iMessage goes to the Apple devices, and SMS goes to the Pixel through
  your iPhone. No message on days with nothing to report.

Everything is free. It needs about 30 minutes, mostly waiting for Docker.

---

## 1. Prepare the Mac mini (once)

1. **Sign in with your Apple ID** (System Settings > Apple Account), and open **Messages**
   once. Check Messages > Settings > iMessage shows your account.
2. **Automatic login**: System Settings > Users & Groups > "Automatically log in as" >
   your user. The containers and the alert run inside your login, so the Mac mini has to
   reach the desktop by itself after a restart.
   (If FileVault is on, macOS won't allow automatic login. Turn FileVault off, or log in
   by hand after each power cut.)
3. **Fixed IP address**, so the backup address never changes:
   System Settings > Network > Wi-Fi or Ethernet > Details > TCP/IP >
   Configure IPv4: "Using DHCP with manual address", and pick an address outside your
   router's range (for example `192.168.1.250`). Ethernet into your switch is best.
4. **Install Docker Desktop** from https://www.docker.com/products/docker-desktop/ (Apple
   silicon version). Open it once, accept the terms, then in its Settings > General turn on
   **Start Docker Desktop when you sign in**.
5. **Install the Xcode command line tools** (gives you `git`):
   ```bash
   xcode-select --install
   ```

## 2. Get the code

```bash
cd ~
git clone https://github.com/gururajtoyota/kids-work-tracker.git
cd kids-work-tracker
```

(It's a private repo, so git asks for your GitHub login. Use a personal access token as
the password, or `gh auth login` if you have the GitHub CLI.)

## 3. Start the dashboard and the daily scrape

```bash
bash deploy/macmini-setup.sh
```

It will:

1. check Docker is running,
2. ask for your Skyward username and password (saved only in `.env` on this Mac),
3. set the daily scrape to 3:00 PM,
4. keep the Mac mini awake and restarting after a power cut (asks for your Mac password),
5. build and start the two containers,
6. offer to run one Skyward check right away (say **y** the first time),
7. announce `kids-dashboard.local` on your network,
8. print the addresses to use.

Check it: open **http://kids-dashboard.local** on your iPhone (Safari) and on the Pixel
(Chrome). If a device can't open it, use the IP address the script printed, e.g.
`http://192.168.1.250`.

Put it on each home screen: iPhone Safari > Share > **Add to Home Screen**.
Pixel Chrome > menu (⋮) > **Add to Home screen**.

## 4. Turn on SMS for the Pixel (on your iPhone, once)

iPhone: Settings > Apps > Messages > **Text Message Forwarding** > turn on the Mac mini.
(On older iOS: Settings > Messages > Text Message Forwarding.) The iPhone has to be on and
on the internet when the alert goes out, which it normally is.

## 5. Set up the daily family alert

```bash
bash deploy/setup-alerts.sh
```

It asks:

| Question | Example |
|---|---|
| iMessage to (Apple devices) | `+15125550101,+15125550102` |
| Existing iMessage group chat id (optional) | leave blank, see below |
| SMS to (the Pixel) | `+15125550103` |
| Send time | `15:30` |

Then it shows today's alert, sends a **test message** to everyone, and runs the job once.
macOS will ask to let Terminal, and then `bash`/`osascript`, control **Messages**: click
**OK** both times. Check every phone got the test.

**Want it in your existing all-Apple family group instead of one-by-one?**
```bash
bash deploy/send-alerts.sh --list-chats     # find the group's id (looks like iMessage;+;chat1234...)
bash deploy/setup-alerts.sh                 # paste that id at the group question
```
A group that includes the Pixel is an SMS group, not iMessage. Scripts can't send to
those reliably, so the Pixel gets its own text.

## 6. Done. What happens every day

| Time | What |
|---|---|
| 3:00 PM | `scraper` logs in to Skyward once and saves the grades |
| 3:30 PM | the Mac mini sends the alert, only if something is due in 2 days or past due |
| any time | anyone on Wi-Fi opens http://kids-dashboard.local |

Example alert:
```
📚 Homework check, Mon Nov 23
Dithya: all clear ✓
Manya:
  • Unit 4 Quiz (Honors Math 7A) due tomorrow
  • 2 past due with no score
http://kids-dashboard.local
```
Writing an item off on the dashboard also removes it from the alert.

---

## Docker commands you'll use

Run these in `~/kids-work-tracker`.

| What | Command |
|---|---|
| What's running | `docker compose ps` |
| Watch the scraper (shows next run time) | `docker compose logs -f scraper` |
| Dashboard log | `docker compose logs -f dashboard` |
| Scrape right now | `docker compose run --rm -e MAX_RETRIES=0 scraper python -m gradebook run` |
| Restart both | `docker compose restart` |
| Stop both | `docker compose down` |
| Start both | `docker compose up -d` |
| Update to the latest code | `git pull && bash deploy/macmini-setup.sh` |
| Rebuild after changing `.env` | `docker compose up -d --build` |
| Today's alert text, without sending | `bash deploy/send-alerts.sh --dry-run` |
| Send the alert now | `bash deploy/send-alerts.sh` |
| Change alert recipients or time | `bash deploy/setup-alerts.sh` |
| Alert log | `tail -50 ~/Library/Logs/kids-dashboard-alerts.log` |
| Name announcement log | `tail -50 ~/Library/Logs/kids-dashboard-mdns.log` |

## Files on the Mac mini

| File | What it is | In git? |
|---|---|---|
| `.env` | Skyward login, schedule, ports, alert thresholds | no |
| `deploy/alerts.env` | who gets alerts and when | no |
| `data/` | scraped grades and assignments | no |
| `state/writeoffs.json` | items you wrote off, with reasons | no |
| `~/Library/LaunchAgents/home.kids-dashboard.mdns.plist` | announces kids-dashboard.local | no |
| `~/Library/LaunchAgents/home.kids-dashboard.alerts.plist` | sends the 3:30 PM alert | no |

Back up `.env`, `deploy/alerts.env` and `state/` if you ever move to a new Mac.

## Settings you might change (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `SCHEDULE_CRON` | `0 15 * * *` | when to scrape (minute hour …) |
| `HTTP_PORT` | `80` | dashboard port on the Mac mini |
| `ALERT_DUE_DAYS` | `2` | how far ahead the alert looks |
| `ALERT_LINK` | `http://kids-dashboard.local` | link at the end of the alert (blank = none) |
| `DASH_FAILING_BELOW` etc. | `70` … | dashboard alert thresholds |

After editing `.env`: `docker compose up -d`.

## If something goes wrong

- **The page won't open on a phone.** Try the IP address. Check `docker compose ps` shows
  both containers "running". If you use the macOS firewall, allow Docker.
- **kids-dashboard.local doesn't work but the IP does.** `tail ~/Library/Logs/kids-dashboard-mdns.log`.
  Re-run `bash deploy/macmini-setup.sh`.
- **No alert came.** `bash deploy/send-alerts.sh --dry-run`. If it prints "no message today",
  there was nothing to report. Otherwise check the alert log for "FAILED".
- **The Pixel didn't get the SMS.** Check Text Message Forwarding (step 4) and that the
  iPhone was online.
- **Permission error from Messages** in the log: System Settings > Privacy & Security >
  Automation > allow Terminal / bash / osascript to control Messages.
- **Scrape failed.** `docker compose logs scraper`, and look in `data/debug/`.
  A rejected password is never retried, to protect your Skyward account.

## Removing it

```bash
bash deploy/setup-alerts.sh --remove      # stop the alert
bash deploy/macmini-setup.sh --remove     # stop containers and the .local name
```
Your `data/` and `state/` folders are kept.

## Testing on a laptop first

Same steps 2, 3 and 5 on the laptop. When done, run both `--remove` commands there, so the
laptop stops scraping, stops sending alerts and stops claiming `kids-dashboard.local`.
