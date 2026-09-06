"""Recover authorized research artifacts; read data only, never execute archive code."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import subprocess,zipfile,tempfile,json,hashlib,re,gzip,io,csv,shutil
ROOT=Path(__file__).resolve().parent;OUT=Path('recovered_artifacts');OUT.mkdir(exist_ok=True)
items=json.loads((ROOT/'artifact_requests.json').read_text())
def sanitize(v):
 if isinstance(v,dict):return {k:('[REDACTED]' if re.search(r'token|secret|password|credential|authorization|email',str(k),re.I) else sanitize(x)) for k,x in v.items()}
 if isinstance(v,list):return [sanitize(x) for x in v]
 if isinstance(v,str):
  if re.search(r'(?i)(?:gh[pousr]_[A-Za-z0-9]{20}|bearer\s|[?&](?:token|sig|key)=)',v):return '[REDACTED CREDENTIAL-BEARING VALUE]'
 return v
def recover(item):
 aid=item['id'];result=dict(item,files=[],status='NOT_RECOVERED');dest=OUT/str(aid);dest.mkdir(exist_ok=True)
 with tempfile.TemporaryDirectory() as tmp:
  arc=Path(tmp)/'artifact.zip'
  with arc.open('wb') as f:r=subprocess.run(['gh','api',f'/repos/thanzo12wizu-stack/v38-watchlist/actions/artifacts/{aid}/zip'],stdout=f,stderr=subprocess.PIPE)
  if r.returncode:result['error']='GitHub artifact download failed: '+r.stderr.decode(errors='replace')[:300];return result
  digest=hashlib.sha256(arc.read_bytes()).hexdigest();result['download_sha256']=digest;result['digest_matches']=not item.get('digest') or item['digest']=='sha256:'+digest
  if not zipfile.is_zipfile(arc):result['error']='not ZIP';return result
  with zipfile.ZipFile(arc) as z:
   for info in z.infolist():
    if info.is_dir():continue
    rec={'name':info.filename,'bytes':info.file_size};result['files'].append(rec)
    if info.file_size>80_000_000:rec['review']='LARGE_SOURCE_DATA_NOT_PARSED';continue
    name=Path(info.filename).name;data=z.read(info);rec['sha256']=hashlib.sha256(data).hexdigest()
    try:
     if name.endswith('.json') and info.file_size<5_000_000:
      obj=sanitize(json.loads(data));target=dest/(str(len(result['files']))+'_'+name);target.write_text(json.dumps(obj,ensure_ascii=False,indent=2));rec['saved']=target.name;rec['review']='JSON_RECOVERED'
     elif re.search(r'\.(csv|csv.gz)$',name):
      raw=gzip.decompress(data) if name.endswith('.gz') else data
      if len(raw)>100_000_000:rec['review']='LARGE_TABLE_HASHED';continue
      reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')));sample=[];count=0
      for row in reader:
       count+=1
       if count<=5:sample.append(sanitize(row))
      rec.update(rows=count,columns=reader.fieldnames,sample=sample,review='SCHEMA_ROWCOUNT_HASH_CHECKED')
      if count<=25000 and re.search(r'summary|metric|perf|bootstrap|robust|compare|comparison|ablation|period|year|ranking|variant|decision',name,re.I):
       # Tables contain research metrics; sanitize cells before durable preservation.
       rr=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))));target=dest/(str(len(result['files']))+'_'+name.removesuffix('.gz'))
       with target.open('w') as f:
        w=csv.DictWriter(f,fieldnames=reader.fieldnames);w.writeheader();w.writerows(sanitize(rr))
       rec['saved']=target.name
    except Exception as exc:rec['parse_error']=type(exc).__name__
  result['status']='RECOVERED' if result['digest_matches'] else 'RECOVERED_DIGEST_MISMATCH'
 return result
rows=[]
with ThreadPoolExecutor(max_workers=4) as pool:
 for fut in as_completed([pool.submit(recover,x) for x in items]):
  r=fut.result();rows.append(r);(OUT/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print('ARTIFACT',r['id'],r['status'],len(r['files']),flush=True)
print('RECOVERY_DONE',len(rows),sum(r['status']=='RECOVERED' for r in rows),flush=True)
