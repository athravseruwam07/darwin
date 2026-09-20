"""Deterministic narration triggers.

A trigger fires only on a transition Darwin could actually sense through the
camera, or on an operator action the browser itself performed. The two live on
separate channels so a pressed button is never reported as a detection.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict

SUSPICION_RATIO = .5

@dataclass(frozen=True)
class Trigger:
    kind: str
    tone: str
    channel: str
    headline: str
    fallback: str
    chips: tuple = ()
    priority: int = 5

    def to_dict(self): return {**asdict(self),'chips':[list(chip) for chip in self.chips]}

def _n(value, digits=3):
    return 'unavailable' if value is None else f'{value:.{digits}f}'

def _i(value):
    return 'no' if value is None else str(int(value))

def _chips(*pairs):
    return tuple((label,value) for label,value in pairs if value is not None)

MUTATION_LABELS = {'swap':'swapped wheels','reverse_left':'reversed the left wheel',
                   'reverse_right':'reversed the right wheel','reverse_both':'reversed both wheels',
                   'weaken_left':'weakened the left wheel','random_mashup':'a seeded random mashup of reviewed factors'}

OPERATOR_ACTIONS = {
    'inject-mutation':('operator_mutation','Operator action · hidden from Darwin'),
    'adaptation-challenge':('operator_challenge','Operator action · hidden from Darwin'),
    'scramble':('operator_scramble','Operator action · hidden from Darwin'),
    'stop':('operator_stop','Operator pressed STOP'),
    'start-calibration':('operator_calibrate','Operator started learning'),
    'navigate':('operator_navigate','Operator started navigation'),
    'navigate-route':('operator_navigate','Operator started a route'),
    'recover':('operator_recover','Operator forced recovery'),
    'reset-model':('operator_reset','Operator cleared the model'),
    'target':('operator_target','Operator set a target'),
    'route':('operator_route','Operator drew a route'),
    'calibration':('operator_camera','Operator recalibrated the camera'),
    'fault':('operator_fault','Operator injected a diagnostic fault'),
    'recenter':('operator_recenter','Operator repositioned the simulation'),
    'connect':('operator_connect','Operator connected hardware'),
    'export':('operator_export','Operator exported the run'),
}

def _point_text(payload):
    values=(payload.get('x_m'),payload.get('y_m'))
    try: return ' at {:.2f}, {:.2f} m'.format(float(values[0]),float(values[1]))
    except (TypeError,ValueError): return ''

def operator_trigger(command, payload=None):
    """Describe an operator command in third person; Darwin is not the speaker."""
    payload=payload if isinstance(payload,dict) else {}
    entry=OPERATOR_ACTIONS.get(str(command))
    if entry is None: return None
    kind,headline=entry
    mapping=payload.get('mapping')
    label=MUTATION_LABELS.get(mapping,'an unlisted mapping' if mapping else None)
    if kind=='operator_mutation':
        text=f'Operator {label} while the robot was driving. Darwin was not told; only repeated camera residuals can reveal it.'
    elif kind=='operator_challenge':
        text=f'Operator started the full adaptation challenge with {label or "a hidden mapping"}. The mapping stays hidden from the learner.'
    elif kind=='operator_scramble':
        text=f'Operator scrambled the motor mapping ({label or "unspecified"}) and froze the previous model.'
    elif kind=='operator_stop':
        text='Operator pressed STOP. Motor output is cut and the active episode is cancelled.'
    elif kind=='operator_fault':
        text=f'Operator injected the diagnostic fault "{payload.get("name","unknown")}".'
    elif kind=='operator_target':
        point=_point_text(payload)
        text=f'Operator selected a target{point}. Darwin plans toward it with the model it already has.'
    elif kind=='operator_calibrate':
        text='Operator started a fresh calibration. Darwin will collect independent probe pulses and refit from camera measurements alone.'
    elif kind=='operator_navigate':
        text='Operator started goal-directed navigation under the currently validated model.'
    elif kind=='operator_reset':
        text='Operator cleared the learned model. Every command becomes meaningless again until Darwin recalibrates.'
    elif kind=='operator_route':
        text=f'Operator drew a route of {len(payload.get("points") or [])} waypoints.'
    else:
        text=headline+'.'
    return Trigger(kind=kind,tone='operator',channel='operator',headline=headline,fallback=text,
        chips=_chips(('mapping',mapping if isinstance(mapping,str) else None)),priority=3)

def _boot(facts):
    return Trigger('boot','boot','darwin','Runtime online',
        'New body, blank slate—time to learn the controls.',
        _chips(('mode',facts['mode']),('state',facts['state'])),priority=4)

def _state_changed(before,after,*names):
    return after['state'] in names and before['state'] not in names

def detect_triggers(before, after):
    """Return the sensed transitions between two fact packets, newest intent first."""
    if not isinstance(after,dict): return []
    if before is None: return [_boot(after)]
    out=[]
    change,previous=after['change'],before['change']
    routine_stops={'awaiting operator start','connected disarmed','operator stop'}
    if (after['stop_reason'] and after['stop_reason']!=before['stop_reason'] and
            after['stop_reason'].lower() not in routine_stops):
        out.append(Trigger('stopped','fault','darwin','Motion stopped',
            'I stopped before that got embarrassing.',
            _chips(('reason',after['stop_reason'])),priority=1))
    if before['tracking_valid'] and not after['tracking_valid']:
        out.append(Trigger('tracking_lost','fault','darwin','Marker lost',
            'I lost sight of myself, so I stopped.',
            _chips(('frame age',f'{_i(after["frame_age_ms"])} ms')),priority=1))
    if _state_changed(before,after,'PROBING'):
        out.append(Trigger('probing','work','darwin','Probing my body',
            'Let me wiggle a little and see what happens.',
            _chips(('valid samples',_i(after['samples']['valid']))),priority=4))
    if _state_changed(before,after,'FITTING'):
        out.append(Trigger('fitting','work','darwin','Fitting the model',
            'I think I’m getting the hang of this body.',
            _chips(('held-out',_i(after['samples']['heldout']))),priority=4))
    if _state_changed(before,after,'RECOVERING'):
        out.append(Trigger('experiments','focus','darwin','Designing experiments',
            'Fine, I’ll learn these controls again.',
            _chips(('valid samples',_i(after['samples']['valid']))),priority=2))
    ratio,previous_ratio=change['ratio'],previous['ratio']
    if (ratio is not None and previous_ratio is not None and not change['detected'] and not previous['detected']
            and ratio>=SUSPICION_RATIO>previous_ratio):
        out.append(Trigger('suspicion','curious','darwin','Something feels off',
            'That move felt suspicious.',
            _chips(('score',_n(change['score'],3)),('threshold',_n(change['threshold'],3)),
                   ('consecutive',_i(change['consecutive_count']))),priority=2))
    sensed,was_sensed=after['sensed_change'],before['sensed_change']
    # The detector flag and the published signal arrive on different polls; latch on either.
    if (change['detected'] or sensed) and not (previous['detected'] or was_sensed):
        score=(sensed or change).get('score'); threshold=(sensed or change).get('threshold')
        out.append(Trigger('change_detected','alarm','darwin','My body changed',
            'Who scrambled my controls?',
            _chips(('score',_n(score,3)),('threshold',_n(threshold,3)),
                   ('evidence',_i(change['evidence_count'])),('source','camera residual')),priority=1))
    if after['model_id'] and after['model_id']!=before['model_id'] and after['model_ready']:
        improvement=after['metrics']['improvement_pct']
        if improvement is not None or after['adaptation_complete'] or (before['sensed_change'] or after['sensed_change']):
            frozen=(after['metrics']['frozen'] or {}).get('normalized_rmse')
            adapted=(after['metrics']['adapted'] or after['metrics']['current'] or {}).get('normalized_rmse')
            out.append(Trigger('adapted','resolved','darwin','New body learned',
                'New controls, same Darwin.',
                _chips(('frozen',_n(frozen,4)),('adapted',_n(adapted,4)),
                       ('improvement',None if improvement is None else f'{improvement:.1f}%'),
                       ('model',after['model_id'])),priority=1))
        else:
            current=(after['metrics']['current'] or {}).get('normalized_rmse')
            out.append(Trigger('model_fitted','resolved','darwin','Baseline model validated',
                'Okay, I know what my wheels do now.',
                _chips(('model',after['model_id']),('held-out error',_n(current,4)),
                       ('valid samples',_i(after['samples']['valid']))),priority=2))
    if _state_changed(before,after,'NAVIGATING'):
        resumed=after['adaptation_complete']
        out.append(Trigger('resumed' if resumed else 'navigating','focus','darwin',
            'Resuming navigation' if resumed else 'Navigating',
            ('Back on track.' if resumed else 'I know where I’m going—probably.'),
            _chips(('distance',None if after['distance_to_target_m'] is None else f'{after["distance_to_target_m"]:.3f} m'),
                   ('model',after['model_id'])),priority=3))
    if after['boundary_recovery'] and not before['boundary_recovery']:
        out.append(Trigger('boundary','curious','darwin','Leaving the safe area',
            'Too close to the edge—turning back.',priority=2))
    if before['boundary_recovery'] and not after['boundary_recovery']:
        out.append(Trigger('boundary_clear','work','darwin','Back inside the buffer',
            'Much better—back to the target.',priority=4))
    if _state_changed(before,after,'GOAL'):
        out.append(Trigger('goal','resolved','darwin','Target reached',
            'Made it.',
            _chips(('final distance',None if after['distance_to_target_m'] is None else f'{after["distance_to_target_m"]:.3f} m')),priority=1))
    if (before['model_id'] and not after['model_id'] and not after['busy']
            and after['state'] in {'DISARMED','READY'} and not after['sensed_change']):
        out.append(Trigger('model_reset','work','darwin','Model cleared',
            'Well, back to square one.',priority=4))
    out.sort(key=lambda trigger:trigger.priority)
    return out
