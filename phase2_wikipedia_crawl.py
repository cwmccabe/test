import json,time,urllib.parse,urllib.request
from collections import defaultdict
from bs4 import BeautifulSoup
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

def parse_list_rows():
    parsed=api({'action':'parse','page':LIST_PAGE,'prop':'text'})
    soup=BeautifulSoup(parsed['parse']['text'],'html.parser')
    rows=[]; table_count=0
    for ti,table in enumerate(soup.select('table.wikitable')):
        trs=table.select('tr')
        if not trs: continue
        headers=[th.get_text(' ',strip=True).lower() for th in trs[0].find_all(['th','td'])]
        title_i=next((i for i,h in enumerate(headers) if 'title' in h or h=='story'),None)
        author_i=next((i for i,h in enumerate(headers) if 'author' in h or 'writer' in h),None)
        year_i=next((i for i,h in enumerate(headers) if 'year' in h or 'date' in h),None)
        if title_i is None: continue
        table_count+=1
        for ri,tr in enumerate(trs[1:]):
            cells=tr.find_all(['td','th'])
            if title_i>=len(cells): continue
            cell=cells[title_i]
            link=next((a for a in cell.find_all('a',href=True) if a['href'].startswith('/wiki/') and 'File:' not in a['href']),None)
            if not link: continue
            raw=link['href'].split('/wiki/',1)[1]
            listed_title=urllib.parse.unquote(raw.split('#',1)[0]).replace('_',' ')
            author=cells[author_i].get_text(' ',strip=True) if author_i is not None and author_i<len(cells) else ''
            year=cells[year_i].get_text(' ',strip=True) if year_i is not None and year_i<len(cells) else ''
            rows.append({'table_index':ti,'row_index':ri,'listed_title':listed_title,'display_title':cell.get_text(' ',strip=True),'author':author,'year':year})
    return rows,table_count

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
            pages={p.get('title',''):p for p in q.get('pages',[])}
            for listed in batch:
                p=pages.get(tmap.get(listed,listed))
                if not p or p.get('missing') or 'pageid' not in p:
                    failures.append({'title':listed,'error':'missing'}); continue
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
        except Exception as e: failures.append({'batch':batch,'error':repr(e)})
        if bi%10==0:print('content batch',bi,flush=True)
        time.sleep(.05)
    return resolved,failures

def main():
    cats=category_members(); list_rows,table_count=parse_list_rows()
    cat_titles=[x['title'] for x in cats]; list_titles=[x['listed_title'] for x in list_rows]
    resolved,failures=resolve_titles(cat_titles+list_titles)
    by_pid=defaultdict(lambda:{'category_memberships':[],'list_rows':[],'listed_titles':[]}); pages={}
    for x in cats:
        p=resolved.get(x['title'])
        if p: pages[p['pageid']]=p; by_pid[p['pageid']]['category_memberships'].append(CATEGORY); by_pid[p['pageid']]['listed_titles'].append(x['title'])
    for x in list_rows:
        p=resolved.get(x['listed_title'])
        if p: pages[p['pageid']]=p; by_pid[p['pageid']]['list_rows'].append(x); by_pid[p['pageid']]['listed_titles'].append(x['listed_title'])
    records=[{**pages[pid],'category_memberships':sorted(set(prov['category_memberships'])),'list_rows':prov['list_rows'],'listed_titles':sorted(set(prov['listed_titles']))} for pid,prov in by_pid.items()]
    payload={'crawl_timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'category':CATEGORY,'list_page':LIST_PAGE,'category_memberships_total':len(cats),'list_rows_total':len(list_rows),'list_table_count':table_count,'distinct_listed_titles':len(set(cat_titles+list_titles)),'distinct_canonical_pageids':len(records),'failures':failures,'records':sorted(records,key=lambda r:(r['title'].casefold(),r['pageid']))}
    with open(OUT,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False)
    print(json.dumps({k:payload[k] for k in ['category_memberships_total','list_rows_total','list_table_count','distinct_listed_titles','distinct_canonical_pageids','failures']},ensure_ascii=False))
if __name__=='__main__':main()
