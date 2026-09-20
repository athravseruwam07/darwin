"""Leave a detached localhost simulation running. Never touches other services."""
from pathlib import Path
import json,re,subprocess,sys,time,urllib.request
root=Path(__file__).resolve().parents[1]
log=root/'reports/demo.log';log.parent.mkdir(exist_ok=True)
with log.open('w') as output:
    proc=subprocess.Popen([sys.executable,'-m','darwin.cli','demo','--mode','simulation','--config','configs/simulation.yaml','--ui-port','8770'],cwd=root,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
for _ in range(100):
    if proc.poll() is not None:raise RuntimeError(log.read_text())
    match=re.search(r'DARWIN SIMULATION (http://[^\s]+)',log.read_text())
    if match:
        url=match.group(1)
        try:
            with urllib.request.urlopen(url+'/api/status',timeout=1) as response:status=json.load(response)
            if status['mode']=='simulation':break
        except OSError:pass
    time.sleep(.05)
else:
    proc.terminate();raise RuntimeError('demo startup timed out')
report={'pid':proc.pid,'url':url,'run_id':status['run_id'],'log':str(log),'mode':'simulation'}
(root/'reports/demo.pid').write_text(str(proc.pid)+'\n');(root/'reports/demo_process.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
