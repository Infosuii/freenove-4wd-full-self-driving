# Freenove local AI driver

A laptop dashboard and closed-loop Ollama controller built around the original
Freenove server, camera transport, ultrasonic sensor and `Ordinary_Car` motor driver.

For step-by-step instructions organized by **laptop terminal, Pi over SSH, and Pi
display**, see the [startup and operating guide](AI_DRIVER_OPERATING_GUIDE.md).

**Development and tests ran on the Pi through SSH, using synthetic peripherals and
model responses. Physical car peripherals were not operated or verified. The laptop
has not been set up yet, and its real Ollama installation has not been tested.** See
[verification evidence and acceptance matrix](AI_DRIVER_VERIFICATION.md).

## Start the system

### 1. Raspberry Pi

Use the original Freenove installation and Raspberry Pi OS hardware dependencies.
Run from `Code/Server` so the existing `params.json` is found. If hardware parameters
have not already been configured, run the original `python3 parameter.py` and enter
the actual connection/PCB versions; do not guess these values. The guarded startup
reports an error rather than prompting invisibly if this file is missing/invalid.

```bash
cd ~/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi/Code/Server
python3 main.py --ai-safe --no-gui --bind 0.0.0.0 --command-port 5000 --video-port 8000 --watchdog 1.0 --max-duration 0.75 --threshold 30
```

Use the Python environment/permissions already used for the original Freenove
hardware installation. `--no-gui` uses Qt's offscreen backend; it still needs the
existing PyQt5 dependency. Only one server and one command client should be active.

**Use `--ai-safe` for this car.** This profile skips servo construction entirely,
rejects servo commands and the legacy autonomous/rotation modes, and routes all
movement through the guard. `Servo()` in the original baseline initializes servo
positions, so merely avoiding pan commands would not have been sufficient.

The original client, motor driver, peripheral implementations and diagnostics remain
available. Running without `--ai-safe` retains the legacy features and their original
movement/servo behavior; the new dashboard deliberately refuses to drive that
unguarded profile. The guarded profile does not run the legacy LED animation worker.

### 2. Laptop setup

The source currently resides on the Pi at
`/home/om/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi`. First follow the operating
guide's **Section 2.2: Download the laptop application FROM the Pi TO the laptop**.
Then run the commands in this section in a local laptop terminal, not through SSH.

Python 3.10+; PyQt5 and Pillow are the two runtime packages, both already used by the
original laptop client. PyQt5 provides the responsive GUI and Pillow validates and
resizes JPEG images. HTTP, TCP, threading, JSON and tests use Python's standard library.
No GPIO, Picamera2, ROS, cloud API, or large model is installed on the laptop by this app.

From the downloaded application folder on the laptop:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ai.txt
```

Windows: activate with `.venv\Scripts\activate` instead. The laptop code uses portable
Qt/stdlib APIs; the automated original-server integration tests ran in the Pi's Linux
environment. The actual laptop installation and display remain to be verified.

Configure a vision model in your existing laptop Ollama installation, for example:

```bash
ollama pull qwen2.5vl:7b
ollama serve
```

`ollama serve` is only needed if Ollama is not already running as a service/app.
The example model is configurable; its speed/VRAM use has **not** been measured here.
Only one model/request is used at a time.

### 3. Configuration and launch

Edit `driver.json`: set `pi_host` to your Pi's hostname/IP and `model` to the exact
installed Ollama tag. The endpoint defaults to laptop loopback `127.0.0.1:11434`.
Hosts are plain hostnames/IPs, without `http://` or paths. No network scanning or SSH
is involved; hostname resolution and bounded connection retries handle connection.

```bash
python -m ai_driver --config driver.json
```

You can keep private settings in ignored `driver.local.json` and pass that filename.
Restart the app after changing configuration. All laptop settings and validation
live in `ai_driver/config.py`; the JSON file only needs to specify overrides.

| Setting | Default | Meaning |
|---|---:|---|
| `pi_host` | `raspberrypi.local` | Pi address |
| `command_port`, `video_port` | `5000`, `8000` | Original command and JPEG services |
| `ollama_host`, `ollama_port` | `127.0.0.1`, `11434` | Laptop Ollama |
| `model` | `qwen2.5vl:7b` | Any compatible installed vision tag |
| `max_action_duration` | `0.75` seconds | Model durations above this are **rejected**, not clamped |
| `manual_duration` | `0.35` seconds | Each manual press is one burst |
| `watchdog_timeout` | `1.0` second | Communication freshness budget; matched against Pi limits |
| `ultrasonic_threshold` | `30` cm | Forward blocking threshold, inclusive |
| `speed` | `1200` | Raw duty request; original server scaling makes this `960` at the motor API |
| `sensor_max_age`, `frame_max_age` | `0.5`, `1.0` seconds | Reject old telemetry/images |
| `poll_interval` | `0.2` seconds | Request existing ultrasonic telemetry |
| `loop_interval`, `settle_time` | `0.2`, `0.15` seconds | Minimum reassessment pause / new-view wait after STOP ACK |
| `inference_timeout`, `decision_max_age` | `30`, `30` seconds | Wall-time inference budget / observation validity budget |
| `min_confidence` | `0.6` | Conservative policy threshold; model confidence is not calibrated probability |
| `history_size`, `image_size` | `12`, `448` | Bounded history and maximum model-image side length |
| `reconnect_interval`, `socket_timeout` | `1.0`, `0.1` seconds | Reconnect delay / bounded laptop send-receive wait |

Pi limits are independent command-line settings. Keep their watchdog, maximum duration
and obstacle threshold aligned with the laptop. The handshake rejects incompatible
limits. Laptop speed and Pi raw duties are capped at `1500`; duration must be no longer
than the watchdog (and the watchdog no longer than two seconds).

**30 cm is a default — tune it using physical testing.** It comes from the original
`Car.run_motor_ultrasonic()` front-obstacle rule, which uses 30 cm, and agrees with
GPIOZero's documented 0.3 m threshold default. The repository's ultrasonic wrapper
configures a 3 m maximum; values outside `(0, 300]` cm are rejected. No ultrasonic
datasheet is included in this repository, and this is not a measured stopping distance.
No extra smoothing/hysteresis constants were invented. Guarded readings use actual
timestamped GPIOZero echo samples: a failed echo becomes unavailable immediately,
rather than allowing GPIOZero's old smoothed value to appear fresh.

## Driving

1. Wait for **Connected — guarded protocol v1**, a current camera image and distance.
2. Use FORWARD/BACKWARD/LEFT/RIGHT, WASD or arrow keys. Q/E and ROTATE buttons turn
   the **whole vehicle** to inspect. LEFT/RIGHT also turn the body; they do not strafe.
3. Each press sends a bounded burst. Release or Space sends STOP. Holding a key/button
   does not renew motion. Typing an objective does not drive the car. Leaving the
   window during manual operation stops it.
4. Click **Test Ollama (hi + image)**. This requests `/api/tags`, `/api/show`, a real
   `hi` inference and a small image inference. Connection, installation, vision status
   and useful failure details are displayed. Older Ollama versions without capability
   metadata are labeled **Image request accepted**, not proven visual understanding.
5. Enter your objective and click **Start AI**, or switch **AI ON**. **AI OFF**, **Stop
   AI**, Space or manual movement disables autonomy; a late model response cannot
   restart it. Reconnection never automatically resumes autonomy.
6. **EMERGENCY STOP / Escape** latches emergency mode immediately, independently of
   inference. **Reset emergency → MANUAL** is deliberate recovery; restarting AI is a
   separate action. Escape works even while editing the objective.

Both manual and AI movement require valid camera, sensor and guarded communication.
A close front obstacle blocks forward motion; reverse/body inspection remain possible
with valid sensor/video data. There is no rear/side range sensor protection.

While the model thinks, the motor command is STOP. For each cycle:

```text
STOP acknowledgement → wait for a new frame → image + distance + objective + recent state
  → local Ollama JSON → strict validation → safety / single-owner arbiter
  → bounded CMD_MOTOR → Pi guard → existing Ordinary_Car → existing PCA9685
  → STOP acknowledgement → new observation
```

The model returns `{action, duration, confidence, status, goal_reached}`. Only seven
actions are allowed. Invalid JSON, duplicate/extra/missing fields, nonfinite/negative/
oversized durations, wrong types and arbitrary actions are rejected. Goal completion
requires STOP. `status` is a brief operational summary, not hidden reasoning.

History is a 12-entry rolling buffer. Repeated or six-step alternating action patterns
request reassessment; only a purposeful inspection rotation or STOP can follow that
request. Continuing the same failed strategy stops the AI for operator review. This
is a conservative pattern detector, not visual odometry or proof that the car is stuck.

## Architecture and safety ownership

- `ai_driver/gui.py`: Qt main thread; latest-frame display and status refresh every
  50 ms. A GUI heartbeat lets the independent controller detect a stalled GUI.
- `network.py`, `protocol.py`: separate command/video threads, bounded line and JPEG
  framing, latest-image replacement, numeric telemetry, visible errors and reconnects.
  Movement is sent synchronously with a short socket timeout; it is never queued for retry.
- `controller.py`: one locked movement arbiter, cancellation epochs, explicit mode and
  action lifecycle, and an independent 20 ms safety monitor. Priority: emergency,
  collision, hardware/camera protection, communication watchdog, manual, AI, objective.
- `driver.py`, `ollama.py`: closed-loop controller and one inference at a time. Cancellation
  ignores late results. A timed-out HTTP worker may finish later, but it cannot drive;
  a new run is blocked until that worker finishes. Images/context do not accumulate.
- `Code/Server/driver_guard.py`: a small opt-in parser/lease guard integrated into the
  existing `main.py` workers, `Server` and `TCPServer`. It owns motor writes in guarded
  mode and calls the original motor abstraction with the original 0.8 scale.
- The Pi guard checks expiration every 10 ms using a monotonic clock. A motor lease ends
  at `min(requested duration, watchdog timeout)`. With defaults, duration expires first.
  **Sensor polls, a connected socket and Ollama activity do not extend a lease.** The Pi
  also stops on command disconnect, invalid sensor state, obstacle, malformed control,
  overlapping motion and shutdown. Hardware write failures latch a fault and retry STOP.
- New logs use a logging worker rather than blocking inference/GUI or guarded motor
  code on file/console output. The original hardware and camera servers are reused.

### Wire protocol additions

The original ports, newline/hash delimiters, raw motor command and sonic response are
retained. A small extension is necessary because original commands have no lifetime.

```text
Laptop → CMD_DRIVER#HELLO#1\n
Pi     → CMD_DRIVER#READY#1#<session>#<watchdog_s>#<max_duration_s>#<threshold_cm>\n
Laptop → CMD_MOTOR#<FL>#<BL>#<FR>#<BR>#<duration_ms>#<session>#<sequence>\n
Pi     → CMD_DRIVER#ACTING#<sequence>\n
Laptop → CMD_MOTOR#0#0#0#0\n
Pi     → CMD_DRIVER#STOPPED#requested#<last_accepted_sequence>\n
Laptop → CMD_SONIC\n
Pi     → CMD_MODE#3#<distance_cm_or_nan>\n
```

Automatic stops use `STOPPED#completed`, `#watchdog`, `#obstacle`, etc., followed by
the sequence. Rejections use `CMD_DRIVER#ERROR#<reason>`. New connections negotiate a
fresh session. Stale sequences/session tokens cannot drive. STOP remains the exact
legacy zero-duty command; its ACK is correlated to the last motion sequence.

Video is still `struct.pack('<I', jpeg_length) + jpeg_bytes`. Partial TCP chunks are
reassembled; bad JPEG payloads are discarded. Impossible lengths/truncated connections
cause reconnect because the legacy stream contains no reliable resynchronization marker.

| Action | Raw wheel signs, FL / BL / FR / BR |
|---|---|
| FORWARD | `+ + + +` |
| BACKWARD | `- - - -` |
| LEFT / ROTATE_LEFT | `- - + +` |
| RIGHT / ROTATE_RIGHT | `+ + - -` |
| STOP | `0 0 0 0` |

These match the executable examples in the original `motor.py`. The original
`CMD_CAR_ROTATE` worker is an infinite, battery-compensated mixed-motion loop, so it
is unsuitable for bounded fixed-camera inspection. Timed raw motor turns use the
existing motor implementation instead; there is no second motor driver.

## Shutdown and troubleshooting

Closing the dashboard cancels AI, sends STOP, stops the controller, waits up to 0.3 s
for a sequence-correlated STOP ACK, and then closes both sockets/resources. An ACK
means the Pi called zero motor duties; it does not prove mechanical standstill.

Laptop logs: `ai-driver.log` in the launch directory, rotating at 2 MB with three
backups. Add `--debug` for protocol details; session tokens are redacted. Logs include
observations/frame sequence and age, numeric distance, inference latency, validated
action/duration/confidence, lifecycle and stop reasons. Images are not logged. Capture
the Pi console alongside these logs when doing physical tests.

| Symptom | Check |
|---|---|
| Connection refused / wrong host | Pi process running, address, matching ports, LAN connectivity |
| Guarded handshake missing | Pi must run the updated `main.py --ai-safe`; old server is intentionally not drive-ready |
| Incompatible safety limits | Align Pi CLI and laptop JSON thresholds/durations/watchdog |
| Camera stale / malformed length | Pi camera logs, ribbon/camera configuration, stream latency; reconnect is automatic |
| Ultrasonic unavailable | Actual wiring/echo and GPIOZero compatibility; zero/no-echo is not treated as clear space |
| Model missing | Exact Ollama model tag and `ollama pull` |
| Vision unsupported / model error | Use a vision-capable model and an Ollama version supporting image chat and JSON schema format |
| Inference timeout / expired observation | Inspect real latency before adjusting the 30 s budgets; the car stays stopped |
| Repeated/oscillating actions | Review the view/objective; change the immediate strategy and deliberately restart |
| Pi hardware fault | Inspect Pi I²C/motor logs and hardware; restart guarded server after fixing the fault |

## Tests and explicit development smoke run

The test doubles live only under `tests/`. Production never silently substitutes them.
On Linux, using the installed Qt/Pillow and GPIOZero (for the sensor adapter test):

```bash
QT_QPA_PLATFORM=offscreen python -B -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen python -B -m tests.smoke --seconds 3
QT_QPA_PLATFORM=offscreen python -B -m ai_driver --config tests/offline.json --quit-after 2
```

The smoke tool explicitly uses **synthetic camera, ultrasonic, motors and scripted AI**.
It runs the original Pi workers, real loopback TCP/HTTP, and production dashboard,
asserting three decisions, two bounded movement calls and a final STOP. Its window is
labeled SIMULATION. `--screenshot /path/to/file.png` optionally captures the synthetic UI.
The offline command demonstrates visible connection failures without a Pi. Remove
`QT_QPA_PLATFORM=offscreen` to inspect either laptop window on a desktop display.

## Physical handoff and limitations

The software chain is implemented and tested; the following still need your physical
verification before relying on autonomous navigation:

- Correct board parameters, Pi 5 dependencies, GPIO/I²C access, motor polarity/wheel
  order under load, usable duty/speed, motor braking, traction and battery behavior.
- Fixed camera orientation/focus/field of view, real JPEG latency and backlog, lighting,
  and confirmation that the guarded startup causes no servo actuation. Your pre-existing
  `camera.py` vertical-flip change was preserved.
- Front ultrasonic mounting/orientation, range/accuracy, no-echo behavior and surfaces
  it misses; confirm the 30 cm default and the 0.5 s freshness window against actual
  stopping distance. Guarded mode intentionally does not mask failed echoes with old data.
- Real body rotation direction/angle, footprint clearance and settling time. Turns are
  timed, not angle-calibrated. Rear and side obstacles, drop-offs, thin/soft/glass objects
  and moving people are not comprehensively covered by a single front range sensor.
- Actual Wi-Fi loss, laptop termination, GUI freeze, emergency-stop response and Pi
  watchdog timing under load. Python/OS scheduling and hardware I/O are not hard-real-time.
- Real Ollama vision capability, quantization/VRAM fit on the RTX 5070 Ti, latency,
  schema adherence, scene/object recognition and ability to pursue your chosen objectives.
  The 30 s inference budget is an assumption, not a measured model benchmark.
- Native laptop display/keyboard behavior and final application exit on your OS.

There is no SLAM, odometry, heading sensor, map, calibrated confidence, reliable global
progress estimate, or guarantee that an objective can be achieved. A STOP ACK and
freshly received JPEG are software observations: the old stream has no acquisition
timestamp, so receive time cannot prove capture time. The software watchdog cannot
stop hardware if the Pi process/OS itself dies or I²C blocks indefinitely. The inherited
protocol is plain TCP for a trusted local LAN; session tokens are freshness checks,
not authentication. Original standalone diagnostics remain useful for your hardware
checks; the legacy servo-based modes are outside this fixed-camera driving profile.
