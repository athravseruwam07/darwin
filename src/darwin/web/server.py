"""HTTP transports commands to the supervisor; it never accesses actuators."""
import asyncio
import inspect
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

STATIC = Path(__file__).with_name('static')
ROOT = Path(__file__).resolve().parents[3]
COMMANDS = {'connect','calibration','target','route','start-calibration','navigate','navigate-route','stop','scramble','recover','adaptation-challenge','inject-mutation','reset-model','export','heartbeat','fault','reset-pose','recenter'}

async def invoke(method, *args):
    if inspect.iscoroutinefunction(method): return await method(*args)
    return await run_in_threadpool(method,*args)

def make_brain(runtime):
    """Narration is optional: without a runtime config the panel stays inert."""
    from darwin.cognition.brain import Brain
    config = getattr(runtime,'config',None)
    if config is None: return Brain(enabled=False)
    return Brain.from_config(config,env_file=ROOT/'.env')

def create_app(runtime, brain=None):
    app = FastAPI(title='Darwin local robot learning',docs_url='/api/docs')
    app.state.runtime = runtime
    app.state.brain = brain if brain is not None else make_brain(runtime)
    app.mount('/static',StaticFiles(directory=STATIC),name='static')
    try: runtime_config = runtime.public_config()
    except Exception: runtime_config = None

    @app.middleware('http')
    async def local_mutations(request, call_next):
        # Localhost binding alone does not stop a hostile website from POSTing.
        origin = request.headers.get('origin')
        if request.method == 'POST' and origin and origin not in {
            f'http://{request.headers.get("host")}', f'https://{request.headers.get("host")}'
        }:
            return Response('Cross-origin commands refused',status_code=403)
        return await call_next(request)

    @app.get('/')
    async def index(): return FileResponse(STATIC/'index.html')
    @app.get('/lab')
    async def lab(): return FileResponse(STATIC/'index.html')
    def observe(snapshot):
        # Narration is best effort and must never break or slow a telemetry read.
        try: app.state.brain.observe(snapshot,runtime_config)
        except Exception: pass
        return snapshot

    @app.get('/api/status')
    async def status(): return observe(await invoke(runtime.snapshot))
    @app.get('/api/brain')
    async def brain_state(): return app.state.brain.snapshot()
    @app.get('/api/brain/voice/{thought_id}')
    async def brain_voice(thought_id:str):
        audio = app.state.brain.audio(thought_id)
        return Response(audio or b'',media_type='audio/mpeg',status_code=200 if audio else 204,
                        headers={'Cache-Control':'no-store'})
    @app.post('/api/brain/voice')
    async def brain_voice_toggle(request:Request):
        body = await request.body()
        payload = json.loads(body) if body else {}
        if not isinstance(payload,dict) or not isinstance(payload.get('enabled',True),bool):
            raise HTTPException(422,'enabled must be boolean')
        return {'ok':True,'voice_enabled':app.state.brain.set_voice(payload.get('enabled',True))}
    @app.get('/api/config')
    async def config(): return await invoke(runtime.public_config)
    @app.get('/api/runs')
    async def runs(): return await invoke(runtime.list_runs)
    @app.get('/api/frame')
    async def frame():
        data = await invoke(runtime.latest_jpeg)
        return Response(data or b'',media_type='image/jpeg',status_code=200 if data else 204,headers={'Cache-Control':'no-store'})

    async def dispatch(name,request):
        if int(request.headers.get('content-length','0')) > 32768: raise HTTPException(413,'Command too large')
        try:
            body = await request.body()
            if len(body)>32768: raise ValueError('Command too large')
            payload = json.loads(body) if body else {}
            if not isinstance(payload,dict): raise ValueError('Payload must be an object')
            result = await invoke(runtime.command,name,payload)
            try: app.state.brain.operator_action(name,payload)
            except Exception: pass
            return result
        except (ValueError, TypeError, KeyError) as exc: raise HTTPException(422,str(exc)) from exc
        except RuntimeError as exc: raise HTTPException(409,str(exc)) from exc

    @app.post('/api/replay/{action}')
    async def replay(action:str,request:Request):
        if action not in {'seek','play'}: raise HTTPException(404,'Unknown replay command')
        return await dispatch('replay-'+action,request)
    @app.post('/api/{command}')
    async def command(command:str,request:Request):
        if command not in COMMANDS: raise HTTPException(404,'Unknown command')
        return await dispatch(command,request)
    @app.websocket('/api/events')
    async def events(socket:WebSocket):
        origin=socket.headers.get('origin')
        if origin and origin not in {f'http://{socket.headers.get("host")}',f'https://{socket.headers.get("host")}'}:
            await socket.close(code=1008); return
        await socket.accept()
        try:
            while True:
                await socket.send_json(observe(await invoke(runtime.snapshot)))
                await asyncio.sleep(.2)
        except (WebSocketDisconnect,RuntimeError): pass
    return app
