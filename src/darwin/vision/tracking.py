import math
import cv2
import numpy as np
from darwin.types import Pose

class Tracker:
    def __init__(self,marker_id=7,heading_offset_rad=0):
        self.marker_id=marker_id; self.heading_offset_rad=heading_offset_rad
        params=cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod=cv2.aruco.CORNER_REFINE_SUBPIX
        params.cornerRefinementWinSize=4
        params.cornerRefinementMaxIterations=40
        params.cornerRefinementMinAccuracy=.001
        self.detector=cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),params)
    def observe(self,frame,calibration):
        timestamp=frame.captured_at if frame.captured_at is not None else frame.received_at
        def invalid(reason): return Pose(frame.id,timestamp,0.,0.,0.,False,0.,calibration.calibration_id,reason)
        if frame.image_bgr.shape[:2] != (calibration.image_size[1],calibration.image_size[0]): return invalid('calibration_resolution_changed')
        if frame.source != 'simulation' and calibration.camera_id not in (frame.source,frame.source+':default'):
            return invalid('calibration_camera_changed')
        corners,ids,_=self.detector.detectMarkers(frame.image_bgr)
        matches=[] if ids is None else [c for c,i in zip(corners,ids.ravel()) if i==self.marker_id]
        if len(matches)!=1: return invalid('marker_missing' if not matches else 'duplicate_marker')
        px=matches[0].reshape(4,2)
        if abs(cv2.contourArea(px))<100: return invalid('marker_too_small')
        world=calibration.image_to_world(px)
        center=world.mean(axis=0)
        direction=(world[1]-world[0]+world[2]-world[3])/2
        theta=math.atan2(direction[1],direction[0])+self.heading_offset_rad+calibration.heading_offset_rad
        theta=math.atan2(math.sin(theta),math.cos(theta))
        return Pose(frame.id,timestamp,float(center[0]),float(center[1]),theta,True,1.,calibration.calibration_id)
