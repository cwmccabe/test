import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict

API = "https://en.wikipedia.org/w/api.php"
UA = "AgenticAIRiskLiteratureReview/1.0 (research crawl; cwmccabe.ai@gmail.com)"
ROOT = "Category:Science fiction novels by year"
OUT = "phase2_sf_novels.json"


def api(params, retries=6):
    params = dict(params)
    params.update({"format": "json", "formatversion": "2", "maxlag": "5"})
    url = API + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(min(30, 2 ** attempt))


def category_members(category, namespace):
    items = []
    cont = {}
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmnamespace": namespace,
            "cmlimit": "max",
            "cmprop": "ids|title|type",
        }
        params.update(cont)
        data = api(params)
        items.extend(data["query"]["categorymembers"])
        if "continue" not in data:
            break
        cont = data["continue"]
    return items


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def main():
    subcats = category_members(ROOT, 14)
    year_categories = sorted(
        [x for x in subcats if x["title"].endswith(" science fiction novels")],
        key=lambda x: x["title"],
    )
    memberships = []
    access_failures = []
    for i, cat in enumerate(year_categories, 1):
        try:
            members = category_members(cat["title"], 0)
            for m in members:
                memberships.append({
                    "year_category": cat["title"],
                    "listed_pageid": m["pageid"],
                    "listed_title": m["title"],
                })
        except Exception as e:
            access_failures.append({"category": cat["title"], "error": repr(e)})
        print(f"{i}/{len(year_categories)} {cat['title']}", flush=True)
        time.sleep(0.05)

    by_pageid = defaultdict(lambda: {"year_categories": [], "listed_titles": []})
    for m in memberships:
        d = by_pageid[m["listed_pageid"]]
        d["year_categories"].append(m["year_category"])
        d["listed_titles"].append(m["listed_title"])

    pageids = sorted(by_pageid)
    pages = {}
    for i, batch in enumerate(chunks(pageids, 20), 1):
        data = api({
            "action": "query",
            "prop": "extracts|info",
            "pageids": "|".join(map(str, batch)),
            "explaintext": "1",
            "inprop": "url",
            "redirects": "1",
        })
        for p in data["query"]["pages"]:
            pages[p["pageid"]] = {
                "pageid": p["pageid"],
                "title": p["title"],
                "fullurl": p.get("fullurl", ""),
                "extract": p.get("extract", ""),
            }
        print(f"extract batch {i}", flush=True)
        time.sleep(0.05)

    records = []
    missing_extract_pages = []
    for pageid, provenance in by_pageid.items():
        page = pages.get(pageid)
        if not page:
            missing_extract_pages.append(pageid)
            page = {"pageid": pageid, "title": provenance["listed_titles"][0], "fullurl": "", "extract": ""}
        records.append({
            **page,
            "year_categories": sorted(set(provenance["year_categories"])),
            "listed_titles": sorted(set(provenance["listed_titles"])),
        })

    payload = {
        "crawl_timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root_category": ROOT,
        "year_category_count": len(year_categories),
        "year_categories": [x["title"] for x in year_categories],
        "total_memberships": len(memberships),
        "distinct_pageids": len(records),
        "access_failures": access_failures,
        "missing_extract_pages": missing_extract_pages,
        "records": sorted(records, key=lambda x: (x["title"].casefold(), x["pageid"])),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(json.dumps({k: payload[k] for k in ["crawl_timestamp_utc", "year_category_count", "total_memberships", "distinct_pageids", "access_failures", "missing_extract_pages"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
