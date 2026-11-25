#!/usr/bin/env python3
"""天気とニュースを取得して public/data.json を書き出す（標準ライブラリのみ）。

- 天気（現在・今日・明日）: Open-Meteo（APIキー不要・座標指定・世界中OK）
- ニュース                 : RSS / Atom
"""
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
OUT_DIR = ROOT / "public"
UA = {"User-Agent": "vrc-weather-news/1.1 (GitHub Actions)"}

# WMO weather code -> 日本語
WMO = {
    0: "快晴", 1: "晴れ", 2: "晴れ時々くもり", 3: "くもり",
    45: "霧", 48: "着氷性の霧",
    51: "弱い霧雨", 53: "霧雨", 55: "強い霧雨", 56: "着氷性霧雨", 57: "強い着氷性霧雨",
    61: "小雨", 63: "雨", 65: "大雨", 66: "着氷性の雨", 67: "強い着氷性の雨",
    71: "小雪", 73: "雪", 75: "大雪", 77: "霧雪",
    80: "にわか雨", 81: "強いにわか雨", 82: "激しいにわか雨",
    85: "にわか雪", 86: "強いにわか雪",
    95: "雷雨", 96: "雹を伴う雷雨", 99: "強い雹を伴う雷雨",
}

# アイコン/演出用の共通カテゴリ（WeatherEnvironment.cs と同じ番号）
CLEAR, PARTLY, CLOUDY, FOG, RAIN, SNOW, THUNDER = range(7)


def wmo_category(c: int) -> int:
    if c <= 1: return CLEAR
    if c == 2: return PARTLY
    if c == 3: return CLOUDY
    if c in (45, 48): return FOG
    if 71 <= c <= 77 or c in (85, 86): return SNOW
    if c >= 95: return THUNDER
    if 51 <= c <= 67 or 80 <= c <= 82: return RAIN
    return CLOUDY


def get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def to_int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ Open-Meteo
def fetch_open_meteo(city: dict, tz: str) -> dict:
    q = urllib.parse.urlencode({
        "latitude": city["lat"], "longitude": city["lon"], "timezone": tz,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,is_day,cloud_cover",
        "hourly": "precipitation_probability,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                 "weather_code,wind_speed_10m_max",
        "forecast_days": 3, "wind_speed_unit": "ms",
    })
    return json.loads(get("https://api.open-meteo.com/v1/forecast?" + q))


def tomorrow_from_open_meteo(d: dict, tomorrow: date) -> dict:
    day = d["daily"]
    i = day["time"].index(tomorrow.isoformat())
    # 6時間ごとの降水確率（0-6, 6-12, 12-18, 18-24時）
    pops = [None] * 4
    hourly = d.get("hourly", {})
    for t, p in zip(hourly.get("time", []), hourly.get("precipitation_probability", [])):
        dt = datetime.fromisoformat(t)
        if dt.date() == tomorrow and p is not None:
            k = dt.hour // 6
            pops[k] = p if pops[k] is None else max(pops[k], p)
    code = day["weather_code"][i]
    return {
        "date": tomorrow.isoformat(),
        "desc": WMO.get(code, "不明"),
        "category": wmo_category(code),
        "max": to_int(day["temperature_2m_max"][i]),
        "min": to_int(day["temperature_2m_min"][i]),
        "pop_max": day["precipitation_probability_max"][i],
        "pops": pops,
        "wind_max": round(day["wind_speed_10m_max"][i], 1),
        "source": "Open-Meteo",
    }


# ------------------------------------------------------------------ 都市ごと
def fetch_city(city: dict, tz: str, tomorrow: date) -> dict:
    om = fetch_open_meteo(city, tz)
    cur, day = om["current"], om["daily"]
    w = {
        "name": city["name"],
        "temp": round(cur["temperature_2m"], 1),
        "humidity": cur["relative_humidity_2m"],
        "wind": round(cur["wind_speed_10m"], 1),
        "code": cur["weather_code"],
        "desc": WMO.get(cur["weather_code"], "不明"),
        "category": wmo_category(cur["weather_code"]),
        "is_day": cur.get("is_day", 1),
        "cloud": cur.get("cloud_cover", 0),
        "utc_offset": om.get("utc_offset_seconds", 0),
        "today_max": to_int(day["temperature_2m_max"][0]),
        "today_min": to_int(day["temperature_2m_min"][0]),
        "today_pop": day["precipitation_probability_max"][0],
    }
    tm = tomorrow_from_open_meteo(om, tomorrow)
    w["tomorrow"] = tm
    # 旧フィールド（互換用）
    w["tomorrow_desc"], w["tomorrow_max"], w["tomorrow_min"] = tm["desc"], tm["max"], tm["min"]
    return w


def fetch_news(feed: dict, limit: int) -> list:
    root = ET.fromstring(get(feed["url"]))
    items = []
    for it in root.iter("item"):  # RSS 2.0
        title = (it.findtext("title") or "").strip()
        if title:
            items.append({"title": title, "source": feed["name"]})
    if not items:  # Atom
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in root.findall("a:entry", ns):
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
            if title:
                items.append({"title": title, "source": feed["name"]})
    return items[:limit]


# ------------------------------------------------------------------ 表示テキスト
def fmt(v, unit=""):
    return "-" if v is None else f"{v}{unit}"


def weather_line(w: dict) -> str:
    return (f"<b>{w['name']}</b>  {w['desc']}  {w['temp']}℃  "
            f"<size=80%>最高{fmt(w['today_max'],'°')} / 最低{fmt(w['today_min'],'°')}  "
            f"降水{fmt(w['today_pop'],'%')}  湿度{w['humidity']}%  風{w['wind']}m/s</size>")


def forecast_line(w: dict) -> str:
    t = w["tomorrow"]
    pops = " / ".join(fmt(p, "%") for p in t["pops"])
    wind = f"最大風速 {t['wind_max']}m/s" if t["wind_max"] is not None else ""
    return (f"<b>{w['name']}</b>  {t['desc']}\n"
            f"<size=80%>  最高{fmt(t['max'],'°')} / 最低{fmt(t['min'],'°')}   "
            f"降水確率(0-6-12-18時) {pops}</size>"
            + (f"\n<size=70%>  {wind}</size>" if wind else ""))


def main() -> int:
    tz = CONFIG.get("timezone", "Asia/Tokyo")
    now = datetime.now(ZoneInfo(tz))
    tomorrow = (now + timedelta(days=1)).date()
    errors = []

    weather = []
    for c in CONFIG["cities"]:
        try:
            weather.append(fetch_city(c, tz, tomorrow))
        except Exception as e:
            errors.append(f"weather {c['name']}: {e}")

    news = []
    ncfg = CONFIG.get("news", {})
    limit = ncfg.get("max_items", 8)
    for f in ncfg.get("feeds", []):
        try:
            news.extend(fetch_news(f, limit))
        except Exception as e:
            errors.append(f"news {f['name']}: {e}")
    news = news[:limit]

    wd = "月火水木金土日"[tomorrow.weekday()]
    credit = "Weather data by Open-Meteo.com (CC BY 4.0)"

    data = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "updated_unix": int(now.timestamp()),
        "tomorrow_date": tomorrow.isoformat(),
        "weather": weather,
        "news": news,
        "weather_text": "\n".join(weather_line(w) for w in weather) or "天気を取得できませんでした",
        "forecast_title": f"明日 {tomorrow.month}/{tomorrow.day}({wd}) の天気",
        "forecast_text": "\n".join(forecast_line(w) for w in weather) or "予報を取得できませんでした",
        "news_text": "\n".join(f"・{n['title']}" for n in news) or "ニュースを取得できませんでした",
        "credit": credit,
        "errors": errors,
    }

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "index.html").write_text(
        '<meta charset="utf-8"><p>VRChat weather/news feed: <a href="data.json">data.json</a></p>',
        encoding="utf-8")
    for e in errors:
        print("WARN:", e, file=sys.stderr)
    print(f"wrote data.json: {len(weather)} cities, {len(news)} news")
    return 1 if not weather and not news else 0


if __name__ == "__main__":
    sys.exit(main())
