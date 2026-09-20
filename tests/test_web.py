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
    assert 'DARWIN' in client.get('/lab').text
    assert 'owner_id' in client.get('/static/app.js').text


def test_dashboard_separates_drive_controls_from_lab_detail():
    client=TestClient(create_app(Runtime()))
    html=client.get('/').text
    script=client.get('/static/app.js').text
    for contract in ['operator-view','command-deck','mutation-toolbar','lab-view','href="/"','href="/lab"']:
        assert contract in html
    assert "location.pathname==='/lab'" in script
    assert 'lab-page' in script


def test_observatory_is_a_no_reload_truthful_learning_interface():
    client=TestClient(create_app(Runtime()))
    html=client.get('/').text
    script=client.get('/static/app.js').text
    for contract in ['data-view="drive"','data-view="lab"','model-field','motor-graph',
                     'cognition-rail','operator-intervention','presenter-toggle','learning-timeline']:
        assert contract in html
    assert 'history.pushState' in script
    assert 'renderModelField' in script
    assert 'renderMotorGraph' in script
    assert 'hidden_mapping' not in html+script
    assert 'neural network' not in (html+script).lower()


def test_drive_to_lab_navigation_preserves_control_lease_without_stopping():
    script=TestClient(create_app(Runtime())).get('/static/app.js').text
    assert 'sessionStorage' in script
    assert 'darwin-owner-id' in script
    assert "sendBeacon('/api/stop'" not in script

def test_dashboard_contains_adaptation_and_route_story():
    client=TestClient(create_app(Runtime()))
    assets=client.get('/').text+client.get('/static/app.js').text
    for identifier in ['adaptation-story','mutation-buttons','draw-route','change-score','model-uncertainty']:
        assert identifier in assets
    for contract in ['change_detection','adaptation_complete','model_uncertainty','frozen_predicted_motion','adapted_predicted_motion',"act('route',{points:","act('navigate-route')","reverse_left","reverse_right","reverse_both","swap","random_mashup"]:
        assert contract in assets

def test_dashboard_has_live_navigation_mutation_and_runtime_narration():
    client=TestClient(create_app(Runtime()))
    assets=client.get('/').text+client.get('/static/app.js').text
    for contract in ['inject-mutation','random_mashup','swap','reverse_left','reverse_right','reverse_both','weaken_left','data-mutation','navigationActive','adaptation-narration','adaptation-timeline','aria-live="polite"']:
        assert contract in assets
    for runtime_signal in ["state.state==='NAVIGATING'",'model_mismatch','collecting fresh probes','FITTING','evaluation','navigation_result']:
        assert runtime_signal in assets
    assert 'mutation-mode' not in assets
    for gate in ['state.owner_id&&state.owner_id!==owner','state.live_mutation_enabled!==false','config.live_mutation_enabled!==false','Live mutation is disabled by this runtime configuration',"document.querySelectorAll('[data-mutation]')"]:
        assert gate in assets


def test_drive_dashboard_surfaces_blind_body_change_signal():
    client=TestClient(create_app(Runtime()))
    html=client.get('/').text
    script=client.get('/static/app.js').text
    assets=html+script
    for identifier in ['brain-signal','change-alert','change-detail','aria-live="polite"']:
        assert identifier in assets
    for contract in ['body_change_signal','Change detected','Watching predictions','New body learned','camera residual']:
        assert contract in script

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
