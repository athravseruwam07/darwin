"""Exact local software workflows; no device access unless explicitly selected."""
from pathlib import Path
import argparse
import importlib.util
import importlib.metadata
import json
import platform
import socket
import sys
import time
from darwin.config import load_config
from darwin.runtime import ROOT

def dump(value): print(json.dumps(value,indent=2,default=str,allow_nan=False),flush=True)

def serve(runtime,port):
    import uvicorn
    from darwin.web.server import create_app
    chosen=port
    for candidate in range(port,min(port+20,65536)):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try: sock.bind(('127.0.0.1',candidate)); chosen=candidate; break
            except OSError: continue
    else: raise RuntimeError('no free localhost port in requested range')
    print(f'DARWIN {runtime.snapshot()["mode"].upper()} http://127.0.0.1:{chosen}',flush=True)
    try: uvicorn.run(create_app(runtime),host='127.0.0.1',port=chosen,log_level='info')
    finally: runtime.close()

def main(argv=None):
    parser=argparse.ArgumentParser(description='Darwin — local observed-motion learning')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    marker=sub.add_parser('marker'); marker.add_argument('--id',type=int,default=7); marker.add_argument('--output',default='reports/robot_marker.png')
    for name in ['simulate','benchmark']:
        p=sub.add_parser(name); p.add_argument('--output',default='reports/'+name); p.add_argument('--observation',choices=['pose','vision'],default='vision' if name=='simulate' else 'pose')
        if name=='simulate': p.add_argument('--seed',type=int,default=42)
        else:
            p.add_argument('--seeds',default='11,22,33,44,55'); p.add_argument('--variants',default='linear,noisy,nonlinear')
    p=sub.add_parser('vision-test'); p.add_argument('--synthetic',action='store_true'); p.add_argument('--output',default='reports/vision')
    p=sub.add_parser('protocol-test'); p.add_argument('--fake',action='store_true')
    for name in ['demo','calibrate']:
        p=sub.add_parser(name); p.add_argument('--mode',choices=['simulation','hardware']); p.add_argument('--config',default='configs/simulation.yaml'); p.add_argument('--ui-port',type=int,default=8770)
    p=sub.add_parser('fit'); p.add_argument('--run',required=True); p.add_argument('--output',required=True)
    p=sub.add_parser('evaluate'); p.add_argument('--run',required=True); p.add_argument('--checkpoint',required=True)
    p=sub.add_parser('replay'); p.add_argument('--run',required=True); p.add_argument('--ui-port',type=int,default=8771)
    p=sub.add_parser('export'); p.add_argument('--run',required=True); p.add_argument('--output',default='reports/exports')
    p=sub.add_parser('camera-test'); p.add_argument('--backend',choices=['oak','webcam','video'],required=True); p.add_argument('--path'); p.add_argument('--index',type=int,default=0)
    p=sub.add_parser('motor-test'); p.add_argument('--port',required=True); p.add_argument('--channel',choices=['A','B']); p.add_argument('--pwm',type=int,default=30); p.add_argument('--pulse-ms',type=int,default=80); p.add_argument('--raised-wheel-confirmed',action='store_true')
    a=parser.parse_args(argv)
    try:
        if a.command=='doctor':
            import cv2,numpy
            from serial.tools import list_ports
            info={'python':sys.version,'executable':sys.executable,'architecture':platform.machine(),'platform':platform.platform(),
                'numpy':numpy.__version__,'opencv':cv2.__version__,'aruco':hasattr(cv2,'aruco'),'default_mode':'simulation',
                'optional_depthai':importlib.metadata.version('depthai') if importlib.util.find_spec('depthai') else 'not installed; simulation unaffected',
                'serial_ports':[{'device':port.device,'description':port.description,'vid':port.vid,'pid':port.pid} for port in list_ports.comports()],
                'device_access':'serial ports enumerated read-only; no serial or camera opened'}
            dump(info)
        elif a.command=='marker':
            from darwin.vision.markers import generate_marker
            dump({'path':str(generate_marker(a.id,a.output))})
        elif a.command=='simulate':
            from darwin.evaluation import simulate
            report=simulate(a.seed,a.output,a.observation); dump({k:v for k,v in report.items() if k!='cases_detail'})
            if not report['passed']: return 1
        elif a.command=='benchmark':
            from darwin.evaluation import benchmark
            report=benchmark([int(s) for s in a.seeds.split(',')],a.output,a.variants.split(','),a.observation)
            dump({k:v for k,v in report.items() if k!='cases_detail'})
            if not report['passed']: return 1
        elif a.command=='vision-test':
            if not a.synthetic: raise ValueError('select --synthetic; physical camera verification is camera-test')
            from darwin.vision.validation import run_synthetic_test
            dump(run_synthetic_test(a.output))
        elif a.command=='protocol-test':
            if not a.fake: raise ValueError('select --fake; no device chosen automatically')
            from darwin.io.fake_serial import run_protocol_tests
            dump(run_protocol_tests())
        elif a.command in {'demo','calibrate'}:
            from darwin.runtime import Runtime
            config=load_config(a.config,mode=a.mode,port=a.ui_port)
            runtime=Runtime(config)
            if a.command=='calibrate' and config.mode=='hardware':
                from darwin.io.camera import make_camera
                runtime.camera=make_camera(config); runtime.camera.start()
            serve(runtime,a.ui_port)
        elif a.command=='fit':
            from darwin.recording.replay import load_transitions
            from darwin.learning.model import MotionModel
            transitions=load_transitions(a.run)
            # Last complete calibration episode only; heldout/navigation are never fit.
            candidates=[t for t in transitions if t.episode_id.endswith(':train') and t.valid]
            if not candidates: raise ValueError('run contains no designated training trials')
            episode=candidates[-1].episode_id
            model=MotionModel(); model.fit([t for t in candidates if t.episode_id==episode]); model.save(a.output)
            dump({'checkpoint':a.output,'model_id':model.model_id,'training_count':len(model.training_action_ids)})
        elif a.command=='evaluate':
            from darwin.recording.replay import load_transitions
            from darwin.learning.model import MotionModel,evaluate
            model=MotionModel.load(a.checkpoint); rows=[t for t in load_transitions(a.run) if t.episode_id.endswith(':heldout') and t.valid]
            if not rows: raise ValueError('run contains no designated heldout trials')
            episode=rows[-1].episode_id
            dump(evaluate(model,[t for t in rows if t.episode_id==episode]))
        elif a.command=='replay':
            from darwin.recording.replay import ReplayRuntime
            serve(ReplayRuntime(a.run),a.ui_port)
        elif a.command=='export':
            from darwin.recording.export import export_run
            dump({'path':str(export_run(a.run,a.output))})
        elif a.command=='camera-test':
            from darwin.io.camera import make_camera
            from darwin.config import Config
            camera=make_camera(Config(mode='hardware',camera_backend=a.backend,camera_path=a.path,camera_index=a.index))
            try:
                camera.start(); deadline=time.monotonic()+5; frame=None
                while time.monotonic()<deadline:
                    frame=camera.latest_frame()
                    if frame is not None: break
                    time.sleep(.02)
                if frame is None: raise RuntimeError('no frame within five seconds')
                dump({'frame_id':frame.id,'shape':frame.image_bgr.shape,'source':frame.source,'timestamp_quality':frame.timestamp_quality,'received_at':frame.received_at,'captured_at':frame.captured_at,'hardware_motion':'never armed'})
            finally: camera.close()
        elif a.command=='motor-test':
            from darwin.io.serial_link import SerialTransport
            if a.channel and not a.raised_wheel_confirmed: raise ValueError('motion requires --raised-wheel-confirmed after team readiness')
            if not 0<abs(a.pwm)<=60 or not 20<=a.pulse_ms<200: raise ValueError('invalid conservative pulse bounds')
            transport=SerialTransport(a.port)
            try:
                transport.connect(); version=transport.handshake(); transport.stop(); dump({'handshake':version,'state':'DISARMED'})
                if a.channel:
                    transport.arm(); transport.send_motor(1,a.pwm if a.channel=='A' else 0,a.pwm if a.channel=='B' else 0,200)
                    time.sleep(a.pulse_ms/1000); transport.stop(); dump({'pulse_completed':a.channel,'physical_response':'operator must verify'})
            finally: transport.close()
    except (ValueError,RuntimeError,OSError,ImportError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr); return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
