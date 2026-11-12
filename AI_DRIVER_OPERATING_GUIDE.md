# AI driver: startup and operating guide

## Your current starting point

**The updated code is currently on the Raspberry Pi, where development is taking
place through SSH. The AI-driver application has not been installed on your laptop.**
The Pi working copy is:

```text
/home/om/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi
```

Your next step is to **download the laptop application from this Pi working copy to
your laptop**, then install its laptop dependencies. Follow Section 2.2 before trying
to launch the dashboard. Nothing done in the Pi's SSH terminal installs a program on
your laptop.

Once setup is complete, use SSH to start the Freenove server **on the Raspberry Pi**,
and run Ollama and the dashboard **locally on the laptop**. A monitor attached to the
Pi is not required for this normal workflow.

This guide describes the implemented software. Physical operation, the actual Wi-Fi
connection and your real Ollama model still need your verification. See
[verification evidence](AI_DRIVER_VERIFICATION.md) and the
[physical handoff notes](AI_DRIVER.md#physical-handoff-and-limitations).

## 1. Which computer runs what?

| Task | Where to run it | Does it need a Pi display? |
|---|---|---|
| Enable/check SSH, configure Pi networking, inspect files | Pi terminal, reached through SSH once available | No; a local display is useful for initial setup/recovery if you cannot reach the Pi |
| Configure the original board parameters (`parameter.py`) | Pi terminal over SSH | No; it uses text prompts |
| Run `main.py --ai-safe --no-gui` | Pi terminal over SSH, preferably inside `tmux` | **No** |
| Capture/stream the car camera for the dashboard | Performed by that Pi server | **No**; streaming does not open a Pi preview window |
| Run Ollama, download/test the model | Laptop's own terminal/Ollama app | No |
| Run the dashboard, view the camera, drive manually or with AI | Laptop's own desktop and terminal | No; the window appears on the laptop |
| See the optional graphical Pi server window | Pi desktop terminal; omit `--no-gui`, retain `--ai-safe` | A Pi graphical session is needed; use an attached monitor for the local procedure below |
| Run the original `camera.py` preview diagnostic | Pi desktop terminal, with the server stopped | Its `Preview.QTGL` window needs a working Pi graphical session; ordinary SSH alone is insufficient |
| Change wiring, inspect the car or confirm actual movement | At the physical car | Requires physical access, not necessarily a display |

There is no AI-driving step that inherently requires a directly attached Pi monitor.
An already-configured remote desktop may substitute for a Pi desktop display for GUI
tasks, subject to its graphics support. Neither remote desktop nor SSH X forwarding
is needed to use the laptop dashboard.

### Keep the terminals separate

Use two terminal windows/tabs on the laptop:

- **Terminal A — Pi/SSH:** after `ssh ...`, commands in this tab run on the Pi.
- **Terminal B — laptop/local:** never SSH in this tab. Run the dashboard here.
- **Terminal C — laptop/local, only if needed:** run `ollama serve` here if Ollama
  is not already running as an app or service.

Typing a command into an SSH tab does **not** run it on the laptop. In particular,
do not run the dashboard or the large Ollama model inside Terminal A.

If your editor is connected through Remote SSH, its integrated terminal may also be
on the Pi. Open a fresh **PowerShell from the Windows Start menu**, or your laptop's
own Terminal app on Linux/macOS, for the download and laptop installation. Merely
seeing a terminal window on the laptop screen does not make that terminal local.

## 2. One-time preparation

### 2.1 Reuse your existing SSH connection details

SSH is already working for this development session. Reuse the Pi username and
hostname/IP from that connection. If you need its address, check your router or run
`hostname -I` in the existing **Pi/SSH** terminal. Keep the laptop and Pi on a mutually
reachable local network.

In the commands below, **`192.168.1.50` is an example address**; replace it with your
Pi's actual address or SSH hostname. The download examples use `om` alongside the
known `/home/om/…` working-copy path. If your SSH login uses a different account, use
that login; the source path remains the actual working-copy path above.

**Laptop, Terminal A:**

```bash
ssh om@192.168.1.50
```

Enter the Pi account's password if requested. Once connected, this tab is a **Pi terminal**.
If your hostname resolves, a command such as `ssh om@raspberrypi.local` also works.

You do not need to enable SSH again or re-image the Pi for this setup. A Pi display
is useful only if you later need local network recovery or the optional desktop
procedures in Section 7.

### 2.2 Download the laptop application FROM the Pi TO the laptop

The updated Pi-side files are already here. Leave them on the Pi. For the laptop,
download these items from the Pi working-copy root:

```text
ai_driver/                         Application source folder
requirements-ai.txt                Laptop Python dependencies
driver.json                        Configuration template
AI_DRIVER.md                       Reference documentation
AI_DRIVER_OPERATING_GUIDE.md        This guide
AI_DRIVER_VERIFICATION.md           Test evidence
LICENSE.txt                        Project license
```

These are sufficient for normal laptop operation. `Code/Server/`, the Pi's
`params.json`, and Pi hardware dependencies stay on the Pi; the laptop app does not
import them. The full Linux integration tests additionally need `tests/` and the
server source, but they are not needed to start driving from the laptop.

**Use one of the following download methods. All download commands run on the
laptop itself, outside SSH.** A fresh upstream Git clone does not contain these
uncommitted AI-driver additions; copy the actual updated Pi files.

#### Windows: local PowerShell

Open PowerShell from the laptop's Start menu. Set the first two variables to the
same host/account you already use for SSH, then run:

```powershell
$PiHost = "192.168.1.50"
$PiUser = "om"
$PiRepo = "/home/om/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi"
$LocalRepo = Join-Path $HOME "Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi"
New-Item -ItemType Directory -Force -Path $LocalRepo | Out-Null
$Items = @("ai_driver", "requirements-ai.txt", "driver.json", "AI_DRIVER.md", "AI_DRIVER_OPERATING_GUIDE.md", "AI_DRIVER_VERIFICATION.md", "LICENSE.txt")
$RemoteItems = @($Items | ForEach-Object { "${PiUser}@${PiHost}:${PiRepo}/$_" })
scp -r @RemoteItems "$LocalRepo"
if ($LASTEXITCODE -ne 0) { throw "Download failed. Check the SSH address, account and source path." }
Set-Location $LocalRepo
Get-ChildItem
```

Enter the Pi's SSH password if requested. `scp` is the OpenSSH file-copy program,
not the dashboard. If it is unavailable on Windows, use the SFTP method below.

#### Linux/macOS: local laptop terminal

```bash
PI_HOST="192.168.1.50"

$PI_USER@$PI_HOST:$PI_REPO/ai_driver" \
  "$PI_USER@$PI_HOST:$PI_REPO/requirements-ai.txt" \
  "$PI_USER@$PI_HOST:$PI_REPO/driver.json" \
  "$PI_USER@$PI_HOST:$PI_REPO/AI_DRIVER.md" \
  "$PI_USER@$PI_HOST:$PI_REPO/AI_DRIVER_OPERATING_GUIDE.md" \
  "$PI_USER@$PI_HOST:$PI_REPO/AI_DRIVER_VERIFICATION.md" \
  "$PI_USER@$PI_HOST:$PI_REPO/LICENSE.txt" \
  "$LOCAL_REPO"
```

Check that `scp` finishes successfully before continuing:

```bash
cd "$LOCAL_REPO"
ls
```

#### SFTP alternative, including Windows WinSCP

1. Open the SFTP client **on the laptop** and connect with the existing Pi SSH host,
   username and password/key. Use your actual SSH port, normally 22.
2. In the **remote/Pi** pane, open
   `/home/om/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi`.
3. In the **local/laptop** pane, create/open a folder named
   `Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi` in your home folder.
4. **Download from remote to local** the seven items listed above. Do not upload a
   fresh upstream copy over the updated Pi project.

After any method, the laptop folder must contain `ai_driver/__main__.py`,
`requirements-ai.txt` and `driver.json`. Next, create a **new laptop virtual
environment** in Section 2.4. The Pi's installed packages do not come with this copy.

These are now two separate copies. When laptop-app source is changed later on the
Pi, close the laptop dashboard and repeat the download. Your laptop-created
`driver.local.json` is not part of the transfer and can retain its settings.

### 2.3 Check the Pi environment and hardware parameters

**Pi/SSH, Terminal A:**

```bash
cd ~/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi/Code/Server
```

Adjust this path if your repository is elsewhere. Use the Python environment that
already runs the original Freenove hardware software. The Pi needs its existing
Picamera2/libcamera, GPIOZero, I²C/SPI and PyQt5 dependencies. The laptop dependency
file alone does not install the Pi hardware stack.

A dependency-import check, which does not construct the car or command movement:

```bash
python3 -c "import PyQt5, picamera2, libcamera, gpiozero, smbus, spidev; print('Pi Python dependency imports OK')"
```

This checks imports, not camera detection, hardware permissions or wiring. If system
Picamera2 is installed but missing in your current Python, check whether an unrelated
virtual environment is active. Use the original working Pi environment rather than
copying the laptop virtual environment to the Pi. Follow the original Freenove setup
instructions for any missing hardware dependencies.

If `params.json` is already correctly configured, keep it. If it is missing/invalid
or you need to correct the board settings:

```bash
python3 parameter.py
```

Answer the connection/PCB questions using your actual hardware. This script is
interactive in the terminal and works over SSH; it needs no monitor or camera preview.
If it asks whether to re-enter values after you have just entered them, answer `no`
unless you need to change them. Always run it on the Pi, since it detects the Pi model.

### 2.4 Prepare the laptop Python environment

**Laptop/local, Terminal B — Linux/macOS:**

```bash
cd ~/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ai.txt
```

**Laptop/local, PowerShell — Windows:** use the folder downloaded in Section 2.2:

```powershell
Set-Location (Join-Path $HOME "Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi")
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

The Windows commands use the environment's interpreter directly, so activating a
PowerShell script is unnecessary. Install dependencies once; you do not need to
recreate the environment each time you drive. The automated checks ran on the Pi
through this SSH environment, with mocked peripherals. Installation and operation
on your actual laptop have not yet been verified on any operating system.

### 2.5 Prepare Ollama on the laptop

**Laptop/local terminal — not SSH:**

```bash
ollama list
```

If Ollama is not running, open the Ollama app/service, or start it in Terminal C:

```bash
ollama serve
```

Keep that terminal open if you started Ollama there. Do not start a second server if
the app/service already owns port 11434. Once Ollama is running, use another **local**
terminal to install your chosen vision model if needed, for example:

```bash
ollama pull qwen2.5vl:7b
```

Use the exact installed tag shown by `ollama list` in the driver configuration. A
different compatible vision model is supported. Pulling downloads the model; ordinary
AI driving then uses the local model. The Pi does not run or need Ollama.

### 2.6 Configure the laptop application

In the **laptop repository root**, make a local configuration copy.

Linux/macOS:

```bash
cp driver.json driver.local.json
```

Windows PowerShell:

```powershell
Copy-Item driver.json driver.local.json
```

Edit `driver.local.json` in your laptop editor. At minimum, set:

```json
{
  "pi_host": "192.168.1.50",
  "command_port": 5000,
  "video_port": 8000,
  "ollama_host": "127.0.0.1",
  "ollama_port": 11434,
  "model": "qwen2.5vl:7b"
}
```

This minimal JSON is valid; omitted settings use defaults. You can instead keep the
additional fields from the supplied file and edit only the addresses/model.

- `pi_host` is the Pi's reachable address, **not** `0.0.0.0` and normally not `127.0.0.1`.
- `ollama_host: 127.0.0.1` means the laptop because the dashboard runs on the laptop.
- Do not include `http://`, a port or `user@` in either host field.
- Default Pi and laptop limits match: **0.75 s** maximum action, **1.0 s** watchdog,
  **30 cm** forward obstacle threshold. If changing these, align both configurations.
  The 30 cm threshold is a default that requires physical tuning.
- Settings take effect when the dashboard restarts. Keep your settings in
  `driver.local.json`, which the Pi-to-laptop download does not overwrite.

## 3. Every driving session: start the Pi server over SSH

### Recommended: keep the server inside `tmux`

`tmux` keeps the Pi program alive if you detach or the administrative SSH session
disconnects. It does not replace the command watchdog. This matters because killing
the Pi server process also kills its software watchdog.

**Laptop Terminal A:** connect to the Pi if not already connected:

```bash
ssh om@192.168.1.50
```

**Now on the Pi:** if `tmux` is not installed, install it once:

```bash
sudo apt install tmux
```

Check whether you already have a session:

```bash
tmux ls
```

If a `freenove-ai` session already exists, attach to it instead of starting another:

```bash
tmux attach -t freenove-ai
```

Otherwise, create one:

```bash
tmux new -s freenove-ai
```

**Inside the Pi's tmux session**, start the guarded server:

```bash
cd ~/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi/Code/Server
QT_QPA_PLATFORM=offscreen python3 -u main.py --ai-safe --no-gui --bind 0.0.0.0 --command-port 5000 --video-port 8000 --watchdog 1.0 --max-duration 0.75 --threshold 30
```

Important details:

- **Retain `--ai-safe`.** It skips servo initialization and enables guarded movement.
  Running the legacy mode is not the startup procedure for this car's broken servos.
- `--no-gui` and the command-local `QT_QPA_PLATFORM=offscreen` select headless operation
  even if an old Qt environment setting exists. Qt is still a dependency, but neither
  an HDMI display nor `ssh -X` is needed. The camera stream remains available.
- `--bind 0.0.0.0` means listen on the Pi's interfaces. The laptop still connects to
  the Pi's real IP/hostname.
- `-u` makes terminal output unbuffered. Look for listeners on ports **5000** and
  **8000**, and `motor_stop reason=startup`. These messages alone do not prove physical
  camera/sensor/motor operation; check the dashboard next.
- Use the original working hardware permissions. If that installation requires root,
  use `sudo env QT_QPA_PLATFORM=offscreen python3 -u main.py` with the same arguments.
  Running the laptop dashboard as root is unnecessary.
- Keep one Pi server and one driving client active. Close the original Freenove client
  before using the new dashboard.

Leave this running. To detach without stopping it, press **Ctrl+B**, release, then **D**.
Reconnect with SSH and `tmux attach -t freenove-ai` whenever you want to see its console.
Detaching or closing the SSH tab is **not** a driving STOP command: the dashboard's
application sockets are separate and AI can continue. Use the dashboard to stop it.

For a short foreground session you can run the same server command directly over SSH
without tmux, but keep that SSH terminal open. For a controlled shutdown use the steps
below rather than closing the terminal or killing the server process.

## 4. Start the dashboard on the laptop

**Laptop/local Terminal B — Linux/macOS:**

```bash
cd ~/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi
source .venv/bin/activate
python -m ai_driver --config driver.local.json
```

**Laptop/local PowerShell — Windows, from the repository root:**

```powershell
.\.venv\Scripts\python.exe -m ai_driver --config driver.local.json
```

The window should appear on your **laptop display**. Do not use the offscreen setting
for normal dashboard operation; that setting belongs to the headless Pi command.

Wait for:

1. **Connected — guarded protocol v1** in command status.
2. **Live JPEG stream** and a current image in the camera area.
3. A numeric **Distance: ... cm** reading.

The application retries connections, but reconnecting never automatically resumes AI.
Both manual and AI movement require valid communication, camera and ultrasonic data.
If a dependency is unavailable, read the displayed error before trying to drive.

## 5. Manual driving, then AI driving

### Manual controls

| Input | Action |
|---|---|
| FORWARD / W / Up arrow | Forward burst |
| BACKWARD / S / Down arrow | Reverse burst |
| LEFT / A / Left arrow | Turn the whole car left |
| RIGHT / D / Right arrow | Turn the whole car right |
| ROTATE LEFT / Q | Rotate the whole car left to inspect |
| ROTATE RIGHT / E | Rotate the whole car right to inspect |
| STOP / Space when not typing | Stop and disable AI |
| EMERGENCY STOP / Escape, including while typing | Latch emergency stop |

Each manual press is a **maximum 0.35 s burst by default**. Releasing it stops earlier;
holding it does not extend movement. Press again for another burst. This is intentional,
so a held/stuck control cannot issue indefinite motion. Click outside the objective
text field before using movement keys. Typing an objective does not drive the car.
Losing dashboard focus during manual operation stops movement.

The camera is fixed. LEFT/RIGHT and ROTATE controls use the drive wheels, never pan/tilt
servos. A close front obstacle blocks forward motion; valid sensor data is still
required for reverse/rotation, which have no rear/side ranging protection.

### Test the actual laptop model

Click **Test Ollama (hi + image)**. The test checks the installed model, performs a
small `hi` inference and submits a small image. Wait for **SUCCESS** and review the
vision status. A reachable endpoint alone is not sufficient. Testing Ollama stops
autonomy first; it does not move the car.

If a previous inference is finishing, the test can report **already busy**. Wait and
retry. Use this button again after correcting an unavailable model or endpoint.

### Start AI

1. Enter an objective, for example **Explore the room safely** or **Find the doorway**.
2. Click **Start AI**, or switch **AI ON**. Either starts using the current objective.
3. Watch the mode, current action, distance and short operational status.

The loop starts stopped and performs:

```text
fresh observation → local model decision → validation and safety checks
→ short bounded action → STOP acknowledgment → new observation
```

The car remains commanded stopped while inference is running. Pauses for inference
are expected; this is not continuous throttle. Oversized/invalid decisions or missing
safety data stop the AI. A reported completed objective also stops it.

To change the objective during operation, **Stop AI**, edit the text, then **Start AI**.
Editing the field alone does not change the objective of an already-running loop.

### Override and recover

- **Stop AI**, **AI OFF**, **STOP** or Space outside text fields stops and returns to
  manual mode. A late model response cannot restart driving.
- Pressing a manual movement control overrides AI, stops the previous action and
  requests the selected manual burst, subject to the safety checks.
- **Escape / EMERGENCY STOP** latches the emergency state. To recover, click
  **Reset emergency → MANUAL**. AI requires a separate deliberate restart.
- After communication loss or a safety/model error, correct the cause and deliberately
  restart AI. If an old HTTP request is still finishing, wait for it to finish first.

## 6. Stop and shut down in this order

1. **Laptop dashboard:** click **Stop AI** or **STOP**. Check its stopped/manual state.
2. **Laptop dashboard:** close the window. The app cancels AI, sends STOP, makes a
   bounded wait for the Pi's STOP acknowledgment, and closes the connections.
3. **Pi/SSH:** attach to the tmux session if detached:

   ```bash
   tmux attach -t freenove-ai
   ```

   Press **Ctrl+C** in the server's foreground terminal. Wait for the shell prompt;
   this invokes the server's shutdown path. Do not use `kill -9` as the normal stop.
4. If finished with the Pi, shut it down from the Pi/SSH terminal:

   ```bash
   sudo shutdown -h now
   ```

   The SSH connection closing is expected. Allow shutdown to finish before removing
   power. Ollama may stay running on the laptop; if you started `ollama serve` in its
   own terminal, Ctrl+C there stops that process.

To stop only AI and keep manual operation available, do just the first step. To restart
the Pi server, stop the dashboard first, stop the server with Ctrl+C, run the same
guarded command again, then reopen the dashboard. Restarting AI is always explicit.

## 7. When using a display directly attached to the Pi

These are **optional local-desktop procedures**, not prerequisites for the normal
SSH/laptop workflow. Log into the Pi desktop and open a terminal on that desktop.
If a server is already running in tmux, stop it first; do not start a competing copy.

### Show the Pi's server window

```bash
cd ~/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi/Code/Server
unset QT_QPA_PLATFORM
python3 main.py --ai-safe --bind 0.0.0.0
```

Omitting `--no-gui` displays the Pi's small server window; **`--ai-safe` remains present**.
The laptop still runs the driving dashboard and Ollama. You do not need to click
anything on the Pi for each AI action. Closing the Pi server window shuts down that
server; pressing its server-off button stops its guarded service.

### Use the original local camera-preview diagnostic

With the dashboard and Pi server stopped, from the **Pi desktop terminal**:

```bash
cd ~/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi/Code/Server
unset QT_QPA_PLATFORM
python3 camera.py
```

The original script requests a QTGL preview, waits about ten seconds and saves
`image.jpg` in that directory. This is the display-dependent camera diagnostic;
the server's ordinary streaming path does not call this preview function. An SSH
terminal without a graphical session is not the right place to run this particular
diagnostic. Restart the guarded server afterwards to use the laptop stream again.

Text-based diagnostics such as `python3 test.py Ultrasonic` can run in a Pi SSH
terminal with the main server stopped; stop the diagnostic with Ctrl+C before
restarting the server. They use actual hardware, not the development simulator.
The standalone motor diagnostic also commands actual motors and is outside the new
dashboard's arbitration/watchdog. Do not use the legacy servo-based modes/diagnostics
for this fixed-camera setup.

## 8. Useful checks, logs and common problems

**Pi/SSH checks**, from a second SSH tab while the server is running:

```bash
hostname -I
tmux ls
ss -ltnp 'sport = :5000 or sport = :8000'
```

These inspect addresses, sessions and listeners. They are not motor commands. The
Pi console is available by reattaching to tmux. A listener is only a startup check;
the dashboard's guarded handshake, image and numeric distance are the runtime checks.

**Laptop logs:** `ai-driver.log`, with rotating backups, in the directory from which
you launched the app. For extra protocol diagnostics, restart with:

```bash
python -m ai_driver --config driver.local.json --debug
```

On Windows use `.\.venv\Scripts\python.exe` in place of `python`. Logs include action
durations, frame age, distance, inference latency, rejection reasons and STOP events.
Session tokens are redacted and images are not dumped into logs.

| Problem | What to do |
|---|---|
| SSH fails | Check the Pi address, configured account, SSH service and Wi-Fi. Use a Pi display for recovery if no other management path is available. |
| Cannot connect, although SSH works | Check the Python server, its `0.0.0.0` bind, ports 5000/8000, and whether the local network/firewall permits them. SSH port 22 alone is not enough. |
| Address already in use / client rejected | Check the existing tmux session, old Freenove server/client and any second dashboard. Stop the existing program normally rather than starting another copy. |
| Guarded handshake missing | Copy the updated Pi files and use `--ai-safe`; the original upstream server alone is not sufficient. |
| Pi Qt says it cannot connect to a display | Use the full headless command with command-local `QT_QPA_PLATFORM=offscreen` and `--no-gui`; do not set `DISPLAY=:0` in plain SSH to try to fix headless startup. |
| Laptop app runs but no window appears | Run it locally in the laptop desktop session. Remove an inherited offscreen setting (`unset QT_QPA_PLATFORM` in a Unix shell, or `Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue` in PowerShell). |
| Pi Python module missing | Check the Pi interpreter and original Freenove dependencies, not the laptop environment. A Pi display does not fix an import error. |
| Camera unavailable/stale | Read Pi camera logs and check for another camera process, then check physical camera configuration. Streaming itself does not need a Pi display. |
| Distance unavailable / movement blocked | Inspect ultrasonic data and wiring. Invalid/no-echo/stale readings intentionally block movement; do not substitute a made-up distance. |
| Ollama test fails | Check Ollama on the **laptop**, its installed vision tag and the displayed inference error. `127.0.0.1` inside an SSH command refers to the Pi, not the laptop. |
| Inference slow / deadline exceeded | Read the logged latency and confirm the model fits the laptop GPU. The car stays stopped; choose/tune the local model before changing time budgets. |
| Manual key holds do not keep driving | Expected: each press is a bounded burst; release and press again. |
| Reconnect succeeds but AI stays off | Expected: review the status and deliberately click Start AI again. |

For the complete settings reference and explanations of thresholds, sensor coverage
and watchdog limitations, see [AI_DRIVER.md](AI_DRIVER.md). No application driving
command normally goes through SSH; SSH is for managing the Pi server and inspecting
it, while driving/video/sensor traffic uses the two configured application ports.
