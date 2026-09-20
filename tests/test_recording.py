import json
import threading
import zipfile
from dataclasses import asdict
import pytest
from darwin.config import Config
from darwin.types import Pose, Transition
from darwin.recording.writer import RunWriter, RecordingError
from darwin.recording.replay import load_transitions, ReplayRuntime
from darwin.recording.export import export_run

def transition():
    return Transition('trial-1','episode-1',1,0,Pose(1,0,.5,.5,0),Pose(2,.42,.51,.5,.1),.42,.01,0,.1,.01/.42,.1/.42)

def test_immutable_records_and_whitelisted_training(tmp_path):
    writer=RunWriter(tmp_path,{'mode':'simulation'},Config())
    writer.append('transitions',{**asdict(transition()),'secret_mapping':[[2,3],[4,5]],'physical_A':40})
    writer.append('actuator_audit',{'secret_mapping':[[2,3],[4,5]]})
    writer.close()
    assert load_transitions(writer.path)==[transition()]
    with pytest.raises(RecordingError): writer.append('events',{'name':'too late'})
    with pytest.raises(FileExistsError): writer.save_artifact('metadata.json',{})
    other=RunWriter(tmp_path);other.close();assert other.path!=writer.path
    assert json.loads((writer.path/'metadata.json').read_text())['mode']=='simulation'

def test_queue_backpressure_never_silently_drops(tmp_path,monkeypatch):
    ready=threading.Event(); release=threading.Event()
    consume=RunWriter._consume
    def stalled(self): ready.set(); release.wait(2);consume(self)
    monkeypatch.setattr(RunWriter,'_consume',stalled)
    writer=RunWriter(tmp_path,queue_size=1);ready.wait(1)
    writer.append('actions',{'id':'first'})
    with pytest.raises(RecordingError,match='queue full'): writer.append('actions',{'id':'second'})
    release.set()
    with pytest.raises(RecordingError): writer.close()
    assert json.loads((writer.path/'actions.jsonl').read_text())['id']=='first'

def test_replay_read_only_seek_preserves_observations(tmp_path):
    writer=RunWriter(tmp_path,{'mode':'simulation'},Config())
    writer.append('observations',Pose(1,0,.5,.5,0));writer.append('transitions',transition());writer.append('observations',Pose(2,.42,.51,.5,.1));writer.close()
    replay=ReplayRuntime(writer.path)
    assert not hasattr(replay,'transport')
    for command in ['connect','arm','navigate','start-calibration','scramble','recover','reset-model','target','heartbeat']:
        with pytest.raises(ValueError,match='read-only'): replay.command(command,{})
    replay.command('replay-seek',{'seconds':replay.snapshot()['replay']['duration_s']})
    state=replay.snapshot();assert state['mode']=='replay';assert state['original_mode']=='simulation'
    assert state['pose']['x_m']==.51 and state['valid_sample_count']==1
    assert state['trail']==[[.5,.5],[.51,.5]]
    replay.command('replay-play',{'playing':True});replay.command('stop')
    assert not replay.snapshot()['replay']['playing']

def test_export_confined_unique_complete(tmp_path):
    writer=RunWriter(tmp_path/'runs',{'mode':'simulation'},Config());writer.append('events',{'event':'STOP'});writer.close()
    output=tmp_path/'exports'
    with pytest.raises(ValueError,match='reports'): export_run(writer.path,tmp_path/'escape')
    archive=export_run(writer.path,output,allowed_root=output)
    with zipfile.ZipFile(archive) as zipped:
        manifest=json.loads(zipped.read('export_manifest.json'))
        assert manifest['mode']=='simulation'
        assert 'events.jsonl' in manifest['files']
        assert json.loads(zipped.read('events.jsonl'))['event']=='STOP'
    assert archive!=export_run(writer.path,output,allowed_root=output)

def test_nonfinite_and_path_kind_rejected(tmp_path):
    writer=RunWriter(tmp_path)
    with pytest.raises(ValueError): writer.append('../../elsewhere',{})
    with pytest.raises(ValueError): writer.append('events',{'value':float('nan')})
    writer.close()

def test_source_identity_and_replay_snapshot_fidelity(tmp_path):
    writer=RunWriter(tmp_path,{'mode':'simulation'},Config())
    expected={'before':{'v_rmse_mps':.003,'omega_rmse_radps':.025},'adapted':{'normalized_rmse':.01}}
    writer.append('snapshots',{'mode':'simulation','state':'READY','pose':asdict(Pose(1,0,.5,.5,0)),
        'model_id':'actual-model','validation_metrics':expected,'trail':[{'x_m':.5,'y_m':.5}],
        'valid_sample_count':24,'rejected_sample_count':2,'owner_id':'old-owner','transport_health':'healthy'})
    writer.append('observations',Pose(2,.42,.51,.5,.1));writer.close()
    metadata=json.loads((writer.path/'metadata.json').read_text())
    assert len(metadata['software_source_sha256'])==64
    assert metadata['software_source_file_count']>10
    assert 'software_git_dirty' in metadata
    replay=ReplayRuntime(writer.path)
    replay.command('seek',{'seconds':replay.snapshot()['replay']['duration_s']})
    first=replay.snapshot();second=replay.snapshot()
    assert first==second  # Repeated polls must never mutate stored snapshots/trails.
    assert first['validation_metrics']==expected
    assert first['model_id']=='actual-model' and first['valid_sample_count']==24
    assert len(first['trail'])==2 and first['owner_id'] is None
    assert not first['transport_health']['connected']
    archive=export_run(writer.path,tmp_path/'exports',allowed_root=tmp_path/'exports',view_mode='replay')
    with zipfile.ZipFile(archive) as zipped:
        manifest=json.loads(zipped.read('export_manifest.json'))
        assert manifest['view_mode']=='replay' and manifest['mode']=='simulation'
        rows=[json.loads(line) for line in zipped.read('snapshots.jsonl').splitlines()]
        assert rows[0]['validation_metrics']==expected

def test_export_refuses_symlinks_and_truncates_only_incomplete_record(tmp_path):
    writer=RunWriter(tmp_path/'runs',{'mode':'simulation'});writer.close()
    (writer.path/'events.jsonl').write_bytes(b'{"event":"complete"}\n{"event":"unfinished')
    archive=export_run(writer.path,tmp_path/'exports',allowed_root=tmp_path/'exports')
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.read('events.jsonl')==b'{"event":"complete"}\n'
    (writer.path/'escape').symlink_to(tmp_path/'exports')
    with pytest.raises(ValueError,match='symlink'): export_run(writer.path,tmp_path/'exports',allowed_root=tmp_path/'exports')
