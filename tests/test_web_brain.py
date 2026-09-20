"""The monologue panel is served from the same local runtime and stays read-only."""
import json
from fastapi.testclient import TestClient
from darwin.cognition.brain import Brain
from darwin.config import Config
from darwin.web.server import create_app

SNAPSHOT={'mode':'simulation','state':'READY','busy':False,'model_id':'abc123','model_ready':True,
          'recovery_phase':'model validated','pose':{'x_m':.5,'y_m':.5,'theta_rad':0,'valid':True},
          'change_detection':{'score':.01,'threshold':.25,'detected':False,'evidence_count':0,'consecutive_count':0},
          'valid_sample_count':24}

class Runtime:
    config=Config()
    def __init__(self): self.commands=[]; self.snap=dict(SNAPSHOT)
    def snapshot(self): return dict(self.snap)
    def public_config(self): return self.config.public()
    def list_runs(self): return []
    def latest_jpeg(self): return b'jpeg'
    def command(self,name,payload): self.commands.append((name,payload)); return {'ok':True}

def test_brain_endpoint_narrates_polled_runtime_state():
    runtime=Runtime(); brain=Brain(enabled=True,min_interval_s=0)
    client=TestClient(create_app(runtime,brain=brain))
    assert client.get('/api/status').status_code==200
    runtime.snap={**SNAPSHOT,'state':'NAVIGATING','busy':True}
    client.get('/api/status')
    body=client.get('/api/brain').json()
    json.dumps(body,allow_nan=False)
    assert body['enabled'] is True
    assert [t['kind'] for t in body['thoughts']]==['boot','navigating']
    assert all(t['channel']=='darwin' for t in body['thoughts'])
    brain.close()

def test_operator_commands_are_logged_on_their_own_channel():
    runtime=Runtime(); brain=Brain(enabled=True,min_interval_s=0)
    client=TestClient(create_app(runtime,brain=brain))
    client.get('/api/status')
    assert client.post('/api/inject-mutation',json={'mapping':'reverse_both','owner_id':'tab'}).status_code==200
    thoughts=client.get('/api/brain').json()['thoughts']
    operator=[t for t in thoughts if t['channel']=='operator']
    assert len(operator)==1 and operator[0]['kind']=='operator_mutation'
    assert 'reversed both wheels' in operator[0]['text']
    assert not any('detected' in t['text'].lower() for t in thoughts)
    assert client.post('/api/heartbeat',json={'owner_id':'tab'}).status_code==200
    assert len([t for t in client.get('/api/brain').json()['thoughts'] if t['channel']=='operator'])==1
    brain.close()

def test_rejected_operator_commands_are_not_narrated():
    class Rejecting(Runtime):
        def command(self,name,payload): raise ValueError('mutation requires active navigation')
    brain=Brain(enabled=True,min_interval_s=0)
    client=TestClient(create_app(Rejecting(),brain=brain))
    client.get('/api/status')
    assert client.post('/api/inject-mutation',json={'mapping':'swap','owner_id':'tab'}).status_code==422
    assert not [t for t in client.get('/api/brain').json()['thoughts'] if t['channel']=='operator']
    brain.close()

def test_voice_audio_is_served_and_toggled_locally():
    class Voice:
        name='eleven_turbo_v2_5'
        def speak(self,text): return b'ID3'+text.encode()[:4]
    brain=Brain(enabled=True,min_interval_s=0,voice=Voice())
    client=TestClient(create_app(Runtime(),brain=brain))
    client.get('/api/status'); brain.drain()
    thought=client.get('/api/brain').json()['thoughts'][0]
    assert thought['voice']=='ready'
    audio=client.get('/api/brain/voice/'+thought['thought_id'])
    assert audio.status_code==200 and audio.headers['content-type']=='audio/mpeg' and audio.content.startswith(b'ID3')
    assert client.get('/api/brain/voice/missing').status_code==204
    assert client.post('/api/brain/voice',json={'enabled':False}).json()=={'ok':True,'voice_enabled':False}
    assert client.get('/api/brain').json()['voice_enabled'] is False
    brain.close()

def test_missing_keys_leave_a_working_local_monologue():
    runtime=Runtime()
    client=TestClient(create_app(runtime))
    client.get('/api/status')
    body=client.get('/api/brain').json()
    assert body['enabled'] is True and body['provider']['model'] is None
    assert body['thoughts'] and body['thoughts'][0]['source']=='local'
    assert client.get('/api/brain/voice/anything').status_code==204

def test_brain_panel_is_shipped_with_the_dashboard():
    client=TestClient(create_app(Runtime()))
    html=client.get('/').text
    script=client.get('/static/brain.js').text
    for contract in ['brain-rail','brain-stream','brain-mute','/static/brain.js']:
        assert contract in html or contract in script
    assert '/api/brain' in script
    assert 'prefers-reduced-motion' in client.get('/static/style.css').text
