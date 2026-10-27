# TCPH Telegram Auto-Poster

Posts your scheduled messages to the **Trading Culture PH Observation Channel**.
It runs on GitHub Actions, so it's free, needs no server, and keeps posting
when your computer is off.

You only edit one file: **`schedule.yaml`**.

---

## One-time setup (about 15 minutes)

### 1. Create the bot
1. In Telegram, open **@BotFather** and send `/newbot`.
2. Give it a name (e.g. `TCPH Poster`) and a username ending in `bot`.
3. BotFather replies with a **token** like `123456789:AA...`. Keep it private.
   Never paste it into a post, a file or a chat.

### 2. Make the bot an admin of your channel
1. Open the channel, then go to **Manage Channel → Administrators → Add Admin**.
2. Search for your bot's username and add it.
3. Turn on **Post Messages**. Turn on **Pin Messages** as well if you'll use `pin: true`.

### 3. Get your channel ID
- **Public channel:** use its username, e.g. `@TradingCulturePH`.
- **Private channel:** forward any post from the channel to **@userinfobot** or
  **@RawDataBot**. It replies with an ID like `-1001234567890`.

### 4. Put the project on GitHub
1. Create a free account at github.com if you don't have one.
2. Click **New repository**, name it `tcph-telegram-bot` and create it.
   - **Public** repo: unlimited free run time. The post texts are visible,
     but your token stays secret.
   - **Private** repo: in `.github/workflows/post.yml`, change the cron to
     `"*/30 * * * *"` to stay inside the free 2,000 minutes a month.
3. Click **uploading an existing file** and drag in everything from this folder,
   including the `.github` folder.

### 5. Add your secrets
In the repo, go to **Settings → Secrets and variables → Actions → New repository secret**
and add both of these:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | `@YourChannel` or `-100...` |

### 6. Turn it on and test
1. Open the **Actions** tab and enable workflows if GitHub asks.
2. Click **Post scheduled Telegram messages → Run workflow** to run it once.
   The log should say "Nothing due" or "Posted ...".

From then on it checks every 10 minutes by itself.

---

## Changing your posts

Edit `schedule.yaml` on GitHub (click the file, then the pencil icon) and commit.
The change applies on the next run.

```yaml
- id: morning-outlook         # unique name
  time: "08:00"               # Philippine time, 24h, in quotes
  days: weekdays              # daily | weekdays | weekends | [mon, wed, fri]
  photo: images/outlook.jpg   # optional image (upload it into an images/ folder)
  pin: true                   # optional
  text: |
    ☀️ <b>Good morning, traders!</b>
    Your message here.
```

- One-off post: use `date: "2026-11-05"` instead of `days`.
- Pause a post: add `enabled: false`.
- Formatting: `<b>bold</b>`, `<i>italic</i>`, `<a href="https://...">link</a>`.
  For a literal `<`, `>` or `&`, write `&lt;`, `&gt;` or `&amp;`.

**Timing:** posts usually go out within about 10 minutes of the set time,
because GitHub's scheduler can run a few minutes late. Nothing posts twice;
`sent_log.json` keeps track of what's already gone out.

---

## Optional: run it on your own PC or a VPS instead

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="123:AA..."
export TELEGRAM_CHAT_ID="@YourChannel"

python bot.py --list             # today's schedule
python bot.py --dry-run          # what would post right now (sends nothing)
python bot.py --test "Hello 👋"  # send one test message
python bot.py --loop             # run forever, posts on the minute
```

## Troubleshooting

| Error | Fix |
|---|---|
| `chat not found` | Wrong `TELEGRAM_CHAT_ID`, or the bot isn't in the channel |
| `not enough rights` | Give the bot the **Post Messages** (and **Pin**) admin rights |
| `Unauthorized` | Token is wrong. Copy it from @BotFather again |
| `can't parse entities` | A stray `<` or `&` in the text. Use `&lt;` or `&amp;` |
| Nothing ever posts | Check the Actions tab is enabled. GitHub pauses schedules in repos with no activity for 60 days, so just re-enable it |
