import json, os, re, urllib.request, urllib.parse, csv, io
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
def get(u):
    try: return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40).read()
    except Exception as e: return ("ERR "+str(e)).encode()
out={}
# Fukui event dataset resources
d=json.loads(get("https://ckan.odp.jig.jp/api/3/action/package_search?q=%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&rows=10"))["result"]["results"]
for p in d:
    for r in p["resources"]:
        if r.get("format","").upper()=="CSV":
            raw=get(r["url"])
            txt=None
            for enc in ("utf-8-sig","cp932"):
                try: txt=raw.decode(enc); break
                except: pass
            txt=txt or raw.decode("utf-8","replace")
            rows=list(csv.reader(io.StringIO(txt)))
            dates=sorted(set(re.findall(r"20\d\d[-/]\d\d?[-/]\d\d?",txt)))
            out["fukui:"+p["title"]]={"url":r["url"],"rows":len(rows),"header":rows[0] if rows else None,"sample":rows[1:4],"min_date":dates[:2],"max_date":dates[-3:]}
for name,u in {"ishikawa_ckan":"https://ckan.opendata.pref.ishikawa.lg.jp/api/3/action/package_search?q=%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&rows=30",
  "ishikawa_front":"https://front.opendata.pref.ishikawa.lg.jp/",
  "toyama_ckan":"https://opendata.pref.toyama.jp/api/3/action/package_search?q=%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&rows=30",
  "toyama_www":"https://www.opendata.pref.toyama.jp/",
  "fukui_lib":"https://www.pref.fukui.lg.jp/doc/toukei-jouhou/opendata/list_ct_kankou.html",
  "niigata_city_od":"https://www.city.niigata.lg.jp/shisei/seisaku/it/open-data/index.html",
  "niigata_pref_list":"https://www.pref.niigata.lg.jp/sec/list10-1.html"}.items():
    t=get(u).decode("utf-8","replace")
    if t.startswith("{"):
        try:
            rs=json.loads(t)["result"]["results"]
            out[name]=[{"title":p["title"],"mod":p.get("metadata_modified"),"lic":p.get("license_title"),"res":[(r.get("format"),r.get("url")) for r in p["resources"]][:4]} for p in rs]; continue
        except: pass
    hits=[m for m in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{0,80})',t) if re.search("イベント|event|観光",m[0]+m[1],re.I)]
    out[name]={"head":t[:120],"len":len(t),"links":hits[:40]}
os.makedirs("probe_out",exist_ok=True)
json.dump(out,open("probe_out/events.json","w"),ensure_ascii=False,indent=1)
