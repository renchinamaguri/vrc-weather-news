import json, urllib.request, urllib.parse
UA={"User-Agent":"vrc-weather-news probe (GitHub Actions)"}
def get(u):
    try:
        return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40).read()
    except Exception as e:
        return ("ERR "+str(e)).encode()
SITES={"ishikawa":"https://ckan.opendata.pref.ishikawa.lg.jp","toyama":"https://opendata.pref.toyama.jp",
       "fukui_odp":"https://ckan.odp.jig.jp","geospatial":"https://www.geospatial.jp/ckan"}
out={}
for k,base in SITES.items():
    for q in ["イベント","観光イベント"]:
        u=base+"/api/3/action/package_search?"+urllib.parse.urlencode({"q":q,"rows":50,"sort":"metadata_modified desc"})
        raw=get(u)
        try:
            d=json.loads(raw)["result"]["results"]
            out[f"{k}:{q}"]=[{"title":p.get("title"),"name":p.get("name"),"org":(p.get("organization") or {}).get("title"),
               "license":p.get("license_title"),"modified":p.get("metadata_modified"),
               "res":[{"url":r.get("url"),"fmt":r.get("format"),"mod":r.get("last_modified") or r.get("created")} for r in p.get("resources",[])][:6]} for p in d]
        except Exception as e:
            out[f"{k}:{q}"]="ERR "+raw[:200].decode("utf-8","replace")
for name,u in {"niigata_city_event":"https://www.city.niigata.lg.jp/shisei/seisaku/it/open-data/opendata-kankou/od-event.html",
               "niigata_insight":"https://niigata.insight-lab.co.jp/niigata-open-data"}.items():
    out[name]=get(u).decode("utf-8","replace")[:20000]
json.dump(out,open("probe_out/events.json","w"),ensure_ascii=False,indent=1)
print({k:(len(v) if isinstance(v,list) else v[:80]) for k,v in out.items()})
