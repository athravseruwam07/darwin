import time
import cv2
import numpy as np
import pytest
from darwin.types import Frame
from darwin.vision.calibration import Calibration
from darwin.vision.markers import marker_image
from darwin.vision.obstacles import ObstacleDetector

def cal(): return Calibration.from_corners([(0,0),(399,0),(399,299),(0,299)],2.,1.5,(400,300))
def frm(image,frame_id=1):
    now=time.monotonic(); return Frame(frame_id,image,now,now)

def test_detects_observed_blobs_in_metric_coordinates():
    image=np.full((300,400,3),235,np.uint8); cv2.circle(image,(100,180),24,(0,0,220),-1); cv2.rectangle(image,(260,70),(320,110),(35,35,35),-1)
    found=ObstacleDetector(min_area_px=250).detect(frm(image),cal())
    assert len(found)==2 and [o.obstacle_id for o in found]==['f1-o0','f1-o1']
    circle=min(found,key=lambda o:o.center_m[0]); assert circle.center_m==pytest.approx((100/399*2,(299-180)/299*1.5),abs=.02)
    assert circle.radius_m==pytest.approx(24/399*2,abs=.02) and 0<circle.confidence<=1

def test_explicit_marker_region_is_excluded():
    image=np.full((300,400,3),235,np.uint8); corners=np.array([[150,110],[230,110],[230,190],[150,190]],np.float32)
    cv2.rectangle(image,(150,110),(230,190),(0,0,0),-1); cv2.circle(image,(330,230),18,(255,0,0),-1)
    found=ObstacleDetector(min_area_px=150).detect(frm(image,8),cal(),robot_marker_corners=corners)
    assert len(found)==1 and found[0].center_m[0]>1.5

def test_detected_aruco_marker_is_automatically_excluded():
    image=np.full((300,400,3),235,np.uint8); raw=cv2.resize(marker_image(7),(80,80),interpolation=cv2.INTER_NEAREST)
    marker=cv2.copyMakeBorder(raw,10,10,10,10,cv2.BORDER_CONSTANT,value=255)
    image[100:200,140:240]=cv2.cvtColor(marker,cv2.COLOR_GRAY2BGR); cv2.circle(image,(320,220),18,(0,0,220),-1)
    found=ObstacleDetector(min_area_px=150).detect(frm(image),cal())
    assert len(found)==1 and found[0].center_m[0]>1.5

@pytest.mark.parametrize('image',[None,np.empty((0,0,3),np.uint8)])
def test_invalid_frames_are_empty(image): assert ObstacleDetector().detect(frm(image) if image is not None else None,cal())==[]

def test_noise_rejection_and_json_types():
    image=np.full((300,400,3),235,np.uint8); image[30:33,30:33]=(0,255,0); cv2.circle(image,(200,150),20,(0,180,180),-1)
    found=ObstacleDetector(min_area_px=200).detect(frm(image),cal()); assert len(found)==1
    payload=found[0].to_dict(); assert all(isinstance(v,float) for v in payload['center_m']) and all(isinstance(v,list) for v in payload['polygon_m'])
