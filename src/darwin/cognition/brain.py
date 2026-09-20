"""The monologue itself: sensed transitions in, human sentences (and audio) out.

Every thought is published immediately with its deterministic sentence, so the
panel is correct offline. Enrichment happens on one background worker that never
touches the runtime, holds no runtime lock, and cannot delay STOP.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import os
import queue
import threading
import time
import uuid

from .facts import cognition_facts
from .triggers import detect_triggers, operator_trigger
from .providers import OpenAIThoughtWriter, ElevenLabsVoice, supported_numbers, load_env_file, clean

MAX_AUDIO_BYTES = 4_000_000

@dataclass
class Thought:
    thought_id: str
    at: float
    kind: str
    tone: str
    channel: str
    headline: str
    text: str
    fallback: str
    source: str = 'local'
    voice: str = 'off'
    chips: tuple = ()
    facts: dict = field(default_factory=dict)

    def to_dict(self):
        return {'thought_id':self.thought_id,'at':round(self.at,3),'kind':self.kind,'tone':self.tone,
                'channel':self.channel,'headline':self.headline,'text':self.text,'source':self.source,
                'voice':self.voice,'chips':[list(chip) for chip in self.chips]}

class Brain:
    """Collects sensed triggers, narrates them, and optionally speaks them."""

    def __init__(self, *, enabled=True, thought_writer=None, voice=None, voice_enabled=True,
                 max_thoughts=40, min_interval_s=6., clock=time.monotonic):
        self.enabled=bool(enabled)
        self.thought_writer=thought_writer if self.enabled else None
        self.voice=voice if self.enabled else None
        self.voice_enabled=bool(voice_enabled) and self.voice is not None
        self.max_thoughts=max(4,int(max_thoughts)); self.min_interval_s=max(0.,float(min_interval_s))
        self.clock=clock
        self._lock=threading.RLock()
        self._thoughts=[]; self._audio={}; self._facts=None
        self._last_at={}; self._last_darwin_at=None; self._pending=0; self._error=None
        self._queue=queue.Queue(maxsize=32); self._worker=None; self._closed=False

    @classmethod
    def from_config(cls, config, env=None, env_file=None):
        """Build a brain from config plus environment keys; keys never live in config."""
        values=dict(load_env_file(env_file) if env_file else {})
        values.update(os.environ if env is None else env)
        writer=voice=None
        if getattr(config,'brain_enabled',True) and values.get('OPENAI_API_KEY'):
            writer=OpenAIThoughtWriter(values['OPENAI_API_KEY'],model=getattr(config,'brain_model','gpt-4o-mini'),
                                       timeout=getattr(config,'brain_timeout_s',6.))
        if getattr(config,'brain_voice_enabled',True) and values.get('ELEVENLABS_API_KEY'):
            voice=ElevenLabsVoice(values['ELEVENLABS_API_KEY'],
                                  voice_id=values.get('ELEVENLABS_VOICE_ID') or getattr(config,'brain_voice_id',''),
                                  model_id=getattr(config,'brain_voice_model','eleven_turbo_v2_5'),
                                  timeout=getattr(config,'brain_voice_timeout_s',12.))
        return cls(enabled=bool(getattr(config,'brain_enabled',True)),thought_writer=writer,voice=voice,
                   voice_enabled=bool(getattr(config,'brain_voice_enabled',True)),
                   max_thoughts=int(getattr(config,'brain_max_thoughts',40)),
                   min_interval_s=float(getattr(config,'brain_min_interval_s',6.)))

    def observe(self, snapshot, config=None):
        """Feed one runtime snapshot; returns the thoughts this snapshot produced."""
        if not self.enabled or self._closed: return []
        facts=cognition_facts(snapshot,config)
        with self._lock:
            previous,self._facts=self._facts,facts
        for trigger in detect_triggers(previous,facts):
            thought=self._record(trigger,facts)
            if thought is not None: return [thought]
        return []

    def operator_action(self, command, payload=None):
        """Record what the operator did. This channel is never Darwin's voice."""
        if not self.enabled or self._closed: return None
        trigger=operator_trigger(command,payload)
        if trigger is None: return None
        with self._lock: facts=self._facts or {}
        return self._record(trigger,facts,rate_limit=False)

    def _record(self, trigger, facts, rate_limit=True):
        now=self.clock()
        with self._lock:
            if (rate_limit and trigger.channel=='darwin' and trigger.priority>1 and
                    self._last_darwin_at is not None and now-self._last_darwin_at<self.min_interval_s):
                return None
            self._last_at[trigger.kind]=now
            if trigger.channel=='darwin': self._last_darwin_at=now
            sentence=clean(trigger.fallback) or 'Waiting for new evidence.'
            thought=Thought(uuid.uuid4().hex[:12],now,trigger.kind,trigger.tone,trigger.channel,
                            trigger.headline,sentence,sentence,chips=trigger.chips,facts=facts)
            self._thoughts.append(thought)
            dropped,self._thoughts=self._thoughts[:-self.max_thoughts],self._thoughts[-self.max_thoughts:]
            for stale in dropped: self._audio.pop(stale.thought_id,None)
            speakable=self.voice_enabled and self.voice is not None and trigger.channel=='darwin'
            if speakable: thought.voice='pending'
            if self.thought_writer is None and not speakable: return thought
            recent=[item.text for item in self._thoughts[-5:-1]]
            self._pending+=1
        if not self._enqueue((thought,trigger,facts,recent,speakable)):
            with self._lock:
                self._pending=max(0,self._pending-1)
                if thought.voice=='pending': thought.voice='off'
        return thought

    def _enqueue(self, job):
        try: self._queue.put_nowait(job)
        except queue.Full: return False
        if self._worker is None or not self._worker.is_alive():
            self._worker=threading.Thread(target=self._work,name='darwin-brain',daemon=True)
            self._worker.start()
        return True

    def _work(self):
        while True:
            try: job=self._queue.get(timeout=.5)
            except queue.Empty:
                with self._lock:
                    if self._closed or not self._pending: return
                continue
            thought,trigger,facts,recent,speakable=job
            try: self._enrich(thought,trigger,facts,recent,speakable)
            except Exception as exc:
                with self._lock: self._error=str(exc)[:200]
            finally:
                with self._lock: self._pending=max(0,self._pending-1)
                self._queue.task_done()

    def _enrich(self, thought, trigger, facts, recent, speakable):
        if self.thought_writer is not None:
            text=None
            try: text=self.thought_writer.write(trigger,facts,recent)
            except Exception as exc:
                with self._lock: self._error=str(exc)[:200]
            if text and supported_numbers(text,{'facts':facts,'sentence':trigger.fallback,
                                                'chips':[list(chip) for chip in trigger.chips]}):
                with self._lock: thought.text=text; thought.source='model'
            elif text:
                with self._lock: self._error='rewrite rejected: unsupported numbers'
        if not speakable: return
        audio=None
        try: audio=self.voice.speak(thought.text)
        except Exception as exc:
            with self._lock: self._error=str(exc)[:200]
        with self._lock:
            if audio and len(audio)<=MAX_AUDIO_BYTES and not self._closed:
                self._audio[thought.thought_id]=bytes(audio); thought.voice='ready'
            else: thought.voice='failed' if self.voice_enabled else 'off'

    def audio(self, thought_id):
        with self._lock: return self._audio.get(str(thought_id))

    def set_voice(self, enabled):
        with self._lock:
            self.voice_enabled=bool(enabled) and self.voice is not None
            return self.voice_enabled

    def snapshot(self):
        with self._lock:
            if not self.enabled:
                return {'enabled':False,'voice_enabled':False,'thoughts':[],
                        'provider':{'model':None,'voice':None,'error':None},'thinking':False}
            return {'enabled':True,'voice_enabled':self.voice_enabled,
                    'thoughts':[thought.to_dict() for thought in self._thoughts],
                    'provider':{'model':getattr(self.thought_writer,'name',None),
                                'voice':getattr(self.voice,'name',None),'error':self._error},
                    'thinking':self._pending>0}

    def drain(self, timeout=15.):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            with self._lock:
                if not self._pending: return True
            time.sleep(.01)
        return False

    def close(self):
        with self._lock:
            self._closed=True; self._audio.clear()
        worker=self._worker
        if worker is not None and worker.is_alive(): worker.join(timeout=1)
