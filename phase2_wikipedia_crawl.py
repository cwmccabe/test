import io,json,time,urllib.parse,urllib.request
from collections import defaultdict
import pandas as pd
import mwparserfromhell

API='https://en.wikipedia.org/w/api.php'
UA='AgenticAIRiskLiteratureReview/1.0 (research crawl; cwmccabe.ai@gmail.com)'
CATEGORY='Category:Science fiction short stories'
LIST_PAGE='List of science fiction short stories'
OUT='phase2_sf_short_fiction.json'

def api(params,retries=6):
    p=dict(params); p.update({'format':'json','formatversion':'2','maxlag':'5'})
    req=urllib.request.Request(API+'?'+urllib.parse.urlencode(p,doseq=True),headers={'User-Agent':UA})
    for a in range(retries):
        try:
            with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
        except Exception:
            if a+1==retries: raise
            time.sleep(min(30,2**a))

def category_members():
    items=[]; cont={}
    while True:
        p={'action':'query','list':'categorymembers','cmtitle':CATEGORY,'cmnamespace':0,'cmlimit':'max','cmprop':'ids|title|type'}; p.update(cont)
        d=api(p); items.extend(d['query']['categorymembers'])
        if 'continue' not in d:return items
        cont=d['continue']

def fetch_url(url):
    req=urllib.request.Request(url,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=120) as r:return r.read()

def parse_list_rows():
    url='https://en.wikipedia.org/wiki/'+LIST_PAGE.replace(' ','_')
    html=fetch_url(url)
    tables=pd.read_html(io.BytesIO(html))
    rows=[]
    for ti,t in enumerate(tables):
        cols=[str(c).strip() for c in t.columns]
        lower=[c.lower() for c in cols]
        title_col=next((cols[i] for i,c in enumerate(lower) if 'title' in c or 'story'==c),None)
        author_col=next((cols[i] for i,c in enumerate(lower) if 'author' in c or 'writer' in c),None)
        year_col=next((cols[i] for i,c in enumerate(lower) if 'year' in c or 'date' in c),None)
        if not title_col: continue
        for ri,row in t.iterrows():
            title=str(row.get(title_col,'')).strip()
            if not title or title.lower() in {'nan','title','story'}: continue
            rows.append({'table_index':ti,'row_index':int(ri),'listed_title':title,'author':str(row.get(author_col,'')).strip() if author_col else '', 'year':str(row.get(year_col,'')).strip() if year_col else ''})
    return rows,tables

def chunks(seq,n):
    for i in range(0,len(seq),n):yield seq[i:i+n]

def clean(v):
    try:return mwparserfromhell.parse(str(v)).strip_code(normalize=True,collapse=True).strip()
    except:return str(v).strip()

def resolve_titles(titles):
    resolved={}; failures=[]
    for bi,batch in enumerate(chunks(sorted(set(titles)),20),1):
        try:
            d=api({'action':'query','prop':'revisions|info','titles':'|'.join(batch),'rvprop':'content','rvslots':'main','inprop':'url','redirects':1})
            q=d['query']; tmap={t:t for t in batch}
            for group in ['normalized','redirects']:
                for item in q.get(group,[]):
                    old,new=item['from'],item['to']
                    for src,target in list(tmap.items()):
                        if target==old:tmap[src]=new
            pages={p['title']:p for p in q['pages']}
            for listed in batch:
                ct=tmap.get(listed,listed); p=pages.get(ct)
                if not p or p.get('missing'): failures.append({'title':listed,'error':'missing'}); continue
                content=''; revs=p.get('revisions',[])
                if revs:content=revs[0].get('slots',{}).get('main',{}).get('content','')
                code=mwparserfromhell.parse(content); fields={}; infobox=''
                for t in code.filter_templates(recursive=False):
                    n=clean(t.name).lower()
                    if n.startswith('infobox') and any(x in n for x in ['book','novel','short story']):
                        infobox=clean(t.name)
                        for par in t.params:fields[clean(par.name).lower()]=clean(par.value)
                        break
                resolved[listed]={'pageid':p['pageid'],'title':p['title'],'fullurl':p.get('fullurl',''),'extract':code.strip_code(normalize=True,collapse=True),'infobox_template':infobox,'infobox_fields':fields}
        except Exception as e:
            failures.append({'batch':batch,'error':repr(e)})
        print('content batch',bi,flush=True);time.sleep(.05)
    return resolved,failures

def main():
    cats=category_members(); list_rows,tables=parse_list_rows()
    cat_titles=[x['title'] for x in cats]; list_titles=[x['listed_title'] for x in list_rows]
    resolved,failures=resolve_titles(cat_titles+list_titles)
    by_pid=defaultdict(lambda:{'category_memberships':[],'list_rows':[],'listed_titles':[]})
    pages={}
    for x in cats:
        p=resolved.get(x['title'])
        if not p:continue
        pages[p['pageid']]=p; d=by_pid[p['pageid']]; d['category_memberships'].append(CATEGORY); d['listed_titles'].append(x['title'])
    for x in list_rows:
        p=resolved.get(x['listed_title'])
        if not p:continue
        pages[p['pageid']]=p; d=by_pid[p['pageid']]; d['list_rows'].append(x); d['listed_titles'].append(x['listed_title'])
    records=[]
    for pid,prov in by_pid.items():
        records.append({**pages[pid],'category_memberships':sorted(set(prov['category_memberships'])),'list_rows':prov['list_rows'],'listed_titles':sorted(set(prov['listed_titles']))})
    payload={'crawl_timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'category':CATEGORY,'list_page':LIST_PAGE,'category_memberships_total':len(cats),'list_rows_total':len(list_rows),'list_table_count':len(tables),'distinct_listed_titles':len(set(cat_titles+list_titles)),'distinct_canonical_pageids':len(records),'failures':failures,'records':sorted(records,key=lambda r:(r['title'].casefold(),r['pageid']))}
    with open(OUT,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False)
    print(json.dumps({k:payload[k] for k in ['category_memberships_total','list_rows_total','list_table_count','distinct_listed_titles','distinct_canonical_pageids','failures']},ensure_ascii=False))
if __name__=='__main__':main()
