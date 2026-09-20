"""Optional DepthAI v3 adapter. Device streaming is hardware-unverified.

API: https://docs.luxonis.com/software-v3/depthai/examples/camera/camera_multiple_outputs.md
Receive-only timestamps deliberately require measured buffering bound for control.
"""
import threading, time
from darwin.types import Frame

class OakCamera:
    def __init__(self,width=640,height=480,fps=30):
        self.width=width; self.height=height; self.fps=fps; self._latest=None
        self._pipeline=None; self._thread=None; self._stop=threading.Event(); self.error=None
    def start(self):
        import depthai as dai
        if int(dai.__version__.split('.')[0])!=3: raise RuntimeError('OAK adapter requires DepthAI v3')
        self._pipeline=dai.Pipeline()
        camera=self._pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        output=camera.requestOutput(size=(self.width,self.height),type=dai.ImgFrame.Type.BGR888p,resizeMode=dai.ImgResizeMode.CROP,fps=self.fps)
        self._queue=output.createOutputQueue(maxSize=1,blocking=False)
        self._pipeline.start(); self._stop.clear()
        self._thread=threading.Thread(target=self._read,daemon=True); self._thread.start()
    def _read(self):
        try:
            while not self._stop.is_set() and self._pipeline.isRunning():
                frame=self._queue.tryGet()
                if frame is not None:
                    self._latest=Frame(frame.getSequenceNum(),frame.getCvFrame(),None,time.monotonic(),'oak','receive_only')
                else: self._stop.wait(.002)
        except Exception as exc: self.error=str(exc)
    def latest_frame(self): return self._latest
    def close(self):
        self._stop.set()
        if self._thread: self._thread.join(.5)
        if self._pipeline: self._pipeline.stop(); self._pipeline.wait()
