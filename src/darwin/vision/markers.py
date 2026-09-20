"""Marker generation and privileged synthetic rendering, never learner features."""
from pathlib import Path
from functools import lru_cache
import cv2
import numpy as np
from darwin.types import Frame

@lru_cache(maxsize=50)
def marker_image(marker_id=7):
    if not 0<=marker_id<50: raise ValueError('invalid marker ID')
    return cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),marker_id,240)

def generate_marker(marker_id,output):
    img=np.full((420,460),255,np.uint8); img[80:320,80:320]=marker_image(marker_id)
    cv2.arrowedLine(img,(340,200),(430,200),0,3,tipLength=.2)
    cv2.putText(img,'FRONT',(335,180),cv2.FONT_HERSHEY_SIMPLEX,.5,0,1)
    cv2.putText(img,f'Darwin DICT_4X4_50 ID {marker_id}',(30,365),cv2.FONT_HERSHEY_SIMPLEX,.6,0,1)
    cv2.putText(img,'Keep white border. Calibrate at marker height.',(15,395),cv2.FONT_HERSHEY_SIMPLEX,.45,0,1)
    p=Path(output); p.parent.mkdir(parents=True,exist_ok=True)
    if not cv2.imwrite(str(p),img): raise IOError('could not write marker')
    return p

def render_frame(x,y,theta,calibration,frame_id,timestamp,hide=False,marker_id=7):
    w,h=calibration.image_size
    # Render four times larger, then antialias: subpixel motion is observable.
    scale=3
    img=np.full((h*scale,w*scale),245,np.uint8)
    if not hide:
        side=.12
        corners=np.array([[-1,1],[1,1],[1,-1],[-1,-1]],float)*side/2
        c,s=np.cos(theta),np.sin(theta)
        corners=corners@np.array([[c,s],[-s,c]])+np.array([x,y])
        dest=calibration.world_to_image(corners).astype(np.float32)*scale
        src=np.array([[0,0],[239,0],[239,239],[0,239]],np.float32)
        hom=cv2.getPerspectiveTransform(src,dest)
        warped=cv2.warpPerspective(marker_image(marker_id),hom,(w*scale,h*scale),flags=cv2.INTER_LINEAR,borderValue=245)
        img=np.minimum(img,warped)
    img=cv2.resize(img,(w,h),interpolation=cv2.INTER_AREA)
    return Frame(frame_id,cv2.cvtColor(img,cv2.COLOR_GRAY2BGR),timestamp,timestamp,'simulation','synthetic')
