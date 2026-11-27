"""Googleマイマップ(公開)のスポット一覧 → data.json 用データ + 画像(写真/地理院地図 + QR)。

画像は 520x200 の1枚: 左 320x200 = 写真(Wikimedia Commons) か 国土地理院の地図、右 200x200 = Googleマップへ飛ぶQR。
Google の地図・写真は保存せず、リンクとQRだけでつなぐ。
"""
import hashlib
import html
import io
import json
import math
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = {"User-Agent": "vrc-weather-news/2.0 (GitHub Actions; hobby VRChat world)"}
PHOTO_W, PHOTO_H, QR_W = 320, 200, 200
TEX_W = PHOTO_W + QR_W
GSI_LAYERS = {  # 種類: (URL, ズーム, 出典の表記)
    "std": ("https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png", 16, "地図: 地理院タイル 標準地図(国土地理院)"),
    "photo": ("https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg", 16, "航空写真: 地理院タイル 全国最新写真(国土地理院)"),
}
IMG_VERSION = "v5"  # 画像の作り方を変えたら上げる(キャッシュを作り直す)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
OK_LICENSES = ("cc by", "cc0", "public domain", "pd", "cc-by")

# 県ごとのおおよその範囲(緯度min, 緯度max, 経度min, 経度max)。範囲外の座標ミスを除外する
PREF_BOX = {
    "新潟": (36.7, 38.6, 137.6, 139.95),
    "富山": (36.25, 37.0, 136.7, 137.8),
    "石川": (36.05, 37.6, 136.2, 137.4),
    "福井": (35.3, 36.3, 135.4, 136.9),
}
GENRES = [
    ("ラーメン", ("ラーメン", "らーめん", "中華そば", "拉麺", "麺家", "ブラック")),
    ("そば・うどん", ("そば", "蕎麦", "うどん", "へぎ")),
    ("カレー", ("カレー",)),
    ("寿司・海鮮", ("寿司", "鮨", "海鮮", "回転", "魚", "のどぐろ", "カニ", "蟹", "刺身")),
    ("カフェ・甘味", ("カフェ", "珈琲", "コーヒー", "喫茶", "スイーツ", "パン", "ケーキ", "甘味", "ジェラート")),
    ("居酒屋・定食", ("居酒屋", "定食", "食堂", "酒", "焼肉", "焼鳥", "とんかつ", "カツ")),
]


def _http(url: str, timeout: int = 25, headers: dict = None) -> bytes:
    url = urllib.parse.quote(url, safe=":/?&=+%|,@#")
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _pip(mod: str, pkg: str):
    try:
        return __import__(mod)
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", pkg], check=True)
        return __import__(mod)


def _text(s: str, limit: int) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t　]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    s = re.sub(r"\s*\n\s*", " / ", s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def parse_kml(data: bytes, kind: str) -> list:
    root = ET.fromstring(data)
    out = []
    for folder in root.iter():
        if not folder.tag.endswith("}Folder") and not folder.tag.endswith("Folder"):
            continue
        fname = ""
        for ch in folder:
            if ch.tag.endswith("}name") or ch.tag == "name":
                fname = (ch.text or "").strip()
                break
        pref = next((p for p in PREF_BOX if p in fname), "")
        for pm in folder:
            if not (pm.tag.endswith("}Placemark") or pm.tag == "Placemark"):
                continue
            name = desc = coords = media = ""
            for el in pm.iter():
                t = el.tag.split("}")[-1]
                if t == "name" and not name:
                    name = (el.text or "").strip()
                elif t == "description" and not desc:
                    desc = el.text or ""
                elif t == "coordinates" and not coords:
                    coords = (el.text or "").strip()
                elif t == "Data" and el.get("name") == "gx_media_links":
                    v = next((c.text for c in el if c.tag.split("}")[-1] == "value"), "") or ""
                    media = v.split()[0] if v.split() else ""
            if not name or not coords:
                continue
            try:
                lon, lat = (float(x) for x in coords.split()[0].split(",")[:2])
            except ValueError:
                continue  # Point 以外(線・面)は対象外
            out.append({"kind": kind, "pref": pref, "name": name, "desc": _text(desc, 90),
                        "lat": lat, "lon": lon, "media": media})
    return out


def clean(spots: list) -> tuple:
    """県の範囲外の座標を除き、同名・同座標の重複をまとめる。"""
    ok, dropped, seen = [], [], {}
    for s in spots:
        box = PREF_BOX.get(s["pref"])
        if not box or not (box[0] <= s["lat"] <= box[1] and box[2] <= s["lon"] <= box[3]):
            dropped.append(f"{s['kind']}:{s['pref']}:{s['name']}")
            continue
        key = (s["kind"], s["pref"], s["name"], round(s["lat"], 3), round(s["lon"], 3))
        if key in seen:
            if len(s["desc"]) > len(seen[key]["desc"]):
                seen[key]["desc"] = s["desc"]
            continue
        seen[key] = s
        ok.append(s)
    return ok, dropped


def genre_of(s: dict) -> str:
    if s["kind"] != "food":
        return ""
    t = s["name"] + s["desc"]
    for g, kws in GENRES:
        if any(k in t for k in kws):
            return g
    return "その他"


def maps_url(s: dict) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={s['lat']:.6f},{s['lon']:.6f}"


# ---------- 画像 ----------
def _cover(img, w, h):
    from PIL import Image
    r = max(w / img.width, h / img.height)
    im = img.resize((max(1, round(img.width * r)), max(1, round(img.height * r))), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


def gsi_map(lat: float, lon: float, fetch=_http, layer: str = "std"):
    """国土地理院のタイル(標準地図/航空写真)を並べて 320x200 を切り出し、中央にピンを描く。"""
    from PIL import Image, ImageDraw, ImageFilter
    url, z, _ = GSI_LAYERS[layer]
    n = 2 ** z
    fx = (lon + 180.0) / 360.0 * n
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    cx, cy = fx * 256, fy * 256
    x0, y0 = int((cx - PHOTO_W / 2) // 256), int((cy - PHOTO_H / 2) // 256)
    x1, y1 = int((cx + PHOTO_W / 2) // 256), int((cy + PHOTO_H / 2) // 256)
    canvas = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256), (235, 235, 235))
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            try:
                tile = Image.open(io.BytesIO(fetch(url.format(z=z, x=tx, y=ty)))).convert("RGB")
                canvas.paste(tile, ((tx - x0) * 256, (ty - y0) * 256))
            except Exception:
                pass
            time.sleep(0.05)
    px, py = cx - x0 * 256, cy - y0 * 256
    left, top = int(px - PHOTO_W / 2), int(py - PHOTO_H / 2)
    im = canvas.crop((left, top, left + PHOTO_W, top + PHOTO_H)).convert("RGBA")
    # ピン(影つき): 先端が中心に来るしずく形
    cxp, cyp = PHOTO_W // 2, PHOTO_H // 2
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((cxp - 10, cyp - 4, cxp + 10, cyp + 4), fill=(0, 0, 0, 120))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(3)))
    d = ImageDraw.Draw(im)
    d.polygon([(cxp - 13, cyp - 30), (cxp + 13, cyp - 30), (cxp, cyp)], fill=(225, 45, 45, 255))
    d.ellipse((cxp - 17, cyp - 50, cxp + 17, cyp - 16), fill=(225, 45, 45, 255), outline=(255, 255, 255, 255), width=3)
    d.ellipse((cxp - 6, cyp - 39, cxp + 6, cyp - 27), fill=(255, 255, 255, 255))
    return im.convert("RGB")


def _pick_commons(titles: list, fetch, must_have: str = "", min_ratio: float = 1.2):
    """候補ファイルのうち、自由なライセンスの横長JPEGを1枚選ぶ。must_have があればタイトルか説明に含まれるものだけ。"""
    from PIL import Image
    if not titles:
        return None
    q = {"action": "query", "titles": "|".join(titles), "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
         "iiurlwidth": 640, "format": "json"}
    pages = json.loads(fetch(COMMONS_API + "?" + urllib.parse.urlencode(q))).get("query", {}).get("pages", {})
    order = {t: i for i, t in enumerate(titles)}
    for p in sorted(pages.values(), key=lambda p: order.get(p.get("title"), 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime") != "image/jpeg" or ii.get("width", 0) < ii.get("height", 1) * min_ratio:
            continue
        md = ii.get("extmetadata", {})
        lic = (md.get("LicenseShortName", {}).get("value") or "").lower()
        if not lic.startswith(OK_LICENSES):
            continue
        if must_have:
            hay = p.get("title", "") + _text(md.get("ImageDescription", {}).get("value", ""), 300)
            if must_have not in hay:
                continue
        artist = _text(md.get("Artist", {}).get("value", ""), 30) or "Wikimedia Commons"
        try:
            img = Image.open(io.BytesIO(fetch(ii["thumburl"]))).convert("RGB")
        except Exception:
            continue
        return _cover(img, PHOTO_W, PHOTO_H), f"{artist} / {md['LicenseShortName']['value']} (Wikimedia Commons)"
    return None


def _km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def wikidata_photo(lat: float, lon: float, name: str, fetch=_http):
    """Wikidata で名前から該当の項目を探し、座標が近い(2km以内)ものの代表画像(P18)を使う。"""
    key = re.sub(r"[（(].*?[）)]|【.*?】|\s+", "", name)
    if len(key) < 2:
        return None
    q = {"action": "wbsearchentities", "search": key, "language": "ja", "uselang": "ja", "limit": 5, "format": "json"}
    ids = [e["id"] for e in json.loads(fetch(WIKIDATA_API + "?" + urllib.parse.urlencode(q))).get("search", [])]
    if not ids:
        return None
    q = {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims", "format": "json"}
    ents = json.loads(fetch(WIKIDATA_API + "?" + urllib.parse.urlencode(q))).get("entities", {})
    for i in ids:
        claims = ents.get(i, {}).get("claims", {})
        try:
            c = claims["P625"][0]["mainsnak"]["datavalue"]["value"]
            img = claims["P18"][0]["mainsnak"]["datavalue"]["value"]
        except (KeyError, IndexError):
            continue
        if _km(lat, lon, c["latitude"], c["longitude"]) > 2.0:
            continue
        r = _pick_commons(["File:" + img], fetch, "", 0.9)
        if r:
            return r
    return None


def commons_photo(lat: float, lon: float, name: str, fetch=_http, near_ok: bool = True):
    """自由なライセンスの写真を探す。(Image, credit) か None。
    1) Wikidata の代表画像(名前+座標が合うもの)  2) 座標の近く(1km)の Commons の写真(観光地のみ)
    3) 名前で検索した Commons の写真(名前がタイトル/説明にあるものだけ)"""
    try:
        r = wikidata_photo(lat, lon, name, fetch)
        if r:
            return r
    except Exception as e:
        print("WARN wikidata", name, e, file=sys.stderr)
    if near_ok:  # お店は「近くの別の写真」を載せると紛らわしいので、観光地だけ
        q = {"action": "query", "list": "geosearch", "gscoordinate": f"{lat}|{lon}", "gsradius": 1000,
             "gsnamespace": 6, "gslimit": 20, "format": "json"}
        res = json.loads(fetch(COMMONS_API + "?" + urllib.parse.urlencode(q)))
        r = _pick_commons([g["title"] for g in res.get("query", {}).get("geosearch", [])], fetch)
        if r:
            return r
    key = re.sub(r"[（(].*?[）)]|【.*?】|\s+", "", name)
    if len(key) < 2:
        return None
    q = {"action": "query", "list": "search", "srsearch": key, "srnamespace": 6, "srlimit": 15, "format": "json"}
    res = json.loads(fetch(COMMONS_API + "?" + urllib.parse.urlencode(q)))
    return _pick_commons([x["title"] for x in res.get("query", {}).get("search", [])], fetch, key)


def qr_image(url: str):
    from PIL import Image
    qrcode = _pip("qrcode", "qrcode")
    q = qrcode.QRCode(border=2, box_size=6, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    im = q.make_image(fill_color="black", back_color="white").convert("RGB")
    return im.resize((QR_W, QR_W), Image.NEAREST)


def _bearing(la1, lo1, la2, lo2):
    p1, p2, dl = map(math.radians, (la1, la2, lo2 - lo1))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _dist_m(la1, lo1, la2, lo2):
    return math.hypot((la2 - la1) * 111000, (lo2 - lo1) * 111000 * math.cos(math.radians(la1)))


def mapillary_photo(lat: float, lon: float, kind: str, fetch=_http):
    """対象の方を向いている Mapillary の街路写真(CC BY-SA)。無ければ None。トークンは環境変数 MAPILLARY_TOKEN。"""
    import os
    from PIL import Image, ImageOps
    token = os.environ.get("MAPILLARY_TOKEN", "").strip()
    if not token.startswith("MLY|"):
        return None
    d0 = 0.002 if kind == "sight" else 0.001
    q = urllib.parse.urlencode({"fields": "id,thumb_1024_url,compass_angle,geometry,is_pano,creator",
                                "bbox": f"{lon-d0},{lat-d0},{lon+d0},{lat+d0}", "limit": 200})
    hdr = {"Authorization": "OAuth " + token}
    data = json.loads(fetch("https://graph.mapillary.com/images?" + q, headers=hdr)).get("data", [])
    best = None
    for it in data:
        if it.get("is_pano") or "compass_angle" not in it or not it.get("thumb_1024_url"):
            continue
        lo, la = it["geometry"]["coordinates"]
        dd = _dist_m(la, lo, lat, lon)
        if dd < 15 or dd > 120:
            continue
        diff = abs((_bearing(la, lo, lat, lon) - it["compass_angle"] + 180) % 360 - 180)
        if diff > 25:
            continue
        score = diff + dd / 10
        if best is None or score < best[0]:
            best = (score, it)
    if not best:
        return None
    it = best[1]
    raw = fetch(it["thumb_1024_url"], headers=hdr)
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im = ImageOps.fit(im, (PHOTO_W, PHOTO_H), Image.LANCZOS)
    who = (it.get("creator") or {}).get("username") or "Mapillary contributor"
    return im, f"{who} / CC BY-SA 4.0 (Mapillary)"


def build_image(s: dict, fetch=_http) -> tuple:
    """(合成画像, クレジット文) を返す。"""
    from PIL import Image
    photo, credit = None, ""
    if True:  # グルメも検索する(見つかるのは有名店だけ)
        try:
            r = commons_photo(s["lat"], s["lon"], s["name"], fetch, near_ok=(s["kind"] == "sight"))
            if r:
                photo, credit = r
        except Exception as e:
            print("WARN commons", s["name"], e, file=sys.stderr)
    if photo is None:
        try:
            r = mapillary_photo(s["lat"], s["lon"], s["kind"], fetch)
            if r:
                photo, credit = r
        except Exception as e:
            print("WARN mapillary", s["name"], e, file=sys.stderr)
    if photo is None:
        layer = "photo"
        photo, credit = gsi_map(s["lat"], s["lon"], fetch, layer), GSI_LAYERS[layer][2]
    tex = Image.new("RGB", (TEX_W, PHOTO_H), (255, 255, 255))
    tex.paste(photo, (0, 0))
    tex.paste(qr_image(maps_url(s)), (PHOTO_W, (PHOTO_H - QR_W) // 2))
    return tex, credit


def build_all(cfg: dict, out_dir: Path, cache_dir: Path, fetch=_http) -> tuple:
    """スポットを取得し、画像を public/img/s000.jpg… に書く。(spots, errors, dropped) を返す。"""
    _pip("PIL", "pillow")  # Actions の標準環境には無いので入れる
    _pip("qrcode", "qrcode")
    errors, raw = [], []
    for m in cfg.get("maps", []):
        kc = cache_dir / f"kml_{m['kind']}.kml"
        try:
            data = fetch(f"https://www.google.com/maps/d/kml?mid={m['mid']}&forcekml=1", 40)
            got = parse_kml(data, m["kind"])
            # 荒らし・誤削除対策: 前回より半分以下に減ったら、前回の正常なデータを使う
            prev = parse_kml(kc.read_bytes(), m["kind"]) if kc.exists() else []
            if prev and len(got) < len(prev) * 0.5:
                errors.append(f"spots {m.get('label', m['kind'])}: {len(prev)}件→{len(got)}件に急減したため前回のデータを使用")
                got = prev
            else:
                cache_dir.mkdir(parents=True, exist_ok=True)
                kc.write_bytes(data)
            raw += got
        except Exception as e:
            errors.append(f"spots {m.get('label', m['kind'])}: {e}")
            if kc.exists():
                raw += parse_kml(kc.read_bytes(), m["kind"])
    spots, dropped = clean(raw)
    spots = spots[: cfg.get("max_slots", 200)]

    img_dir = out_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    for old in img_dir.glob("s*.jpg"):
        old.unlink()
    cache_dir.mkdir(parents=True, exist_ok=True)
    result = []
    for i, s in enumerate(spots):
        key = hashlib.sha1(f"{IMG_VERSION}|{s['kind']}|{s['name']}|{s['lat']:.5f}|{s['lon']:.5f}".encode()).hexdigest()[:16]
        cj, cm = cache_dir / f"{key}.jpg", cache_dir / f"{key}.json"
        try:
            if cj.exists() and cm.exists():
                credit = json.loads(cm.read_text(encoding="utf-8"))["credit"]
            else:
                tex, credit = build_image(s, fetch)
                tex.save(cj, "JPEG", quality=82)
                cm.write_text(json.dumps({"credit": credit}, ensure_ascii=False), encoding="utf-8")
            (img_dir / f"s{i:03d}.jpg").write_bytes(cj.read_bytes())
        except Exception as e:
            errors.append(f"spot image {s['name']}: {e}")
            credit = ""
        result.append({"i": i, "kind": s["kind"], "pref": s["pref"], "name": s["name"], "desc": s["desc"],
                       "genre": genre_of(s), "url": maps_url(s), "credit": credit})
    return result, errors, dropped
