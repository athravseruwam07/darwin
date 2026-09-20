from dataclasses import replace
import threading, time
import pytest
from darwin.io.fake_serial import FakeTransport, FakeFirmware, run_protocol_tests
from darwin.io.actuator import HardwareActuator
from darwin.io.serial_link import ProtocolError
from darwin.config import Config
from darwin.types import RequestedAction

def test_protocol_suite(): assert run_protocol_tests()['passed']

@pytest.fixture
def transport():
    t=FakeTransport(ack_timeout_ms=40); t.connect(); yield t; t.shutdown()

def action(): return RequestedAction('test',(1.,-.6),120)

def test_normal_pulse_explicit_stop(transport):
    a=HardwareActuator(transport,replace(Config(),settle_ms=10)); start=time.monotonic()
    result=a.execute(action()); elapsed=time.monotonic()-start
    assert result.accepted and .12<=elapsed<.3
    assert not transport.endpoint.firmware.armed and transport.endpoint.firmware.outputs==(0,0)
    assert sum(b'M ' in c for c in transport.endpoint.commands)==1

def test_stop_interrupts_and_no_later_write(transport):
    a=HardwareActuator(transport,Config()); result=[]
    worker=threading.Thread(target=lambda:result.append(a.execute(action()))); worker.start()
    deadline=time.monotonic()+1
    while transport.endpoint.firmware.outputs==(0,0) and time.monotonic()<deadline: time.sleep(.001)
    a.stop(); after=len(transport.endpoint.commands); worker.join(1)
    assert not result[0].accepted and not transport.endpoint.firmware.armed
    assert not any(b'M ' in c or b'ARM\n' in c for c in transport.endpoint.commands[after:])

def test_safety_checked_during_pulse(transport):
    start=time.monotonic()
    a=HardwareActuator(transport,Config(),lambda:'tracking stale' if time.monotonic()-start>.025 else None)
    result=a.execute(action())
    assert not result.accepted and 'tracking stale' in result.error
    assert time.monotonic()-start<.12 and not transport.endpoint.firmware.armed

def test_stop_while_arm_ack_pending_blocks_motor(transport):
    original=transport.arm; entered=threading.Event(); resume=threading.Event()
    def arm(): original(); entered.set(); resume.wait(.5)
    transport.arm=arm
    a=HardwareActuator(transport,Config()); results=[]
    worker=threading.Thread(target=lambda:results.append(a.execute(action()))); worker.start(); assert entered.wait(.5)
    stopper=threading.Thread(target=a.stop); stopper.start(); time.sleep(.01); resume.set()
    worker.join(1); stopper.join(1)
    assert not results[0].accepted
    assert not any(b'M ' in c for c in transport.endpoint.commands)

@pytest.mark.parametrize('fault',['invalid_ack','missing_ack','reset','disconnect'])
def test_fault_latches_no_rearm(transport,fault):
    transport.arm(); transport.fault(fault)
    with pytest.raises(ProtocolError): transport.send_motor(1,20,20,100)
    with pytest.raises(ProtocolError): transport.arm()

def test_zero_every_hardware_map(transport):
    a=HardwareActuator(transport,replace(Config(),settle_ms=0))
    for name in ['identity','swap','reverse_one','reverse_both','unequal']:
        a.scramble(name); r=a.execute(RequestedAction(name,(0.,0.),20))
        assert r.accepted and a.audit_records[-1]['physical_pwm']==[0,0]

def test_explicit_left_and_right_direction_reversal(transport):
    actuator=HardwareActuator(transport,replace(Config(),settle_ms=0,pwm_scale=80))
    for name,expected in [('reverse_left',[-80,40]),('reverse_right',[80,-40]),('reverse_both',[-80,-40])]:
        actuator.scramble(name)
        result=actuator.execute(RequestedAction(name,(1.,.5),20))
        assert result.accepted
        assert actuator.audit_records[-1]['physical_pwm']==expected

def test_hardware_scramble_accepts_shared_weak_wheel_name(transport):
    actuator=HardwareActuator(transport,replace(Config(),settle_ms=0,pwm_scale=90,max_pwm=90))
    actuator.scramble('weaken_left')
    actuator.execute(RequestedAction('weak',(1.,1.),20))
    assert actuator.audit_records[-1]['physical_pwm']==[63,90]

def test_reordered_sequences_and_stop_disarms():
    f=FakeFirmware(); f.line('ARM'); f.line('M 10 30 30 100')
    assert f.line('M 9 30 30 100')=='ERR DISARMED'
    assert f.line('M 11 30 30 100')=='ERR DISARMED'
    assert f.line('STOP')=='OK STOP' and not f.armed

def test_unexpected_watchdog_is_fault_not_normal_pulse(transport):
    # Real PTY firmware expires early, while ordinary ACK acceptance still works.
    original=transport.send_motor
    def early_expiry(*args):
        ack=original(*args)
        transport.endpoint.firmware.expires=time.monotonic()+.015
        return ack
    transport.send_motor=early_expiry
    a=HardwareActuator(transport,replace(Config(),settle_ms=0))
    result=a.execute(action())
    assert not result.accepted and 'TIMEOUT' in result.error
    assert transport.health['error'] and not transport.endpoint.firmware.armed
    with pytest.raises(ProtocolError): transport.arm()

def test_scheduled_stop_does_not_hide_prior_timeout(transport):
    transport.arm(); transport.send_motor(1,30,30,20); time.sleep(.04)
    transport.stop()
    assert transport.health['error'] and 'TIMEOUT' in transport.health['error']
    assert not transport.endpoint.firmware.armed
    with pytest.raises(ProtocolError): transport.arm()

def test_callback_fault_during_settle_invalidates_sample(transport):
    start=time.monotonic()
    a=HardwareActuator(transport,Config(),lambda:'camera lost during settle' if time.monotonic()-start>.15 else None)
    result=a.execute(action())
    assert not result.accepted and 'camera lost' in result.error
    assert not transport.endpoint.firmware.armed

def test_normal_pulse_has_no_timeout_event(transport):
    a=HardwareActuator(transport,replace(Config(),settle_ms=100))
    result=a.execute(action())
    assert result.accepted and transport.health['error'] is None
    assert not transport.endpoint.firmware.armed

def test_embedded_carriage_return_cannot_form_arm_or_number():
    f=FakeFirmware()
    assert f.feed(b'AR\rM\n')==['ERR DISARMED'] and not f.armed
    f.feed(b'ARM\r\n')
    assert f.feed(b'M 1 0 0 1\r00\n')==['ERR DISARMED'] and not f.armed

def test_stop_error_even_if_connection_survives(transport):
    original=transport.stop
    def stop_fault():
        original(); transport.health['error']='unexpected reset during STOP'
    transport.stop=stop_fault
    a=HardwareActuator(transport,replace(Config(),settle_ms=0))
    result=a.execute(action())
    assert not result.accepted and 'reset' in result.error
