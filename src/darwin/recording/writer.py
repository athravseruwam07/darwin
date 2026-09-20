"""Append-only records on a bounded worker queue; failures are never hidden."""
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import json
import hashlib
import subprocess
import queue
import threading
import time
import uuid
import yaml

KINDS = frozenset({'observations', 'actions', 'transitions', 'events', 'actuator_audit', 'frames', 'snapshots'})

class RecordingError(RuntimeError):
    pass

def plain(value):
    if is_dataclass(value): return asdict(value)
    if hasattr(value, 'tolist'): return value.tolist()
    if isinstance(value, Path): return str(value)
    raise TypeError(f'Unsupported record type: {type(value).__name__}')

def source_identity():
    """Hash this project's source/config, never discover a surrounding Git repo."""
    root = Path(__file__).resolve().parents[3]
    paths = sorted({p for folder in ('src', 'configs') for p in (root/folder).rglob('*')
                    if p.is_file() and p.suffix in {'.py','.js','.css','.html','.yaml','.yml','.toml'}
                    and '__pycache__' not in p.parts})
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(root)).encode()); digest.update(b'\0')
        digest.update(path.read_bytes()); digest.update(b'\0')
    result = {'software_source_sha256':digest.hexdigest(), 'software_source_file_count':len(paths),
              'software_git_commit':None, 'software_git_dirty':None,
              'software_source_state':'content hash; project has no Git baseline'}
    if (root/'.git').exists():
        try:
            head = subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,timeout=2)
            status = subprocess.run(['git','-C',str(root),'status','--porcelain','--untracked-files=normal','--','src','configs'],capture_output=True,text=True,timeout=2)
            if head.returncode==0 and status.returncode==0:
                result.update(software_git_commit=head.stdout.strip(),software_git_dirty=bool(status.stdout.strip()),software_source_state='Git source/config status plus content hash')
        except (OSError,subprocess.TimeoutExpired): result['software_source_state']='content hash; Git metadata unavailable'
    return result

class RunWriter:
    def __init__(self, root='data/runs', metadata=None, config=None, queue_size=1024):
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:10]
        self.path = Path(root).resolve() / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        self._queue = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._failure = None
        self._closed = False
        self._sequence = 0
        deps = {}
        for name in ['numpy', 'opencv-contrib-python', 'fastapi', 'pyserial']:
            try: deps[name] = version(name)
            except PackageNotFoundError: deps[name] = 'unavailable'
        self.save_artifact('metadata.json', {'schema_version': 1, 'run_id': self.run_id,
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'software_version': '0.1.0', 'dependency_versions': deps, **source_identity(),
            'timestamp_domain': 'host_monotonic; simulation observation time synthetic',
            'measurement_version': 'pulse_plus_settle_v1', **(metadata or {})})
        if config is not None:
            data = asdict(config) if is_dataclass(config) else config
            with (self.path / 'config.yaml').open('x') as handle: yaml.safe_dump(data, handle)
        for kind in KINDS: (self.path / f'{kind}.jsonl').touch(exist_ok=False)
        (self.path / 'checkpoints').mkdir()
        self._thread = threading.Thread(target=self._consume, name='darwin-recording', daemon=True)
        self._thread.start()

    def save_artifact(self, name, record):
        if name not in {'metadata.json', 'calibration.json', 'evaluation.json'}:
            raise ValueError('unsupported artifact name')
        with (self.path / name).open('x') as handle:
            json.dump(record, handle, default=plain, allow_nan=False, indent=2)

    def append(self, kind, record):
        if kind not in KINDS: raise ValueError('unknown record kind')
        data = asdict(record) if is_dataclass(record) else dict(record)
        with self._lock:
            self._check()
            if self._closed: raise RecordingError('run already closed')
            self._sequence += 1
            line = json.dumps({**data, '_sequence': self._sequence, '_recorded_monotonic': time.monotonic()}, default=plain, allow_nan=False)
            try: self._queue.put_nowait((kind, line))
            except queue.Full as exc:
                self._failure = RecordingError('essential recording queue full: stop episode')
                raise self._failure from exc

    def _check(self):
        if self._failure: raise RecordingError(str(self._failure)) from self._failure

    def _consume(self):
        handles = {}
        try:
            while True:
                item = self._queue.get()
                try:
                    if item is None: break
                    kind, line = item
                    if kind not in handles: handles[kind] = (self.path / f'{kind}.jsonl').open('a', buffering=1)
                    handles[kind].write(line + '\n')
                except BaseException as exc:
                    self._failure = exc
                finally: self._queue.task_done()
        finally:
            for handle in handles.values(): handle.close()

    def flush(self, timeout=3):
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            self._check()
            if time.monotonic() >= deadline: raise RecordingError('recording flush deadline exceeded')
            time.sleep(.002)
        self._check()

    def close(self):
        with self._lock:
            if self._closed: return
            self._closed = True
        try: self.flush()
        finally:
            try: self._queue.put(None, timeout=.1)
            except queue.Full: pass
            self._thread.join(timeout=3)
        self._check()
