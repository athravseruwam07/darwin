from pathlib import Path
import json, math
import cv2
import numpy as np
from .calibration import Calibration
from .tracking import Tracker
from .markers import render_frame

def run_synthetic_test(output):
    out=Path(output); out.mkdir(parents=True,exist_ok=True)
    tracker=Tracker(); errors=[]; failures=[]; count=0
    calibrations=[Calibration.from_corners([(0,0),(639,0),(639,479),(0,479)],1,1,(640,480)),Calibration.from_corners([(110,30),(590,70),(630,460),(25,420)],1,1,(640,480))]
    for ci,cal in enumerate(calibrations):
        for x,y in [(0.25,.25),(.5,.5),(.7,.65)]:
            for theta in np.linspace(-math.pi+.01,math.pi-.01,25):
                count+=1; frame=render_frame(x,y,theta,cal,count,count*.1)
                pose=tracker.observe(frame,cal)
                if not pose.valid: failures.append([ci,x,y,float(theta),pose.invalid_reason]); continue
                errors.append([math.hypot(pose.x_m-x,pose.y_m-y),abs(math.atan2(math.sin(pose.theta_rad-theta),math.cos(pose.theta_rad-theta)))])
                if count in (13,89): cv2.imwrite(str(out/f'frame_{count}.png'),frame.image_bgr)
    drop=tracker.observe(render_frame(.5,.5,0,calibrations[0],999,100,hide=True),calibrations[0])
    a=np.array(errors)
    report={'mode':'synthetic camera; actual OpenCV ArUco detection','opencv':cv2.__version__,'frames':count,'detected':len(errors),'failures':failures,'position_rmse_m':float(np.sqrt(np.mean(a[:,0]**2))),'position_max_m':float(a[:,0].max()),'heading_rmse_rad':float(np.sqrt(np.mean(a[:,1]**2))),'heading_max_rad':float(a[:,1].max()),'occlusion_invalid':not drop.valid,'thresholds':{'position_max_m':.004,'heading_max_rad':.04},'passed':bool(not failures and not drop.valid and a[:,0].max()<.004 and a[:,1].max()<.04)}
    (out/'results.json').write_text(json.dumps(report,indent=2)); return report
