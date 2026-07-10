import json,time,urllib.parse,urllib.request
from collections import deque,defaultdict
import mwparserfromhell
API='https://en.wikipedia.org/w/api.php'; UA='AgenticAIRiskLiteratureReview/1.0 (research crawl; cwmccabe.ai@gmail.com)'; ROOT='Category:Fables'; OUT='phase2_fables.json'
EXACT_INDEX={"Aesop's Fables",'Panchatantra','Hitopadesha',"La Fontaine's Fables",'Perry Index'}

def api(params,retries=6):
    p=dict(params); p.update({'format':'json','formatversion':'2','maxlag':'5'}); req=urllib.request.Request(API+'?'+urllib.parse.urlencode(p,doseq=True),headers={'User-Agent':UA})
    for a in range(retries):
        try:
            with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
        except Exception:
            if a+1==retries: raise
            time.sleep(min(30,2**a))

def cat_members(cat):
    out=[]; cont={}
    while True:
        p={'action':'query','list':'categorymembers','cmtitle':cat,'cmnamespace':'0|14','cmlimit':'max','cmprop':'ids|title|type'}; p.update(cont); d=api(p); out.extend(d['query']['categorymembers'])
        if 'continue' not in d:return out
        cont=d['continue']

def chunks(seq,n):
    for i in range(0,len(seq),n):yield seq[i:i+n]

def clean(v):
    try:return mwparserfromhell.parse(str(v)).strip_code(normalize=True,collapse=True).strip()
    except:return str(v).strip()

def fetch_pages(titles):
    resolved={}; failures=[]
    for bi,batch in enumerate(chunks(sorted(set(titles)),20),1):
        try:
            d=api({'action':'query','prop':'revisions|info','titles':'|'.join(batch),'rvprop':'content','rvslots':'main','inprop':'url','redirects':1}); q=d['query']; tmap={t:t for t in batch}
            for group in ['normalized','redirects']:
                for item in q.get(group,[]):
                    old,new=item['from'],item['to']
                    for src,target in list(tmap.items()):
                        if target==old:tmap[src]=new
            pages={p.get('title',''):p for p in q.get('pages',[])}
            for listed in batch:
                p=pages.get(tmap.get(listed,listed))
                if not p or p.get('missing') or 'pageid' not in p: failures.append({'title':listed,'error':'missing'}); continue
                content=''; revs=p.get('revisions',[])
                if revs:content=revs[0].get('slots',{}).get('main',{}).get('content','')
                code=mwparserfromhell.parse(content); fields={}; infobox=''
                for t in code.filter_templates(recursive=False):
                    n=clean(t.name).lower()
                    if n.startswith('infobox'):
                        infobox=clean(t.name)
                        for par in t.params:fields[clean(par.name).lower()]=clean(par.value)
                        break
                resolved[listed]={'pageid':p['pageid'],'title':p['title'],'fullurl':p.get('fullurl',''),'wikitext':content,'extract':code.strip_code(normalize=True,collapse=True),'infobox_template':infobox,'infobox_fields':fields}
        except Exception as e: failures.append({'batch':batch,'error':repr(e)})
        if bi%20==0:print('page batch',bi,flush=True)
        time.sleep(.03)
    return resolved,failures

def is_index_title(title):
    if title in EXACT_INDEX:return True
    tl=title.casefold()
    return tl.startswith('list of ') and any(k in tl for k in ['fable','panchatantra','vetala tale','jataka'])

def index_links(page):
    if not is_index_title(page['title']):return []
    code=mwparserfromhell.parse(page['wikitext']); links=[]
    for link in code.filter_wikilinks(recursive=True):
        title=clean(link.title).split('#',1)[0].strip()
        if title and ':' not in title:links.append(title)
    return sorted(set(links)) if len(set(links))>=10 else []

def main():
    q=deque([ROOT]); seen=set(); categories=[]; cat_edges=[]; direct=[]; failures=[]
    while q:
        cat=q.popleft()
        if cat in seen:continue
        seen.add(cat);categories.append(cat)
        try:members=cat_members(cat)
        except Exception as e:failures.append({'category':cat,'error':repr(e)});continue
        for m in members:
            if m['ns']==14:q.append(m['title']);cat_edges.append({'parent':cat,'child':m['title']})
            elif m['ns']==0:direct.append({'category':cat,'listed_pageid':m['pageid'],'listed_title':m['title']})
        if len(categories)%25==0:print('categories',len(categories),'direct',len(direct),flush=True)
    direct_titles=[x['listed_title'] for x in direct];pages1,fail1=fetch_pages(direct_titles);failures.extend(fail1);index_sources=[];index_targets=[]
    for listed,p in pages1.items():
        links=index_links(p)
        if links:
            index_sources.append({'source_title':p['title'],'source_pageid':p['pageid'],'source_url':p['fullurl'],'link_count':len(links)})
            index_targets.extend({'source_title':p['title'],'source_pageid':p['pageid'],'source_url':p['fullurl'],'listed_title':t} for t in links)
    pages2,fail2=fetch_pages([x['listed_title'] for x in index_targets]);failures.extend(fail2);by_pid=defaultdict(lambda:{'category_memberships':[],'index_sources':[],'listed_titles':[]});pages={}
    for x in direct:
        p=pages1.get(x['listed_title'])
        if p:pages[p['pageid']]=p;d=by_pid[p['pageid']];d['category_memberships'].append(x['category']);d['listed_titles'].append(x['listed_title'])
    for x in index_targets:
        p=pages2.get(x['listed_title'])
        if p:pages[p['pageid']]=p;d=by_pid[p['pageid']];d['index_sources'].append({'source_title':x['source_title'],'source_pageid':x['source_pageid'],'source_url':x['source_url']});d['listed_titles'].append(x['listed_title'])
    records=[]
    for pid,prov in by_pid.items():
        p=pages[pid];records.append({k:v for k,v in p.items() if k!='wikitext'}|{'category_memberships':sorted(set(prov['category_memberships'])),'index_sources':list({(x['source_pageid'],x['source_title'],x['source_url']):x for x in prov['index_sources']}.values()),'listed_titles':sorted(set(prov['listed_titles']))})
    payload={'crawl_timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'root_category':ROOT,'category_count':len(categories),'category_edges':len(cat_edges),'direct_memberships_total':len(direct),'distinct_direct_titles':len(set(direct_titles)),'index_source_count':len(index_sources),'index_sources':index_sources,'index_link_memberships_total':len(index_targets),'distinct_listed_titles_union':len(set(direct_titles+[x['listed_title'] for x in index_targets])),'distinct_canonical_pageids':len(records),'failures':failures,'records':sorted(records,key=lambda r:(r['title'].casefold(),r['pageid']))}
    with open(OUT,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False)
    print(json.dumps({k:payload[k] for k in ['category_count','direct_memberships_total','distinct_direct_titles','index_source_count','index_sources','index_link_memberships_total','distinct_listed_titles_union','distinct_canonical_pageids','failures']},ensure_ascii=False))
if __name__=='__main__':main()
