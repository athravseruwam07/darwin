"""Optional cloud voices for the monologue.

Both providers are best-effort: a missing key, a timeout, or a malformed answer
returns None and the caller keeps the deterministic sentence. Only the public
fact packet is ever sent, and nothing here can command a motor.
"""
from __future__ import annotations
from pathlib import Path
import json
import re
import urllib.request

OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
ELEVENLABS_URL = 'https://api.elevenlabs.io/v1/text-to-speech/'
NUMBER = re.compile(r'\d+(?:\.\d+)?')
SYSTEM_PROMPT = (
    "You are the inner monologue of Darwin, a two-wheel robot that learns the relationship between two "
    "abstract motor commands and camera-observed motion using a small ridge regression. "
    "Rewrite the supplied event as one tiny, playful first-person reaction with gentle humor. "
    "Rules: use ONLY the facts given; never output digits, measurements, percentages, hardware parts, sensors, emotions about people, "
    "or knowledge of why your body changed; you learn only from camera measurements, so never claim anyone "
    "told you anything; never mention being a language model; no markdown, no quotes, one sentence under 70 characters."
)

def post_json(url, data, headers, timeout):
    """POST an already-serialized JSON body and return the raw response bytes."""
    body=data.encode() if isinstance(data,str) else data
    request=urllib.request.Request(url,data=body,headers=headers,method='POST')
    with urllib.request.urlopen(request,timeout=timeout) as response: return response.read()

def load_env_file(path):
    """Read a local KEY=VALUE file. Missing or malformed lines are ignored."""
    path=Path(path)
    try: text=path.read_text(encoding='utf-8')
    except OSError: return {}
    values={}
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('export '): line=line[7:].strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key,_,value=line.partition('=')
        key=key.strip(); value=value.strip().strip('"').strip("'")
        if key: values[key]=value
    return values

def supported_numbers(text, facts):
    """Reject rewrites whose numbers are not backed by the fact packet."""
    if not isinstance(text,str): return False
    known=set()
    def walk(node):
        if isinstance(node,dict): [walk(value) for value in node.values()]
        elif isinstance(node,(list,tuple)): [walk(value) for value in node]
        elif isinstance(node,bool): pass
        elif isinstance(node,(int,float)):
            for digits in range(6): known.add(f'{float(node):.{digits}f}'.rstrip('0').rstrip('.') or '0')
            known.add(str(node))
        elif isinstance(node,str): known.update(NUMBER.findall(node))
    walk(facts)
    known={value.lstrip('0') or '0' for value in known}
    for token in NUMBER.findall(text):
        candidate=token.rstrip('0').rstrip('.') if '.' in token else token
        candidate=(candidate.lstrip('0') or '0')
        if candidate not in known and token.lstrip('0') not in known: return False
    return True

class OpenAIThoughtWriter:
    """Rephrase one trigger into Darwin's voice, or return None on any failure."""
    def __init__(self, api_key, model='gpt-4o-mini', timeout=6., transport=post_json, max_tokens=110, temperature=.7):
        self.api_key=api_key; self.model=model; self.timeout=timeout
        self.transport=transport; self.max_tokens=max_tokens; self.temperature=temperature
        self.name=model

    def write(self, trigger, facts, recent=()):
        payload={'model':self.model,'max_tokens':self.max_tokens,'temperature':self.temperature,
            'messages':[{'role':'system','content':SYSTEM_PROMPT},
                        {'role':'user','content':json.dumps({
                            'event':trigger.kind,'headline':trigger.headline,'tone':trigger.tone,
                            'deterministic_sentence':trigger.fallback,'runtime_facts':facts,
                            'recent_thoughts':list(recent)[-4:]},allow_nan=False,default=str)}]}
        headers={'Authorization':'Bearer '+str(self.api_key),'Content-Type':'application/json'}
        try:
            raw=self.transport(OPENAI_URL,json.dumps(payload,allow_nan=False,default=str),headers,self.timeout)
            body=json.loads(raw)
            text=body['choices'][0]['message']['content']
        except Exception: return None
        return clean(text)

class ElevenLabsVoice:
    """Speak one sentence, or return None so the panel stays silent."""
    def __init__(self, api_key, voice_id='21m00Tcm4TlvDq8ikWAM', model_id='eleven_turbo_v2_5',
                 timeout=12., transport=post_json, stability=.4, similarity=.75):
        self.api_key=api_key; self.voice_id=voice_id; self.model_id=model_id
        self.timeout=timeout; self.transport=transport; self.stability=stability; self.similarity=similarity
        self.name=model_id

    def speak(self, text):
        if not isinstance(text,str) or not text.strip(): return None
        payload={'text':text.strip(),'model_id':self.model_id,
                 'voice_settings':{'stability':self.stability,'similarity_boost':self.similarity}}
        headers={'xi-api-key':str(self.api_key),'Content-Type':'application/json','Accept':'audio/mpeg'}
        try:
            audio=self.transport(ELEVENLABS_URL+str(self.voice_id),json.dumps(payload),headers,self.timeout)
        except Exception: return None
        return audio if isinstance(audio,(bytes,bytearray)) and audio else None

def clean(text, limit=72):
    """Collapse a model answer into one plain, bounded sentence block."""
    if not isinstance(text,str): return None
    text=' '.join(text.split()).strip().strip('"').strip("'").strip()
    text=re.sub(r'^[-*#>\s]+','',text)
    if not text or NUMBER.search(text): return None
    text=re.split(r'(?<=[.!?])\s+',text,maxsplit=1)[0]
    return text[:limit].rstrip()
