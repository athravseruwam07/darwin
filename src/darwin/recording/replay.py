"""Read-only timeline. No actuator, camera, serial, or live runtime imports."""
from dataclasses import fields, asdict
from pathlib import Path
import json
import copy
import threading
import time
import yaml
from darwin.types import Pose, Transition

POSE_FIELDS = frozenset(field.name for field in fields(Pose))
TRANSITION_FIELDS = frozenset(field.name for field in fields(Transition))

def records(path):
    path = Path(path)
    if not path.exists(): return []
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]

def load_transitions(run_path):
    result = []
    for row in records(Path(run_path) / 'transitions.jsonl'):
        data = {key: value for key, value in row.items() if key in TRANSITION_FIELDS}
        for key in ('start_pose', 'end_pose'):
            data[key] = Pose(**{k:v for k,v in data[key].items() if k in POSE_FIELDS})
        result.append(Transition(**data))
    return result

class ReplayRuntime:
    def __init__(self, run_path):
        self.path = Path(run_path).resolve()
        self.metadata = json.loads((self.path / 'metadata.json').read_text())
        self._config = yaml.safe_load((self.path/'config.yaml').read_text()) if (self.path/'config.yaml').exists() else {}
        self._rows = []
        for kind in ('observations', 'actions', 'transitions', 'events', 'snapshots'):
            for row in records(self.path/f'{kind}.jsonl'): self._rows.append((kind,row))
        self._rows.sort(key=lambda pair: pair[1].get('_sequence', 0))
        times = [r.get('_recorded_monotonic', float(i)) for i,(_,r) in enumerate(self._rows)]
        self._times = [t-times[0] for t in times] if times else []
        self._cursor = 1 if self._rows else 0
        self._playing = False
        self._play_start = 0.
        self._offset = 0.
        self._lock = threading.RLock()

    def public_config(self): return {**self._config, 'mode':'replay'}
    def list_runs(self): return [{'run_id': self.path.name, 'mode': self.metadata.get('mode','unknown')}]
    def latest_jpeg(self): return None
    def close(self): self._playing = False

    def command(self, name, payload=None):
        payload = payload or {}
        with self._lock:
            if name in {'replay-seek', 'seek'}:
                position = float(payload.get('seconds',0))
                if not 0 <= position <= (self._times[-1] if self._times else 0): raise ValueError('seek outside recorded timeline')
                self._offset = position
                self._play_start = time.monotonic()
                self._cursor = sum(t <= position for t in self._times)
            elif name in {'replay-play','play'}:
                self.snapshot()
                self._offset = self._times[self._cursor-1] if self._cursor else 0
                self._playing = bool(payload.get('playing', True)); self._play_start = time.monotonic()
            elif name == 'export':
                from darwin.recording.export import export_run
                return {'ok':True,'path':str(export_run(self.path, view_mode='replay'))}
            elif name == 'stop':
                self.snapshot(); self._playing = False
                self._offset = self._times[self._cursor-1] if self._cursor else 0
            else: raise ValueError('Replay is read-only; live commands are unavailable')
            return {'ok':True, 'state':'REPLAY'}

    def snapshot(self):
        with self._lock:
            if self._playing:
                position = self._offset + time.monotonic()-self._play_start
                self._cursor = sum(t <= position for t in self._times)
                if self._cursor == len(self._rows): self._playing = False
            state = dict(mode='replay',state='REPLAY',run_id=self.path.name, original_mode=self.metadata.get('mode','unknown'),
                pose=None,target=None,trail=[],predicted_motion=None,valid_sample_count=0,rejected_sample_count=0,
                model_id=None,validation_metrics={},transport_health={'connected':False,'detail':'Read-only replay'},busy=False,
                replay={'playing':self._playing,'position_s':self._times[self._cursor-1] if self._cursor else 0,'duration_s':self._times[-1] if self._times else 0,'record_count':len(self._rows)})
            if (self.path/'calibration.json').exists(): state['calibration']=json.loads((self.path/'calibration.json').read_text())
            for kind,row in self._rows[:self._cursor]:
                if kind == 'snapshots': state.update(copy.deepcopy({k:v for k,v in row.items() if not k.startswith('_')}))
                elif kind == 'observations':
                    pose = row.get('pose',row)
                    if 'x_m' in pose:
                        state['pose']={k:v for k,v in pose.items() if k in POSE_FIELDS}
                        if pose.get('valid',True): state['trail'].append([pose['x_m'],pose['y_m']])
                elif kind == 'transitions':
                    if not row.get('valid',True): state['rejected_sample_count'] += 1
                    elif ':heldout' in row.get('episode_id',''): state['heldout_sample_count']=state.get('heldout_sample_count',0)+1
                    elif not row.get('episode_id','').startswith('navigation:'): state['valid_sample_count'] += 1
                elif kind == 'events':
                    event = row.get('kind',row.get('event',row.get('name',row.get('type',''))))
                    if event in {'model_reset','scramble'}:
                        state.update(model_id=None,valid_sample_count=0,heldout_sample_count=0)
                        if event=='model_reset': state['validation_metrics']={}
                    if event=='calibration' and 'points_px' in row:
                        state['calibration']={k:v for k,v in row.items() if not k.startswith('_') and k not in {'kind','at','wall_monotonic'}}
                    if event=='intervention': state['trail']=[]
                    if 'target' in row: state['target']=row['target']
                    if 'model_id' in row: state['model_id']=row['model_id']
                    if 'validation_metrics' in row: state['validation_metrics']=row['validation_metrics']
                    if 'metrics' in row: state['validation_metrics']=row['metrics']
                    state.setdefault('events',[]).append(row)
            state.update(mode='replay',state='REPLAY',busy=False,owner_id=None,transport_health={'connected':False,'detail':'Read-only replay; no transport'},original_mode=self.metadata.get('mode','unknown'))
            state['trail']=state['trail'][-1000:]
            return state
