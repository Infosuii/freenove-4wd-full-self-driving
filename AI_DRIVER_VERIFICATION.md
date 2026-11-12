# AI driver verification record

Execution host: **the Raspberry Pi accessed through SSH**, as clarified by the user.
The working copy is `/home/om/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi` on the Pi.
The laptop application has not yet been copied to, installed on, or tested on the
user's laptop. Earlier references to a "local run" mean local to this remote Pi
execution environment, not local to the laptop.

Environment: Linux, Python 3.13.5, Qt 5.15.15, Pillow 11.1.0, GPIOZero 2.0.1; 2026-09-17.
Qt/Pillow were already installed and imported successfully; no extra framework or
new runtime package was needed in this development environment.

## Evidence boundaries

- **No physical car peripherals operated or verified by these tests.** The code was
  executed on the Pi, but camera/sensor/motor boundaries were replaced by test doubles.
  This does not assert that the car is physically disconnected. Synthetic data are
  explicitly confined to test/development modules.
- **No real Ollama server exercised.** A real GET to
  `http://127.0.0.1:11434/api/tags` returned connection refused **on the Pi**. That probe
  did not reach or test the laptop's Ollama installation. Ollama behavior was verified
  with injected HTTP responses and real HTTP stand-ins on the Pi's loopback interface.
- **Real original Freenove code executed on the Pi with hardware mocked:** `main.py` window/startup and
  command/car/video workers, `Server`, `TCPServer`, motor and PCA9685 logic. Peripherals
  were replaced at interfaces; a complete integration test executes the original motor
  and PCA9685 modules with **only SMBus mocked at the motor hardware boundary**.
- Original diagnostics were imported and their entry points checked. They were not
  run on hardware. GPIOZero's echo-read boundary was mocked to exercise freshness;
  the new adapter depends on GPIOZero's `_read` implementation and needs Pi confirmation.
- Pi OS dependency loading and the real camera/I²C/GPIO startup are hardware-dependent.
  Full `main.py` CLI startup against the actual car peripherals was not exercised.
- The offscreen GUI and TCP/HTTP integration checks all ran in this Pi environment.
  They do not verify the laptop's GUI/GPU, real laptop-to-Pi network traffic or model
  performance. No tests need to be reinterpreted as physical driving because the
  development host happens to be the Pi.

## Automated acceptance matrix

Final full-suite command and actual summary:

```text
QT_QPA_PLATFORM=offscreen python -B -m unittest discover -s tests -q

----------------------------------------------------------------------
Ran 82 tests in 5.209s

OK
```

The verbose full-suite run also passed all 82 tests. `git diff --check` passed.

All test names below are within the passing unittest suite, unless labeled otherwise.
Tests use subtests to cover many values/edges; method count is not the number of cases.

| Requirement | Evidence | Classification |
|---|---|---|
| Pi server startup/workers | `RealServerIntegrationTests.test_original_main_starts_with_mock_hardware_and_correct_profile` | Automated; real server code, fake hardware |
| Preserve baseline motor semantics | `BaselineTests.test_motor_signs_match_original_executable_examples`, `test_original_motor_runs_with_only_pca9685_mocked` | Automated AST comparison + original motor execution with fake peripheral |
| Original diagnostic entry points | `BaselineTests.test_existing_hardware_diagnostic_entrypoints_import_without_hardware` | Automated import; actual device tests require hardware |
| No servo use | `BaselineTests.test_safe_car_initialization_never_constructs_servo`, guard rejected-command tests, integration wire inspection | Automated; no servo construction/commands in guarded path |
| Camera framing and freshness | `ProtocolTests` arbitrary split, malformed/truncated JPEG and replace/stale buffer tests | Automated synthetic bytes |
| Camera lifecycle | `BaselineTests.test_original_camera_lifecycle_with_picamera2_boundary_mocked` | Original Camera/StreamingOutput; Picamera2 mocked |
| Command connection/framing | `NetworkBoundaryTests.test_original_tcp_server_reassembles_bytewise_commands_and_disconnect_callback` | Real loopback TCP and original server transport |
| Missing dependencies visible | `NetworkBoundaryTests.test_real_client_fails_visibly_with_absent_local_services`; production GUI offline run | Automated + real offscreen app on Pi, no live hardware service |
| Reconnect requires restart | `RealServerIntegrationTests.test_socket_disconnect_reconnect_requires_deliberate_ai_restart` | Real socket disconnect/reconnect, fake motor |
| GUI image/distance | `GuiTests.test_camera_and_ultrasonic_render_synthetic_runtime_data` | Real Qt rendering, synthetic telemetry/JPEG |
| Buttons and keys | `GuiTests.test_buttons_send_exact_motor_bytes_and_release_stop`, `test_keyboard_uses_same_paths_and_does_not_drive_while_typing` | Real Qt events; exact mocked transport bytes |
| Manual commands reach motor | `RealServerIntegrationTests.test_all_actions_through_real_sockets_parser_to_original_motor_interface` | All actions over real TCP to fake motor call |
| AI controls/objective | `GuiTests` start/stop/toggle/emergency tests; closed-loop observation assertions | Automated real Qt events + mocked model |
| Ollama connection/model/vision/hi | `OllamaTests` success/failure/probe/request/response tests | HTTP mocks; real urllib against local HTTP stub |
| Structured output validation | `ValidationTests` | Automated valid actions, all missing fields, duplicate/extra fields, JSON/type/action/duration/status/confidence/goal rejection cases |
| Safety priority and modes | `ControllerTests.test_explicit_priority_order_under_simultaneous_faults`, all-state-transition test | Automated deterministic priority/transition edges |
| Every sensor failure | `ProtocolTests.test_all_invalid_sensor_values`, guard/controller sensor-failure tests | Missing/zero/negative/NaN/infinity/oversized/stale test inputs |
| Stop on close obstacle | Controller/guard tests; `test_obstacle_is_enforced_on_pi_independent_of_laptop` | Unit + real TCP integration, synthetic range |
| Watchdog, silence, deadlines | `GuardTests` exact fake-clock deadlines, non-renewing telemetry and independent real watchdog thread; integration silence test | Automated; mocked motors, local scheduler only |
| Bounded rotation/action lifecycle | Controller completion/cancellation/interruption/overlap tests; guard duration/rejection tests | Automated |
| Manual/AI/emergency arbitration | Controller concurrent-writer and priority tests; guard serialization tests | Automated Python thread races, instrumented motor/transport |
| Slow/hanging/failed inference | `DriverTests` timeout, error, late-result, emergency responsiveness tests | Blocking/scripted model doubles |
| Missing camera/invalid/internal state | Controller safety-condition tests and driver camera-after-action/model-error tests | Automated fail-safe stops |
| STOP acknowledgement | Network sequence-correlation tests; driver missing startup/post-action ACK tests | Automated + real server ACKs in integration |
| Complete software chain | `test_complete_camera_ollama_validation_safety_network_motor_closed_loop` and `test_complete_pipeline_executes_original_motor_and_pca_with_only_smbus_mocked` | Camera → model → validation → safety → arbiter → real TCP → real Pi guard → original motor/PCA logic (fake SMBus) |
| Observe repeatedly rather than indefinite drive | `DriverTests.test_closed_loop_reobserves_bounded_actions_objective_and_state`; full integration test | Multiple distinct images/decisions, interleaved STOPs, exact motor sequence |
| Oscillation/reassessment/bounded memory | Driver oscillation recovery/rejection and controller memory tests | Synthetic action histories and new-view assertions |
| Shutdown | Runtime/controller/GUI shutdown-order tests | Cancel → STOP → bounded ACK wait → socket/resource close |
| Logging | Debug-token-redaction test; actual smoke and offline logs | Automated redaction + local run evidence |

## Runs on the Pi development host

Laptop-application code executed on the Pi against unused loopback service ports:

```bash
QT_QPA_PLATFORM=offscreen python -B -m ai_driver --config tests/offline.json --quit-after 2
```

Observed connection-refused reports for both Pi services, visible connection-error
state, no movement, attempted shutdown STOP, `stop_acknowledged=False`, and clean exit.
This generated the laptop application's rotating log **on the Pi** using the
production logging path. It was not an installation or run on the actual laptop.

Explicit development smoke run:

```bash
QT_QPA_PLATFORM=offscreen python -B -m tests.smoke --seconds 3 --screenshot /tmp/opencode/ai-driver-dashboard.png
```

Actual terminal result:

```text
SMOKE PASS: GUI + original Pi workers + loopback TCP/HTTP + synthetic peripherals/model; 3 decisions, 2 bounded motor calls, final STOP
```

Logs showed different observation frame sequences (4, 10, 16), a FORWARD call and a
ROTATE_LEFT call each lasting 0.100 s, sequence-correlated STOP ACKs, and a final
scripted goal STOP. These are synthetic software events, **not physical motion or
real model reasoning**. The offscreen screenshot was rendered and inspected.

An initial smoke harness shared Qt's last-window-close signal with the original Pi
window, causing the Pi's `sys.exit` callback to exit before the smoke assertions. The
harness was corrected to separate this lifecycle callback; the rerun printed the
explicit PASS above. Production Pi/laptop run in separate processes.

## Running and interpreting checks

```bash
QT_QPA_PLATFORM=offscreen python -B -m unittest discover -s tests -v
git diff --check
```

Expected failure tests intentionally emit error/STOP logs; those are assertions of
failure handling, not failed test methods. The environment emitted Qt offscreen
plugin/runtime-directory notices; widget tests and application runs still completed.
Source compilation is tested in-memory because existing user-owned bytecode caches
in `Code/Server/__pycache__` were not writable. No cache permissions were changed.

For everything still requiring physical verification and remaining navigation/sensor/
watchdog limitations, see [the physical handoff section](AI_DRIVER.md#physical-handoff-and-limitations).
