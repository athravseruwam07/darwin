'use strict';
// Darwin's inner monologue. Everything drawn here comes from /api/brain; this file
// never infers runtime state, and a malformed thought is dropped instead of rendered.
function brainClock(at,origin){const seconds=Number(at)-Number(origin);if(!Number.isFinite(seconds)||seconds<0)return '00:00';const total=Math.floor(seconds);return String(Math.floor(total/60)%100).padStart(2,'0')+':'+String(total%60).padStart(2,'0');}
function parseThoughts(body){if(!body||typeof body!=='object'||!Array.isArray(body.thoughts))return[];const seen=new Set();return body.thoughts.filter(item=>{if(!item||typeof item!=='object')return false;if(typeof item.thought_id!=='string'||!item.thought_id)return false;if(typeof item.text!=='string'||!item.text.trim())return false;if(!Number.isFinite(Number(item.at)))return false;if(seen.has(item.thought_id))return false;seen.add(item.thought_id);return true;}).map(item=>({thought_id:item.thought_id,at:Number(item.at),kind:typeof item.kind==='string'?item.kind:'thought',tone:typeof item.tone==='string'?item.tone:'work',channel:item.channel==='operator'?'operator':'darwin',headline:typeof item.headline==='string'?item.headline:'',text:item.text.trim(),source:item.source==='model'?'model':'local',voice:['ready','pending','failed','off'].includes(item.voice)?item.voice:'off',chips:Array.isArray(item.chips)?item.chips.filter(chip=>Array.isArray(chip)&&chip.length===2&&chip.every(value=>typeof value==='string'||typeof value==='number')).slice(0,4).map(chip=>[String(chip[0]),String(chip[1])]):[]}));}
function brainStatus(body,speaking){if(!body||body.enabled!==true)return{label:'Offline',mode:'offline'};if(speaking)return{label:'Speaking',mode:'speaking'};if(body.thinking===true)return{label:'Thinking',mode:'thinking'};return{label:'Listening',mode:'idle'};}
function speakable(thoughts,played){return thoughts.filter(thought=>thought.voice==='ready'&&thought.channel==='darwin'&&!played.has(thought.thought_id)).map(thought=>thought.thought_id);}
function providerLabel(body){if(!body||body.enabled!==true)return 'narration disabled';const model=typeof body.provider?.model==='string'?body.provider.model:null,voice=typeof body.provider?.voice==='string'?body.provider.voice:null;return (model?model+' voice':'local narration · no OPENAI_API_KEY')+(voice?' · '+voice:' · no speech');}
window.DarwinBrain={brainClock,parseThoughts,brainStatus,speakable,providerLabel};
const rail=document.getElementById('brain-rail');
if(rail){
const pick=id=>document.getElementById(id),stream=pick('brain-stream'),audio=new Audio();
const reduceMotion=window.matchMedia?.('(prefers-reduced-motion: reduce)');
const storage={get(key,fallback){try{const value=localStorage.getItem(key);return value===null?fallback:value;}catch{return fallback;}},set(key,value){try{localStorage.setItem(key,value);}catch{}}};
let body={},thoughts=[],origin=null,rendered=new Map(),played=new Set(),queue=[],speaking=false,pollBusy=false;
let voiceOn=storage.get('darwin-brain-voice','off')==='on',open=storage.get('darwin-brain-open','on')==='on';
const TONE_WORDS={boot:'BOOT',work:'WORKING',focus:'DRIVING',curious:'SUSPICIOUS',alarm:'CHANGE SENSED',resolved:'LEARNED',fault:'HALTED',operator:'OPERATOR'};
function applyLayout(){rail.dataset.open=open?'true':'false';pick('brain-collapse').setAttribute('aria-expanded',String(open));pick('brain-collapse').textContent=open?'Hide thoughts':'Show thoughts';}
function applyVoiceButton(){const button=pick('brain-mute'),available=typeof body.provider?.voice==='string';button.disabled=!available;button.dataset.on=voiceOn&&available?'true':'false';button.setAttribute('aria-pressed',String(voiceOn&&available));button.textContent=voiceOn&&available?'Voice on':'Voice';button.title=!available?'Add ELEVENLABS_API_KEY to enable voice':voiceOn?'Mute Darwin':'Let Darwin speak';}
function card(thought){const li=document.createElement('li');li.className='thought';li.dataset.tone=thought.tone;li.dataset.channel=thought.channel;li.dataset.kind=thought.kind;
const head=document.createElement('div');head.className='thought-head';
const tone=document.createElement('span');tone.className='thought-tone';tone.textContent=TONE_WORDS[thought.tone]||'NOTE';
const time=document.createElement('time');time.textContent=brainClock(thought.at,origin);
head.append(tone,time);
const headline=document.createElement('span');headline.className='thought-headline';headline.textContent=thought.headline;
const text=document.createElement('p');text.className='thought-text';text.textContent=thought.text;
li.append(head,headline,text);
if(thought.chips.length){const chips=document.createElement('div');chips.className='thought-chips';for(const[label,value]of thought.chips){const chip=document.createElement('span');const b=document.createElement('b');b.textContent=label;chip.append(b,document.createTextNode(value));chips.append(chip);}li.append(chips);}
const foot=document.createElement('div');foot.className='thought-foot';
const source=document.createElement('span');source.className='thought-source';source.dataset.source=thought.source;source.textContent=thought.channel==='operator'?'Darwin cannot see this':thought.source==='model'?'AI phrasing · grounded facts':'Grounded in runtime facts';
foot.append(source);
if(thought.channel==='darwin'){const speak=document.createElement('button');speak.className='thought-speak';speak.type='button';speak.textContent='▶';speak.title='Replay this thought';speak.hidden=thought.voice!=='ready';speak.onclick=()=>playThought(thought.thought_id,true);foot.append(speak);}
li.append(foot);
return li;}
function reveal(node,text){if(reduceMotion?.matches){node.textContent=text;return;}const step=Math.max(1,Math.ceil(text.length/60));let index=0;node.textContent='';node.classList.add('typing');const tick=()=>{index=Math.min(text.length,index+step);node.textContent=text.slice(0,index);if(index<text.length)setTimeout(tick,16);else node.classList.remove('typing');};tick();}
function render(){const atBottom=stream.scrollHeight-stream.scrollTop-stream.clientHeight<80;const live=new Set();
for(const thought of thoughts){live.add(thought.thought_id);const existing=rendered.get(thought.thought_id);
if(!existing){const node=card(thought);rendered.set(thought.thought_id,{node,text:thought.text,voice:thought.voice});stream.append(node);if(thought.channel==='darwin')reveal(node.querySelector('.thought-text'),thought.text);continue;}
if(existing.text!==thought.text){existing.text=thought.text;const node=existing.node.querySelector('.thought-text');reveal(node,thought.text);existing.node.querySelector('.thought-source').dataset.source=thought.source;existing.node.querySelector('.thought-source').textContent=thought.source==='model'?'AI phrasing · grounded facts':'Grounded in runtime facts';}
if(existing.voice!==thought.voice){existing.voice=thought.voice;const speak=existing.node.querySelector('.thought-speak');if(speak)speak.hidden=thought.voice!=='ready';}}
for(const[id,entry]of rendered)if(!live.has(id)){entry.node.remove();rendered.delete(id);}
pick('brain-empty').hidden=thoughts.length>0;
if(atBottom)stream.scrollTop=stream.scrollHeight;
const status=brainStatus(body,speaking);pick('brain-status').textContent=status.label;rail.dataset.status=status.mode;
const alarm=thoughts.length&&thoughts[thoughts.length-1].tone==='alarm';rail.dataset.alert=alarm?'true':'false';
pick('brain-provider').textContent=providerLabel(body);
pick('brain-count').textContent=thoughts.length?thoughts.length+' thoughts':'—';
applyVoiceButton();}
function playThought(id,manual){if(!voiceOn&&!manual)return;played.add(id);speaking=true;rail.dataset.status='speaking';pick('brain-status').textContent='Speaking';audio.src='/api/brain/voice/'+encodeURIComponent(id);audio.play().catch(()=>{speaking=false;if(!manual){voiceOn=false;storage.set('darwin-brain-voice','off');applyVoiceButton();}});}
function pump(){if(speaking||!voiceOn||!queue.length)return;playThought(queue.shift(),false);}
audio.addEventListener('ended',()=>{speaking=false;pump();render();});
audio.addEventListener('error',()=>{speaking=false;pump();});
async function pollBrain(){if(pollBusy)return;pollBusy=true;try{const response=await fetch('/api/brain');if(!response.ok)throw Error('brain unavailable');const next=await response.json();body=next&&typeof next==='object'?next:{};thoughts=parseThoughts(body);if(origin===null&&thoughts.length)origin=thoughts[0].at;
if(voiceOn){const ready=speakable(thoughts,played);for(const id of ready)if(!queue.includes(id))queue.push(id);pump();}else{for(const thought of thoughts)played.add(thought.thought_id);queue=[];}
render();}catch{body={...body,enabled:body.enabled===true?true:false};render();}finally{pollBusy=false;}}
pick('brain-collapse').onclick=()=>{open=!open;storage.set('darwin-brain-open',open?'on':'off');applyLayout();};
pick('brain-mute').onclick=async()=>{voiceOn=!voiceOn;storage.set('darwin-brain-voice',voiceOn?'on':'off');applyVoiceButton();
try{await fetch('/api/brain/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:voiceOn})});}catch{}
if(voiceOn){played=new Set(thoughts.slice(0,-1).map(thought=>thought.thought_id));queue=speakable(thoughts,played);pump();}else{audio.pause();speaking=false;queue=[];}
pollBrain();};
applyLayout();applyVoiceButton();pollBrain();setInterval(pollBrain,700);
}
