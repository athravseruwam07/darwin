"""Confined, non-overwriting ZIP export with checksums and explicit origin mode."""
from pathlib import Path
import hashlib
import json
import uuid
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[3]

def export_run(run_path, output='reports/exports', *, allowed_root=None, view_mode=None):
    source = Path(run_path).resolve()
    if not (source/'metadata.json').is_file(): raise ValueError('not a recorded run')
    root = Path(allowed_root).resolve() if allowed_root is not None else PROJECT_ROOT/'reports'
    destination = Path(output).resolve()
    if not destination.is_relative_to(root.resolve()): raise ValueError('exports must remain inside reports directory')
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f'{source.name}_{uuid.uuid4().hex[:8]}.zip'
    metadata = json.loads((source/'metadata.json').read_text())
    manifest = {'schema_version':1,'run_id':source.name,'mode':metadata.get('mode','unknown'),'view_mode':view_mode or metadata.get('mode','unknown'),'files':{}}
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as output_zip:
        for path in sorted(source.rglob('*')):
            if path.is_symlink(): raise ValueError('run contains a symlink')
            if path.is_file():
                data = path.read_bytes()
                # A concurrently growing JSONL is exported at a complete-record boundary.
                if path.suffix=='.jsonl' and data and not data.endswith(b'\n'):
                    data=data[:data.rfind(b'\n')+1]
                relative = str(path.relative_to(source))
                manifest['files'][relative] = hashlib.sha256(data).hexdigest()
                output_zip.writestr(relative,data)
        output_zip.writestr('export_manifest.json',json.dumps(manifest,indent=2))
    return archive
