"""Latest-frame acquisition; timestamps are receive-only, never implied capture time."""
import threading, time
import cv2
from darwin.types import Frame

class OpenCVCamera:
    def __init__(self,source,width=640,height=480,fps=30,backend='webcam'):
        self.source=source; self.width=width; self.height=height; self.fps=fps; self.backend=backend
        self._latest=None; self._stop=threading.Event(); self._thread=None; self.error=None; self._cap=None
    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._cap=cv2.VideoCapture(self.source)
        if not self._cap.isOpened(): self._cap.release(); raise RuntimeError(f'{self.backend} camera could not open {self.source}')
        if self.backend=='webcam':
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,self.width); self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT,self.height)
            self._cap.set(cv2.CAP_PROP_FPS,self.fps); self._cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
        self._stop.clear(); self._thread=threading.Thread(target=self._read,daemon=True); self._thread.start()
    def _read(self):
        count=0
        while not self._stop.is_set():
            ok,img=self._cap.read()
            if not ok: self.error='end_of_video' if self.backend=='video' else 'camera_read_failed'; break
            count+=1; self._latest=Frame(count,img,None,time.monotonic(),self.backend,'receive_only')
            if self.backend=='video': self._stop.wait(1/self.fps)
    def latest_frame(self): return self._latest
    def close(self):
        self._stop.set()
        if self._thread: self._thread.join(.5)
        if self._cap: self._cap.release()

class VideoCamera(OpenCVCamera):
    def __init__(self,path,**kwargs): super().__init__(path,backend='video',**kwargs)
