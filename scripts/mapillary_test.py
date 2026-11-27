import json, math, os, sys, urllib.request, urllib.parse
TOKEN = os.environ["MAPILLARY_TOKEN"]
PLACES = [("s_kenrokuen", "金沢 兼六園", 36.56210, 136.66270, 0.002),
          ("s_takaoka", "高岡 大仏", 36.74890, 137.01600, 0.002),
          ("s_tojinbo", "福井 東尋坊", 36.23710, 136.12590, 0.002),
          ("s_yahiko", "新潟 弥彦神社", 37.70600, 138.82800, 0.002),
          ("f_kanazawa", "金沢 近江町市場", 36.57150, 136.65890, 0.001),
          ("f_toyama", "富山駅前", 36.70150, 137.21350, 0.001),
          ("f_fukui", "福井駅前", 36.06200, 136.22300, 0.001),
          ("f_niigata", "新潟 ぽんしゅ館", 37.91200, 139.06200, 0.001)]
os.makedirs("test_out", exist_ok=True)
def get(url):
    r = urllib.request.Request(url, headers={"Authorization": "OAuth " + TOKEN})
    return urllib.request.urlopen(r, timeout=30).read()
def bearing(la1, lo1, la2, lo2):
    p1, p2, dl = map(math.radians, (la1, la2, lo2 - lo1))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360
def dist(la1, lo1, la2, lo2):
    return math.hypot((la2 - la1) * 111000, (lo2 - lo1) * 111000 * math.cos(math.radians(la1)))
res = []
for key, name, lat, lon, d0 in PLACES:
    q = urllib.parse.urlencode({"fields": "id,thumb_1024_url,captured_at,compass_angle,geometry,is_pano",
                                "bbox": f"{lon-d0},{lat-d0},{lon+d0},{lat+d0}", "limit": 200})
    try:
        d = json.loads(get("https://graph.mapillary.com/images?" + q)).get("data", [])
    except Exception as e:
        res.append({"place": name, "error": str(e)}); continue
    best = None
    for it in d:
        if it.get("is_pano") or "compass_angle" not in it: continue
        lo, la = it["geometry"]["coordinates"]
        dd = dist(la, lo, lat, lon)
        if dd < 15 or dd > 120: continue
        diff = abs((bearing(la, lo, lat, lon) - it["compass_angle"] + 180) % 360 - 180)
        if diff > 25: continue
        score = diff + dd / 10 - (it.get("captured_at", 0) / 1e12) * 0
        if best is None or score < best[0]: best = (score, it, dd, diff)
    if not best:
        res.append({"place": name, "candidates": len(d), "found": 0}); continue
    _, it, dd, diff = best
    open(f"test_out/{key}.jpg", "wb").write(get(it["thumb_1024_url"]))
    res.append({"place": name, "candidates": len(d), "found": 1, "id": it["id"], "dist_m": round(dd), "angle_off": round(diff)})
json.dump(res, open("test_out/result.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
