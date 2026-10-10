import json,hashlib,re,argparse
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--manifest',default=str(Path(__file__).with_name('block17_candidate.json')));args=parser.parse_args()
m=json.loads(Path(args.manifest).read_text());verified=[];status=[];hashes=True
for c in m['candidates']:
 d=Path(c['directory'])
 for f,h in c['sha256'].items():hashes=hashes and hashlib.sha256((d/f).read_bytes()).hexdigest()==h
 verified.append(json.loads((d/'verification.json').read_text()));status.append((d/'status.txt').read_text())
stages={
 'pure_hex_zero_free':hashes and all('unstructured_blocks=0' in s and re.search(r'hexes=[1-9][0-9]* tets=0 prisms=0 pyramids=0',s) for s in status),
 'local_mesh_check':hashes and all(v.get('mesh_check_ok',False) for v in verified),
 'local_quality':hashes and all(v['cell_quality']['min']>=.15 and v['relative_volume_error']<.01 for v in verified),
 'local_connectivity':hashes and all(v['connectivity']['single_connected_volume'] for v in verified),
 'cad_fit_and_coverage':False,'conformal_interfaces':False,'whole_block17_mesh':False,'naming':False}
# Later stages require explicit audit artifacts; never infer them from local cell counts.
for key,field in [('cad_fit_and_coverage','cad_projection'),('conformal_interfaces','conformal_interfaces'),('whole_block17_mesh','whole_block17'),('naming','naming')]:
 evidence=m.get(field)
 if evidence:
  q=Path(evidence['path']);valid=hashlib.sha256(q.read_bytes()).hexdigest()==evidence['sha256'];r=json.loads(q.read_text());stages[key]=valid and r.get('verified',False)
print(json.dumps({'details':stages}))
print(json.dumps(dict({'passed_verification_stages':sum(stages.values()),'evidence_hashes_valid':int(hashes),'whole_block17_complete':int(all(stages.values()))},**{k:int(v) for k,v in stages.items()})))
