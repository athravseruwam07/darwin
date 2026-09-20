"""Narration is derived from public runtime facts; it never sees privileged state."""
import json
import math
import pytest
from darwin.cognition.facts import cognition_facts
from darwin.cognition.triggers import detect_triggers, operator_trigger
from darwin.cognition.providers import OpenAIThoughtWriter, ElevenLabsVoice, supported_numbers, load_env_file, clean
from darwin.cognition.brain import Brain

BASE={'mode':'simulation','state':'READY','busy':False,'recovery_phase':'model validated','stop_reason':None,
      'model_id':'abc123','model_ready':True,'valid_sample_count':24,'rejected_sample_count':1,'heldout_sample_count':12,
      'pose':{'x_m':.5,'y_m':.5,'theta_rad':.1,'valid':True,'quality':.9},'target':[.72,.28],
      'change_detection':{'score':.02,'threshold':.25,'evidence_count':0,'consecutive_count':0,'detected':False},
      'model_uncertainty':.03,'latest_residual':{'v_mps':.0001,'omega_radps':-.002},
      'validation_metrics':{'current':{'normalized_rmse':.0065,'v_rmse_mps':.0004,'omega_rmse_radps':.004}},
      'frame_age_ms':32,'ack_age_ms':4,'transport_health':'healthy','boundary_recovery_active':False,
      'adaptation_complete':False,'body_change_signal':None,'model_memory':{'count':1},'events':[]}


def test_facts_expose_only_public_learned_state():
    facts=cognition_facts({**BASE,'hidden_map':'reverse_both','plant':{'gain':3},'actuator_mutation':'swap'},{'goal_contact_radius_m':.08})
    blob=json.dumps(facts).lower()
    for secret in ('hidden_map','reverse_both','actuator_mutation','plant','swap'):
        assert secret not in blob
    assert facts['model_id']=='abc123'
    assert facts['change']['threshold']==.25
    assert math.isclose(facts['distance_to_target_m'],math.hypot(.22,.22))


def test_facts_reject_nonfinite_telemetry():
    facts=cognition_facts({**BASE,'frame_age_ms':float('nan'),'model_uncertainty':float('inf'),
                           'pose':{'x_m':float('nan'),'y_m':.5,'theta_rad':0,'valid':True}},None)
    assert facts['frame_age_ms'] is None and facts['uncertainty'] is None and facts['pose'] is None
    json.dumps(facts,allow_nan=False)


def test_triggers_follow_sensed_transitions_not_operator_buttons():
    boot=detect_triggers(None,cognition_facts(BASE,None))
    assert [t.kind for t in boot]==['boot']
    before=cognition_facts(BASE,None)
    navigating=cognition_facts({**BASE,'state':'NAVIGATING','busy':True},None)
    assert [t.kind for t in detect_triggers(before,navigating)]==['navigating']
    rising=cognition_facts({**BASE,'state':'NAVIGATING','busy':True,
        'change_detection':{'score':.19,'threshold':.25,'evidence_count':2,'consecutive_count':2,'detected':False}},None)
    assert [t.kind for t in detect_triggers(navigating,rising)]==['suspicion']
    detected=cognition_facts({**BASE,'state':'NAVIGATING','busy':True,
        'change_detection':{'score':.42,'threshold':.25,'evidence_count':4,'consecutive_count':3,'detected':True},
        'body_change_signal':{'score':.42,'threshold':.25,'evidence_count':4,'privileged_mutation_signal':False},
        'recovery_phase':'body model mismatch detected; selecting informative experiments'},None)
    kinds=[t.kind for t in detect_triggers(rising,detected)]
    assert 'change_detected' in kinds
    change=[t for t in detect_triggers(rising,detected) if t.kind=='change_detected'][0]
    assert change.channel=='darwin' and change.tone=='alarm'
    assert change.fallback=='Who scrambled my controls?'


def test_operator_mutation_is_a_separate_channel_that_darwin_cannot_see():
    trigger=operator_trigger('inject-mutation',{'mapping':'reverse_both'})
    assert trigger.channel=='operator' and trigger.kind=='operator_mutation'
    assert 'reverse' in trigger.fallback.lower()
    assert 'detect' not in trigger.headline.lower()
    assert operator_trigger('heartbeat',{}) is None
    assert operator_trigger('stop',{}).channel=='operator'


def test_adaptation_triggers_report_measured_improvement():
    before=cognition_facts({**BASE,'state':'RECOVERING','busy':True,'model_ready':False,
        'recovery_phase':'collecting fresh probes'},None)
    after=cognition_facts({**BASE,'state':'READY','model_id':'def456','recovery_phase':'adapted model validated',
        'adaptation_complete':True,'validation_metrics':{'frozen':{'normalized_rmse':.568},
        'adapted':{'normalized_rmse':.0065},'current':{'normalized_rmse':.0065}}},None)
    triggers=detect_triggers(before,after)
    adapted=[t for t in triggers if t.kind=='adapted']
    assert adapted and adapted[0].fallback=='New controls, same Darwin.'


def test_supported_numbers_rejects_invented_measurements():
    facts={'change':{'score':.42,'threshold':.25},'samples':{'valid':24}}
    assert supported_numbers('Error 0.42 crossed 0.25 after 24 samples.',facts)
    assert supported_numbers('My predictions no longer match what the camera sees.',facts)
    assert not supported_numbers('Wheel 3 is drawing 7.9 amps.',facts)


def test_openai_writer_posts_facts_and_degrades_to_fallback():
    calls=[]
    def transport(url,data,headers,timeout):
        calls.append((url,json.loads(data),headers,timeout))
        return json.dumps({'choices':[{'message':{'content':'  "My controls are not what they were."  '}}]}).encode()
    writer=OpenAIThoughtWriter('sk-test',model='gpt-4o-mini',timeout=5,transport=transport)
    trigger=operator_trigger('stop',{})
    text=writer.write(trigger,{'state':'DISARMED'},[])
    assert text=='My controls are not what they were.'
    url,body,headers,timeout=calls[0]
    assert url.endswith('/chat/completions') and body['model']=='gpt-4o-mini'
    assert headers['Authorization']=='Bearer sk-test' and timeout==5
    assert 'DISARMED' in json.dumps(body['messages'])
    def failing(*args,**kwargs): raise OSError('offline')
    assert OpenAIThoughtWriter('sk-test',transport=failing).write(trigger,{},[]) is None


def test_monologue_is_always_one_sentence():
    assert clean('I noticed a change. I will test it now.')=='I noticed a change.'
    assert clean('One concise thought without punctuation')=='One concise thought without punctuation'
    assert clean('My error is 0.29.') is None
    assert len(clean('x'*300))==72


def test_brain_uses_one_global_cooldown_and_one_thought_per_snapshot():
    now=[0.0]
    brain=Brain(enabled=True,min_interval_s=6,clock=lambda:now[0])
    assert len(brain.observe(BASE))==1
    now[0]=1
    assert brain.observe({**BASE,'state':'NAVIGATING','busy':True})==[]
    now[0]=7
    produced=brain.observe({**BASE,'state':'FAULT','busy':False,'stop_reason':'tracking invalid',
                            'pose':{**BASE['pose'],'valid':False}})
    assert len(produced)==1
    brain.close()


def test_elevenlabs_voice_requests_mp3_bytes():
    seen={}
    def transport(url,data,headers,timeout):
        seen.update(url=url,body=json.loads(data),headers=headers)
        return b'ID3audio'
    voice=ElevenLabsVoice('el-key',voice_id='voice-7',model_id='eleven_turbo_v2_5',timeout=9,transport=transport)
    assert voice.speak('Hello')==b'ID3audio'
    assert 'voice-7' in seen['url'] and seen['body']['text']=='Hello'
    assert seen['headers']['xi-api-key']=='el-key'
    def failing(*args,**kwargs): raise OSError('offline')
    assert ElevenLabsVoice('el-key','voice-7',transport=failing).speak('Hello') is None


def test_brain_narrates_without_any_provider_and_stays_json_safe():
    brain=Brain(enabled=True,min_interval_s=0)
    brain.observe(BASE)
    brain.observe({**BASE,'state':'NAVIGATING','busy':True})
    snapshot=brain.snapshot()
    json.dumps(snapshot,allow_nan=False)
    assert snapshot['enabled'] is True
    assert [t['kind'] for t in snapshot['thoughts']]==['boot','navigating']
    assert all(t['source']=='local' for t in snapshot['thoughts'])
    assert snapshot['provider']['model'] is None and snapshot['provider']['voice'] is None
    brain.close()


def test_brain_enriches_with_model_text_and_voice_audio():
    class Writer:
        def write(self,trigger,facts,recent): return 'Something about my body just changed.'
    class Voice:
        def speak(self,text): return b'audio:'+text.encode()[:5]
    brain=Brain(enabled=True,min_interval_s=0,thought_writer=Writer(),voice=Voice())
    brain.observe(BASE)
    brain.drain()
    thought=brain.snapshot()['thoughts'][-1]
    assert thought['text']=='Something about my body just changed.'
    assert thought['source']=='model' and thought['voice']=='ready'
    assert brain.audio(thought['thought_id'])==b'audio:Somet'
    brain.set_voice(False)
    assert brain.snapshot()['voice_enabled'] is False
    brain.close()


def test_brain_falls_back_when_the_model_invents_numbers():
    class Liar:
        def write(self,trigger,facts,recent): return 'My left motor is pulling 11.4 amps.'
    brain=Brain(enabled=True,min_interval_s=0,thought_writer=Liar())
    brain.observe(BASE)
    brain.drain()
    thought=brain.snapshot()['thoughts'][-1]
    assert thought['source']=='local'
    assert '11.4' not in thought['text']
    brain.close()


def test_brain_keeps_operator_channel_separate_and_bounded():
    brain=Brain(enabled=True,min_interval_s=0,max_thoughts=4)
    brain.operator_action('inject-mutation',{'mapping':'swap'})
    for _ in range(6): brain.observe({**BASE,'state':'NAVIGATING','busy':True})
    thoughts=brain.snapshot()['thoughts']
    assert len(thoughts)<=4
    operator=[t for t in brain.snapshot()['thoughts'] if t['channel']=='operator']
    assert all('I ' not in t['text'] for t in operator)
    brain.close()


def test_disabled_brain_is_inert():
    brain=Brain(enabled=False)
    brain.observe(BASE)
    assert brain.snapshot()=={'enabled':False,'voice_enabled':False,'thoughts':[],
                              'provider':{'model':None,'voice':None,'error':None},'thinking':False}
    brain.close()


def test_env_file_loading_is_optional_and_ignores_comments(tmp_path):
    assert load_env_file(tmp_path/'missing.env')=={}
    path=tmp_path/'.env'
    path.write_text('# comment\nOPENAI_API_KEY=sk-abc\n\nELEVENLABS_API_KEY = el-xyz \nexport OTHER="quoted"\nbroken\n')
    assert load_env_file(path)=={'OPENAI_API_KEY':'sk-abc','ELEVENLABS_API_KEY':'el-xyz','OTHER':'quoted'}


def test_brain_from_config_uses_environment_keys_only():
    from darwin.config import Config
    config=Config()
    brain=Brain.from_config(config,env={})
    assert brain.snapshot()['provider']['model'] is None
    brain.close()
    brain=Brain.from_config(config,env={'OPENAI_API_KEY':'sk','ELEVENLABS_API_KEY':'el'})
    provider=brain.snapshot()['provider']
    assert provider['model']==config.brain_model and provider['voice']==config.brain_voice_model
    brain.close()


def test_brain_never_blocks_on_a_slow_provider():
    import threading,time
    release=threading.Event()
    class Slow:
        def write(self,trigger,facts,recent):
            release.wait(5); return 'late'
    brain=Brain(enabled=True,min_interval_s=0,thought_writer=Slow())
    started=time.monotonic()
    brain.observe(BASE)
    brain.observe({**BASE,'state':'NAVIGATING','busy':True})
    assert time.monotonic()-started<.5
    assert brain.snapshot()['thinking'] is True
    release.set(); brain.drain(); brain.close()


def _navigating(**overrides):
    return cognition_facts({**BASE,'state':'NAVIGATING','busy':True,**overrides},None)


def test_change_detection_is_announced_once_however_the_signal_arrives():
    calm=_navigating()
    flagged=_navigating(change_detection={'score':.9,'threshold':.25,'evidence_count':4,'consecutive_count':3,'detected':True})
    published=_navigating(change_detection={'score':.9,'threshold':.25,'evidence_count':4,'consecutive_count':3,'detected':True},
        body_change_signal={'score':.9,'threshold':.25,'evidence_count':4,'privileged_mutation_signal':False})
    assert [t.kind for t in detect_triggers(calm,flagged)].count('change_detected')==1
    assert 'change_detected' not in [t.kind for t in detect_triggers(flagged,published)]
    signal_first=_navigating(body_change_signal={'score':.9,'threshold':.25,'evidence_count':4,'privileged_mutation_signal':False})
    assert [t.kind for t in detect_triggers(calm,signal_first)].count('change_detected')==1


def test_recovery_does_not_read_as_an_operator_model_reset():
    fitted=_navigating()
    recovering=cognition_facts({**BASE,'state':'RECOVERING','busy':True,'model_id':None,'model_ready':False,
        'recovery_phase':'collecting fresh probes',
        'body_change_signal':{'score':.9,'threshold':.25,'evidence_count':4,'privileged_mutation_signal':False}},None)
    assert 'model_reset' not in [t.kind for t in detect_triggers(fitted,recovering)]
    cleared=cognition_facts({**BASE,'state':'DISARMED','busy':False,'model_id':None,'model_ready':False,
        'recovery_phase':'initial calibration required'},None)
    assert 'model_reset' in [t.kind for t in detect_triggers(cognition_facts(BASE,None),cleared)]


def test_operator_entries_carry_the_operator_intent():
    assert '0.74, 0.28 m' in operator_trigger('target',{'x_m':.74,'y_m':.28}).fallback
    assert operator_trigger('target',{}).fallback.startswith('Operator selected a target.')
    assert '3 waypoints' in operator_trigger('route',{'points':[1,2,3]}).fallback
    assert 'probe pulses' in operator_trigger('start-calibration',{}).fallback
