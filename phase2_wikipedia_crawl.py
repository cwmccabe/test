import json,time,urllib.parse,urllib.request
from collections import deque,defaultdict
import mwparserfromhell

API='https://en.wikipedia.org/w/api.php'
UA='AgenticAIRiskLiteratureReview/1.0 (research crawl; cwmccabe.ai@gmail.com)'
ROOTS=['Category:Folklore by country','Category:Fairy tales by country','Category:Legends by country']
LIST_PAGE='List of fairy tales'
OUT='phase2_folklore_fairy_legends.json'

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

def fetch_list_wikitext():
    d=api({'action':'query','prop':'revisions|info','titles':LIST_PAGE,'rvprop':'content','rvslots':'main','inprop':'url','redirects':1})
    p=d['query']['pages'][0];content=p['revisions'][0]['slots']['main']['content'];code=mwparserfromhell.parse(content)
    links=[]
    for link in code.filter_wikilinks(recursive=True):
        title=clean(link.title).split('#',1)[0].strip()
        if title and ':' not in title:links.append(title)
    return {'pageid':p['pageid'],'title':p['title'],'fullurl':p.get('fullurl',''),'listed_titles':sorted(set(links))}

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
    categories=[];edges=[];direct=[];failures=[];root_reach=defaultdict(set)
    q=deque((r,r) for r in ROOTS);seen_by_root=set()
    while q:
        root,cat=q.popleft();key=(root,cat)
        if key in seen_by_root:continue
        seen_by_root.add(key);root_reach[cat].add(root)
        if cat not in categories:categories.append(cat)
        try:members=cat_members(cat)
        except Exception as e:failures.append({'category':cat,'root':root,'error':repr(e)});continue
        for m in members:
            if m['ns']==14:
                q.append((root,m['title']));edges.append({'root':root,'parent':cat,'child':m['title']})
            elif m['ns']==0:direct.append({'root':root,'category':cat,'listed_pageid':m['pageid'],'listed_title':m['title']})
        if len(seen_by_root)%250==0:print('category-root visits',len(seen_by_root),'unique cats',len(categories),'direct',len(direct),flush=True)
    list_info=fetch_list_wikitext();list_titles=list_info['listed_titles'];direct_titles=[x['listed_title'] for x in direct]
    pages,fail2=fetch_pages(direct_titles+list_titles);failures.extend(fail2)
    by_pid=defaultdict(lambda:{'root_memberships':set(),'category_memberships':set(),'list_sources':[],'listed_titles':set()});canonical={}
    for x in direct:
        p=pages.get(x['listed_title'])
        if p:
            canonical[p['pageid']]=p;d=by_pid[p['pageid']];d['root_memberships'].add(x['root']);d['category_memberships'].add(x['category']);d['listed_titles'].add(x['listed_title'])
    for title in list_titles:
        p=pages.get(title)
        if p:
            canonical[p['pageid']]=p;d=by_pid[p['pageid']];d['list_sources'].append({'source_title':list_info['title'],'source_pageid':list_info['pageid'],'source_url':list_info['fullurl']});d['listed_titles'].add(title)
    records=[]
    for pid,prov in by_pid.items():
        p=canonical[pid];records.append({**p,'root_memberships':sorted(prov['root_memberships']),'category_memberships':sorted(prov['category_memberships']),'list_sources':prov['list_sources'],'listed_titles':sorted(prov['listed_titles'])})
    payload={'crawl_timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'roots':ROOTS,'list_page':list_info,'category_root_visits':len(seen_by_root),'distinct_categories_traversed':len(categories),'category_edges':len(edges),'direct_memberships_total':len(direct),'distinct_direct_titles':len(set(direct_titles)),'list_link_memberships_total':len(list_titles),'distinct_list_titles':len(set(list_titles)),'distinct_listed_titles_union':len(set(direct_titles+list_titles)),'distinct_canonical_pageids':len(records),'failures':failures,'records':sorted(records,key=lambda r:(r['title'].casefold(),r['pageid']))}
    with open(OUT,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False)
    print(json.dumps({k:payload[k] for k in ['category_root_visits','distinct_categories_traversed','category_edges','direct_memberships_total','distinct_direct_titles','list_link_memberships_total','distinct_list_titles','distinct_listed_titles_union','distinct_canonical_pageids','failures']},ensure_ascii=False))
if __name__=='__main__':main()
