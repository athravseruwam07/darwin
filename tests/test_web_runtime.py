"""The REST surface drives the actual model, controller, tracker, and run log."""
import math
import time
from pathlib import Path
from fastapi.testclient import TestClient
from darwin.config import Config
from darwin.runtime import Runtime
from darwin.recording.replay import ReplayRuntime, load_transitions
from darwin.web.server import create_app

def test_full_camera_runtime_rest_workflow(tmp_path):
    runtime=Runtime(Config(observation='vision'),realtime=False,run_root=tmp_path)
    client=TestClient(create_app(runtime))
    owner={'owner_id':'test-browser'}
    def operation(name):
        response=client.post('/api/'+name,json=owner)
        assert response.status_code==200,response.text
        deadline=time.monotonic()+20
        while runtime.busy and time.monotonic()<deadline:
            client.post('/api/heartbeat',json=owner);time.sleep(.005)
        state=client.get('/api/status').json()
        assert not state['busy']
        assert state['error'] is None,state['error']
        return state
    try:
        assert client.get('/api/frame').headers['content-type']=='image/jpeg'
        assert client.get('/api/status').json()['pose']['valid']
        learned=operation('start-calibration');assert learned['valid_sample_count']==24
        assert learned['model_id']
        assert client.post('/api/target',json={'x_m':.64,'y_m':.64}).status_code==200
        navigated=operation('navigate');assert navigated['state']=='GOAL'
        assert client.post('/api/recenter',json={}).status_code==200
        assert client.post('/api/scramble',json={}).status_code==200
        assert client.get('/api/status').json()['model_id'] is None
        recovered=operation('recover');assert recovered['validation_metrics']['adapted']['normalized_rmse']<recovered['validation_metrics']['frozen']['normalized_rmse']
        assert recovered['adaptation_complete'] is True
        assert operation('navigate')['state']=='GOAL'
        assert client.post('/api/stop',json={}).status_code==200
        assert client.post('/api/reset-model',json={}).status_code==200
        assert client.get('/api/status').json()['model_id'] is None
    finally: runtime.close()
    rows=load_transitions(runtime.writer.path)
    required_learning_rows=sum((runtime.config.initial_trials,runtime.config.validation_trials,
                                runtime.config.recovery_trials,runtime.config.recovery_validation_trials))
    assert len(rows)>=required_learning_rows
    replay=ReplayRuntime(runtime.writer.path);replay_client=TestClient(create_app(replay))
    duration=replay.snapshot()['replay']['duration_s']
    assert replay_client.post('/api/replay/seek',json={'seconds':duration}).status_code==200
    status=replay_client.get('/api/status').json()
    assert status['mode']=='replay' and status['pose']['valid']
    assert not status['transport_health']['connected']
    assert replay_client.post('/api/navigate',json=owner).status_code==422

def test_runtime_http_validation_and_export_path_injection(tmp_path,monkeypatch):
    runtime=Runtime(Config(observation='pose'),realtime=False,run_root=tmp_path)
    client=TestClient(create_app(runtime))
    exports=[]
    def export(source,output): exports.append((source,output));return Path(output)/'safe.zip'
    monkeypatch.setattr('darwin.recording.export.export_run',export)
    try:
        for body in ['{"x_m":NaN,"y_m":0.5}','{"x_m":Infinity,"y_m":0.5}','{"x_m":0.99,"y_m":0.5}']:
            assert client.post('/api/target',content=body,headers={'Content-Type':'application/json'}).status_code==422
        assert runtime.target is None
        response=client.post('/api/export',json={'run':'/etc','output':'/tmp/unconfined','path':'../../escape'})
        assert response.status_code==200
        assert exports[0][0]==runtime.writer.path
        assert Path(exports[0][1]).parts[-2:]==('reports','exports')
    finally: runtime.close()


def test_drawn_route_is_validated_and_navigated_with_the_learned_model(tmp_path):
    runtime=Runtime(Config(observation='pose'),realtime=False,run_root=tmp_path)
    client=TestClient(create_app(runtime))
    owner={'owner_id':'route-browser'}
    try:
        assert client.post('/api/start-calibration',json=owner).status_code==200
        runtime.wait(owner=owner['owner_id'])
        client.post('/api/recenter',json={'x_m':.5,'y_m':.5,'theta_rad':0}).raise_for_status()

        points=[{'x_m':.57,'y_m':.53},{'x_m':.64,'y_m':.60}]
        assert client.post('/api/route',json={'points':points}).status_code==200
        assert client.get('/api/status').json()['route']==points
        assert client.post('/api/route',json={'points':[]}).status_code==422
        assert client.post('/api/route',json={'points':points[:1]}).status_code==422
        assert client.post('/api/route',content='{"points":[{"x_m":NaN,"y_m":0.5}]}',headers={'Content-Type':'application/json'}).status_code==422

        assert client.post('/api/navigate-route',json=owner).status_code==200
        runtime.wait(owner=owner['owner_id'])
        status=client.get('/api/status').json()
        assert status['state']=='GOAL'
        assert status['route_index']==1
        assert math.hypot(status['pose']['x_m']-.64,status['pose']['y_m']-.60)<=runtime.config.goal_contact_radius_m
    finally:
        runtime.close()
