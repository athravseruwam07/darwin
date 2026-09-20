"""Planar metric calibration. Reference corners MUST be at marker plane height."""
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib, json, math
import cv2
import numpy as np

@dataclass(frozen=True)
class Calibration:
    points_px: tuple
    width_m: float
    height_m: float
    image_size: tuple
    camera_id: str = 'simulation'
    heading_offset_rad: float = 0.
    marker_height_m: float = 0.

    def __post_init__(self):
        p = np.asarray(self.points_px, dtype=float)
        if p.shape != (4,2) or not np.isfinite(p).all(): raise ValueError('four finite TL TR BR BL corners required')
        if not all(math.isfinite(v) for v in (self.width_m,self.height_m,self.heading_offset_rad,self.marker_height_m)) or min(self.width_m,self.height_m)<=0 or self.marker_height_m<0: raise ValueError('invalid dimensions')
        if len(self.image_size)!=2 or min(self.image_size)<2: raise ValueError('invalid image size')
        if np.any(p<0) or np.any(p>=np.asarray(self.image_size)): raise ValueError('corners outside image')
        edges=np.roll(p,-1,axis=0)-p
        crosses=edges[:,0]*np.roll(edges,-1,axis=0)[:,1]-edges[:,1]*np.roll(edges,-1,axis=0)[:,0]
        if not np.all(crosses>1) or abs(cv2.contourArea(p.astype(np.float32)))<100: raise ValueError('corners must be noncrossing clockwise TL TR BR BL with sufficient area')

    @classmethod
    def from_corners(cls, points_px,width_m,height_m,image_size,camera_id='simulation',heading_offset_rad=0,marker_height_m=0):
        return cls(tuple(tuple(float(v) for v in p) for p in points_px),float(width_m),float(height_m),tuple(image_size),camera_id,float(heading_offset_rad),float(marker_height_m))
    @property
    def homography(self):
        world=np.array([[0,self.height_m],[self.width_m,self.height_m],[self.width_m,0],[0,0]],np.float32)
        return cv2.getPerspectiveTransform(np.asarray(self.points_px,np.float32),world)
    def image_to_world(self, points): return self._transform(points,self.homography)
    def world_to_image(self, points): return self._transform(points,np.linalg.inv(self.homography))
    @staticmethod
    def _transform(points,h):
        p=np.asarray(points,dtype=np.float64).reshape(-1,2)
        if not np.isfinite(p).all(): raise ValueError('nonfinite points')
        return cv2.perspectiveTransform(p[None],h)[0]
    @property
    def calibration_id(self): return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()[:16]
    def to_dict(self): return {**asdict(self),'calibration_id':self.calibration_id,'point_order':'TL TR BR BL','reference_plane':'marker height; no parallax correction'}
    @classmethod
    def from_dict(cls,d):
        c=cls.from_corners(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
        if d.get('calibration_id',c.calibration_id)!=c.calibration_id: raise ValueError('calibration identity mismatch')
        return c
    def save(self,path):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(self.to_dict(),indent=2))
    @classmethod
    def load(cls,path): return cls.from_dict(json.loads(Path(path).read_text()))
