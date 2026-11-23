# Mac mini setup, step by step

This puts the whole thing on the Mac mini:

- **home server** (the `home-server` folder): one **Caddy** container on ports 80 and 443.
  Every app gets its own name, `https://<name>.local`, with a certificate from Caddy's own
  **private certificate authority** (the "Home Server" CA). The CA lives only on the Mac
  mini; nothing is bought and nothing goes to the internet. Each phone and laptop trusts
  it once, then every app shows the padlock.
- **scraper** container: checks Skyward every day at **3:00 PM**.
- **dashboard** container: always on at **https://kids-dashboard.local**, the first app.
- **family alert**: at **3:30 PM** the Mac mini texts what's due in the next 2 days and
  what's past due. iMessage goes to the Apple devices, and SMS goes to the Pixel through
  your iPhone. No message on days with nothing to report.

```
 iPhone / Pixel / MacBook                      Mac mini (fixed IP, e.g. 192.168.1.250)
 https://kids-dashboard.local  ─┐            ┌─────────────────────────────────────────┐
 https://recipes.local (later) ─┼─ :443 ───> │ Caddy "home-proxy" ─┬─> kids-dashboard  │
 https://192.168.1.250         ─┘            │  (Home Server CA)   └─> recipes-web ... │
                                             │ Bonjour: announces every <name>.local   │
                                             └─────────────────────────────────────────┘
```

Everything is free. It needs about 45 minutes, mostly waiting for Docker.

---

## 1. Prepare the Mac mini (once)

1. **Sign in with your Apple ID** (System Settings > Apple Account), and open **Messages**
   once. Check Messages > Settings > iMessage shows your account.
2. **Automatic login**: System Settings > Users & Groups > "Automatically log in as" >
   your user. The containers and the alert run inside your login, so the Mac mini has to
   reach the desktop by itself after a restart.
   (If FileVault is on, macOS won't allow automatic login. Turn FileVault off, or log in
   by hand after each power cut.)
3. **Fixed IP address**, so the address and its certificate never change:
   System Settings > Network > Wi-Fi or Ethernet > Details > TCP/IP >
   Configure IPv4: "Using DHCP with manual address", and pick an address outside your
   router's range (for example `192.168.1.250`). Ethernet into your switch is best.
4. **Install Docker Desktop** from https://www.docker.com/products/docker-desktop/ (Apple
   silicon version). Open it once, accept the terms, then in its Settings > General turn on
   **Start Docker Desktop when you sign in**. Caddy runs inside Docker, so there's nothing
   else to install for it (no Homebrew needed).
5. **Install the Xcode command line tools** (gives you `git`):
   ```bash
   xcode-select --install
   ```

## 2. Get the code

Two folders, side by side in the same parent folder:

```bash
mkdir -p ~/VsCode && cd ~/VsCode
git clone https://github.com/gururajtoyota/home-server.git
git clone https://github.com/gururajtoyota/kids-work-tracker.git
```

(They're private repos, so git asks for your GitHub login. Use a personal access token as
the password, or `gh auth login` if you have the GitHub CLI.) If home-server lives
somewhere else, run step 4 as `HOME_SERVER_DIR=/path/to/home-server bash deploy/macmini-setup.sh`.

## 3. Install Caddy, the home server

```bash
cd ~/VsCode/home-server
bash bin/setup.sh
```

It will:

1. check Docker is running,
2. save this Mac's IP in `home-server/.env` (so `https://<ip>` gets a certificate too),
3. create the shared Docker network `home-proxy` and start Caddy (container `home-proxy`,
   image `caddy:2.8.4-alpine`) on ports **80** and **443**,
4. create the **Home Server CA** in `home-server/caddy-data/` and copy its public
   certificate to `home-server/certs/home-ca.crt`,
5. install a LaunchAgent that announces every app's `.local` name on your network,
6. list the apps (none yet; step 4 adds the dashboard).

Check it:

```bash
docker ps --filter name=home-proxy        # STATUS should say "Up"
curl -s http://localhost/home-ca.crt | head -1    # -----BEGIN CERTIFICATE-----
```

**Back up `home-server/caddy-data/`** somewhere private (an encrypted USB stick or your
password manager's file storage). It holds the CA's private key. Never commit it (it's in
`.gitignore`). If it's lost, Caddy makes a new CA and every device has to trust it again.

## 4. Start the dashboard and the daily scrape

```bash
cd ~/VsCode/kids-work-tracker
bash deploy/macmini-setup.sh
```

It will:

1. check Docker is running,
2. ask for your Skyward username and password (saved only in `.env` on this Mac),
3. set the daily scrape to 3:00 PM,
4. keep the Mac mini awake and restarting after a power cut (asks for your Mac password),
5. build and start the two containers (the dashboard also answers directly on port 8787),
6. offer to run one Skyward check right away (say **y** the first time),
7. run the home server setup again (safe to repeat) and register
   `https://kids-dashboard.local` with it. The plain IP goes to the dashboard too,
8. check the page answers over https with a valid home certificate, and print the addresses.

## 5. Trust the home certificate on each device (once per device)

Until a device trusts the Home Server CA it shows "Not private" / "Your connection is not
private". Do this once on each device; it then covers every app on the Mac mini.
The download link is plain http on purpose, so a new device can fetch it:
**http://192.168.1.250/home-ca.crt** (use your Mac mini's IP;
`http://kids-dashboard.local/home-ca.crt` works too).

**Mac mini itself:**
```bash
bash ~/VsCode/home-server/bin/trust-this-mac.sh      # asks for your Mac password
```

**MacBook:** open the link in Safari or Chrome; `home-ca.crt` lands in Downloads. Then either
- double-click it > Keychain Access opens > add it to **System** > double-click
  "Home Server - 2026 ECC Root" > **Trust** > "When using this certificate": **Always Trust**
  > close the window and enter your password, or
- in Terminal: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/Downloads/home-ca.crt`

Quit and reopen the browser.

**iPhone / iPad** (Safari, not Chrome, for the download):
1. Open the link. Tap **Allow** at "This website is trying to download a configuration
   profile", then **Close**.
2. Settings > General > **VPN & Device Management** > "Home Server - 2026 ECC Root" >
   **Install** (enter your passcode) > Install > Done.
   (Or tap "Profile Downloaded" at the top of Settings.)
3. Settings > General > About > **Certificate Trust Settings** > turn **on** "Home Server -
   2026 ECC Root" > Continue. Without this step Safari still warns.

**Pixel (Android 14/15):**
1. Open the link in Chrome; `home-ca.crt` downloads.
2. Settings > Security & privacy > More security & privacy > **Encryption & credentials** >
   **Install a certificate** > **CA certificate** > Install anyway > enter the PIN > pick
   `home-ca.crt` from Downloads.
   (Menu names vary a little: search Settings for "CA certificate".)
3. Chrome uses it right away. Android may show "Network may be monitored"; that's
   expected for a home CA you installed yourself.

Check: open **https://kids-dashboard.local** on each device. You should see the padlock
and no warning. The page opens in kids mode; each child taps their picture. Grown-ups
tap **Grown-ups** on that picker screen and enter `DASH_PARENT_PIN` from `.env`
(4 digits; set it before the kids get the link).

Put it on each home screen: iPhone Safari > Share > **Add to Home Screen**.
Pixel Chrome > menu (⋮) > **Add to Home screen**. (If you added an `http://` shortcut
earlier, delete it and add the https one.)

The CA is valid for 10 years. App certificates renew by themselves every few hours; you
never touch them.

## 6. Turn on SMS for the Pixel (on your iPhone, once)

iPhone: Settings > Apps > Messages > **Text Message Forwarding** > turn on the Mac mini.
(On older iOS: Settings > Messages > Text Message Forwarding.) The iPhone has to be on and
on the internet when the alert goes out, which it normally is.

## 7. Set up the daily family alert

```bash
cd ~/VsCode/kids-work-tracker
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

## 8. Done. What happens every day

| Time | What |
|---|---|
| 3:00 PM | `scraper` logs in to Skyward once and saves the grades |
| 3:30 PM | the Mac mini sends the alert, only if something is due in 2 days or past due |
| any time | anyone on Wi-Fi opens https://kids-dashboard.local |

Example alert:
```
📚 Homework check, Mon Nov 23
Dithya: all clear ✓
Manya:
  • Unit 4 Quiz (Honors Math 7A) due tomorrow
  • 2 past due with no score
https://kids-dashboard.local
```
Writing an item off on the dashboard also removes it from the alert.

## 9. Adding another app later

Every app shares the Mac mini's one IP through the home server; the name in the address
picks the app, and each name gets its own certificate from the same CA (so devices that
already trust it need nothing new). For a new app in `~/VsCode/recipes`:

1. In its `docker-compose.yml`, name the web container and put it on the shared network
   (don't publish port 80 or 443):
   ```yaml
   services:
     web:
       container_name: recipes-web
       networks: [default, home-proxy]
   networks:
     home-proxy:
       external: true
   ```
2. Start it and give it a name:
   ```bash
   cd ~/VsCode/recipes && docker compose up -d
   bash ~/VsCode/home-server/bin/add-app.sh recipes recipes-web:3000
   ```
   (`3000` is the port the app listens on inside its container.)

`https://recipes.local` works a few seconds later on every device. `bash bin/list-apps.sh`
in home-server lists all names. More in `home-server/README.md`.

---

## Commands you'll use

In `~/VsCode/kids-work-tracker`:

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

In `~/VsCode/home-server`:

| What | Command |
|---|---|
| Set up / update / after an IP change | `bash bin/setup.sh` |
| All app names | `bash bin/list-apps.sh` |
| Add / remove an app | `bash bin/add-app.sh <name> <container>:<port>` / `bash bin/remove-app.sh <name>` |
| Caddy log | `docker logs -f home-proxy` |
| Restart Caddy | `docker compose restart` |
| Trust the CA on this Mac | `bash bin/trust-this-mac.sh` |
| Name announcement log | `tail -50 ~/Library/Logs/home-server-mdns.log` |

## Files on the Mac mini

| File | What it is | In git? |
|---|---|---|
| `kids-work-tracker/.env` | Skyward login, schedule, ports, alert thresholds | no |
| `kids-work-tracker/deploy/alerts.env` | who gets alerts and when | no |
| `kids-work-tracker/data/` | scraped grades and assignments | no |
| `kids-work-tracker/state/writeoffs.json` | items you wrote off, with reasons | no |
| `home-server/sites/*.caddy` | one per app name, written by add-app.sh | yes |
| `home-server/caddy-data/` | the Home Server CA (private key!) and app certificates | **never** |
| `home-server/certs/home-ca.crt` | the CA's public certificate, for devices | no |
| `home-server/.env` | this Mac's IP | no |
| `~/Library/LaunchAgents/home.server.mdns.plist` | announces every app's `.local` name | no |
| `~/Library/LaunchAgents/home.kids-dashboard.alerts.plist` | sends the 3:30 PM alert | no |

Back up `kids-work-tracker/.env`, `deploy/alerts.env`, `state/` and
`home-server/caddy-data/` if you ever move to a new Mac. Copying `caddy-data/` to the new
Mac before step 3 keeps the same CA, so no device needs re-trusting.

## Settings you might change (`kids-work-tracker/.env`)

| Setting | Default | Meaning |
|---|---|---|
| `SCHEDULE_CRON` | `0 15 * * *` | when to scrape (minute hour …) |
| `HTTP_PORT` | `8787` | direct dashboard port, no https (ports 80/443 belong to the home server) |
| `ALERT_DUE_DAYS` | `2` | how far ahead the alert looks |
| `ALERT_LINK` | `https://kids-dashboard.local` | link at the end of the alert (blank = none) |
| `DASH_FAILING_BELOW` etc. | `70` … | dashboard alert thresholds |

After editing `.env`: `docker compose up -d`.

## If something goes wrong

- **"Not private" / certificate warning.** That device doesn't trust the CA yet (step 5).
  On iPhone, the usual miss is Certificate Trust Settings (step 5, iPhone 3). If you
  tested on a laptop first, that laptop had its own CA: trust the Mac mini's too.
- **The page won't open on a phone.** Try `https://<ip>`, then `http://<ip>:8787`. Check
  `docker compose ps` shows both containers "running" and `docker ps` shows `home-proxy`.
  If you use the macOS firewall, allow Docker.
- **`http://<ip>:8787` works but the name and plain IP don't.** The home server is down or
  can't reach the dashboard: `docker logs home-proxy`, then re-run `bash deploy/macmini-setup.sh`.
- **kids-dashboard.local doesn't work but the IP does.** `tail ~/Library/Logs/home-server-mdns.log`.
  Re-run `bash deploy/macmini-setup.sh`.
- **The IP changed** (and `https://<ip>` warns). Fix the IP (step 1.3), then
  `bash ~/VsCode/home-server/bin/setup.sh`.
- **No alert came.** `bash deploy/send-alerts.sh --dry-run`. If it prints "no message today",
  there was nothing to report. Otherwise check the alert log for "FAILED".
- **The Pixel didn't get the SMS.** Check Text Message Forwarding (step 6) and that the
  iPhone was online.
- **Permission error from Messages** in the log: System Settings > Privacy & Security >
  Automation > allow Terminal / bash / osascript to control Messages.
- **Scrape failed.** `docker compose logs scraper`, and look in `data/debug/`.
  A rejected password is never retried, to protect your Skyward account.

## Removing it

```bash
cd ~/VsCode/kids-work-tracker
bash deploy/setup-alerts.sh --remove        # stop the alert
bash deploy/macmini-setup.sh --remove       # stop containers and the .local name
bash ../home-server/bin/setup.sh --remove   # stop the home server (only if no other apps use it)
```
Your `data/`, `state/` and `caddy-data/` folders are kept.
To stop trusting the CA on a Mac: `bash ~/VsCode/home-server/bin/trust-this-mac.sh --remove`.
On iPhone: Settings > General > VPN & Device Management > the profile > Remove.

## Testing on a laptop first

Same steps 2 to 5 on the laptop (the laptop gets its own test CA). When done, run all
three `--remove` commands there, so the laptop stops scraping, stops sending alerts and
stops claiming `kids-dashboard.local`. Then on the iPhone remove the laptop's profile
(Settings > General > VPN & Device Management) and install the Mac mini's one.
Or, to keep a single CA, copy the laptop's `home-server/caddy-data/` folder to the
Mac mini before step 3 there.
