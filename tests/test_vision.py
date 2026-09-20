import math, time
import cv2
import numpy as np
import pytest
from darwin.vision.calibration import Calibration
from darwin.vision.markers import render_frame, generate_marker
from darwin.vision.tracking import Tracker
from darwin.vision.validation import run_synthetic_test
from darwin.types import Frame

@pytest.fixture
def cal(): return Calibration.from_corners([(20,10),(610,30),(625,465),(10,440)],1,1,(640,480))

def test_metric_inverse_and_y(cal,tmp_path):
    points=np.array([[0,0],[.25,.8],[1,1]])
    assert np.allclose(cal.image_to_world(cal.world_to_image(points)),points)
    assert cal.image_to_world([[20,10]])[0,1]==pytest.approx(1)
    cal.save(tmp_path/'cal.json'); assert Calibration.load(tmp_path/'cal.json').calibration_id==cal.calibration_id

@pytest.mark.parametrize('points',[[(0,0),(600,400),(600,0),(0,400)],[(0,0)]*4,[(0,0),(600,0),(600,400),(0,float('nan'))]])
def test_bad_corners(points):
    with pytest.raises(ValueError): Calibration.from_corners(points,1,1,(640,480))

def test_actual_marker_and_heading_offset(cal,tmp_path):
    image=cv2.imread(str(generate_marker(7,tmp_path/'marker.png')))
    assert 7 in cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)).detectMarkers(image)[1]
    frame=render_frame(.5,.5,math.pi-.01,cal,1,3.)
    pose=Tracker(heading_offset_rad=.2).observe(frame,cal)
    assert pose.valid and abs(pose.theta_rad-(-math.pi+.19))<.02

def test_occlusion_and_stale_identity(cal):
    tracker=Tracker(); frame=render_frame(.5,.5,0,cal,1,1.)
    a=tracker.observe(frame,cal); b=tracker.observe(frame,cal)
    assert a.observed_at==b.observed_at==1. and a.frame_id==b.frame_id
    assert not tracker.observe(render_frame(.5,.5,0,cal,2,2.,hide=True),cal).valid
    small=Frame(3,np.zeros((100,100,3),np.uint8),3.,3.)
    assert tracker.observe(small,cal).invalid_reason=='calibration_resolution_changed'

def test_synthetic_sweep(tmp_path): assert run_synthetic_test(tmp_path)['passed']

def test_recorded_video_latest_only(cal,tmp_path):
    from darwin.io.video import VideoCamera
    p=tmp_path/'test.avi'; writer=cv2.VideoWriter(str(p),cv2.VideoWriter_fourcc(*'MJPG'),30,(640,480))
    for i in range(5): writer.write(render_frame(.4+i*.01,.5,0,cal,i,i/30).image_bgr)
    writer.release(); camera=VideoCamera(str(p),fps=30); camera.start()
    deadline=time.monotonic()+2
    while not camera.error and time.monotonic()<deadline: time.sleep(.01)
    frame=camera.latest_frame(); assert frame.id==5 and frame.timestamp_quality=='receive_only' and frame.captured_at is None
    assert camera.latest_frame() is frame
    camera.close()
