# Darwin measured simulation evidence

Cases: 60; seeds: [11, 22, 33, 44, 55]; variants: ['linear', 'noisy', 'nonlinear']; mappings: ['reverse_both', 'reverse_one', 'swap', 'unequal_gains'].

Every task uses a 0.06 m goal radius, 500 ms dwell, 100 actions / 45 synthetic seconds. Every explicit recenter is recorded as an intervention between trials. Frozen navigation uses conservative unknown-response boundary checks. All failures stay in denominators.

| Phase | Success / trials | Fraction |
|---|---:|---:|
| before_navigation | 240 / 240 | 100.0% |
| frozen_navigation | 0 / 240 | 0.0% |
| adapted_navigation | 240 / 240 | 100.0% |

Minimum adapted vs frozen normalized prediction error reduction: 94.06%

Workflow errors: 0. Passed declared easy simulation gates: True.

These are simulated observations; no hardware performance claim. Held-out IDs are disjoint from fit IDs. Frozen/adapted models are scored on identical new-map held-out pulses.

| Seed | Plant | Map | Observation | Before v RMSE m/s | Frozen yaw RMSE rad/s | Adapted yaw RMSE rad/s | Reduction |
|---|---|---|---|---:|---:|---:|---:|
| 11 | linear | swap | pose | 0.000016 | 1.012553 | 0.000046 | 99.98% |
| 11 | linear | reverse_one | pose | 0.000016 | 0.699000 | 0.000047 | 99.97% |
| 11 | linear | reverse_both | pose | 0.000016 | 1.012838 | 0.000047 | 99.98% |
| 11 | linear | unequal_gains | pose | 0.000016 | 0.675526 | 0.000035 | 99.99% |
| 22 | linear | swap | pose | 0.000026 | 1.008511 | 0.000037 | 99.98% |
| 22 | linear | reverse_one | pose | 0.000026 | 0.720777 | 0.000037 | 99.97% |
| 22 | linear | reverse_both | pose | 0.000026 | 1.008569 | 0.000037 | 99.98% |
| 22 | linear | unequal_gains | pose | 0.000026 | 0.670753 | 0.000029 | 99.99% |
| 33 | linear | swap | pose | 0.000027 | 1.070864 | 0.000046 | 99.98% |
| 33 | linear | reverse_one | pose | 0.000027 | 0.765857 | 0.000041 | 99.97% |
| 33 | linear | reverse_both | pose | 0.000027 | 1.069723 | 0.000046 | 99.98% |
| 33 | linear | unequal_gains | pose | 0.000027 | 0.736750 | 0.000032 | 99.99% |
| 44 | linear | swap | pose | 0.000024 | 0.634007 | 0.000030 | 99.96% |
| 44 | linear | reverse_one | pose | 0.000024 | 0.628430 | 0.000038 | 99.98% |
| 44 | linear | reverse_both | pose | 0.000024 | 0.634081 | 0.000030 | 99.97% |
| 44 | linear | unequal_gains | pose | 0.000024 | 0.537657 | 0.000029 | 99.99% |
| 55 | linear | swap | pose | 0.000022 | 1.117068 | 0.000051 | 99.98% |
| 55 | linear | reverse_one | pose | 0.000022 | 0.686919 | 0.000045 | 99.97% |
| 55 | linear | reverse_both | pose | 0.000022 | 1.117429 | 0.000051 | 99.98% |
| 55 | linear | unequal_gains | pose | 0.000022 | 0.668020 | 0.000034 | 99.98% |
| 11 | noisy | swap | pose | 0.001425 | 1.015185 | 0.007975 | 98.62% |
| 11 | noisy | reverse_one | pose | 0.001425 | 0.699769 | 0.008412 | 98.43% |
| 11 | noisy | reverse_both | pose | 0.001425 | 1.015471 | 0.007976 | 98.82% |
| 11 | noisy | unequal_gains | pose | 0.001425 | 0.677715 | 0.007946 | 98.14% |
| 22 | noisy | swap | pose | 0.001923 | 1.012639 | 0.009117 | 98.62% |
| 22 | noisy | reverse_one | pose | 0.001923 | 0.723517 | 0.004266 | 98.26% |
| 22 | noisy | reverse_both | pose | 0.001923 | 1.012694 | 0.009117 | 98.83% |
| 22 | noisy | unequal_gains | pose | 0.001923 | 0.674006 | 0.009099 | 98.21% |
| 33 | noisy | swap | pose | 0.001525 | 1.073161 | 0.012174 | 98.13% |
| 33 | noisy | reverse_one | pose | 0.001525 | 0.762456 | 0.009562 | 97.40% |
| 33 | noisy | reverse_both | pose | 0.001525 | 1.071994 | 0.012173 | 98.36% |
| 33 | noisy | unequal_gains | pose | 0.001525 | 0.740578 | 0.012177 | 97.54% |
| 44 | noisy | swap | pose | 0.001025 | 0.630330 | 0.009534 | 97.91% |
| 44 | noisy | reverse_one | pose | 0.001025 | 0.621768 | 0.009419 | 98.00% |
| 44 | noisy | reverse_both | pose | 0.001025 | 0.630455 | 0.009534 | 98.56% |
| 44 | noisy | unequal_gains | pose | 0.001025 | 0.532789 | 0.009536 | 98.00% |
| 55 | noisy | swap | pose | 0.001852 | 1.121685 | 0.010351 | 98.54% |
| 55 | noisy | reverse_one | pose | 0.001852 | 0.693402 | 0.008009 | 96.87% |
| 55 | noisy | reverse_both | pose | 0.001852 | 1.122036 | 0.010351 | 98.71% |
| 55 | noisy | unequal_gains | pose | 0.001852 | 0.673265 | 0.006906 | 98.14% |
| 11 | nonlinear | swap | pose | 0.002073 | 0.884956 | 0.020958 | 97.04% |
| 11 | nonlinear | reverse_one | pose | 0.002073 | 0.611948 | 0.022450 | 95.81% |
| 11 | nonlinear | reverse_both | pose | 0.002073 | 0.885156 | 0.021006 | 96.94% |
| 11 | nonlinear | unequal_gains | pose | 0.002073 | 0.586414 | 0.024900 | 94.90% |
| 22 | nonlinear | swap | pose | 0.002656 | 0.887728 | 0.016164 | 97.44% |
| 22 | nonlinear | reverse_one | pose | 0.002656 | 0.638061 | 0.018693 | 96.71% |
| 22 | nonlinear | reverse_both | pose | 0.002656 | 0.887786 | 0.016131 | 98.28% |
| 22 | nonlinear | unequal_gains | pose | 0.002656 | 0.586565 | 0.015660 | 96.65% |
| 33 | nonlinear | swap | pose | 0.002244 | 0.918153 | 0.025690 | 96.62% |
| 33 | nonlinear | reverse_one | pose | 0.002244 | 0.659791 | 0.015460 | 96.75% |
| 33 | nonlinear | reverse_both | pose | 0.002244 | 0.917154 | 0.025675 | 97.14% |
| 33 | nonlinear | unequal_gains | pose | 0.002244 | 0.629534 | 0.019289 | 96.11% |
| 44 | nonlinear | swap | pose | 0.001608 | 0.550317 | 0.018428 | 95.20% |
| 44 | nonlinear | reverse_one | pose | 0.001608 | 0.544896 | 0.028294 | 95.10% |
| 44 | nonlinear | reverse_both | pose | 0.001608 | 0.550358 | 0.018340 | 96.82% |
| 44 | nonlinear | unequal_gains | pose | 0.001608 | 0.454421 | 0.029063 | 94.06% |
| 55 | nonlinear | swap | pose | 0.002723 | 0.966567 | 0.025779 | 96.47% |
| 55 | nonlinear | reverse_one | pose | 0.002723 | 0.603875 | 0.021076 | 95.57% |
| 55 | nonlinear | reverse_both | pose | 0.002723 | 0.966885 | 0.025790 | 97.18% |
| 55 | nonlinear | unequal_gains | pose | 0.002723 | 0.583628 | 0.019260 | 95.30% |
