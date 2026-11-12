## Freenove 4WD AI Driver

> A local AI driver for the Freenove 4WD Smart Car Kit for Raspberry Pi: a laptop
> dashboard and closed-loop Ollama vision controller, with a safety guard and
> watchdog on the Pi.

**This is a modified fork, not an official Freenove repository.** It is built on the
[Freenove 4WD Smart Car Kit for Raspberry Pi](https://github.com/Freenove/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi)
by Freenove Creative Technology Co., Ltd., which is released under
[CC BY-NC-SA 3.0](http://creativecommons.org/licenses/by-nc-sa/3.0/). This fork is
released under the same licence and is for non-commercial use only. It is not
affiliated with or endorsed by Freenove.

**What changed from the original:**

- **Added:** the `ai_driver/` package, `Code/Server/driver_guard.py`, `tests/`,
  `driver.json`, `requirements-ai.txt`, the `AI_DRIVER*.md` documents and the
  `bugfixes` source-review notes.
- **Modified:** Freenove's `Code/Server/camera.py`, `car.py`, `main.py`, `server.py`,
  `tcp_server.py` and `ultrasonic.py`, for the guarded AI-safe mode (servo-free
  startup, timestamped ultrasonic samples, camera frame timeouts and a vertically
  flipped camera by default), and this README.
- **Unchanged:** everything else, including Freenove's tutorials, datasheets,
  pictures, client and applications. Their original README content follows the
  AI driver section below.

### Local AI driver (laptop + Ollama)

Start with the [operating guide](AI_DRIVER_OPERATING_GUIDE.md) for step-by-step laptop,
SSH and Pi-display instructions, driving controls and shutdown.
The working copy is currently on the Pi; the guide begins with downloading the
laptop application from the Pi and setting it up locally on the laptop.

See [AI_DRIVER.md](AI_DRIVER.md) for the fixed-camera laptop dashboard, guarded Pi
integration, setup and operation. [Verification evidence](AI_DRIVER_VERIFICATION.md)
documents automated tests and the boundary between synthetic software checks and
physical verification.

<div style="text-align: center;">
  <img src='Picture/icon.png' width='45%' style='display:inline-block; margin-right:5px;'/>
  <img src='Picture/icon1.png' width='40%' style='display:inline-block;'/>
</div>

### Connection Board Version
<table>
  <tr>
    <th>PCB Version</th>
    <th>PCB Picture</th>
  </tr>
  <tr>
    <td>V1.0</td>
    <td align="center">
      <img src='Picture/PCB_V1.0.png' width='30%' alt='V1.0'/>
    </td>
  </tr>
  <tr>
    <td>V2.0</td>
    <td align="center">
      <img src='Picture/PCB_V2.0.png' width='30%' alt='V2.0'/>
    </td>
  </tr>
</table>


### Download

* **Use command in console**

	Run following command to download all the files in this repository.

	`git clone https://github.com/Freenove/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi.git`

* **Manually download in browser**

	Click the green "Clone or download" button, then click "Download ZIP" button in the pop-up window.
	Do NOT click the "Open in Desktop" button, it will lead you to install Github software.

> If you meet any difficulties, please contact our support team for help.

### Support

Freenove provides free and quick customer support. Including but not limited to:

* Quality problems of products
* Using Problems of products
* Questions of learning and creation
* Opinions and suggestions
* Ideas and thoughts

Please send an email to:

[support@freenove.com](mailto:support@freenove.com)

We will reply to you within one working day.

### Purchase

Please visit the following page to purchase our products:

http://store.freenove.com

Business customers please contact us through the following email address:

[sale@freenove.com](mailto:sale@freenove.com)

### Copyright

All the files in this repository are released under [Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License](http://creativecommons.org/licenses/by-nc-sa/3.0/).

![markdown](https://i.creativecommons.org/l/by-nc-sa/3.0/88x31.png)

This means you can use them on your own derived works, in part or completely. But NOT for the purpose of commercial use.
You can find a copy of the license in this repository.

Freenove brand and logo are copyright of Freenove Creative Technology Co., Ltd. Can't be used without formal permission.


### About

Freenove is an open-source electronics platform.

Freenove is committed to helping customer quickly realize the creative idea and product prototypes, making it easy to get started for enthusiasts of programing and electronics and launching innovative open source products.

Our services include:

* Robot kits
* Learning kits for Arduino, Raspberry Pi and micro:bit
* Electronic components and modules, tools
* Product customization service

Our code and circuit are open source. You can obtain the details and the latest information through visiting the following web site:

http://www.freenove.com
