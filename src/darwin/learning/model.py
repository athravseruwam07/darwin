"""Small CPU ridge model fitted only to public observed transitions."""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from darwin.types import FEATURE_VERSION, MEASUREMENT_VERSION
from .features import features, FEATURE_ORDER

SCHEMA_VERSION = 1

def _arrays(transitions):
    rows = [t for t in transitions if t.valid]
    if not rows: raise ValueError('no valid transitions')
    for t in rows:
        if not t.start_pose.valid or not t.end_pose.valid: raise ValueError('invalid pose in valid transition')
        if t.elapsed_s <= 0 or not np.isfinite([t.elapsed_s,t.v_mps,t.omega_radps]).all(): raise ValueError('invalid measured motion')
        if t.feature_version != FEATURE_VERSION or t.measurement_version != MEASUREMENT_VERSION: raise ValueError('incompatible feature/measurement version')
        if t.start_pose.calibration_id != t.end_pose.calibration_id: raise ValueError('calibration changed during transition')
    return rows, features([[t.u1,t.u2] for t in rows]), np.array([[t.v_mps,t.omega_radps] for t in rows])

def _errors(pred, actual):
    residual = pred-actual
    rmse = np.sqrt(np.mean(residual**2, axis=0))
    mae = np.mean(np.abs(residual), axis=0)
    return {'v_rmse_mps':float(rmse[0]), 'omega_rmse_radps':float(rmse[1]),
            'v_mae_mps':float(mae[0]), 'omega_mae_radps':float(mae[1]),
            'normalized_rmse':float(np.sqrt(np.mean((residual/np.array([.08,.7]))**2))),
            'normalization_scales':[.08,.7], 'count':len(actual)}

class MotionModel:
    def __init__(self, ridge_lambda=.001):
        if not np.isfinite(ridge_lambda) or ridge_lambda < 0: raise ValueError('invalid regularization')
        self.ridge_lambda = ridge_lambda
        self.coefficients = None
        self.model_id = None
        self.training_action_ids = []
        self.metrics = {}
        self.config_id = None
        self.calibration_id = None
        self.fit_at = None

    def fit(self, transitions):
        rows, x, y = _arrays(transitions)
        if len(rows) < 6: raise ValueError('at least six independent pulses required')
        ids = [t.action_id for t in rows]
        if len(set(ids)) != len(ids): raise ValueError('duplicate training pulse IDs')
        rank = int(np.linalg.matrix_rank(x))
        if rank < 3: raise ValueError('rank deficient action coverage')
        configs = {t.config_id for t in rows}
        calibrations = {t.start_pose.calibration_id for t in rows}
        if len(configs) != 1 or len(calibrations) != 1: raise ValueError('mixed configuration/calibration')
        self.coefficients = np.linalg.solve(x.T@x + self.ridge_lambda*np.diag([1.,1.,0.]), x.T@y)
        self.config_id = next(iter(configs)); self.calibration_id = next(iter(calibrations))
        self.training_action_ids = ids
        self.fit_at = time.time()
        self.model_id = hashlib.sha256(json.dumps({'coefficients':self.coefficients.tolist(),'ids':ids},sort_keys=True).encode()).hexdigest()[:16]
        self.metrics = {'training_count':len(rows),'feature_rank':rank,'condition_number':float(np.linalg.cond(x)),
                        'action_min':x[:,:2].min(axis=0).tolist(),'action_max':x[:,:2].max(axis=0).tolist(),
                        'training':_errors(self.predict(x[:,:2]), y)}
        return self.metrics

    def predict(self, actions):
        if self.coefficients is None: raise ValueError('model not fitted')
        x = features(actions)
        y = x@self.coefficients
        # Affine measurement bias is diagnostic, never a propulsion source.
        y[np.all(x[:,:2] == 0, axis=1)] = 0
        return y

    def save(self, path):
        if self.coefficients is None: raise ValueError('model not fitted')
        data = {'schema_version':SCHEMA_VERSION,'feature_version':FEATURE_VERSION,'feature_order':FEATURE_ORDER,
                'measurement_version':MEASUREMENT_VERSION,'coefficients':self.coefficients.tolist(),
                'normalization':{'features':'none','targets':'SI'},'ridge_lambda':self.ridge_lambda,
                'training_action_ids':self.training_action_ids,'config_id':self.config_id,
                'calibration_id':self.calibration_id,'fit_at':self.fit_at,'model_id':self.model_id,'metrics':self.metrics}
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
        return path

    @classmethod
    def load(cls, path, config_id=None, calibration_id=None):
        data = json.loads(Path(path).read_text())
        if data.get('schema_version') != SCHEMA_VERSION or data.get('feature_version') != FEATURE_VERSION or data.get('measurement_version') != MEASUREMENT_VERSION or data.get('feature_order') != FEATURE_ORDER:
            raise ValueError('incompatible checkpoint schema/features/measurement')
        if config_id is not None and data['config_id'] != config_id: raise ValueError('checkpoint configuration mismatch')
        if calibration_id is not None and data['calibration_id'] != calibration_id: raise ValueError('checkpoint calibration mismatch')
        obj = cls(data['ridge_lambda'])
        obj.coefficients = np.asarray(data['coefficients'], dtype=float)
        if obj.coefficients.shape != (3,2) or not np.isfinite(obj.coefficients).all(): raise ValueError('invalid coefficients')
        for field in ('training_action_ids','config_id','calibration_id','fit_at','model_id','metrics'): setattr(obj,field,data[field])
        return obj

def evaluate(model, transitions):
    rows,x,y = _arrays(transitions)
    if set(model.training_action_ids)&{t.action_id for t in rows}: raise ValueError('held-out evaluation overlaps training pulses')
    if any(t.config_id != model.config_id or t.start_pose.calibration_id != model.calibration_id for t in rows): raise ValueError('evaluation identity mismatch')
    return _errors(model.predict(x[:,:2]), y)
