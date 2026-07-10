import json,time,urllib.parse,urllib.request
from collections import deque,defaultdict
import mwparserfromhell

API='https://en.wikipedia.org/w/api.php'
UA='AgenticAIRiskLiteratureReview/1.0 (research crawl; cwmccabe.ai@gmail.com)'
ROOT='Category:Mythology by culture'
OUT='phase2_mythology.json'

def api(params,retries=7):
    p=dict(params);p.update({'format':'json','formatversion':'2','maxlag':'5'})
    req=urllib.request.Request(API+'?'+urllib.parse.urlencode(p,doseq=True),headers={'User-Agent':UA})
    for a in range(retries):
        try:
            with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
        except Exception:
            if a+1==retries:raise
            time.sleep(min(45,2**a))

def clean(v):
    try:return mwparserfromhell.parse(str(v)).strip_code(normalize=True,collapse=True).strip()
    except:return str(v).strip()

def cat_members(cat):
    out=[];cont={}
    while True:
        p={'action':'query','list':'categorymembers','cmtitle':cat,'cmnamespace':'0|14','cmlimit':'max','cmprop':'ids|title|type'};p.update(cont)
        d=api(p);out.extend(d['query']['categorymembers'])
        if 'continue' not in d:return out
        cont=d['continue']

def chunks(seq,n):
    for i in range(0,len(seq),n):yield seq[i:i+n]

def fetch_pages(titles):
    resolved={};failures=[]
    for bi,batch in enumerate(chunks(sorted(set(titles)),20),1):
        try:
            d=api({'action':'query','prop':'revisions|info','titles':'|'.join(batch),'rvprop':'content','rvslots':'main','inprop':'url','redirects':1});q=d['query'];tmap={t:t for t in batch}
            for group in ['normalized','redirects']:
                for item in q.get(group,[]):
                    old,new=item['from'],item['to']
                    for src,target in list(tmap.items()):
                        if target==old:tmap[src]=new
            pages={p.get('title',''):p for p in q.get('pages',[])}
            for listed in batch:
                p=pages.get(tmap.get(listed,listed))
                if not p or p.get('missing') or 'pageid' not in p:
                    failures.append({'title':listed,'error':'missing'});continue
                content='';revs=p.get('revisions',[])
                if revs:content=revs[0].get('slots',{}).get('main',{}).get('content','')
                code=mwparserfromhell.parse(content);fields={};infobox=''
                for t in code.filter_templates(recursive=False):
                    n=clean(t.name).lower()
                    if n.startswith('infobox'):
                        infobox=clean(t.name)
                        for par in t.params:fields[clean(par.name).lower()]=clean(par.value)
                        break
                resolved[listed]={'pageid':p['pageid'],'title':p['title'],'fullurl':p.get('fullurl',''),'extract':code.strip_code(normalize=True,collapse=True),'infobox_template':infobox,'infobox_fields':fields}
        except Exception as e:failures.append({'batch':batch,'error':repr(e)})
        if bi%50==0:print('page batch',bi,'of',((len(set(titles))+19)//20),flush=True)
        time.sleep(.025)
    return resolved,failures

def main():
    q=deque([ROOT]);seen=set();categories=[];edges=[];direct=[];failures=[]
    while q:
        cat=q.popleft()
        if cat in seen:continue
        seen.add(cat);categories.append(cat)
        try:members=cat_members(cat)
        except Exception as e:failures.append({'category':cat,'error':repr(e)});continue
        for m in members:
            if m['ns']==14:q.append(m['title']);edges.append({'parent':cat,'child':m['title']})
            elif m['ns']==0:direct.append({'category':cat,'listed_pageid':m['pageid'],'listed_title':m['title']})
        if len(categories)%250==0:print('categories',len(categories),'direct',len(direct),flush=True)
    direct_titles=[x['listed_title'] for x in direct];pages,fail2=fetch_pages(direct_titles);failures.extend(fail2)
    by_pid=defaultdict(lambda:{'category_memberships':set(),'listed_titles':set()});canonical={}
    for x in direct:
        p=pages.get(x['listed_title'])
        if p:
            canonical[p['pageid']]=p;d=by_pid[p['pageid']];d['category_memberships'].add(x['category']);d['listed_titles'].add(x['listed_title'])
    records=[]
    for pid,prov in by_pid.items():
        p=canonical[pid];records.append({**p,'category_memberships':sorted(prov['category_memberships']),'listed_titles':sorted(prov['listed_titles'])})
    payload={'crawl_timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'root_category':ROOT,'category_count':len(categories),'category_edges':len(edges),'direct_memberships_total':len(direct),'distinct_direct_titles':len(set(direct_titles)),'distinct_canonical_pageids':len(records),'failures':failures,'records':sorted(records,key=lambda r:(r['title'].casefold(),r['pageid']))}
    with open(OUT,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False)
    print(json.dumps({k:payload[k] for k in ['category_count','category_edges','direct_memberships_total','distinct_direct_titles','distinct_canonical_pageids','failures']},ensure_ascii=False))
if __name__=='__main__':main()
