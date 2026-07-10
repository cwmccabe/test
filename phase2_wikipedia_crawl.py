import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    items, cont = [], {}
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
            return items
        cont = data["continue"]


def resolve_title(listed_title):
    data = api({
        "action": "query",
        "prop": "extracts|info",
        "titles": listed_title,
        "explaintext": "1",
        "inprop": "url",
        "redirects": "1",
    })
    pages = data["query"]["pages"]
    if len(pages) != 1:
        raise RuntimeError(f"Unexpected page count for {listed_title!r}: {len(pages)}")
    p = pages[0]
    return {
        "pageid": p["pageid"],
        "title": p["title"],
        "fullurl": p.get("fullurl", ""),
        "extract": p.get("extract", ""),
        "missing": bool(p.get("missing", False)),
    }


def main():
    subcats = category_members(ROOT, 14)
    year_categories = sorted(
        [x for x in subcats if x["title"].endswith(" science fiction novels")],
        key=lambda x: x["title"],
    )
    memberships, access_failures = [], []
    for i, cat in enumerate(year_categories, 1):
        try:
            for m in category_members(cat["title"], 0):
                memberships.append({
                    "year_category": cat["title"],
                    "listed_pageid": m["pageid"],
                    "listed_title": m["title"],
                })
        except Exception as e:
            access_failures.append({"category": cat["title"], "error": repr(e)})
        print(f"category {i}/{len(year_categories)} {cat['title']}", flush=True)
        time.sleep(0.05)

    unique_titles = sorted({m["listed_title"] for m in memberships})
    resolved, unresolved_titles = {}, []
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_title = {executor.submit(resolve_title, title): title for title in unique_titles}
        completed = 0
        for future in as_completed(future_to_title):
            title = future_to_title[future]
            try:
                resolved[title] = future.result()
            except Exception as e:
                unresolved_titles.append(title)
                access_failures.append({"extract_title": title, "error": repr(e)})
            completed += 1
            if completed % 100 == 0 or completed == len(unique_titles):
                print(f"extract {completed}/{len(unique_titles)}", flush=True)

    by_canonical_pageid = defaultdict(lambda: {
        "year_categories": [], "listed_titles": [], "listed_pageids": []
    })
    pages = {}
    for m in memberships:
        page = resolved.get(m["listed_title"])
        if page is None:
            continue
        pid = page["pageid"]
        pages[pid] = page
        d = by_canonical_pageid[pid]
        d["year_categories"].append(m["year_category"])
        d["listed_titles"].append(m["listed_title"])
        d["listed_pageids"].append(m["listed_pageid"])

    records = []
    for pid, provenance in by_canonical_pageid.items():
        records.append({
            **pages[pid],
            "year_categories": sorted(set(provenance["year_categories"])),
            "listed_titles": sorted(set(provenance["listed_titles"])),
            "listed_pageids": sorted(set(provenance["listed_pageids"])),
        })

    empty_extract_pageids = sorted(r["pageid"] for r in records if not r["extract"].strip())
    payload = {
        "crawl_timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root_category": ROOT,
        "year_category_count": len(year_categories),
        "year_categories": [x["title"] for x in year_categories],
        "total_memberships": len(memberships),
        "distinct_listed_titles": len(unique_titles),
        "distinct_canonical_pageids": len(records),
        "access_failures": access_failures,
        "unresolved_titles": sorted(set(unresolved_titles)),
        "empty_extract_pageids": empty_extract_pageids,
        "records": sorted(records, key=lambda x: (x["title"].casefold(), x["pageid"])),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    summary_keys = [
        "crawl_timestamp_utc", "year_category_count", "total_memberships",
        "distinct_listed_titles", "distinct_canonical_pageids", "access_failures",
        "unresolved_titles", "empty_extract_pageids"
    ]
    print(json.dumps({k: payload[k] for k in summary_keys}, ensure_ascii=False))


if __name__ == "__main__":
    main()
