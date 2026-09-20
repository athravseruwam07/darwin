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
COMMANDS = {'connect','calibration','target','start-calibration','navigate','stop','scramble','recover','reset-model','export','heartbeat','fault','reset-pose','recenter'}

async def invoke(method, *args):
    if inspect.iscoroutinefunction(method): return await method(*args)
    return await run_in_threadpool(method,*args)

def create_app(runtime):
    app = FastAPI(title='Darwin local robot learning',docs_url='/api/docs')
    app.state.runtime = runtime
    app.mount('/static',StaticFiles(directory=STATIC),name='static')

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
    @app.get('/api/status')
    async def status(): return await invoke(runtime.snapshot)
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
            return await invoke(runtime.command,name,payload)
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
                await socket.send_json(await invoke(runtime.snapshot))
                await asyncio.sleep(.2)
        except (WebSocketDisconnect,RuntimeError): pass
    return app
