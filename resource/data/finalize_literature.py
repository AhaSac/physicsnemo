"""Build an audited, offline-readable bibliography from collected primary sources."""
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter, defaultdict
import csv, hashlib, html, json, re

ROOT=Path(__file__).resolve().parent

class Meta(HTMLParser):
    def __init__(self): super().__init__(); self.meta=defaultdict(list)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta' and a.get('name') and a.get('content'):
            self.meta[a['name']].append(a['content'])

def clean(s): return re.sub(r'\s+',' ',html.unescape(str(s))).strip()
def escape(s): return clean(s).replace('|','\\|')
def words(s): return set(re.findall(r'[a-z0-9]{3,}',s.lower()))
def dump(name,obj): (ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def write_csv(name,rows,keys):
    with (ROOT/name).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def main():
    rows=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    for filename in ['publisher_results.json','late_results.json','freepaper_results.json']:
        p=ROOT/'metadata'/filename
        if p.exists():
            for new in json.loads(p.read_text(encoding='utf-8')):
                old=next((r for r in rows if r['id']==new['id']),None)
                if old is None: rows.append(new)
                elif old['status']!='downloaded': old.update(new)
    logs=[]
    for p in (ROOT/'metadata').glob('*http_log*.json'):
        logs.extend(json.loads(p.read_text(encoding='utf-8')))
    for p in (ROOT/'metadata').glob('http_log*.json'):
        logs.extend(json.loads(p.read_text(encoding='utf-8')))
    checks=[]
    for r in rows:
        r['catalog_title']=r.get('catalog_title',r['title'])
        r['catalog_year']=r.get('catalog_year',r['year'])
        r['accessed']='2026-09-28'
        r['publication_type']='publication; consult source'
        meta={}
        for suffix in ['_arxiv.html','_landing.html']:
            p=ROOT/'sources'/(r['id']+suffix)
            if p.exists():
                parser=Meta(); parser.feed(p.read_text(encoding='utf-8',errors='replace'))
                if parser.meta.get('citation_title'): meta=parser.meta; break
        if meta:
            r['title']=clean(meta['citation_title'][0])
            if meta.get('citation_author'): r['authors']='; '.join(meta['citation_author'])
            for key in ['citation_date','citation_online_date','citation_publication_date']:
                if meta.get(key): r['source_date']=meta[key][0]; break
        ax=re.search(r'arxiv.org/(?:abs|pdf)/(\d{4}\.\d+)',r['url'])
        if ax:
            r['arxiv_id']=ax[1]; r['publication_type']='arXiv preprint / author manuscript'
            if meta.get('citation_arxiv_id'): r['arxiv_version']=meta['citation_arxiv_id'][0]
        cp=ROOT/'sources'/(r['id']+'_crossref.json')
        if cp.exists():
            try:
                m=json.loads(cp.read_text(encoding='utf-8'))['message']
                r['title']=clean(m.get('title',[r['title']])[0])
                r['authors']='; '.join(' '.join([a.get('given',''),a.get('family','')]).strip() or a.get('name','') for a in m.get('author',[])) or r.get('authors','')
                r['publication_type']=m.get('type',r['publication_type'])
                r['venue']='; '.join(m.get('container-title',[]))
                r['doi']=m.get('DOI','')
            except (ValueError,KeyError): pass
        if '\ufffd' in r.get('authors','') or not r.get('authors'): r['authors']='See primary source; not parsed'
        if r['id']=='EX014': r['publication_type']='proceedings-article'; r['venue']='Proceedings of Machine Learning Research, volume 326'
        if r['id']=='PN040': r['publication_type']='thesis / institutional report'
        if r['id']=='PN061': r['publication_type']='conference abstract'
        if r['id']=='PN067': r['publication_type']='conference poster / abstract only'
        if r['id']=='PN053': r['publication_type']='proceedings-article'
        if r['id'] in ['PN002','PN008']: r['publication_type']='repository record; consult Zenodo metadata'
        if r['status']=='downloaded':
            p=ROOT/r['file']; data=p.read_bytes()
            tp=ROOT/'texts'/(p.stem+'.txt'); tx=tp.read_text(encoding='utf-8',errors='replace')
            sha=hashlib.sha256(data).hexdigest()
            ok=data.startswith(b'%PDF-') and sha==r['sha256'] and tx.count('\f')>0 and len(tx.strip())>100
            tokens=words(r['title']); score=len(tokens & words('\f'.join(tx.split('\f')[:3])))/max(1,len(tokens))
            checks.append({'id':r['id'],'valid_pdf_text_hash':ok,'pages':tx.count('\f'),'title_word_coverage_first3pages':round(score,3),'file':r['file']})
            if not ok: raise RuntimeError('Invalid PDF '+r['id'])
            r['pages']=tx.count('\f'); r['note']='PDF signature, text extraction and SHA-256 verified'
            r['downloaded_version']='arXiv version; see saved metadata' if ax else 'public PDF; see pdf_url'
            if 'preprints.org' in r.get('pdf_url',''): r['downloaded_version']='preprint corresponding to journal record'; r['note']+='; downloaded author preprint, not publisher version'
        else:
            related=[x for x in logs if r['url'].lower() in x.get('url','').lower() or (r.get('doi') and r['doi'].lower() in x.get('url','').lower())]
            statuses=sorted({x['status'] for x in related if 'status' in x})
            errors=list(dict.fromkeys(x['error'] for x in related if 'error' in x))
            r['http_statuses']=statuses
            r['note']='未取得可验证的公开 PDF；落地页与元数据已尽量保留。'
            if statuses: r['note']+=' 检索 HTTP 状态：'+', '.join(map(str,statuses))+'。'
            if errors: r['note']+=' 网络或服务器错误，详见 metadata HTTP 日志。'
            if r['id']=='EX001': r['note']+=' AIAA 返回 403；Luminary 完整技术论文入口要求邮箱表单。公开 V&V 报告另存 technical_documents，不能代替该论文。'
            elif r['id']=='EX002': r['note']+=' AIAA 返回 403；本次未核验到开放全文。'
            elif r['id']=='PN006': r['note']+=' SAE 页面显示全文访问受限；公开摘要可读。'
            elif r['id']=='PN061': r['note']+=' 已取得会议摘要网页；PDF 请求重定向到 HTML。'
            elif r['id']=='PN067': r['note']+=' 官方记录类型为会议海报；本次页面未找到可下载附件。'
            if r['status']=='pending': raise RuntimeError('Unattempted item '+r['id'])
    rows.sort(key=lambda x:x['id'])
    dump('manifest.json',rows)
    keys=['id','group','year','title','authors','publication_type','downloaded_version','venue','domain','url','status','file','pdf_url','doi','arxiv_id','arxiv_version','source_date','sha256','pages','bytes','note']
    write_csv('manifest.csv',rows,keys)
    dump('metadata/pdf_integrity.json',checks)
    low=[r for r in checks if r['title_word_coverage_first3pages']<0.5]
    dump('metadata/title_review_flags.json',low)
    ok=[r for r in rows if r['status']=='downloaded']; missing=[r for r in rows if r['status']!='downloaded']
    mb=sum(r.get('bytes',0) for r in ok)/1024**2
    pn=[r for r in rows if r['id'].startswith('PN')]
    group_names={
        'Luminary':'Luminary 求解器与优化', 'Luminary_affiliated_processing':'Luminary 作者参与的流场数据处理',
        'Emmi_AI':'Emmi AI', 'Emmi_AI_AWS_ETH':'Emmi AI / AWS / ETH 合作',
        'Emmi_AI_research_lineage':'Emmi AI 研究谱系',
        'Neural_Concept':'Neural Concept', 'Neural_Concept_research_lineage':'Neural Concept 研究谱系',
        'BeyondMath':'BeyondMath 合作基准', 'AWS_CAE_ML':'AWS / CAE-ML 工业数据集',
        'Academic_dataset':'学术 CFD 数据集', 'NVIDIA_core':'NVIDIA 核心方法',
        'Academic_core':'学术核心方法', 'PhysicsNeMo_recipe':'PhysicsNeMo 示例关联方法',
        'Siemens':'Siemens', 'Academic_NVIDIA_lineage':'神经算子方法谱系',
        'Google_DeepMind':'Google DeepMind', 'NVIDIA_framework_history':'NVIDIA SimNet / Modulus 历史',
        'PhysicsNeMo_official_catalog':'PhysicsNeMo 官方研究目录（包括社区研究）'}
    lines=['# 论文与研究记录索引','',f'截止 2026-09-28：{len(rows)} 条去重记录，{len(ok)} 份 PDF 下载并通过校验，{len(missing)} 条未取得全文。PDF 中可能包含会议摘要、学位论文或报告；类型逐条列出。','',
           '分组表示检索入口／研究关联，不代表每篇论文均由对应企业独立完成。PN 条目完整保留官方目录范围，因此包含非 CFD 的气象、固体、能源等应用。EX 为本次补充。标题优先采用下载当日的 arXiv／出版社元数据；目录原题与原年份保存在 JSON 的 catalog_title / catalog_year。','',
           '## 优先阅读','']
    priority=['EX015','EX004','EX005','PN042','PN046','EX014','EX020','EX035','EX003','EX021','EX022','EX018']
    for ident in priority:
        r=next(x for x in rows if x['id']==ident)
        lines.append(f"- {ident} [{escape(r['title'])}]({r.get('file',r['url'])}) · [来源]({r['url']})")
    for g in dict.fromkeys(r['group'] for r in rows):
        lines+=['',f'## {group_names.get(g,g)}','','| ID | 年份 | 标题／来源 | 文献类型 | 全文 |','|---|---|---|---|---|']
        for r in rows:
            if r['group']!=g: continue
            link=f"[PDF · {r['pages']} 页]({r['file']})" if r['status']=='downloaded' else '未取得；见缺失清单'
            if 'preprints.org' in r.get('pdf_url',''): link+='（预印本）'
            lines.append(f"| {r['id']} | {r['year']} | [{escape(r['title'])}]({r['url']}) | {r['publication_type']} | {link} |")
    (ROOT/'论文索引.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    missing_lines=['# 未取得全文的记录','',f'共 {len(missing)} 条。HTTP 403、超时或抓取失败不自动等于付费墙；以下只说明本次获取结果。未把 HTML 错误页改名成 PDF。','', '| ID | 论文／来源 | 原因 |','|---|---|---|']
    for r in missing: missing_lines.append(f"| {r['id']} | [{escape(r['title'])}]({r['url']}) | {escape(r['note'])} |")
    (ROOT/'缺失全文清单.md').write_text('\n'.join(missing_lines)+'\n',encoding='utf-8')
    bib=[]
    def bibsafe(s): return str(s).replace('&',r'\&').replace('%',r'\%').replace('_',r'\_').replace('#',r'\#')
    for r in rows:
        vals={'title':'{'+bibsafe(r['title'])+'}','year':r['year'],'url':r['url'],'note':'Accessed 2026-09-28; '+r['publication_type']}
        if not r['authors'].startswith('See primary'): vals['author']=' and '.join(bibsafe(a.strip()) for a in r['authors'].split(';'))
        if r.get('doi'): vals['doi']=r['doi']
        if r.get('arxiv_id'): vals.update(eprint=r['arxiv_id'],archivePrefix='arXiv')
        if r.get('file'): vals['file']=r['file']
        bib.append('@misc{'+r['id']+',\n'+',\n'.join('  '+k+' = {'+v+'}' for k,v in vals.items())+'\n}')
    (ROOT/'references.bib').write_text('\n\n'.join(bib)+'\n',encoding='utf-8')
    sources={}
    for filename in ['additional_sources.json','late_sources.json']:
        p=ROOT/filename
        if p.exists(): sources.update(json.loads(p.read_text(encoding='utf-8')))
    sources.update({'luminary_resources.html':'https://luminary.ai/resources/','physicsnemo_research_live.html':'https://docs.nvidia.com/physicsnemo/latest/physicsnemo/research.html','luminary_hlpw5.html':'https://vv.luminary.ai/aerospace-and-defense-hlpw5','luminary_hf_datasets.json':'https://huggingface.co/api/datasets?author=luminary-shift','SHIFT_Pump_card.html':'https://huggingface.co/datasets/luminary-shift/Pump','SHIFT_Battery_card.html':'https://huggingface.co/datasets/luminary-shift/Battery','SHIFT_Truck_card.html':'https://huggingface.co/datasets/luminary-shift/Truck','SHIFT_Truck_abstract.html':'https://drivn.secure-platform.com/a/solicitations/284/sessiongallery/24310/application/197479'})
    sl=['# 官方技术资料与数据卡','','这些条目独立于论文计数。网页快照保留下载时内容；可优先打开相邻 .txt 文本。部分数据集原始文件需要申请访问，本次只收录公开数据说明。','','| 名称 | 在线来源 | 本地快照 |','|---|---|---|']
    for name,url in sorted(sources.items()):
        p=ROOT/'sources'/name
        if p.exists(): sl.append(f'| {name} | [来源]({url}) | [快照](sources/{name})'+(f' · [文本](sources/{name}.txt)' if Path(str(p)+'.txt').exists() else '')+' |')
    for p in sorted((ROOT/'technical_documents').glob('*.pdf')): sl.append(f'| {p.stem} | 见补充下载日志 | [PDF](technical_documents/{p.name}) |')
    (ROOT/'资料来源索引.md').write_text('\n'.join(sl)+'\n',encoding='utf-8')
    readme=f'''# AI CFD 文献与高保真数据资料包

检索截止 **2026-09-28**。已整理 **{len(rows)} 条研究记录**，下载并验证 **{len(ok)} 份 PDF**（合计约 {mb:.1f} MiB），**{len(missing)} 条未取得公开全文**。技术资料和数据卡另列，不混入论文数量。

- [中文综述：企业、数据生成、预处理与质量控制](AI_CFD_高保真数据生成与处理综述.md)
- [论文索引与优先阅读顺序](论文索引.md)
- [CFD 数据流程对照表](CFD数据流程对照.csv)
- [官方技术资料与数据卡](资料来源索引.md)
- [未取得全文的记录和原因](缺失全文清单.md)
- [Excel 可打开的完整清单](manifest.csv) / [机器可读 JSON](manifest.json) / [BibTeX](references.bib)
- [检索范围与方法](检索范围与方法.md)

## 范围

PhysicsNeMo 在线官方研究目录与本地 `docs/research.md` 对照，共 **{len(pn)} 条**，全部纳入；其中 {sum(r['status']=='downloaded' for r in pn)} 条取得 PDF。另补充 Luminary 可核验研究、SimNet / Modulus 方法谱系、NVIDIA 核心模型、其他企业代表论文及必要 CFD 数据集。官方目录包括社区应用和非 CFD 研究，不能等同于 NVIDIA 自著论文全集。Luminary 的 AIAA 论文、合作研究、作者参与的流场处理工作与产品技术文档分别标明。

全球所有 AI CFD 论文没有单一完备清单。本资料包对官方目录做逐条收录，对扩展企业做有来源的代表性覆盖；不声称穷尽所有企业、所有引用论文或未公开成果。未取得全文的条目仍保留题名、入口和元数据。

## 文件组织与复核

`papers/` 为全文；`texts/` 为对应提取文本；`sources/` 为一手网页／元数据快照；`technical_documents/` 为厂商技术 PDF；`metadata/` 包含请求日志、逐篇 PDF 校验、题名匹配检查和代码来源记录。本次下载的是论文与技术资料，没有下载 CFD 原始场数据。

每份成功 PDF 均检查 `%PDF-` 文件头、文本提取、页数及 SHA-256。BibTeX 使用通用 `@misc` 以避免误填期刊信息，正式投稿引用前仍应使用出版社推荐格式。`manifest.json` 保留原目录题名、解析后题名、来源类型和访问日期。

更新时先修改候选清单，再运行 `collect_literature.py` 对指定 ID 获取公开全文；下载任务结束后运行 `finalize_literature.py` 生成索引。不要用 `init` 覆盖已有下载状态；不要同时运行多个写同一个 manifest 的下载进程。
'''
    (ROOT/'README.md').write_text(readme,encoding='utf-8')
    code_paths=['physicsnemo/datapipes/cae/readers.py','physicsnemo/datapipes/cae/domino_datapipe.py']
    code_paths+=['examples/cfd/external_aerodynamics/domino/src/'+s for s in ['compute_statistics.py','cache_data.py','shuffle_volumetric_curator_output.py','conf/config.yaml','loss.py']]
    provenance=[]
    for rel in code_paths:
        p=ROOT.parents[1]/rel
        provenance.append({'path':rel,'exists':p.exists(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None})
    dump('metadata/code_provenance.json',{'review_date':'2026-09-28','git_head':'426f7552da4b4fa675e404e8a4f437e27681b668','files':provenance})
    for name in ['SHIFT_SUV_README.md','SHIFT_Wing_README.md']:
        p=ROOT/'sources'/name
        if p.exists() and p.stat().st_size<500: p.rename(p.with_name(p.stem+'_access_error.txt'))
    matrix=ROOT/'CFD数据流程对照.csv'
    matrix.write_text(matrix.read_text(encoding='utf-8-sig'),encoding='utf-8-sig')
    # Normalize the original hand-curated metadata without changing its selection.
    for filename in ['additional_papers.json','late_papers.json']:
        p=ROOT/filename
        old=json.loads(p.read_text(encoding='utf-8'))
        for r in old:
            current=next(x for x in rows if x['id']==r['id'])
            r.update(title=current['title'],authors=current['authors'])
        p.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
    links=[]
    for p in ROOT.glob('*.md'):
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
            if not target.startswith(('http://','https://','#')):
                links.append({'document':p.name,'target':target,'exists':(ROOT/target).exists()})
    dump('metadata/local_link_validation.json',links)
    assert all(x['exists'] for x in links), 'Broken local link'
    assert len({r['id'] for r in rows})==len(rows), 'Duplicate record ID'
    assert len({r['sha256'] for r in ok})==len(ok), 'Duplicate PDF'
    assert len(list((ROOT/'papers').glob('*.pdf')))==len(ok), 'Unindexed PDF'
    print(json.dumps({'records':len(rows),'downloaded':len(ok),'missing':len(missing),'MiB':round(mb,1),'low_title_match':low},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
