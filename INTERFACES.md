# Shared integration contract

Read src/darwin/types.py and config.py. Lead owns these, runtime.py, episodes.py, safety.py, cli.py, evaluation.py, configs, docs and dependency lock. Workers own listed directories and uniquely named tests. No Git mutations. SI units; host monotonic timestamps, simulated clock separately declared. Full-cycle model: measure pulse + settle displacement divided by full-cycle time (measurement_version=pulse_plus_settle_v1). Same model/controller/runtime in both modes. No hidden plant or mapping in public contracts.

Learning worker API:
- learning.model.MotionModel(ridge_lambda=.001); fit(list[Transition]) -> metrics dict; predict(actions Nx2) -> ndarray Nx2; model_id, training_action_ids, metrics; save(path), classmethod load(path, config_id=None, calibration_id=None). Zero action predicts zero propulsion.
- learning.model.evaluate(model, transitions) -> dict with v_rmse_mps, omega_rmse_radps, normalized_rmse, count.
- control.exploration.probe_actions(seed,count,pulse_ms,episode_id) -> list[RequestedAction].
- control.policy.Policy(config).choose(pose,target tuple,model,safety_context=None) -> RequestedAction|None; target reached handled runtime. Predicted average v/omega multiplied by full cycle seconds in rollouts.
- simulation.environment.SimulationEnvironment(config): now property; observe()->Pose; execute(action)->ActuationReceipt (advances full pulse+settle fake clock); stop(); scramble(name=None)->str opaque change id; reset_pose(x=.5,y=.5,theta=0) explicit logged intervention by caller; truth_for_renderer()->(x,y,theta) privileged only renderer call; audit_records list consumed solely audit writer; fault(name,enabled). Observation synthetic noisy pose. property last_frame optional. Runtime owns generated-frame tracking through vision worker.

Vision/hardware worker API:
- vision.calibration.Calibration.from_corners(points_px,width_m,height_m,image_size,camera_id='simulation',heading_offset_rad=0,marker_height_m=0); to_dict/from_dict/save/load; image_to_world(points Nx2), world_to_image(points Nx2); calibration_id.
- vision.tracking.Tracker(marker_id=7,heading_offset_rad=0).observe(frame,calibration)->Pose.
- vision.markers.generate_marker(marker_id,output); render_frame(x,y,theta,calibration,frame_id,timestamp,hide=False)->Frame. Robot front is right edge direction of marker (corner 0 to corner 1), world theta 0 = +x.
- io.serial_link.SerialTransport(port,baudrate=115200,ack_timeout_ms=100): transport protocol methods. io.fake_serial.FakeTransport same, fault(name,enabled), health.
- io.actuator.HardwareActuator(transport,config): execute(action)->receipt starts a bounded pulse and explicitly STOP after duration, settle; stop() invalidates delayed writes; scramble(name=None)->opaque id; audit_records. It should support cancellation and a safety callback during pulse, agree with lead on details.
- io.camera.make_camera(config) -> CameraSource; optional imports lazy. vision.validation.run_synthetic_test(output)->report dict; io.fake_serial.run_protocol_tests()->report dict.

UI/data worker API:
- recording.writer.RunWriter(root='data/runs',metadata=None,config=None): run_id, path; append(kind,record), flush(), close(). JSONL filenames use kind e.g observations/actions/transitions/events/actuator_audit. No overwrite; raw immutable; bounded queue with error rather than missing essentials. Save metadata/config/calibration.
- recording.replay.load_transitions(run_path)->list[Transition] explicit whitelist.
- recording.replay.ReplayRuntime(run_path): snapshot(), command(name,payload), latest_jpeg()->bytes|None. No live transport. Timeline seek/play read only.
- recording.export.export_run(run_path,output)->path.
- web.server.create_app(runtime) -> FastAPI. Runtime.command(name,payload=None)->dict quick return; snapshot()->dict JSON safe; latest_jpeg()->bytes|None; public_config()->dict; list_runs()->list; close(). Endpoints as handoff, alias command names hyphenated. command stop must be prompt; worker doesn't access motors. UI snapshot keys mode,state,stop_reason,run_id,pose,target,trail,predicted_motion,transport_health,frame_age_ms,ack_age_ms,valid_sample_count,rejected_sample_count,model_id,validation_metrics,recovery_phase,busy,calibration,events. Lease: browser sends heartbeat command payload owner_id, episode-start includes owner_id. Buttons no fabricated metrics. Calibration corners API through runtime. Fault command(name enabled) for diagnostics. Export command returns path.
