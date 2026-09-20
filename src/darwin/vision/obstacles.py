"""Deterministic overhead-camera obstacle extraction."""
from dataclasses import dataclass
import math
from typing import Any, Sequence
import cv2
import numpy as np
from darwin.types import Frame
from .calibration import Calibration

@dataclass(frozen=True)
class DetectedObstacle:
    obstacle_id: str
    center_m: tuple[float,float]
    radius_m: float
    polygon_m: tuple[tuple[float,float],...]
    bounds_m: tuple[float,float,float,float]
    confidence: float
    area_px: float
    def to_dict(self)->dict[str,Any]:
        return {'obstacle_id':self.obstacle_id,'center_m':[float(v) for v in self.center_m],
                'radius_m':float(self.radius_m),'polygon_m':[[float(x),float(y)] for x,y in self.polygon_m],
                'bounds_m':[float(v) for v in self.bounds_m],'confidence':float(self.confidence),'area_px':float(self.area_px)}

class ObstacleDetector:
    """Detect observed saturated/dark blobs; never persists or invents objects."""
    def __init__(self, *, min_area_px=180., max_area_fraction=.35, saturation_threshold=80,
                 dark_value_threshold=135, marker_padding_px=12, polygon_epsilon_fraction=.025,
                 robot_marker_id: int|None=7, marker_dictionary_id=cv2.aruco.DICT_4X4_50):
        if min_area_px<=0 or not 0<max_area_fraction<=1: raise ValueError('invalid obstacle area bounds')
        self.min_area_px=float(min_area_px); self.max_area_fraction=float(max_area_fraction)
        self.saturation_threshold=int(saturation_threshold); self.dark_value_threshold=int(dark_value_threshold)
        self.marker_padding_px=int(marker_padding_px); self.polygon_epsilon_fraction=float(polygon_epsilon_fraction)
        self.robot_marker_id=robot_marker_id
        self._marker_detector=cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(marker_dictionary_id),cv2.aruco.DetectorParameters())

    def detect(self, frame: Frame|None, calibration: Calibration, *, robot_marker_corners: Sequence[Sequence[float]]|np.ndarray|None=None)->list[DetectedObstacle]:
        if frame is None or frame.image_bgr is None or frame.image_bgr.size==0: return []
        image=frame.image_bgr
        if image.ndim!=3 or image.shape[2]!=3 or image.dtype!=np.uint8: return []
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV); saturation=hsv[:,:,1]; value=hsv[:,:,2]
        mask=np.where(((saturation>=self.saturation_threshold)&(value>=35))|(value<=self.dark_value_threshold),255,0).astype(np.uint8)
        marker_corners=robot_marker_corners
        if marker_corners is None and self.robot_marker_id is not None:
            corners,ids,_=self._marker_detector.detectMarkers(image)
            if ids is not None:
                matches=np.flatnonzero(ids.ravel()==self.robot_marker_id)
                if len(matches): marker_corners=corners[int(matches[0])].reshape(-1,2)
        if marker_corners is not None:
            points=np.asarray(marker_corners,np.float32).reshape(-1,2)
            if len(points)>=3 and np.isfinite(points).all():
                marker_mask=np.zeros(mask.shape,np.uint8); cv2.fillConvexPoly(marker_mask,np.rint(points).astype(np.int32),255)
                if self.marker_padding_px>0:
                    size=2*self.marker_padding_px+1; marker_mask=cv2.dilate(marker_mask,np.ones((size,size),np.uint8))
                mask[marker_mask>0]=0
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        maximum=image.shape[0]*image.shape[1]*self.max_area_fraction; candidates=[]
        for contour in contours:
            area=float(cv2.contourArea(contour)); moments=cv2.moments(contour)
            if self.min_area_px<=area<=maximum and moments['m00']>0:
                candidates.append((moments['m10']/moments['m00'],moments['m01']/moments['m00'],contour,area))
        candidates.sort(key=lambda item:(round(item[0],6),round(item[1],6)))
        result=[]
        for center_x,center_y,contour,area in candidates:
            perimeter=float(cv2.arcLength(contour,True)); epsilon=max(1.,perimeter*self.polygon_epsilon_fraction)
            polygon_px=cv2.approxPolyDP(contour,epsilon,True).reshape(-1,2)
            polygon_array=calibration.image_to_world(polygon_px); polygon=tuple((float(x),float(y)) for x,y in polygon_array)
            if len(polygon)<3: continue
            center_array=calibration.image_to_world([(center_x,center_y)])[0]; center=(float(center_array[0]),float(center_array[1]))
            (_, _),radius_px=cv2.minEnclosingCircle(contour)
            radius_points=calibration.image_to_world([(center_x+radius_px,center_y),(center_x,center_y+radius_px)])
            radius=max(math.dist(center,tuple(map(float,radius_points[0]))),math.dist(center,tuple(map(float,radius_points[1]))))
            xs=[p[0] for p in polygon]; ys=[p[1] for p in polygon]
            hull_area=float(cv2.contourArea(cv2.convexHull(contour))); solidity=area/hull_area if hull_area else 0
            confidence=max(0.,min(1.,.65*solidity+.35*min(1.,area/(self.min_area_px*4))))
            result.append(DetectedObstacle(f'f{frame.id}-o{len(result)}',center,float(radius),polygon,
                                           (min(xs),min(ys),max(xs),max(ys)),float(confidence),area))
        return result
