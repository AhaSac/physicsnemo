"""Public literature collector. Writes only below this directory; no CFD datasets."""
from pathlib import Path
import csv, hashlib, html, json, re, subprocess, sys, time
from html.parser import HTMLParser
from urllib.parse import urljoin, quote
import requests

ROOT = Path(__file__).resolve().parent
for d in ('papers', 'sources', 'metadata', 'texts'):
    (ROOT/d).mkdir(exist_ok=True)
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'PublicResearchBibliography/1.0'
LOG = []
LAST_ARXIV = 0

def fetch(url, name=None):
    global LAST_ARXIV
    if 'arxiv.org' in url:
        time.sleep(max(0, 3.1-(time.monotonic()-LAST_ARXIV)))
        LAST_ARXIV = time.monotonic()
    try:
        r = SESSION.get(url, timeout=(12, 45))
        LOG.append({'url':url, 'status':r.status_code, 'final_url':r.url})
        if name:
            (ROOT/'sources'/name).write_bytes(r.content)
        r.raise_for_status()
        return r
    except Exception as e:
        LOG.append({'url':url, 'error':str(e)})
        return None

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.pdfs=[]; self.text=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='a' and a.get('href'): self.links.append(a['href'])
        if tag=='meta' and a.get('name','').lower()=='citation_pdf_url': self.pdfs.append(a.get('content',''))
    def handle_data(self,s): self.text.append(s)

def parse(s):
    p=Links(); p.feed(s); return p

def save_state(rows):
    (ROOT/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'metadata'/'http_log.json').write_text(json.dumps(LOG,ensure_ascii=False,indent=2),encoding='utf-8')
    keys=['id','group','year','title','authors','domain','url','status','file','pdf_url','sha256','pages','note']
    with (ROOT/'manifest.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def supplements():
    urls={
        'SHIFT_Pump_card.html':'https://huggingface.co/datasets/luminary-shift/Pump',
        'SHIFT_Battery_card.html':'https://huggingface.co/datasets/luminary-shift/Battery',
        'SHIFT_Truck_card.html':'https://huggingface.co/datasets/luminary-shift/Truck',
        'SHIFT_Truck_abstract.html':'https://drivn.secure-platform.com/a/solicitations/284/sessiongallery/24310/application/197479',
    }
    for name,url in urls.items():
        r=fetch(url,name)
        if r is not None:
            p=parse(r.text)
            (ROOT/'sources'/(name+'.txt')).write_text('\n'.join(p.text),encoding='utf-8')
        print(name,'ok' if r is not None else 'failed',flush=True)
    folder=ROOT/'technical_documents'; folder.mkdir(exist_ok=True)
    url='https://vv.luminary.ai/hubfs/Luminary+Cloud_HLPW5+V%26V+Case.pdf?hsLang=en'
    r=fetch(url)
    if r is not None and r.content.startswith(b'%PDF-'):
        p=folder/'Luminary_HLPW5_Validation_Case.pdf'; p.write_bytes(r.content)
        subprocess.run(['pdftotext','-layout',str(p),str(folder/(p.stem+'.txt'))],capture_output=True)
    (ROOT/'metadata'/'http_log_supplements.json').write_text(json.dumps(LOG,ensure_ascii=False,indent=2),encoding='utf-8')

def initial():
    md=(ROOT.parents[1]/'docs'/'research.md').read_text(encoding='utf-8')
    (ROOT/'sources'/'physicsnemo_official_research_local.md').write_text(md,encoding='utf-8')
    rows=[]; year=''
    for line in md.splitlines():
        if re.match(r'## 20\d\d$',line): year=line[-4:]
        m=re.match(r'\| \[(.*?)\]\((.*?)\) \| (.*?) \| (.*?) \|',line)
        if m:
            title,url,authors,domain=m.groups()
            rows.append(dict(id=f'PN{len(rows)+1:03}',group='PhysicsNeMo_official_catalog',year=year,title=title,url=url,authors=authors,domain=domain,status='pending'))
    extra=ROOT/'additional_papers.json'
    if extra.exists():
        for row in json.loads(extra.read_text(encoding='utf-8')):
            if row['url'] not in {x['url'] for x in rows}: rows.append(row|{'status':'pending'})
    save_state(rows)
    return rows

def snapshots():
    urls={
      'luminary_resources.html':'https://luminary.ai/resources/',
      'physicsnemo_research_live.html':'https://docs.nvidia.com/physicsnemo/latest/physicsnemo/research.html',
      'SHIFT_SUV_README.md':'https://huggingface.co/datasets/luminary-shift/SUV/raw/main/README.md',
      'SHIFT_Wing_README.md':'https://huggingface.co/datasets/luminary-shift/Wing/raw/main/README.md',
      'luminary_hlpw5.html':'https://vv.luminary.ai/aerospace-and-defense-hlpw5',
      'luminary_hf_datasets.json':'https://huggingface.co/api/datasets?author=luminary-shift',
    }
    extra=ROOT/'additional_sources.json'
    if extra.exists(): urls.update(json.loads(extra.read_text(encoding='utf-8')))
    for name,url in urls.items():
        r=fetch(url,name)
        print('SOURCE',name,r.status_code if r is not None else 'failed',flush=True)
        if r is not None and name.endswith('.html'):
            p=parse(r.text)
            (ROOT/'sources'/(name+'.txt')).write_text('\n'.join(p.text),encoding='utf-8')
            (ROOT/'sources'/(name+'.links.json')).write_text(json.dumps(p.links,indent=2),encoding='utf-8')
    (ROOT/'metadata'/'http_log_sources.json').write_text(json.dumps(LOG,ensure_ascii=False,indent=2),encoding='utf-8')

def store_pdf(row,r,url):
    if r is None or not r.content.startswith(b'%PDF-'): return False
    slug=re.sub('[^A-Za-z0-9]+','_',row['title']).strip('_')[:105]
    name=f"{row['id']}_{row['year']}_{slug}.pdf"
    p=ROOT/'papers'/name; p.write_bytes(r.content)
    txt=ROOT/'texts'/(p.stem+'.txt')
    check=subprocess.run(['pdftotext','-layout',str(p),str(txt)],capture_output=True)
    row.update(status='downloaded' if check.returncode==0 else 'pdf_parse_failed',file='papers/'+name,pdf_url=url,sha256=hashlib.sha256(r.content).hexdigest(),bytes=len(r.content))
    if txt.exists():
        row['pages']=txt.read_text(encoding='utf-8',errors='replace').count('\f')
    return check.returncode==0

def download(row):
    url=row['url']; candidates=row.get('pdf_candidates',[])[:]
    ax=re.search(r'arxiv.org/(?:abs|pdf)/(\d{4}\.\d+)',url)
    if ax:
        ident=ax[1]
        r=fetch('https://arxiv.org/abs/'+ident,row['id']+'_arxiv.html')
        if r is not None:
            metas=dict(re.findall(r'<meta\s+name="([^"]+)"\s+content="([^"]*)"',r.text))
            row['arxiv_metadata']=metas
        candidates+=['https://arxiv.org/pdf/'+ident]
    else:
        doi=url.split('doi.org/')[-1] if 'doi.org/' in url else None
        if doi and not doi.startswith('10.5281'):
            r=fetch('https://api.crossref.org/works/'+quote(doi,safe=''),row['id']+'_crossref.json')
            if r is not None:
                msg=r.json().get('message',{})
                row['doi']=msg.get('DOI',doi)
                for a in msg.get('link',[]):
                    if 'pdf' in a.get('content-type','') or '.pdf' in a.get('URL',''): candidates.append(a['URL'])
        if doi and doi.startswith('10.5281/zenodo.'):
            r=fetch('https://zenodo.org/api/records/'+doi.split('.')[-1],row['id']+'_zenodo.json')
            if r is not None:
                for f in r.json().get('files',[]):
                    if f['key'].lower().endswith('.pdf'): candidates.append(f['links']['self'])
        r=fetch(url,row['id']+'_landing.html')
        if r is not None:
            if store_pdf(row,r,url): return
            p=parse(r.text)
            candidates += [urljoin(r.url,u) for u in p.pdfs]
            candidates += [urljoin(r.url,u) for u in p.links if '.pdf' in u.lower() or '/doi/pdf/' in u or '/content/pdf/' in u]
        if doi and doi.startswith('10.1007/'):
            candidates.append('https://link.springer.com/content/pdf/'+doi+'.pdf')
        if doi and doi.startswith('10.2514/'):
            candidates.append('https://arc.aiaa.org/doi/pdf/'+doi)
        if doi and doi.startswith('10.1029/'):
            candidates.append('https://agupubs.onlinelibrary.wiley.com/doi/pdfdirect/'+doi)
    for candidate in list(dict.fromkeys(candidates))[:5]:
        if store_pdf(row,fetch(candidate),candidate): return
    row.update(status='unavailable',note='未取得可验证的公开 PDF；见 HTTP 日志和落地页。未绕过付费、登录或表单。')

if __name__=='__main__':
    mode=sys.argv[1] if len(sys.argv)>1 else 'download'
    if mode=='sources': snapshots()
    elif mode=='supplements': supplements()
    elif mode=='freepaper':
        rows=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
        row=next(r for r in rows if r['id']=='PN058')
        url='https://www.ctresources.info/ccc/free.html?id=10057'
        r=fetch(url,'PN058_free_landing.html')
        if not store_pdf(row,r,url) and r is not None:
            for link in parse(r.text).links:
                if '.pdf' in link.lower():
                    pdf=urljoin(r.url,link)
                    if store_pdf(row,fetch(pdf),pdf): break
        (ROOT/'metadata'/'freepaper_results.json').write_text(json.dumps([row],ensure_ascii=False,indent=2),encoding='utf-8')
        (ROOT/'metadata'/'freepaper_http_log.json').write_text(json.dumps(LOG,ensure_ascii=False,indent=2),encoding='utf-8')
        print(row['id'],row['status'],flush=True)
    elif mode=='late':
        from concurrent.futures import ThreadPoolExecutor, as_completed
        late_path=ROOT/'metadata'/'late_results.json'
        rows=json.loads(late_path.read_text(encoding='utf-8')) if late_path.exists() else json.loads((ROOT/'late_papers.json').read_text(encoding='utf-8'))
        for row in rows:
            if row['status']!='downloaded' and 'arxiv.org' in row['url']:
                download(row); print(row['id'],row['status'],flush=True)
                late_path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        candidates=json.loads((ROOT/'retry_candidates.json').read_text(encoding='utf-8'))
        allrows=json.loads((ROOT/'metadata'/'publisher_results.json').read_text(encoding='utf-8'))
        todo=[r for r in allrows if r['id'] in candidates and r['status']!='downloaded']
        def retry(row):
            for url in candidates[row['id']]:
                if store_pdf(row,fetch(url),url): break
            return row
        with ThreadPoolExecutor(max_workers=4) as pool:
            for row in pool.map(retry,todo):
                old=next((r for r in rows if r['id']==row['id']),None)
                if old: old.update(row)
                else: rows.append(row)
                late_path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
                print('RETRY',row['id'],row['status'],flush=True)
        for name,url in json.loads((ROOT/'late_sources.json').read_text(encoding='utf-8')).items():
            r=fetch(url,name)
            if r is not None: (ROOT/'sources'/(name+'.txt')).write_text('\n'.join(parse(r.text).text),encoding='utf-8')
        (ROOT/'metadata'/'late_http_log.json').write_text(json.dumps(LOG,ensure_ascii=False,indent=2),encoding='utf-8')
    elif mode in ('parallel','publishers'):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        rows=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
        old=ROOT/'metadata'/'http_log.json'
        if old.exists(): LOG.extend(json.loads(old.read_text(encoding='utf-8')))
        chosen=set(sys.argv[2:])
        todo=[r for r in rows if r['status']!='downloaded' and (not chosen or r['id'] in chosen) and (mode!='publishers' or 'arxiv.org' not in r['url'])]
        assert all('arxiv.org' not in r['url'] for r in todo), 'Use serial mode for arXiv rate limits'
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(download,r):r for r in todo}
            for future in as_completed(futures):
                row=futures[future]
                try: future.result()
                except Exception as e: row.update(status='error',note=str(e))
                if mode=='publishers':
                    (ROOT/'metadata'/'publisher_results.json').write_text(json.dumps(todo,ensure_ascii=False,indent=2),encoding='utf-8')
                    (ROOT/'metadata'/'publisher_http_log.json').write_text(json.dumps(LOG,ensure_ascii=False,indent=2),encoding='utf-8')
                else: save_state(rows)
                print(row['id'],row['status'],row['title'][:85],flush=True)
        if mode!='publishers': save_state(rows)
    elif mode=='init': print(len(initial()))
    elif mode=='download':
        rows=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8')) if (ROOT/'manifest.json').exists() else initial()
        log_path=ROOT/'metadata'/'http_log.json'
        if log_path.exists(): LOG.extend(json.loads(log_path.read_text(encoding='utf-8')))
        selected=set(sys.argv[2:])
        if selected=={'arxiv'}: selected={r['id'] for r in rows if 'arxiv.org' in r['url']}
        rows.sort(key=lambda r: (0 if r.get('priority') else 1 if 'arxiv.org' in r['url'] else 2, r['id']))
        for row in rows:
            if selected and row['id'] not in selected: continue
            if row['status']=='downloaded': continue
            try: download(row)
            except Exception as e: row.update(status='error',note=str(e))
            save_state(rows)
            print(row['id'],row['status'],row['title'][:85],flush=True)
        save_state(rows)
