from fastapi.testclient import TestClient
from darwin.web.server import create_app

class Runtime:
    def __init__(self): self.commands=[]
    def snapshot(self): return {'mode':'simulation','state':'DISARMED','busy':False}
    def public_config(self): return {'mode':'simulation','arena_width_m':1}
    def list_runs(self): return [{'run_id':'sample'}]
    def latest_jpeg(self): return b'jpeg'
    def command(self,name,payload):
        self.commands.append((name,payload))
        if payload.get('invalid'): raise ValueError('invalid payload')
        return {'ok':True}

def test_all_controls_reach_same_runtime():
    runtime=Runtime();client=TestClient(create_app(runtime))
    for command in ['connect','calibration','target','start-calibration','navigate','stop','scramble','recover','reset-model','export','heartbeat','fault','reset-pose']:
        assert client.post('/api/'+command,json={'owner_id':'tab-1'}).status_code==200
        assert runtime.commands[-1]==(command,{'owner_id':'tab-1'})
    assert client.get('/api/status').json()['mode']=='simulation'
    assert client.get('/api/config').json()['arena_width_m']==1
    assert client.get('/api/runs').json()==[{'run_id':'sample'}]
    assert client.get('/api/frame').content==b'jpeg'
    assert 'DARWIN' in client.get('/').text
    assert 'owner_id' in client.get('/static/app.js').text

def test_bad_commands_and_origin_refused():
    client=TestClient(create_app(Runtime()))
    assert client.post('/api/motor',json={}).status_code==404
    assert client.post('/api/target',json=[]).status_code==422
    assert client.post('/api/target',json={'invalid':True}).status_code==422
    assert client.post('/api/target',content='not json').status_code==422
    assert client.post('/api/target',json={'x':'x'*40000}).status_code==413
    assert client.post('/api/navigate',headers={'Origin':'https://untrusted.example'},json={}).status_code==403
    assert client.post('/api/stop',headers={'Origin':'http://testserver'},json={}).status_code==200

def test_websocket_status_no_control_lease():
    runtime=Runtime();client=TestClient(create_app(runtime))
    with client.websocket_connect('/api/events') as socket: assert socket.receive_json()['state']=='DISARMED'
    assert runtime.commands==[]
