"""Execute the exact browser coordinate functions independently of DOM rendering."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

@pytest.mark.skipif(not shutil.which('node'),reason='Node optional: browser exercises same geometry')
def test_browser_homography_and_css_letterbox_click_mapping():
    javascript=(Path(__file__).resolve().parents[1]/'src/darwin/web/static/app.js').read_text(encoding='utf-8').split('window.DarwinGeometry=')[0]
    assertions='''
const assert=require('assert');
const corners=[[40,20],[570,35],[600,440],[20,410]], world=[[0,1],[1,1],[1,0],[0,0]];
const forward=homography(corners,world), backward=homography(world,corners);
for(const p of [[.23,.23],[.77,.77],[.5,.5],[.4,.7]]){let q=project(forward,project(backward,p));assert(Math.abs(q[0]-p[0])<1e-10&&Math.abs(q[1]-p[1])<1e-10);}
assert.deepStrictEqual(canvasPoint(330,250,{left:10,top:10,width:640,height:480},640,480),[320,240]);
assert.deepStrictEqual(canvasPoint(490,250,{left:10,top:10,width:960,height:480},640,480),[320,240]);
assert.strictEqual(canvasPoint(20,250,{left:10,top:10,width:960,height:480},640,480),null);
assert.deepStrictEqual(canvasPoint(330,490,{left:10,top:10,width:640,height:960},640,480),[320,240]);
assert(project(forward,corners[0])[1]>.99);assert(project(forward,corners[3])[1]<.01);
assert.strictEqual(residualText({v_mps:.00006,omega_radps:-.0039}),'Forward +0.00006 m/s · Yaw −0.0039 rad/s');
assert.strictEqual(residualText(null),'Latest pre-update residual: unavailable');
assert(!residualText({v_mps:NaN,omega_radps:Infinity}).includes('NaN'));
assert.strictEqual(poseText({valid:false,x_m:0,y_m:0,theta_rad:0,invalid_reason:'marker not detected'}),'Tracking unavailable · marker not detected');
assert.strictEqual(poseText({valid:true,x_m:.5,y_m:.6,theta_rad:.1}),'0.500, 0.600 m · 0.10 rad');
assert.strictEqual(poseText(null),'Tracking unavailable');
let cognition=cognitionState({model_id:'m1',events:[{kind:'mutation_injected'}],change_detection:{detected:false}});
assert.strictEqual(cognition.key,'unaware');
cognition=cognitionState({model_id:'m1',events:[{kind:'mutation_injected'}],change_detection:{detected:true,score:.8}});
assert.strictEqual(cognition.key,'detected');
const motorPoint=projectMotorPoint(-1,1,.5,640,420);
assert(motorPoint.every(Number.isFinite));assert.strictEqual(motorPoint.length,2);
assert.deepStrictEqual(normalizeModelField({grid_size:2,points:[{left:-1,right:1,v_mps:.2,omega_radps:.3},{left:0,right:0,v_mps:NaN,omega_radps:0}]}).points.length,1);
const base={mode:'hardware',state:'READY',busy:false,model_id:'model',model_ready:true,pose:{valid:true,x_m:.5,y_m:.5},transport_health:'healthy',valid_sample_count:24};
let controls=controlAvailability({...base,target:null},{goal_radius_m:.06},{hasGeometry:true,hasFrame:true,calibrating:false,requestBusy:false});
assert.strictEqual(controls.navigate.enabled,false);assert.strictEqual(controls.navigate.reason,'Choose a target first');
controls=controlAvailability({...base,target:[.575,.5]},{goal_radius_m:.06,goal_contact_radius_m:.08},{hasGeometry:true,hasFrame:true,calibrating:false,requestBusy:false});
assert.strictEqual(controls.navigate.enabled,false);assert(controls.navigate.reason.includes('reached'));
controls=controlAvailability({...base,target:[.8,.8]},{goal_radius_m:.06,goal_contact_radius_m:.08},{hasGeometry:true,hasFrame:true,calibrating:false,requestBusy:false});
assert.strictEqual(controls.navigate.enabled,true);assert.strictEqual(controls.stop.enabled,false);
controls=controlAvailability({...base,busy:true,target:[.8,.8]},{goal_radius_m:.06,goal_contact_radius_m:.08},{hasGeometry:true,hasFrame:true,calibrating:false,requestBusy:false});
assert.strictEqual(controls.navigate.enabled,false);assert.strictEqual(controls.stop.enabled,true);
controls=controlAvailability({...base,model_id:null,model_ready:false,target:null},{goal_radius_m:.06},{hasGeometry:true,hasFrame:true,calibrating:false,requestBusy:false});
assert.strictEqual(controls.selectTarget.enabled,false);assert.strictEqual(controls.resetModel.enabled,true);
console.log('coordinate geometry and measurement formatting verified');
'''
    result=subprocess.run(['node','-e',javascript+assertions],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
