import os
import time
import json
import requests
import sqlite3

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL_ID"]

API = "https://showmytrades.com/api/public/calendar/v1"
TEHRAN = ZoneInfo("Asia/Tehran")

DB = "alphapips.db"

URL = f"https://api.telegram.org/bot{TOKEN}/"

CURRENCIES = {
    "USD": "دلار آمریکا",
    "EUR": "یورو",
    "GBP": "پوند انگلیس",
    "JPY": "ین ژاپن",
    "AUD": "دلار استرالیا",
    "CAD": "دلار کانادا",
    "CHF": "فرانک سوئیس",
    "NZD": "دلار نیوزیلند",
    "CNY": "یوان چین"
}

IMPACTS = {
    "high": "🔴 زیاد",
    "medium": "🟠 متوسط",
    "low": "🟢 کم",
    "holiday": "⚪ تعطیلی"
}

TRANSLATIONS = {
    "CPI": "شاخص قیمت مصرف‌کننده",
    "Core CPI": "شاخص قیمت مصرف‌کننده هسته",
    "GDP": "تولید ناخالص داخلی",
    "Unemployment Rate": "نرخ بیکاری",
    "Nonfarm Payrolls": "اشتغال بخش غیرکشاورزی",
    "Interest Rate": "نرخ بهره",
    "Retail Sales": "خرده‌فروشی",
    "PPI": "شاخص قیمت تولیدکننده",
    "PMI": "شاخص مدیران خرید",
    "Trade Balance": "تراز تجاری",
    "Employment Change": "تغییرات اشتغال"
}


def fa_number(value):
    table = str.maketrans(
        "0123456789",
        "۰۱۲۳۴۵۶۷۸۹"
    )
    return str(value).translate(table)


def translate_title(title):
    for key, value in TRANSLATIONS.items():
        if key.lower() in title.lower():
            return f"{value} ({key})"

    return title


def get_events(days=1):
    response = requests.get(
        API,
        params={
            "impact": "all",
            "days": days
        },
        timeout=20
    )

    response.raise_for_status()

    return response.json().get("events", [])


def event_time(event):
    dt = datetime.fromtimestamp(
        int(event["ts"]),
        timezone.utc
    )
    return dt.astimezone(TEHRAN)


def format_event(event):
    currency = event.get("currency", "")
    title = event.get("title", "خبر اقتصادی")

    dt = event_time(event)

    actual = event.get("actual") or "در انتظار انتشار"
    forecast = event.get("forecast") or "نامشخص"
    previous = event.get("previous") or "نامشخص"

    impact = IMPACTS.get(
        event.get("impact"),
        "⚪ نامشخص"
    )

    return (
        f"🌍 {CURRENCIES.get(currency, currency)} ({currency})\n"
        f"📰 {translate_title(title)}\n"
        f"🕒 ساعت: {fa_number(dt.strftime('%H:%M'))}\n"
        f"📊 اهمیت: {impact}\n"
        f"قبلی: {fa_number(previous)}\n"
        f"پیش‌بینی: {fa_number(forecast)}\n"
        f"واقعی: {fa_number(actual)}"
    )


def send_message(text):
    response = requests.post(
        URL + "sendMessage",
        json={
            "chat_id": CHANNEL,
            "text": text
        },
        timeout=20
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(result)

    return result["result"]["message_id"]


def edit_message(message_id, text):
    response = requests.post(
        URL + "editMessageText",
        json={
            "chat_id": CHANNEL,
            "message_id": message_id,
            "text": text
        },
        timeout=20
    )

    response.raise_for_status()
    return response.json()


def database():
    con = sqlite3.connect(DB)

    con.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            message_id INTEGER,
            content TEXT
        )
    """)

    con.commit()
    return con


def publish_calendar(days=1):
    events = get_events(days)

    now = datetime.now(TEHRAN).date()

    grouped = {}

    for event in events:
        dt = event_time(event)

        if days == 1 and dt.date() != now:
            continue

        day = dt.strftime("%Y-%m-%d")
        grouped.setdefault(day, []).append(event)

    con = database()

    for day, items in grouped.items():

        items.sort(key=lambda x: x["ts"])

        date_text = datetime.strptime(
            day, "%Y-%m-%d"
        ).strftime("%Y/%m/%d")

        text = (
            "🔱 ALPHAPIPS\n"
            "📅 تقویم اقتصادی فارکس\n"
            f"📆 تاریخ: {fa_number(date_text)}\n"
            "━━━━━━━━━━━━━━\n\n"
        )

        text += "\n\n━━━━━━━━━━━━━━\n\n".join(
            format_event(e) for e in items
        )

        text += "\n\n🔱 ALPHAPIPS TRADE"

        key = f"{day}"

        old = con.execute(
            "SELECT message_id, content FROM events WHERE event_id=?",
            (key,)
        ).fetchone()

        if old:
            if old[1] != text:
                edit_message(old[0], text)

                con.execute(
                    "UPDATE events SET content=? WHERE event_id=?",
                    (text, key)
                )
        else:
            message_id = send_message(text)

            con.execute(
                "INSERT INTO events VALUES (?, ?, ?)",
                (key, message_id, text)
            )

        con.commit()

    con.close()


def update_results():
    con = database()

    rows = con.execute(
        "SELECT event_id, message_id, content FROM events"
    ).fetchall()

    con.close()

    for key, message_id, old_text in rows:

        try:
            events = get_events(2)

            day_events = [
                e for e in events
                if event_time(e).strftime("%Y-%m-%d") == key
            ]

            if not day_events:
                continue

            date_text = datetime.strptime(
                key, "%Y-%m-%d"
            ).strftime("%Y/%m/%d")

            new_text = (
                "🔱 ALPHAPIPS\n"
                "📅 تقویم اقتصادی فارکس\n"
                f"📆 تاریخ: {fa_number(date_text)}\n"
                "━━━━━━━━━━━━━━\n\n"
            )

            new_text += "\n\n━━━━━━━━━━━━━━\n\n".join(
                format_event(e) for e in sorted(
                    day_events,
                    key=lambda x: x["ts"]
                )
            )

            new_text += "\n\n🔱 ALPHAPIPS TRADE"

            if new_text != old_text:
                edit_message(message_id, new_text)

                con = database()

                con.execute(
                    "UPDATE events SET content=? WHERE event_id=?",
                    (new_text, key)
                )

                con.commit()
                con.close()

        except Exception as error:
            print("Update error:", error)


def main():
    print("ALPHAPIPS Calendar Started")

    while True:
        try:
            now = datetime.now(TEHRAN)

            # تقویم روزانه ساعت ۷ صبح تهران
            if now.hour == 7 and now.minute < 5:
                publish_calendar(1)

            # تقویم هفتگی یکشنبه ساعت ۸ صبح
            if (
                now.weekday() == 6
                and now.hour == 8
                and now.minute < 5
            ):
                publish_calendar(7)

            # بررسی نتایج واقعی اخبار
            if now.minute % 5 == 0:
                update_results()

            time.sleep(60)

        except Exception as error:
            print("Main error:", error)
            time.sleep(60)


if __name__ == "__main__":
    main()
