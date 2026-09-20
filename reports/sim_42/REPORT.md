# Darwin measured simulation evidence

Cases: 1; seeds: [42]; variants: ['linear']; mappings: ['reverse_one'].

Every task uses a 0.06 m goal radius, 500 ms dwell, 100 actions / 45 synthetic seconds. Every explicit recenter is recorded as an intervention between trials. Frozen navigation uses conservative unknown-response boundary checks. All failures stay in denominators.

| Phase | Success / trials | Fraction |
|---|---:|---:|
| before_navigation | 4 / 4 | 100.0% |
| frozen_navigation | 0 / 4 | 0.0% |
| adapted_navigation | 4 / 4 | 100.0% |

Minimum adapted vs frozen normalized prediction error reduction: 99.54%

Workflow errors: 0. Passed declared easy simulation gates: True.

These are simulated observations; no hardware performance claim. Held-out IDs are disjoint from fit IDs. Frozen/adapted models are scored on identical new-map held-out pulses.

| Seed | Plant | Map | Observation | Before v RMSE m/s | Frozen yaw RMSE rad/s | Adapted yaw RMSE rad/s | Reduction |
|---|---|---|---|---:|---:|---:|---:|
| 42 | linear | reverse_one | vision | 0.000318 | 0.689602 | 0.002704 | 99.54% |
