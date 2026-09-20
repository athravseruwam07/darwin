"""Real subprocess HTTP smoke test; ephemeral port; always clean up own process."""
import json,socket,subprocess,sys,time,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
proc=subprocess.Popen([sys.executable,'-m','darwin.cli','demo','--config','configs/simulation.yaml','--ui-port',str(port)],cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
url=f'http://127.0.0.1:{port}'
def request(path,payload=None):
    req=urllib.request.Request(url+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=3) as response:return response.read()
try:
    deadline=time.monotonic()+10
    while True:
        try:status=json.loads(request('/api/status'));break
        except OSError:
            if time.monotonic()>deadline:raise RuntimeError('server did not start')
            time.sleep(.05)
    assert status['mode']=='simulation' and status['state']=='DISARMED'
    assert b'DARWIN' in request('/') and request('/api/frame')[:2]==b'\xff\xd8'
    request('/api/start-calibration',{'owner_id':'smoke'})
    request('/api/stop',{})
    time.sleep(.2)
    status=json.loads(request('/api/status'));assert status['state']=='DISARMED' and not status['busy']
    count=status['valid_sample_count'];time.sleep(.2)
    assert json.loads(request('/api/status'))['valid_sample_count']==count
    print(json.dumps({'passed':True,'port':port,'checks':['real server','HTML','status','JPEG','async learn','STOP','no post-stop samples']}))
finally:
    proc.terminate()
    try:proc.wait(timeout=5)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
