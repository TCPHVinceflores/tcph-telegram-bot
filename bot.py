"""
TCPH Telegram scheduled-post bot.

Reads posts from schedule.yaml and sends any that are due to your Telegram
channel. Remembers what it already sent (sent_log.json) so nothing posts twice.

Usage:
  python bot.py              # check once and post anything due (used by GitHub Actions)
  python bot.py --loop       # run forever, checking every minute (for a VPS / always-on PC)
  python bot.py --dry-run    # show what WOULD post right now, send nothing
  python bot.py --test "Hello"   # send one test message right now
  python bot.py --list       # print today's schedule

Needs two environment variables:
  TELEGRAM_BOT_TOKEN   from @BotFather
  TELEGRAM_CHAT_ID     e.g. @YourChannelUsername or -100xxxxxxxxxx
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent
SCHEDULE_FILE = ROOT / "schedule.yaml"
LOG_FILE = ROOT / "sent_log.json"

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_GROUPS = {
    "daily": DAY_NAMES,
    "everyday": DAY_NAMES,
    "weekdays": DAY_NAMES[:5],
    "weekends": DAY_NAMES[5:],
}


# ---------------------------------------------------------------- schedule ---

def load_schedule():
    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    settings = data.get("settings", {}) or {}
    posts = data.get("posts", []) or []
    tz = ZoneInfo(settings.get("timezone", "Asia/Manila"))
    window = int(settings.get("catch_up_minutes", 90))
    ids = set()
    for p in posts:
        if "id" not in p or "time" not in p:
            sys.exit(f"Every post needs an 'id' and a 'time'. Problem with: {p}")
        if p["id"] in ids:
            sys.exit(f"Duplicate post id: {p['id']}")
        ids.add(p["id"])
        if not (p.get("text") or p.get("photo")):
            sys.exit(f"Post '{p['id']}' needs 'text' and/or 'photo'.")
    return settings, posts, tz, window


def expand_days(days):
    if days is None:
        return set(DAY_NAMES)
    if isinstance(days, str):
        days = [days]
    out = set()
    for d in days:
        d = str(d).strip().lower()
        out.update(DAY_GROUPS.get(d, [d[:3]]))
    return out


def parse_time(t):
    # YAML may turn 08:00 into an int of minutes (sexagesimal) - handle both.
    if isinstance(t, int):
        return t // 60, t % 60
    h, m = str(t).strip().split(":")
    return int(h), int(m)


def runs_on(post, day: date):
    if post.get("enabled") is False:
        return False
    if post.get("date"):  # one-off post on a specific date
        return str(post["date"]) == day.isoformat()
    if post.get("start_date") and day.isoformat() < str(post["start_date"]):
        return False
    if post.get("end_date") and day.isoformat() > str(post["end_date"]):
        return False
    return DAY_NAMES[day.weekday()] in expand_days(post.get("days"))


def due_posts(posts, now, window_min, log):
    """Posts whose time today (or yesterday, around midnight) has passed,
    within the catch-up window, and that haven't been sent for that slot."""
    due = []
    for day in (now.date() - timedelta(days=1), now.date()):
        for p in posts:
            if not runs_on(p, day):
                continue
            h, m = parse_time(p["time"])
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=now.tzinfo)
            key = f"{p['id']}@{slot.strftime('%Y-%m-%d %H:%M')}"
            if slot <= now < slot + timedelta(minutes=window_min) and key not in log:
                due.append((slot, key, p))
    return sorted(due, key=lambda x: x[0])


# ------------------------------------------------------------------- state ---

def load_log():
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_log(log, now):
    # keep only the last 14 days so the file stays small
    cutoff = (now - timedelta(days=14)).strftime("%Y-%m-%d")
    log = {k: v for k, v in log.items() if k.split("@")[1][:10] >= cutoff}
    LOG_FILE.write_text(json.dumps(log, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------- telegram ---

def tg(method, token, data, files=None):
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                      data=data, files=files, timeout=30)
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram error on {method}: {body.get('description')}")
    return body["result"]


def send_post(p, token, chat_id, settings):
    parse_mode = p.get("parse_mode", settings.get("parse_mode", "HTML"))
    common = {"chat_id": chat_id, "parse_mode": parse_mode}
    if p.get("silent") or settings.get("silent"):
        common["disable_notification"] = "true"
    if p.get("buttons"):
        kb = [[{"text": b["text"], "url": b["url"]}] for b in p["buttons"]]
        common["reply_markup"] = json.dumps({"inline_keyboard": kb})

    text = (p.get("text") or "").strip()
    photo = p.get("photo")
    if photo:
        if len(text) > 1024:
            raise ValueError(f"Post '{p['id']}': photo captions max out at 1024 characters.")
        data = {**common, "caption": text}
        if str(photo).startswith("http"):
            msg = tg("sendPhoto", token, {**data, "photo": photo})
        else:
            with open(ROOT / photo, "rb") as f:
                msg = tg("sendPhoto", token, data, files={"photo": f})
    else:
        data = {**common, "text": text,
                "disable_web_page_preview": "false" if p.get("link_preview") else "true"}
        msg = tg("sendMessage", token, data)

    if p.get("pin"):
        tg("pinChatMessage", token, {"chat_id": chat_id, "message_id": msg["message_id"],
                                     "disable_notification": "true"})
    return msg


# -------------------------------------------------------------------- main ---

def run_once(dry_run=False, now=None):
    settings, posts, tz, window = load_schedule()
    now = now or datetime.now(tz)
    log = load_log()
    due = due_posts(posts, now, window, log)

    if not due:
        print(f"[{now:%Y-%m-%d %H:%M} {tz.key}] Nothing due.")
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or settings.get("chat_id")
    if not dry_run and not (token and chat_id):
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first.")

    failures = 0
    for slot, key, p in due:
        if dry_run:
            print(f"[DRY RUN] would post '{p['id']}' (scheduled {slot:%a %H:%M})")
            continue
        try:
            send_post(p, token, chat_id, settings)
            log[key] = datetime.now(tz).isoformat(timespec="seconds")
            print(f"Posted '{p['id']}' (scheduled {slot:%a %H:%M})")
            time.sleep(1)  # be gentle with Telegram rate limits
        except Exception as e:  # keep going with the other posts
            failures += 1
            print(f"FAILED '{p['id']}': {e}", file=sys.stderr)

    if not dry_run:
        save_log(log, now)
    return 1 if failures else 0


def list_today():
    settings, posts, tz, _ = load_schedule()
    today = datetime.now(tz).date()
    print(f"Schedule for {today:%A %Y-%m-%d} ({tz.key}):")
    rows = [(parse_time(p["time"]), p["id"]) for p in posts if runs_on(p, today)]
    for (h, m), pid in sorted(rows):
        print(f"  {h:02d}:{m:02d}  {pid}")
    if not rows:
        print("  (no posts today)")


def main():
    ap = argparse.ArgumentParser(description="TCPH Telegram scheduled-post bot")
    ap.add_argument("--loop", action="store_true", help="run forever, checking every minute")
    ap.add_argument("--dry-run", action="store_true", help="show what would post, send nothing")
    ap.add_argument("--test", metavar="TEXT", help="send one test message now")
    ap.add_argument("--list", action="store_true", help="print today's schedule")
    args = ap.parse_args()

    if args.list:
        return list_today()

    if args.test:
        settings, *_ = load_schedule()
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        chat_id = os.environ.get("TELEGRAM_CHAT_ID") or settings.get("chat_id")
        send_post({"id": "test", "text": args.test}, token, chat_id, settings)
        print("Test message sent.")
        return 0

    if args.loop:
        print("Bot running. Press Ctrl+C to stop.")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
            time.sleep(60)

    sys.exit(run_once(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
