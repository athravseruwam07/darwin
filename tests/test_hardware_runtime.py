"""Hardware-mode integration using generated webcam frames and private PTYs only.

These tests never enumerate/open a physical serial port or camera.
"""
from dataclasses import replace
import time
import pytest
from darwin.config import Config
from darwin.io.fake_serial import FakeTransport
from darwin.runtime import Runtime
from darwin.safety import SafetyViolation
from darwin.types import RequestedAction
from darwin.vision.calibration import Calibration
from darwin.vision.markers import render_frame


class GeneratedWebcam:
    def __init__(self,calibration,*,delay=0.,moving=False,fail_start=False,frozen=False):
        self.calibration=calibration; self.delay=delay; self.moving=moving
        self.fail_start=fail_start; self.frozen=frozen; self.started=False; self.closed=False
        self.count=0; self.frame=None; self.created=0.
    def start(self):
        self.started=True
        if self.fail_start: raise RuntimeError('injected partial camera startup failure')
    def latest_frame(self):
        if not self.started or self.closed: return None
        now=time.monotonic()
        if self.frame is not None and (self.frozen or now-self.created<.025): return self.frame
        self.count+=1; self.created=now
        x=(.48 if self.count%2 else .52) if self.moving else .5
        f=render_frame(x,.5,0,self.calibration,self.count,now-self.delay)
        self.frame=replace(f,source='webcam',captured_at=None,received_at=now-self.delay,timestamp_quality='receive_only')
        return self.frame
    def close(self): self.closed=True


@pytest.fixture
def hardware_factory(monkeypatch,tmp_path):
    calibration=Calibration.from_corners([(0,0),(639,0),(639,479),(0,479)],1,1,(640,480),camera_id='webcam')
    path=tmp_path/'calibration.json'; calibration.save(path)
    serials=[]; cameras=[]; runtimes=[]; camera_options={}
    def make_serial(*args,**kwargs):
        transport=FakeTransport(ack_timeout_ms=60); serials.append(transport); return transport
    def make_camera(config):
        camera=GeneratedWebcam(calibration,**camera_options); cameras.append(camera); return camera
    monkeypatch.setattr('darwin.io.serial_link.SerialTransport',make_serial)
    monkeypatch.setattr('darwin.io.camera.make_camera',make_camera)
    def create(**overrides):
        config=Config(mode='hardware',camera_backend='webcam',serial_port='TEST_PTY_ONLY',calibration_path=str(path),hardware_confirmed=True,timestamp_bound_ms=20,measured_probe_bound_m=.04,operator_lease_ms=5000)
        runtime=Runtime(replace(config,**overrides),realtime=False,run_root=tmp_path/'runs')
        runtimes.append(runtime); return runtime
    yield create,camera_options,serials,cameras
    for runtime in runtimes: runtime.close()
    for serial in serials: serial.shutdown()


def motor_writes(transport):
    return [data for data in transport.endpoint.commands if b'ARM\n' in data or b'M ' in data]


def begin_internal_episode(runtime):
    runtime._cancel.clear()
    return runtime.safety.start('integration-test',runtime.now)


def test_connect_and_reconnect_disarmed_invalidates_model_and_data(hardware_factory):
    create,options,serials,cameras=hardware_factory
    runtime=create(); runtime.command('connect')
    old_actuator=runtime.actuator; old_camera=runtime.camera; old_transport=runtime.transport
    assert runtime.state=='DISARMED' and not runtime.safety.active and runtime.pose.valid
    assert not motor_writes(old_transport)
    runtime.model_ready=True; runtime.frozen_model=object(); runtime.samples=[object()]
    runtime.heldout=[object()]; runtime.metrics={'old':1}; runtime._audit_index=7; runtime.last_receipt=object()
    runtime.command('connect')
    assert runtime.actuator is not old_actuator and old_camera.closed
    assert not old_transport.health['connected']
    assert not runtime.model_ready and runtime.frozen_model is None and runtime.samples==[] and runtime.heldout==[]
    assert runtime.metrics=={} and runtime.last_receipt is None and runtime._audit_index==0
    assert runtime.state=='DISARMED' and not runtime.safety.active
    assert runtime.frame is not old_camera.frame and runtime.pose.valid
    assert all(not motor_writes(t) for t in serials)
    with pytest.raises(ValueError,match='validated model'): runtime.command('navigate',{'owner_id':'test'})


def test_partial_camera_failure_closes_camera_and_transport(hardware_factory):
    create,options,serials,cameras=hardware_factory
    options['fail_start']=True; runtime=create()
    with pytest.raises(RuntimeError,match='partial camera'): runtime.command('connect')
    assert cameras[-1].closed and not serials[-1].health['connected']
    assert not runtime._hardware_connected and runtime.state=='DISARMED'
    assert runtime.pose is None and not motor_writes(serials[-1])


def test_receive_age_plus_measured_capture_bound_rejects_start(hardware_factory):
    create,options,serials,cameras=hardware_factory
    options['delay']=.09
    runtime=create(timestamp_bound_ms=80); runtime.command('connect')
    assert runtime.pose.valid
    with pytest.raises(SafetyViolation,match='stale frame'): runtime.command('start-calibration',{'owner_id':'test'})
    assert not runtime.safety.active and not motor_writes(serials[-1])


def test_missing_measured_probe_bound_rejects_start(hardware_factory):
    create,options,serials,cameras=hardware_factory
    runtime=create(measured_probe_bound_m=None); runtime.command('connect')
    with pytest.raises(SafetyViolation,match='measured maximum probe'): runtime.command('start-calibration',{'owner_id':'test'})
    assert not runtime.safety.active and not motor_writes(serials[-1])


def test_settling_requires_distinct_fresh_observations(hardware_factory):
    create,options,serials,cameras=hardware_factory
    options['frozen']=True
    runtime=create(); runtime.command('connect'); generation=begin_internal_episode(runtime)
    with pytest.raises(SafetyViolation): runtime._wait_stationary(generation)
    assert not motor_writes(serials[-1])


def test_moving_observations_never_unlock_pulse(hardware_factory):
    create,options,serials,cameras=hardware_factory
    options['moving']=True
    runtime=create(); runtime.command('connect'); generation=begin_internal_episode(runtime)
    with pytest.raises(SafetyViolation,match='not measurably settled'):
        runtime._pulse(RequestedAction('moving',(0.5,0.5),120),generation,exploration=True)
    assert not motor_writes(serials[-1])


def test_stationary_gate_then_full_hardware_adapter_pulse(hardware_factory):
    create,options,serials,cameras=hardware_factory
    runtime=create(); runtime.command('connect'); generation=begin_internal_episode(runtime)
    started=time.monotonic(); runtime._wait_stationary(generation)
    assert time.monotonic()-started>=runtime.config.stationary_window_s*.8
    assert not motor_writes(serials[-1])
    sample=runtime._pulse(RequestedAction('pty-pulse',(0.5,-0.5),120),generation,exploration=True)
    assert sample.valid and runtime.last_receipt.accepted
    assert any(b'M ' in data for data in motor_writes(serials[-1]))
    assert not serials[-1].endpoint.firmware.armed and serials[-1].endpoint.firmware.outputs==(0,0)
    assert serials[-1].health['error'] is None

def test_calibration_camera_identity_mismatch_prevents_motion(hardware_factory):
    create,options,serials,cameras=hardware_factory
    runtime=create(); runtime.command('connect')
    runtime.calibration=replace(runtime.calibration,camera_id='oak')
    runtime._observe()
    assert not runtime.pose.valid and runtime.pose.invalid_reason=='calibration_camera_changed'
    with pytest.raises(SafetyViolation,match='tracking invalid'): runtime.command('start-calibration',{'owner_id':'test'})
    assert not motor_writes(serials[-1])


def test_idle_firmware_reset_latches_until_reconnect(hardware_factory):
    create,options,serials,cameras=hardware_factory
    runtime=create(); runtime.command('connect')
    serials[-1].endpoint._emit('DARWIN_FW 1')
    deadline=time.monotonic()+.5
    while runtime._healthy() and time.monotonic()<deadline: time.sleep(.005)
    assert not runtime._healthy()
    with pytest.raises(SafetyViolation,match='transport'): runtime.command('start-calibration',{'owner_id':'test'})
    assert not motor_writes(serials[-1])
    runtime.command('connect')
    assert runtime._healthy() and not runtime.safety.active and runtime.state=='DISARMED'
    assert not runtime.model_ready and not motor_writes(serials[-1])


def test_tracking_loss_during_actual_pty_pulse_stops_and_rejects(hardware_factory):
    import threading
    create,options,serials,cameras=hardware_factory
    runtime=create(); runtime.command('connect'); generation=begin_internal_episode(runtime)
    runtime._wait_stationary(generation); errors=[]
    def pulse():
        try: runtime._pulse(RequestedAction('lost-frame',(0.5,.5),120),generation,exploration=True)
        except SafetyViolation as exc: errors.append(str(exc))
    thread=threading.Thread(target=pulse); thread.start()
    deadline=time.monotonic()+.5
    while serials[-1].endpoint.firmware.outputs==(0,0) and time.monotonic()<deadline: time.sleep(.002)
    assert serials[-1].endpoint.firmware.outputs!=(0,0)
    cameras[-1].delay=.3
    thread.join(1)
    assert not thread.is_alive() and errors
    assert not serials[-1].endpoint.firmware.armed and serials[-1].endpoint.firmware.outputs==(0,0)
    assert not runtime.last_receipt.accepted and not runtime.safety.active
    writes=len(motor_writes(serials[-1])); time.sleep(.04)
    assert len(motor_writes(serials[-1]))==writes

@pytest.mark.parametrize('dimensions,resolution',[((.5,.5),(640,480)),((1.,1.),(800,600))])
def test_saved_calibration_must_match_config_before_run_or_device_creation(monkeypatch,tmp_path,dimensions,resolution):
    width,height=resolution
    cal=Calibration.from_corners([(0,0),(width-1,0),(width-1,height-1),(0,height-1)],*dimensions,resolution,camera_id='webcam')
    path=tmp_path/'mismatch.json'; cal.save(path)
    def forbidden(*args,**kwargs): raise AssertionError('device constructor must not run')
    monkeypatch.setattr('darwin.io.serial_link.SerialTransport',forbidden)
    monkeypatch.setattr('darwin.io.camera.make_camera',forbidden)
    run_root=tmp_path/'runs'
    config=Config(mode='hardware',camera_backend='webcam',calibration_path=str(path))
    with pytest.raises(ValueError,match='calibration.*(dimensions|resolution)'):
        Runtime(config,run_root=run_root)
    assert not run_root.exists()
