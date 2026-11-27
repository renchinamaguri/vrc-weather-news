import json, os, sys, urllib.request, urllib.parse
TOKEN = os.environ["MAPILLARY_TOKEN"]
PLACES = [("s_kenrokuen", "金沢 兼六園", 36.56210, 136.66270),
          ("s_takaoka", "高岡 大仏", 36.74890, 137.01600),
          ("s_tojinbo", "福井 東尋坊", 36.23710, 136.12590),
          ("s_yahiko", "新潟 弥彦神社", 37.70600, 138.82800)]
os.makedirs("test_out", exist_ok=True)
def get(url):
    r = urllib.request.Request(url, headers={"Authorization": "OAuth " + TOKEN})
    return urllib.request.urlopen(r, timeout=30).read()
import re
print("token shape:", len(TOKEN), "parts:", len(TOKEN.split("|")), "starts MLY|:", TOKEN.startswith("MLY|"), "has space/newline:", bool(re.search(r"\s", TOKEN)), "lens:", [len(x) for x in TOKEN.split("|")])
res = []
for key, name, lat, lon in PLACES:
    d0 = 0.001
    q = urllib.parse.urlencode({"fields": "id,thumb_1024_url,captured_at,compass_angle",
                                "bbox": f"{lon-d0},{lat-d0},{lon+d0},{lat+d0}", "limit": 5, "access_token": TOKEN})
    try:
        d = json.loads(get("https://graph.mapillary.com/images?" + q)).get("data", [])
    except Exception as e:
        body = e.read().decode()[:200] if hasattr(e, "read") else ""
        res.append({"place": name, "error": str(e), "body": body}); continue
    if not d:
        res.append({"place": name, "found": 0}); continue
    it = d[0]
    open(f"test_out/{key}.jpg", "wb").write(get(it["thumb_1024_url"]))
    res.append({"place": name, "found": len(d), "id": it["id"], "captured_at": it.get("captured_at")})
json.dump(res, open("test_out/result.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
# rerun2
# rerun3
