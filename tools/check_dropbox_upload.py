"""Read-only macOS File Provider upload-state observation of this package only.
No sharing, invitations, settings or credentials. No full provider dumps retained.
"""
import argparse,concurrent.futures,datetime,json,re,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
paths=[a.package]+sorted(x for x in a.package.rglob('*') if x.is_file() or x.is_dir())
def observe(path):
 try:
  proc=subprocess.run(['/usr/bin/fileproviderctl','evaluate',str(path)],capture_output=True,text=True,timeout=30)
  state={k:v for k,v in re.findall(r'^\s+(isUploaded|isUploading|isExcludedFromSync|isSyncPaused) = ([^;\n]+);',proc.stdout+proc.stderr,re.M)}
  return {'relative_path':str(path.relative_to(a.package)),'command_returncode':proc.returncode,'provider_state':state,'uploaded_observed':proc.returncode==0 and state.get('isUploaded')=='1' and state.get('isUploading')=='0' and state.get('isExcludedFromSync')=='0' and state.get('isSyncPaused')=='0'}
 except Exception as e:return {'relative_path':str(path.relative_to(a.package)),'uploaded_observed':False,'observation_error':type(e).__name__}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(observe,paths))
r={'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'method':'macOS fileproviderctl evaluate per package file and directory, plus package root; read-only','items_observed':len(records),'all_report_uploaded':all(x['uploaded_observed'] for x in records),'uploaded_observed':sum(x['uploaded_observed'] for x in records),'items':records,'limits':'Provider-reported upload state, not independent server download verification. Recipient access was not checked; no invitation or new sharing link created.'}
a.output.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({k:v for k,v in r.items() if k!='items'}))
