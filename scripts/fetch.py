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
    url = urllib.parse.quote(url, safe=":/?&=+%")  # 日本語を含むURLも通す
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


# ------------------------------------------------------------------ 気象庁（明日の予報）
# https://www.jma.go.jp/bosai/forecast/data/forecast/{office}.json （非公式・仕様変更の可能性あり）
JMA_NAMES = {
    "100": "晴れ", "101": "晴れ時々くもり", "102": "晴れ一時雨", "103": "晴れ時々雨",
    "104": "晴れ一時雪", "105": "晴れ時々雪", "110": "晴れのち時々くもり", "111": "晴れのちくもり",
    "112": "晴れのち一時雨", "113": "晴れのち時々雨", "114": "晴れのち雨", "115": "晴れのち一時雪",
    "117": "晴れのち雪",
    "200": "くもり", "201": "くもり時々晴れ", "202": "くもり一時雨", "203": "くもり時々雨",
    "204": "くもり一時雪", "205": "くもり時々雪", "206": "くもり一時雨か雪", "207": "くもり時々雨か雪",
    "210": "くもりのち時々晴れ", "211": "くもりのち晴れ", "212": "くもりのち一時雨",
    "213": "くもりのち時々雨", "214": "くもりのち雨", "215": "くもりのち一時雪", "217": "くもりのち雪",
    "218": "くもりのち雨か雪",
    "300": "雨", "301": "雨時々晴れ", "302": "雨時々止む", "303": "雨時々雪", "304": "雨か雪",
    "306": "大雨", "308": "雨で暴風を伴う", "309": "雨一時雪", "311": "雨のち晴れ", "313": "雨のちくもり",
    "314": "雨のち時々雪", "315": "雨のち雪",
    "400": "雪", "401": "雪時々晴れ", "402": "雪時々止む", "403": "雪時々雨", "405": "大雪",
    "406": "風雪強い", "407": "暴風雪", "409": "雪一時雨", "411": "雪のち晴れ", "413": "雪のちくもり",
    "414": "雪のち雨",
}


def jma_category(code: str, text: str) -> int:
    if "雷" in text: return THUNDER
    if "雪" in text: return SNOW
    if "雨" in text or code.startswith("3"): return RAIN
    if "霧" in text or code == "209": return FOG
    if code.startswith("1"):
        return CLEAR if code in ("100", "110", "111") else PARTLY
    return CLOUDY


def jma_pop(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def tomorrow_from_jma(city: dict, tomorrow: date) -> dict:
    office, area = city["jma_office"], city["jma_area"]
    data = json.loads(get(f"https://www.jma.go.jp/bosai/forecast/data/forecast/{office}.json"))
    ts = data[0]["timeSeries"]

    # 天気（コード・文章）
    wa = next(a for a in ts[0]["areas"] if a["area"]["code"] == area)
    idx = next(i for i, t in enumerate(ts[0]["timeDefines"])
               if datetime.fromisoformat(t).date() == tomorrow)
    code = wa["weatherCodes"][idx]
    text = wa["weathers"][idx].replace("　", "")
    desc = JMA_NAMES.get(code, text)

    # 降水確率（6時間ごと）
    pops = [None] * 4
    pa = next(a for a in ts[1]["areas"] if a["area"]["code"] == area)
    for t, p in zip(ts[1]["timeDefines"], pa["pops"]):
        dt = datetime.fromisoformat(t)
        if dt.date() == tomorrow:
            pops[dt.hour // 6] = jma_pop(p)
    valid = [p for p in pops if p is not None]

    # 気温（観測地点名で選ぶ。0時=最低、9時=最高）
    tmin = tmax = None
    point = city.get("jma_point")
    ta = next((a for a in ts[2]["areas"] if a["area"]["name"] == point), ts[2]["areas"][0])
    for t, v in zip(ts[2]["timeDefines"], ta["temps"]):
        dt = datetime.fromisoformat(t)
        if dt.date() == tomorrow and v != "":
            if dt.hour == 0: tmin = to_int(v)
            elif dt.hour == 9: tmax = to_int(v)

    return {
        "date": tomorrow.isoformat(),
        "desc": desc,
        "category": jma_category(code, text),
        "max": tmax,
        "min": tmin,
        "pop_max": max(valid) if valid else None,
        "pops": pops,
        "wind_max": None,
        "source": "JMA",
        "area_name": wa["area"]["name"],
    }


# ------------------------------------------------------------------ 都市ごと
def fetch_city(city: dict, tz: str, tomorrow: date) -> dict:
    om = fetch_open_meteo(city, tz)
    cur, day = om["current"], om["daily"]
    w = {
        "name": city["name"],
        "lat": city["lat"], "lon": city["lon"],
        "dx": city.get("map_dx", 0), "dy": city.get("map_dy", 0),  # 地図上の表示位置の微調整(px)
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
    if city.get("jma_office"):
        try:
            jm = tomorrow_from_jma(city, tomorrow)
            # 気象庁に無い値は Open-Meteo で補う
            for k in ("max", "min", "pop_max", "wind_max"):
                if jm[k] is None:
                    jm[k] = tm[k]
            jm["pops"] = [j if j is not None else o for j, o in zip(jm["pops"], tm["pops"])]
            tm = jm
        except Exception as e:  # 形式変更・通信失敗 → Open-Meteo にフォールバック
            print(f"WARN: JMA {city['name']}: {e!r}", file=sys.stderr)
    w["tomorrow"] = tm
    # 旧フィールド（互換用）
    w["tomorrow_desc"], w["tomorrow_max"], w["tomorrow_min"] = tm["desc"], tm["max"], tm["min"]
    return w


def fetch_news(feed: dict, limit: int, exclude=()) -> list:
    root = ET.fromstring(get(feed["url"]))
    items = []
    for it in root.iter("item"):  # RSS 2.0（Googleニュースは「見出し - 媒体名」形式）
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip() or feed["name"]
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].rstrip()
        for sep in (" | ", "｜", " - "):  # サイト名の付属部分を落とす
            if sep in title and len(title.split(sep)[0]) >= 8:
                title = title.split(sep)[0].strip()
        if title and not any(x in title for x in exclude):
            items.append({"title": title, "source": src, "area": feed["name"],
                          "link": (it.findtext("link") or "").strip()})
    if not items:  # Atom
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in root.findall("a:entry", ns):
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
            if title:
                items.append({"title": title, "source": feed["name"], "area": feed["name"]})
    return items[: feed.get("limit", limit)]



# ------------------------------------------------------------------ 記事ページから画像と冒頭を取る
import html as _html
import re
import urllib.parse

IMG_DIR = OUT_DIR / "img"
THUMB_W, THUMB_H = 640, 177


def _pil():
    try:
        from PIL import Image
    except ImportError:  # Actions の標準環境には無いので入れる
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pillow"], check=True)
        from PIL import Image
    return Image


def decode_gnews(link: str) -> str:
    """Googleニュースの転送URLから元記事のURLを取り出す。失敗したら空文字。"""
    try:
        u = urllib.parse.urlparse(link)
        if u.netloc != "news.google.com":
            return link
        b64 = u.path.rstrip("/").split("/")[-1]
        page = get(f"https://news.google.com/articles/{b64}", timeout=20).decode("utf-8", "replace")
        sg = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not sg or not ts:
            return ""
        inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                 f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{b64}",{ts.group(1)},"{sg.group(1)}"]')
        body = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", inner]]])}).encode()
        req = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body,
            headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("utf-8", "replace")
        parsed = json.loads(txt.split("\n\n")[1])[:-2]
        return json.loads(parsed[0][2])[1]
    except Exception as e:
        print("WARN: gnews decode:", repr(e), file=sys.stderr)
        return ""


def _meta(page: str, *names) -> str:
    for n in names:
        for pat in (rf'<meta[^>]+(?:property|name)=["\']{n}["\'][^>]*content=["\']([^"\']*)["\']',
                    rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{n}["\']'):
            m = re.search(pat, page, re.I)
            if m and m.group(1).strip():
                return _html.unescape(m.group(1)).strip()
    return ""


def enrich(item: dict, idx: int) -> None:
    """item に body と image(0/1) を足す。取れなければ空。"""
    item["body"], item["image"] = "", 0
    url = decode_gnews(item.get("link", ""))
    if not url:
        return
    raw = get(url, timeout=25)[:600000]
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000])
    page = raw.decode(m.group(1).decode() if m else "utf-8", "replace")
    desc = _meta(page, "og:description", "description")
    desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", desc))
    item["body"] = desc[:110] + ("…" if len(desc) > 110 else "")
    img = _meta(page, "og:image", "twitter:image")
    if img:
        img = urllib.parse.urljoin(url, img)
        try:
            data = get(img, timeout=25)
            if len(data) <= 8_000_000:
                import io
                Image = _pil()
                im = Image.open(io.BytesIO(data)).convert("RGB")
                w, h = im.size
                th = w * THUMB_H / THUMB_W
                if th <= h:  # 縦が余る → 上寄りで切る
                    top = int((h - th) * 0.3)
                    im = im.crop((0, top, w, top + int(th)))
                else:
                    tw = h * THUMB_W / THUMB_H
                    left = int((w - tw) / 2)
                    im = im.crop((left, 0, left + int(tw), h))
                im = im.resize((THUMB_W, THUMB_H), Image.LANCZOS)
                IMG_DIR.mkdir(parents=True, exist_ok=True)
                im.save(IMG_DIR / f"n{idx}.jpg", "JPEG", quality=80)
                item["image"] = 1
        except Exception as e:
            print("WARN: image:", repr(e), file=sys.stderr)


def pick_best(cands: list, idx: int) -> dict:
    """候補のうち、画像が取れた最初の記事を採用（無ければ先頭）。"""
    first = None
    for c in cands[:3]:
        try:
            enrich(c, idx)
        except Exception as e:
            print("WARN: enrich:", repr(e), file=sys.stderr)
            c.setdefault("body", ""); c.setdefault("image", 0)
        if first is None:
            first = c
        if c.get("image"):
            return c
    return first


# ------------------------------------------------------------------ 気象庁 防災気象情報（北陸）
JMA_FEED = "https://www.data.jma.go.jp/developer/xml/feed/extra.xml"
ATOM = "{http://www.w3.org/2005/Atom}"


def fetch_jma_alerts(offices: list, per_office: int, limit: int) -> list:
    root = ET.fromstring(get(JMA_FEED, timeout=30))
    found = []
    seen = set()
    for e in root.findall(ATOM + "entry"):
        office = (e.findtext(f"{ATOM}author/{ATOM}name") or "").strip()
        if office not in offices:
            continue
        title = (e.findtext(ATOM + "title") or "").strip()
        text = (e.findtext(ATOM + "content") or "").strip()
        if not text or "解説" in title:
            continue
        # 【石川県気象警報・注意報】を取り、先頭の見出し語として県名を残す
        text = text.replace("【", "").replace("】", " ")
        key = (office, text)
        if key in seen:
            continue
        seen.add(key)
        found.append({"office": office, "updated": e.findtext(ATOM + "updated") or "", "text": text})
    found.sort(key=lambda x: x["updated"], reverse=True)
    out, count = [], {}
    for f in found:
        if count.get(f["office"], 0) >= per_office:
            continue
        count[f["office"]] = count.get(f["office"], 0) + 1
        t = f["text"]
        if len(t) > 70:
            t = t[:69] + "…"
        out.append({"title": t, "source": f["office"]})
    return out[:limit]


# ------------------------------------------------------------------ 表示テキスト
def fmt(v, unit=""):
    return "-" if v is None else f"{v}{unit}"


def weather_line(w: dict) -> str:
    return (f"<b>{w['name']}</b>  {w['desc']}  {w['temp']}℃  "
            f"<size=80%>最高{fmt(w['today_max'],'°')} / 最低{fmt(w['today_min'],'°')}  "
            f"降水{fmt(w['today_pop'],'%')}  湿度{w['humidity']}%  風{w['wind']}m/s</size>")


def now_line(w: dict) -> str:
    return (f"<b>{w['name']}</b>  {w['desc']}  {w['temp']}℃  "
            f"<size=80%>{fmt(w['today_max'],'°')}/{fmt(w['today_min'],'°')}  降水{fmt(w['today_pop'],'%')}</size>")


def forecast_line(w: dict, compact: bool = False) -> str:
    t = w["tomorrow"]
    if compact:  # 都市が多いときは1都市1行
        return (f"<b>{w['name']}</b>  {t['desc']}  "
                f"<size=80%>{fmt(t['max'],'°')}/{fmt(t['min'],'°')}  降水{fmt(t['pop_max'],'%')}</size>")
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
    jcfg = ncfg.get("jma_alerts")
    if jcfg:
        try:
            news.extend(fetch_jma_alerts(jcfg["offices"], jcfg.get("per_office", 2), limit))
        except Exception as e:
            errors.append(f"jma alerts: {e}")
    if IMG_DIR.exists():
        for old in IMG_DIR.glob("*.jpg"):
            old.unlink()
    for idx, f in enumerate(ncfg.get("feeds", [])):
        try:
            cands = fetch_news(dict(f, limit=6), 6, ncfg.get("exclude", []))
            if cands:
                best = pick_best(cands, idx)
                if best:
                    best["idx"] = idx
                    news.append(best)
        except Exception as e:
            errors.append(f"news {f['name']}: {e}")
    seen_t, uniq = set(), []
    for n in news:
        if len(n["title"]) > 70:
            n["title"] = n["title"][:69] + "…"
        n.pop("link", None)
        if n["title"] in seen_t:
            continue
        seen_t.add(n["title"])
        uniq.append(n)
    news = uniq[:limit]
    if not news and jcfg:
        news = [{"title": "現在、北陸に発表中の気象情報はありません", "source": "気象庁"}]

    wd = "月火水木金土日"[tomorrow.weekday()]
    credit = "Weather data by Open-Meteo.com (CC BY 4.0)"
    if any(w["tomorrow"]["source"] == "JMA" for w in weather):
        credit = "明日の予報: 気象庁 / 現在の天気: Open-Meteo.com (CC BY 4.0) / ニュース: Googleニュース / 地図: 地球地図日本"

    data = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "updated_unix": int(now.timestamp()),
        "tomorrow_date": tomorrow.isoformat(),
        "weather": weather,
        "news": news,
        "weather_text": "\n".join(weather_line(w) for w in weather) or "天気を取得できませんでした",
        "list_now": "\n".join(now_line(w) for w in weather) or "天気を取得できませんでした",
        "list_tomorrow": "\n".join(forecast_line(w, True) for w in weather) or "予報を取得できませんでした",
        "forecast_title": f"明日 {tomorrow.month}/{tomorrow.day}({wd}) の天気",
        "forecast_text": "\n".join(forecast_line(w, len(weather) > 5) for w in weather) or "予報を取得できませんでした",
        "news_text": "\n".join(f"<color=#8FD3FF>[{n.get('area', '')}]</color> {n['title']}" if n.get("area") else f"・{n['title']}" for n in news) or "ニュースを取得できませんでした",
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
