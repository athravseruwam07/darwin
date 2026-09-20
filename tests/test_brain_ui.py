"""Run the browser monologue parsers directly; malformed thoughts must never render."""
from pathlib import Path
import shutil
import subprocess
import pytest

STATIC=Path(__file__).resolve().parents[1]/'src/darwin/web/static'

@pytest.mark.skipif(not shutil.which('node'),reason='Node optional: the same parsers run in the browser')
def test_browser_monologue_parsers_are_defensive():
    javascript=(STATIC/'brain.js').read_text(encoding='utf-8').split('window.DarwinBrain=')[0]
    assertions='''
const assert=require('assert');
assert.strictEqual(brainClock(130.4,10),'02:00');
assert.strictEqual(brainClock(NaN,0),'00:00');
assert.strictEqual(brainClock(5,50),'00:00');
assert.deepStrictEqual(parseThoughts(null),[]);
assert.deepStrictEqual(parseThoughts({thoughts:'nope'}),[]);
const parsed=parseThoughts({thoughts:[
  {thought_id:'a',at:1,kind:'change_detected',tone:'alarm',channel:'darwin',headline:'My body changed',text:' Controls scrambled. ',source:'model',voice:'ready',chips:[['score','0.412'],['bad'],['evidence','4']]},
  {thought_id:'a',at:2,text:'duplicate'},
  {thought_id:'b',at:Infinity,text:'nonfinite'},
  {thought_id:'c',at:3,text:'   '},
  {at:4,text:'no id'},
  {thought_id:'d',at:5,text:'operator note',channel:'operator',tone:'operator',voice:'weird',source:'guess'},
  null]});
assert.strictEqual(parsed.length,2);
assert.strictEqual(parsed[0].text,'Controls scrambled.');
assert.deepStrictEqual(parsed[0].chips,[['score','0.412'],['evidence','4']]);
assert.strictEqual(parsed[1].channel,'operator');
assert.strictEqual(parsed[1].voice,'off');
assert.strictEqual(parsed[1].source,'local');
assert.strictEqual(latestThought(parsed).thought_id,'a');
assert.deepStrictEqual(brainStatus({enabled:false},false),{label:'Offline',mode:'offline'});
assert.deepStrictEqual(brainStatus({enabled:true,thinking:true},false),{label:'Thinking',mode:'thinking'});
assert.deepStrictEqual(brainStatus({enabled:true,thinking:true},true),{label:'Speaking',mode:'speaking'});
assert.deepStrictEqual(brainStatus({enabled:true},false),{label:'Listening',mode:'idle'});
assert.deepStrictEqual(speakable(parsed,new Set()),['a']);
assert.deepStrictEqual(speakable(parsed,new Set(['a'])),[]);
assert.deepStrictEqual(speakable([{thought_id:'fallback',channel:'darwin',voice:'failed'}],new Set(),true),['fallback']);
assert(providerLabel({enabled:true,provider:{}}).includes('OPENAI_API_KEY'));
assert.strictEqual(providerLabel({enabled:true,provider:{model:'gpt-4o-mini',voice:'eleven_turbo_v2_5'}}),'gpt-4o-mini voice · eleven_turbo_v2_5');
assert.strictEqual(providerLabel({enabled:false}),'narration disabled');
'''
    result=subprocess.run(['node','-e',javascript+assertions],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

@pytest.mark.skipif(not shutil.which('node'),reason='Node optional')
def test_monologue_script_parses():
    assert subprocess.run(['node','--check',str(STATIC/'brain.js')],capture_output=True).returncode==0

def test_monologue_never_reads_privileged_runtime_fields():
    script=(STATIC/'brain.js').read_text(encoding='utf-8')
    for privileged in ('hidden_map','plant','mutation_map','actuator_mutation','scramble_map'):
        assert privileged not in script
    assert '/api/brain' in script
    assert 'http://' not in script and 'https://' not in script

def test_monologue_respects_reduced_motion_and_keeps_stop_reachable():
    script=(STATIC/'brain.js').read_text(encoding='utf-8')
    css=(STATIC/'style.css').read_text(encoding='utf-8')
    assert 'prefers-reduced-motion: reduce' in script
    assert '@media(prefers-reduced-motion:reduce)' in css
    assert 'await' not in script.split('function playThought')[1].split('function pump')[0]
    html=(STATIC/'index.html').read_text(encoding='utf-8')
    assert html.index('data-command="stop"')<html.index('id="brain-rail"')


def test_monologue_lives_in_observatory_without_cluttering_arena():
    html=(STATIC/'index.html').read_text(encoding='utf-8')
    arena=html.split('<main class="operator-view"',1)[1].split('<main class="lab-view"',1)[0]
    observatory=html.split('<main class="lab-view"',1)[1]
    assert 'brain-rail' not in arena
    assert 'Darwin’s inner monologue' in observatory
    assert 'brain-thought' in observatory
    assert 'brain-stream' not in observatory
    assert 'OpenAI' not in arena and 'ElevenLabs' not in arena
    script=(STATIC/'brain.js').read_text(encoding='utf-8')
    for removed_fluff in ('thought-tone','thought-headline','thought-chips','thought-source'):
        assert removed_fluff not in script
