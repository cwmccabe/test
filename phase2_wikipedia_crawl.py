import json, os, time, urllib.parse, urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import mwparserfromhell

API='https://en.wikipedia.org/w/api.php'
UA='AgenticAIRiskLiteratureReview/1.0 (research crawl; cwmccabe.ai@gmail.com)'
FRAME=os.environ.get('FRAME','mythology').strip().lower()
WORKERS=12

CONFIG={
  'folklore': {
    'roots':['Category:Folklore by country','Category:Fairy tales by country','Category:Legends by country'],
    'list_page':'List of fairy tales',
    'out':'phase2_folklore_fairy_legends.json'
  },
  'mythology': {
    'roots':['Category:Mythology by culture'],
    'list_page':None,
    'out':'phase2_mythology.json'
  }
}[FRAME]

def api(params,retries=7):
    p=dict(params); p.update({'format':'json','formatversion':'2','maxlag':'5'})
    url=API+'?'+urllib.parse.urlencode(p,doseq=True)
    for a in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA})
            with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
        except Exception:
            if a+1==retries: raise
            time.sleep(min(30,2**a))

def clean(v):
    try:return mwparserfromhell.parse(str(v)).strip_code(normalize=True,collapse=True).strip()
    except:return str(v).strip()

def cat_members(cat):
    out=[]; cont={}
    while True:
        p={'action':'query','list':'categorymembers','cmtitle':cat,'cmnamespace':'0|14','cmlimit':'max','cmprop':'ids|title|type'}; p.update(cont)
        d=api(p); out.extend(d['query']['categorymembers'])
        if 'continue' not in d:return out
        cont=d['continue']

def traverse_root(root):
    seen=set(); queue=deque([root]); edges=[]; direct=[]; failures=[]
    while queue:
        frontier=[]
        while queue and len(frontier)<WORKERS*8:
            cat=queue.popleft()
            if cat not in seen:
                seen.add(cat); frontier.append(cat)
        if not frontier: continue
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs={ex.submit(cat_members,cat):cat for cat in frontier}
            for fut in as_completed(futs):
                cat=futs[fut]
                try: members=fut.result()
                except Exception as e:
                    failures.append({'category':cat,'root':root,'error':repr(e)}); continue
                for m in members:
                    if m['ns']==14:
                        child=m['title']; edges.append({'root':root,'parent':cat,'child':child})
                        if child not in seen: queue.append(child)
                    elif m['ns']==0:
                        direct.append({'root':root,'category':cat,'listed_pageid':m['pageid'],'listed_title':m['title']})
        if len(seen)%500< len(frontier): print(FRAME,root,'categories',len(seen),'direct',len(direct),flush=True)
    return {'root':root,'categories':sorted(seen),'edges':edges,'direct':direct,'failures':failures}

def fetch_list_info(title):
    d=api({'action':'query','prop':'revisions|info','titles':title,'rvprop':'content','rvslots':'main','inprop':'url','redirects':1})
    p=d['query']['pages'][0]; content=p['revisions'][0]['slots']['main']['content']; code=mwparserfromhell.parse(content)
    links=[]
    for link in code.filter_wikilinks(recursive=True):
        t=clean(link.title).split('#',1)[0].strip()
        if t and ':' not in t: links.append(t)
    return {'pageid':p['pageid'],'title':p['title'],'fullurl':p.get('fullurl',''),'listed_titles':sorted(set(links))}

def chunks(seq,n):
    s=list(seq)
    for i in range(0,len(s),n): yield s[i:i+n]

def fetch_batch(batch):
    d=api({'action':'query','prop':'revisions|info','titles':'|'.join(batch),'rvprop':'content','rvslots':'main','inprop':'url','redirects':1})
    q=d['query']; tmap={t:t for t in batch}
    for group in ['normalized','redirects']:
        for item in q.get(group,[]):
            old,new=item['from'],item['to']
            for src,target in list(tmap.items()):
                if target==old:tmap[src]=new
    pages={p.get('title',''):p for p in q.get('pages',[])}
    resolved={}; failures=[]
    for listed in batch:
        p=pages.get(tmap.get(listed,listed))
        if not p or p.get('missing') or 'pageid' not in p:
            failures.append({'title':listed,'error':'missing'}); continue
        content=''; revs=p.get('revisions',[])
        if revs: content=revs[0].get('slots',{}).get('main',{}).get('content','')
        code=mwparserfromhell.parse(content); fields={}; infobox=''
        for t in code.filter_templates(recursive=False):
            n=clean(t.name).lower()
            if n.startswith('infobox'):
                infobox=clean(t.name)
                for par in t.params: fields[clean(par.name).lower()]=clean(par.value)
                break
        resolved[listed]={'pageid':p['pageid'],'title':p['title'],'fullurl':p.get('fullurl',''),'extract':code.strip_code(normalize=True,collapse=True),'infobox_template':infobox,'infobox_fields':fields}
    return resolved,failures

def fetch_pages(titles):
    batches=list(chunks(sorted(set(titles)),20)); resolved={}; failures=[]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs={ex.submit(fetch_batch,b):i for i,b in enumerate(batches,1)}
        done=0
        for fut in as_completed(futs):
            done+=1
            try:r,f=fut.result(); resolved.update(r); failures.extend(f)
            except Exception as e: failures.append({'batch_index':futs[fut],'error':repr(e)})
            if done%100==0: print(FRAME,'page batches',done,'of',len(batches),flush=True)
    return resolved,failures

def main():
    with ThreadPoolExecutor(max_workers=len(CONFIG['roots'])) as ex:
        root_results=list(ex.map(traverse_root,CONFIG['roots']))
    direct=[]; edges=[]; failures=[]; categories=set(); root_category_counts={}
    for rr in root_results:
        root_category_counts[rr['root']]=len(rr['categories']); categories.update(rr['categories']); edges.extend(rr['edges']); direct.extend(rr['direct']); failures.extend(rr['failures'])
    list_info=fetch_list_info(CONFIG['list_page']) if CONFIG['list_page'] else None
    list_titles=list_info['listed_titles'] if list_info else []
    direct_titles=[x['listed_title'] for x in direct]
    pages,fail2=fetch_pages(direct_titles+list_titles); failures.extend(fail2)
    by_pid=defaultdict(lambda:{'root_memberships':set(),'category_memberships':set(),'list_sources':[],'listed_titles':set()}); canonical={}
    for x in direct:
        p=pages.get(x['listed_title'])
        if p:
            canonical[p['pageid']]=p; d=by_pid[p['pageid']]; d['root_memberships'].add(x['root']); d['category_memberships'].add(x['category']); d['listed_titles'].add(x['listed_title'])
    for title in list_titles:
        p=pages.get(title)
        if p:
            canonical[p['pageid']]=p; d=by_pid[p['pageid']]; d['list_sources'].append({'source_title':list_info['title'],'source_pageid':list_info['pageid'],'source_url':list_info['fullurl']}); d['listed_titles'].add(title)
    records=[]
    for pid,prov in by_pid.items():
        p=canonical[pid]; records.append({**p,'root_memberships':sorted(prov['root_memberships']),'category_memberships':sorted(prov['category_memberships']),'list_sources':prov['list_sources'],'listed_titles':sorted(prov['listed_titles'])})
    payload={'crawl_timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'frame':FRAME,'roots':CONFIG['roots'],'root_category_counts':root_category_counts,'list_page':list_info,'distinct_categories_traversed':len(categories),'category_edges':len(edges),'direct_memberships_total':len(direct),'distinct_direct_titles':len(set(direct_titles)),'list_link_memberships_total':len(list_titles),'distinct_list_titles':len(set(list_titles)),'distinct_listed_titles_union':len(set(direct_titles+list_titles)),'distinct_canonical_pageids':len(records),'failures':failures,'records':sorted(records,key=lambda r:(r['title'].casefold(),r['pageid']))}
    with open(CONFIG['out'],'w',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False)
    print(json.dumps({k:payload[k] for k in ['frame','root_category_counts','distinct_categories_traversed','category_edges','direct_memberships_total','distinct_direct_titles','list_link_memberships_total','distinct_list_titles','distinct_listed_titles_union','distinct_canonical_pageids','failures']},ensure_ascii=False))
if __name__=='__main__':main()
