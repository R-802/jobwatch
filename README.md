# Rocket Lab job watch

Checks Rocket Lab's job board every 30 minutes and emails you when a new
avionics / electronics / hardware-technician role opens in Auckland.
It runs free on GitHub Actions, so your computer doesn't need to be on.

## Setup (about 10 minutes)

### 1. Get a Gmail app password
The bot sends email from your Gmail account to itself (or to any address you choose).

1. Turn on 2-Step Verification for your Google account, if it isn't on already.
2. Go to https://myaccount.google.com/apppasswords, create an app password
   called "job watch", and copy the 16-character code.

(Outlook/Fastmail/etc. work too: set `SMTP_HOST` and `SMTP_PORT` secrets for your provider.)

### 2. Make a **private** GitHub repo
Create a new private repo (e.g. `rocketlab-job-watch`) and upload these files,
keeping the folder structure:

```
rocketlab_watch.py
.github/workflows/watch.yml
README.md
```

Use a private repo: GitHub pauses scheduled jobs in public repos that go quiet for 60 days.
Checking every 30 min uses about 1,450 of the 2,000 free Actions minutes a private repo gets each month.

### 3. Add your secrets
In the repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Name        | Value                                   |
|-------------|-----------------------------------------|
| `SMTP_USER` | your Gmail address                      |
| `SMTP_PASS` | the 16-character app password           |
| `EMAIL_TO`  | (optional) where alerts go, if not your Gmail |

### 4. Allow the bot to save its memory
**Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save.

### 5. Start it
**Actions** tab → enable workflows if asked → **Rocket Lab job watch** → **Run workflow**.

Within a minute you should get a "watcher is running" email listing the matching
roles open right now. After that, you'll only get an email when a new one appears.

## Tweaking what it watches
Edit the lists near the top of `rocketlab_watch.py`:

- `LOCATIONS`: add `"NZ"` to include Mahia/Warkworth, or `""` for everywhere.
- `TITLE_KEYWORDS`: regexes matched against the job title.
- `DISCIPLINE_KEYWORDS`: matched against Rocket Lab's "Job Discipline" field.
- `EXCLUDE_KEYWORDS`: e.g. uncomment `\bprincipal\b` to skip very senior roles.

To change the frequency, edit the `cron` line in `.github/workflows/watch.yml`.
Going more often than every 30 min will exceed the free minutes on a private repo.

## Running it on your own machine instead
```
SMTP_USER=you@gmail.com SMTP_PASS=xxxx python3 rocketlab_watch.py
python3 rocketlab_watch.py --dry-run   # see what matches without sending
```
Then put it in cron / Task Scheduler to run on a schedule.
