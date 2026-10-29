"""
daily_post.py - posts today's free food to GroupMe and Discord, and makes the
weekly Instagram graphic. GitHub runs it every weekday morning. It only reads
the events the main pipeline already found, so it costs nothing to run.

Secrets it uses (Settings > Secrets and variables > Actions):
  GROUPME_BOT_IDS    one or more GroupMe bot IDs, separated by commas
  DISCORD_WEBHOOKS   one or more Discord webhook links, separated by commas
Either can be left out.

DRY_RUN=1 prints the message instead of posting it.
"""
import json
import os
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

CT = ZoneInfo("America/Chicago")
HERE = Path(__file__).parent
EVENTS = HERE / "docs" / "events.json"
IG_DIR = HERE / "docs" / "instagram"
SITE_NAME = os.getenv("SITE_NAME", "Campus Events + Free Food")


def site_url(source):
    base = os.getenv("SITE_URL")
    if not base and os.getenv("GITHUB_REPOSITORY"):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
        base = f"https://{owner.lower()}.github.io/{repo}/"
    base = base or ""
    return f"{base}?utm_source={source}" if base else ""


def load_events():
    if not EVENTS.exists():
        return []
    return json.loads(EVENTS.read_text()).get("events", [])


def fmt_time(hm):
    if not hm:
        return "Time TBA"
    h, m = map(int, hm.split(":"))
    ap = "pm" if h >= 12 else "am"
    h = h % 12 or 12
    return f"{h}:{m:02d}{ap}" if m else f"{h}{ap}"


def food_today(events, day):
    """Free food on one day, clearly stated first, members-only left out."""
    items = [e for e in events if e.get("date") == day.isoformat() and e.get("free_food") and not e.get("members_only")]
    items.sort(key=lambda e: (e.get("food_confidence") != "stated", e.get("start_time") or "99"))
    return items


def line(e):
    bits = [fmt_time(e.get("start_time")), e.get("title") or "Event", f"({e.get('org_name')})"]
    s = f"• {bits[0]}: {bits[1]} {bits[2]}"
    if e.get("location"):
        s += f" at {e['location']}"
    food = e.get("food_details") or "food"
    s += f", {food}" + (" (likely)" if e.get("food_confidence") == "likely" else "")
    return s


def build_message(events, day, limit, source):
    items = food_today(events, day)
    if not items:
        return None
    head = f"Free food today ({day:%a} {day.month}/{day.day})"
    link = site_url(source)
    tail = f"\n\nMore events + add to your calendar: {link}" if link else ""
    lines, used = [], len(head) + len(tail) + 40
    for i, e in enumerate(items):
        l = line(e)
        if used + len(l) + 1 > limit:
            lines.append(f"+ {len(items) - i} more on the site")
            break
        lines.append(l)
        used += len(l) + 1
    return head + "\n\n" + "\n".join(lines) + tail


def post_groupme(bot_id, text):
    r = requests.post("https://api.groupme.com/v3/bots/post", json={"bot_id": bot_id, "text": text}, timeout=20)
    return r.status_code


def post_discord(url, text):
    r = requests.post(url, json={"content": text}, timeout=20)
    return r.status_code


# ---------------------------------------------------------------- weekly Instagram graphic
def _font(size, bold=False):
    from PIL import ImageFont
    names = (["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
    for folder in ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/liberation2"]:
        for n in names:
            p = Path(folder) / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def fit(d, text, font, max_w):
    """Shorten text with an ellipsis until it fits max_w pixels."""
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def graphic_start():
    """The week starts today, or tomorrow if it's already evening."""
    now = datetime.now(CT)
    return now.date() + timedelta(days=1) if now.hour >= 17 else now.date()


def make_graphic(events, start):
    """A 1080x1350 image of free food for the next 7 days, plus a caption to paste."""
    from PIL import Image, ImageDraw
    end = start + timedelta(days=6)
    items = [e for e in events if e.get("free_food") and not e.get("members_only") and e.get("date")
             and start.isoformat() <= e["date"] <= end.isoformat()]
    items.sort(key=lambda e: (e["date"], e.get("start_time") or "99"))
    W, H, M = 1080, 1350, 72
    bg, ink, muted, accent, good = (250, 248, 245), (31, 29, 26), (107, 102, 94), (191, 87, 0), (31, 122, 77)
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 16], fill=accent)
    d.text((M, 70), "Free food this week", font=_font(64, True), fill=ink)
    d.text((M, 150), f"{start:%b} {start.day} to {end:%b} {end.day} · UT Austin student orgs", font=_font(30), fill=muted)
    y = 230
    shown, last_day = 0, None
    for e in items:
        dd = date.fromisoformat(e["date"])
        need = (58 if dd != last_day else 0) + 96
        if y + need > H - 150:
            break
        if dd != last_day:
            d.text((M, y), f"{dd:%A} {dd.month}/{dd.day}".upper(), font=_font(26, True), fill=accent)
            y += 50
            last_day = dd
        food = fit(d, e.get("food_details") or "Free food", _font(22, True), 240)
        fw = d.textlength(food, font=_font(22, True))
        pill_x = W - M - fw - 28
        d.rounded_rectangle([pill_x, y + 2, W - M, y + 40], radius=19, fill=(230, 244, 236))
        d.text((pill_x + 14, y + 8), food, font=_font(22, True), fill=good)
        d.text((M, y), fmt_time(e.get("start_time")) if e.get("start_time") else "TBA", font=_font(32, True), fill=ink)
        d.text((M + 170, y), fit(d, e.get("title") or "Event", _font(32, True), pill_x - (M + 170) - 20), font=_font(32, True), fill=ink)
        sub = e.get("org_name") or ""
        if e.get("location"):
            sub += f" · {e['location']}"
        d.text((M + 170, y + 44), fit(d, sub, _font(24), W - M - (M + 170)), font=_font(24), fill=muted)
        y += 96
        shown += 1
    if not items:
        d.text((M, y), "No free food found yet this week.", font=_font(32), fill=muted)
    more = len(items) - shown
    d.text((M, H - 120), (f"+ {more} more · " if more > 0 else "") + "Full list + calendar: link in bio", font=_font(30, True), fill=ink)
    d.text((M, H - 74), "Pulled automatically from org Instagram posts. Check the original post.", font=_font(22), fill=muted)
    IG_DIR.mkdir(parents=True, exist_ok=True)
    im.save(IG_DIR / "this-week.png", optimize=True)
    cap = [f"Free food at UT this week ({start:%b} {start.day} to {end:%b} {end.day}) 🍕", ""]
    for e in items[:15]:
        dd = date.fromisoformat(e["date"])
        cap.append(f"{dd:%a}: {e.get('title') or 'Event'} ({e.get('org_name')}), {fmt_time(e.get('start_time'))}"
                   + (f" at {e['location']}" if e.get("location") else ""))
    tags = []
    for e in items:
        h = e.get("org_handle")
        if h and f"@{h}" not in tags:
            tags.append(f"@{h}")
    cap += ["", "Every event + calendar subscription: link in bio"]
    if tags:
        cap += ["", "Featuring " + " ".join(tags[:20])]   # Instagram allows up to 20 tags per caption
    cap += ["", "#utaustin #hookem #freefood"]
    (IG_DIR / "caption.txt").write_text("\n".join(cap), encoding="utf-8")
    return shown, len(items)


def main():
    today = datetime.now(CT).date()
    events = load_events()
    dry = bool(os.getenv("DRY_RUN"))

    shown, total = make_graphic(events, graphic_start())
    print(f"Instagram graphic: {shown} of {total} free-food events this week -> docs/instagram/this-week.png")

    bots = [b.strip() for b in os.getenv("GROUPME_BOT_IDS", "").split(",") if b.strip()]
    hooks = [h.strip() for h in os.getenv("DISCORD_WEBHOOKS", "").split(",") if h.strip()]
    gm = build_message(events, today, 1000, "groupme")
    dc = build_message(events, today, 2000, "discord")
    if not gm:
        print("No free food found for today, so nothing was posted.")
        return
    if dry or not (bots or hooks):
        print("---- message preview ----\n" + gm + "\n-------------------------")
        if not (bots or hooks):
            print("No GroupMe bots or Discord webhooks set up yet, so nothing was posted.")
        return
    for b in bots:
        print(f"GroupMe bot ...{b[-4:]}: {post_groupme(b, gm)}")
    for h in hooks:
        print(f"Discord webhook ...{h[-6:]}: {post_discord(h, dc)}")


if __name__ == "__main__":
    main()
