"""Recorded evaluation, scored only from observations. Truth stays in renderer."""
from pathlib import Path
from dataclasses import replace
import json
import math
import time
import numpy as np
from darwin.config import Config
from darwin.runtime import Runtime
from darwin.control.policy import Policy

TASKS=[{'target':[.67,.65],'heading':0.}, {'target':[.34,.65],'heading':1.2},
       {'target':[.65,.34],'heading':-1.3}, {'target':[.35,.35],'heading':2.7}]
MAPS=['swap','reverse_left','reverse_right','reverse_both','unequal_gains']

def job(runtime,name):
    runtime.command(name,{'owner_id':'cli'})
    try: return runtime.wait(owner='cli')
    except RuntimeError as exc:
        if name=='navigate': return runtime._job_result or {'success':False,'reason':str(exc)}
        raise

def recenter(runtime,heading=0):
    runtime.command('recenter',{'theta_rad':heading})
    runtime.policy=Policy(runtime.config)

def frozen_trial(runtime,task,budget=100):
    """Deliberate evaluation: known stale model cannot authorize motion near bounds.

    Every pulse uses the stricter unknown-response central-area check. Same budgets
    as adapted trials; a conservative boundary stop is a retained failure.
    """
    recenter(runtime,task['heading']); runtime.command('target',{'target':task['target']})
    gen=runtime.safety.start('cli',runtime.now); runtime._cancel.clear()
    runtime.state='FROZEN_EVALUATION'; started=runtime.now; count=0
    result=None
    try:
        while count<budget:
            runtime.safety.heartbeat('cli')
            pose=runtime._observe()
            distance=math.hypot(task['target'][0]-pose.x_m,task['target'][1]-pose.y_m)
            if distance<=runtime.config.goal_contact_radius_m:
                dwelling=True
                for _ in range(math.ceil(runtime.config.goal_dwell_ms/50)):
                    runtime.env.advance(.05); runtime.safety.heartbeat('cli')
                    pose=runtime._observe(log=True); runtime._check(gen,exploration=True)
                    distance=math.hypot(task['target'][0]-pose.x_m,task['target'][1]-pose.y_m)
                    if distance>runtime.config.goal_contact_radius_m: dwelling=False; break
                if dwelling:
                    result={'success':True,'actions':count,'final_distance_m':distance}; break
                continue
            action=runtime.policy.choose(pose,task['target'],runtime.frozen_model)
            if action is None: raise RuntimeError('frozen model has no useful safe action')
            runtime._pulse(replace(action,episode_id='frozen-evaluation'),gen,exploration=True)
            count+=1
        if result is None: raise RuntimeError('frozen evaluation action budget')
    except Exception as exc:
        pose=runtime.pose
        result={'success':False,'actions':count,'final_distance_m':math.hypot(task['target'][0]-pose.x_m,task['target'][1]-pose.y_m),'reason':str(exc)}
    finally:
        runtime._stop('frozen baseline finished')
    result.update(elapsed_s=runtime.now-started,task=task)
    runtime._event('frozen_navigation_result',result)
    return result

def run_case(seed=42,mapping='reverse_left',variant='linear',observation='vision',tasks=None,run_root=None):
    config=Config(seed=seed,plant_variant=variant,observation=observation)
    runtime=Runtime(config,realtime=False,run_root=run_root)
    result={'seed':seed,'mapping':mapping,'variant':variant,'observation':observation,
            'run_id':runtime.run_id,'run_path':str(runtime.writer.path),
            'thresholds':{'goal_radius_m':config.goal_radius_m,'goal_contact_radius_m':config.goal_contact_radius_m,'max_actions':config.max_episode_actions,
            'max_seconds':config.max_episode_seconds,'dwell_ms':config.goal_dwell_ms,'safe_bounds':config.safe_bounds,
            'success_fraction_target':.8,'normalized_prediction_reduction_target':.8},'interventions':[],
            'before_navigation':[],'frozen_navigation':[],'adapted_navigation':[]}
    tasks=tasks or TASKS
    try:
        job(runtime,'start-calibration')
        for task in tasks:
            recenter(runtime,task['heading']); result['interventions'].append('explicit recenter before baseline task')
            runtime.command('target',{'target':task['target']})
            result['before_navigation'].append({**job(runtime,'navigate'),'task':task})
        recenter(runtime); result['interventions'].append('explicit recenter before scramble')
        runtime.command('scramble',{'mapping':mapping})
        for task in tasks:
            result['frozen_navigation'].append(frozen_trial(runtime,task))
            result['interventions'].append('explicit recenter before frozen task')
        recenter(runtime); result['interventions'].append('explicit recenter before recovery')
        job(runtime,'recover')
        for task in tasks:
            recenter(runtime,task['heading']); result['interventions'].append('explicit recenter before adapted task')
            runtime.command('target',{'target':task['target']})
            result['adapted_navigation'].append({**job(runtime,'navigate'),'task':task})
        result['prediction']=runtime.metrics
        frozen=runtime.metrics['frozen']['normalized_rmse']; adapted=runtime.metrics['adapted']['normalized_rmse']
        result['prediction_error_reduction']=1-adapted/frozen if frozen else None
        result['valid_training_count']=len(runtime.samples); result['heldout_count']=len(runtime.heldout)
        result['invalid_samples']=len(runtime.rejected)
        result['boundary_stops']=sum('boundary' in (r.get('reason') or '') for phase in ['before_navigation','frozen_navigation','adapted_navigation'] for r in result[phase])
        result['error']=None
    except Exception as exc:
        result['error']=str(exc)
        # Missing scheduled navigation trials remain explicit failures in denominators.
        for phase in ['before_navigation','frozen_navigation','adapted_navigation']:
            while len(result[phase])<len(tasks): result[phase].append({'success':False,'reason':'workflow failed: '+str(exc),'task':tasks[len(result[phase])]})
    finally:
        runtime.writer.save_artifact('evaluation.json',result)
        runtime.close()
    return result

def write_report(cases,output):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    contact_radius=cases[0]['thresholds'].get('goal_contact_radius_m',cases[0]['thresholds']['goal_radius_m']) if cases else 0.
    summary={'mode':'SIMULATION','cases':len(cases),'seeds':sorted({c['seed'] for c in cases}),
             'variants':sorted({c['variant'] for c in cases}),'mappings':sorted({c['mapping'] for c in cases}),
             'failures':[{'run_id':c['run_id'],'error':c['error']} for c in cases if c.get('error')],
             'navigation':{},'cases_detail':cases}
    for phase in ['before_navigation','frozen_navigation','adapted_navigation']:
        trials=[r for c in cases for r in c[phase]]
        successes=sum(bool(t.get('success')) for t in trials)
        summary['navigation'][phase]={'successes':successes,'trials':len(trials),'success_fraction':successes/len(trials) if trials else 0}
    reductions=[c['prediction_error_reduction'] for c in cases if c.get('prediction_error_reduction') is not None]
    summary['prediction_reduction_min']=min(reductions) if reductions else None
    summary['prediction_reduction_mean']=float(np.mean(reductions)) if reductions else None
    summary['passed']=not summary['failures'] and summary['navigation']['before_navigation']['success_fraction']>=.8 and summary['navigation']['adapted_navigation']['success_fraction']>=.8 and bool(reductions) and min(reductions)>=.8
    (output/'results.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
    lines=['# Darwin measured simulation evidence','',f"Cases: {len(cases)}; seeds: {summary['seeds']}; variants: {summary['variants']}; mappings: {summary['mappings']}.",'',
           f'Every task succeeds when the {contact_radius:.2f} m robot footprint reaches the point target, with a 500 ms dwell and 100 actions / 45 synthetic seconds. Every explicit recenter is recorded as an intervention between trials. Frozen navigation uses conservative unknown-response boundary checks. All failures stay in denominators.','',
           '| Phase | Success / trials | Fraction |','|---|---:|---:|']
    for phase,stats in summary['navigation'].items(): lines.append(f"| {phase} | {stats['successes']} / {stats['trials']} | {stats['success_fraction']:.1%} |")
    lines.extend(['',f"Minimum adapted vs frozen normalized prediction error reduction: {summary['prediction_reduction_min']:.2%}" if reductions else 'No prediction results.',
                  '',f"Workflow errors: {len(summary['failures'])}. Passed declared easy simulation gates: {summary['passed']}.",
                  '', 'These are simulated observations; no hardware performance claim. Held-out IDs are disjoint from fit IDs. Frozen/adapted models are scored on identical new-map held-out pulses.', '',
                  '| Seed | Plant | Map | Observation | Before v RMSE m/s | Frozen yaw RMSE rad/s | Adapted yaw RMSE rad/s | Reduction |','|---|---|---|---|---:|---:|---:|---:|'])
    for c in cases:
        if 'prediction' in c:
            p=c['prediction']; lines.append(f"| {c['seed']} | {c['variant']} | {c['mapping']} | {c['observation']} | {p['before']['v_rmse_mps']:.6f} | {p['frozen']['omega_rmse_radps']:.6f} | {p['adapted']['omega_rmse_radps']:.6f} | {c['prediction_error_reduction']:.2%} |")
        else: lines.append(f"| {c['seed']} | {c['variant']} | {c['mapping']} | {c['observation']} | ERROR: {c['error']} | | | |")
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    # Standalone standard SVG chart from measured data, no plotting dependency.
    bars=[]
    for i,c in enumerate(cases):
        if 'prediction' not in c: continue
        for j,(phase,color) in enumerate([('before','#278bc6'),('frozen','#ef8159'),('adapted','#48b69c')]):
            val=c['prediction'][phase]['normalized_rmse']; x=130+min(val,2)*380
            bars.append(f'<rect x="130" y="{40+i*34+j*9}" width="{max(.3,x-130):.2f}" height="7" fill="{color}"/>')
        bars.append(f'<text x="4" y="{55+i*34}" font-size="9">{c["seed"]} {c["mapping"]}</text>')
    chart=f'<svg xmlns="http://www.w3.org/2000/svg" width="950" height="{max(100,len(cases)*34+60)}"><rect width="100%" height="100%" fill="white"/><text x="10" y="20">Measured normalized RMSE — blue before / orange frozen / green adapted</text>{"".join(bars)}</svg>'
    (output/'prediction_comparison.svg').write_text(chart)
    return summary

def simulate(seed,output,observation='vision'):
    return write_report([run_case(seed,observation=observation)],output)

def benchmark(seeds,output,variants=('linear','noisy','nonlinear'),observation='pose'):
    cases=[]
    for variant in variants:
        for seed in seeds:
            for mapping in MAPS:
                cases.append(run_case(seed,mapping,variant,observation))
                print(json.dumps({'completed':len(cases),'seed':seed,'variant':variant,'mapping':mapping,'error':cases[-1].get('error')}),flush=True)
    return write_report(cases,output)
