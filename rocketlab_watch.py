#!/usr/bin/env python3
"""
Rocket Lab job watcher.

Checks Rocket Lab's public Greenhouse job feed, filters for roles you care
about, and emails you any that it hasn't seen before.

Standard library only - no pip installs needed.

Alerts: if SMTP_USER + SMTP_PASS are set it emails you; otherwise (in GitHub
Actions) it opens a GitHub issue, which GitHub emails you about.

Email config (optional) comes from environment variables:
  SMTP_HOST   (default smtp.gmail.com)
  SMTP_PORT   (default 465)
  SMTP_USER   your email login, e.g. you@gmail.com
  SMTP_PASS   an app password (NOT your normal password)
  EMAIL_TO    where to send alerts (defaults to SMTP_USER)

Usage:
  python rocketlab_watch.py              # normal run
  python rocketlab_watch.py --dry-run    # print the email instead of sending, don't save state
  python rocketlab_watch.py --feed f.json  # use a local feed file (for testing)
"""

import argparse
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

# --------------------------------------------------------------------------
# WHAT TO WATCH FOR - edit these to taste
# --------------------------------------------------------------------------

FEED_URL = "https://boards-api.greenhouse.io/v1/boards/rocketlab/jobs"

# A job's location must contain one of these (case-insensitive).
# Add "NZ" to cover Mahia / Warkworth too, or "" to watch everywhere.
LOCATIONS = ["Auckland"]

# A job matches if its TITLE matches any of these regexes (case-insensitive)...
TITLE_KEYWORDS = [
    r"avionic",                 # Avionics Engineer, Avionics Technician, ...
    r"electronic",              # Electronics Engineer / Technician
    r"electrical",
    r"hardware",                # Hardware Engineer, Hardware-in-the-loop
    r"\bHITL\b",                # Senior HITL Technician
    r"\bPCBA?\b",
    r"embedded",
    r"firmware",
    r"\bFPGA\b",
    r"\bRF\b",
    r"radio frequency",
    r"instrumentation",
    r"power (systems?|electronics)",
    r"harness",
    r"test technician",         # Production Test Technician
    r"integration technician",  # Vehicle Integration Technician
]

# ...OR its "Job Discipline" field contains one of these.
DISCIPLINE_KEYWORDS = ["avionic", "electric", "electronic"]

# Skip anything whose title matches these, even if it matched above.
EXCLUDE_KEYWORDS = [
    # r"\bintern\b",
    # r"\bprincipal\b",
]

# How alerts look in your inbox.
SUBJECT_PREFIX = "🚀 ROCKET LAB JOB ALERT:"
SENDER_NAME = "Rocket Lab Job Alert"

STATE_FILE = Path(__file__).with_name("seen_jobs.json")

# --------------------------------------------------------------------------


def fetch_feed(url, attempts=3):
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "rocketlab-job-watch/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # network blip, 5xx, bad JSON...
            last_err = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"Could not fetch job feed after {attempts} tries: {last_err}")


def discipline_of(job):
    for m in job.get("metadata") or []:
        if (m.get("name") or "").lower().startswith("job discipline"):
            v = m.get("value")
            if isinstance(v, list):
                return ", ".join(str(x) for x in v)
            return str(v) if v else ""
    return ""


def is_match(job):
    title = job.get("title", "")
    location = (job.get("location") or {}).get("name", "")
    discipline = discipline_of(job)

    if LOCATIONS and not any(loc.lower() in location.lower() for loc in LOCATIONS):
        return False
    if any(re.search(p, title, re.I) for p in EXCLUDE_KEYWORDS):
        return False
    if any(re.search(p, title, re.I) for p in TITLE_KEYWORDS):
        return True
    if discipline and any(k in discipline.lower() for k in DISCIPLINE_KEYWORDS):
        return True
    return False


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None  # first run


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def nice_date(iso):
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%a %d %b %Y")
    except ValueError:
        return iso


def build_email(jobs, first_run):
    n = len(jobs)
    if first_run:
        subject = f"{SUBJECT_PREFIX} watcher running - {n} matching role{'s' if n != 1 else ''} open now"
        intro = ("Your Rocket Lab job watcher is set up. These matching roles are open right now. "
                 "From here on you'll only get an email when a new one appears.")
    else:
        subject = f"{SUBJECT_PREFIX} " + "; ".join(j["title"] for j in jobs[:3])
        if n > 3:
            subject += f" (+{n - 3} more)"
        intro = f"{n} new matching role{'s' if n != 1 else ''} just appeared. Apply early!"

    jobs = sorted(jobs, key=lambda j: j.get("first_published") or "", reverse=True)

    text_lines = [intro, ""]
    html_items = []
    for j in jobs:
        loc = (j.get("location") or {}).get("name", "")
        disc = discipline_of(j)
        posted = nice_date(j.get("first_published"))
        details = " | ".join(x for x in [loc, disc, f"posted {posted}" if posted else ""] if x)
        text_lines += [f"* {j['title']}", f"  {details}", f"  {j['absolute_url']}", ""]
        html_items.append(
            f'<li style="margin-bottom:12px"><a href="{html.escape(j["absolute_url"])}" '
            f'style="font-size:16px;font-weight:bold">{html.escape(j["title"])}</a><br>'
            f'<span style="color:#666">{html.escape(details)}</span></li>'
        )
    text_lines.append(f"Checked {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    body_html = (f"<p>{html.escape(intro)}</p><ul style='padding-left:18px'>{''.join(html_items)}</ul>"
                 f"<p style='color:#999;font-size:12px'>Sent by your rocketlab-job-watch bot.</p>")
    return subject, "\n".join(text_lines), body_html


def send_email(subject, text, body_html):
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    if not user or not password:
        raise RuntimeError("SMTP_USER and SMTP_PASS must be set")
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    to = os.environ.get("EMAIL_TO") or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((SENDER_NAME, user))
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)


def open_github_issue(subject, text):
    """Alert via a GitHub issue - GitHub emails the repo owner about it. No passwords needed."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise RuntimeError("No email settings and not running in GitHub Actions - nowhere to send the alert")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": subject, "body": text}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "rocketlab-job-watch/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("Opened issue:", json.load(r).get("html_url"))


def notify(subject, text, body_html):
    if os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS"):
        send_email(subject, text, body_html)
        print("Email sent.")
    else:
        open_github_issue(subject, text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print email, don't send or save state")
    ap.add_argument("--feed", help="read feed from a local JSON file instead of the web")
    args = ap.parse_args()

    feed = json.loads(Path(args.feed).read_text()) if args.feed else fetch_feed(FEED_URL)
    all_jobs = feed.get("jobs", [])
    if not all_jobs:
        print("Feed returned no jobs - probably a hiccup, skipping this run.")
        return

    matches = [j for j in all_jobs if is_match(j)]
    state = load_state()
    first_run = state is None
    seen = {} if first_run else state.get("seen", {})

    new = [j for j in matches if str(j["id"]) not in seen]
    print(f"{len(all_jobs)} jobs in feed, {len(matches)} match your filters, {len(new)} new.")
    for j in new:
        print(f"  NEW: {j['title']}  ->  {j['absolute_url']}")

    if new:
        subject, text, body_html = build_email(new, first_run)
        if args.dry_run:
            print("\n--- EMAIL (dry run) ---\nSubject:", subject, "\n")
            print(text)
            return
        notify(subject, text, body_html)

    if args.dry_run:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for j in new:
        seen[str(j["id"])] = {"title": j["title"], "first_seen": now}
    if new or first_run:
        save_state({"seen": seen})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
