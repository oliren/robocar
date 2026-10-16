# Autostart — robot_car.service

Runs the whole robot (motor driver + web server) on boot via systemd,
using the `robot_car_bringup` launch file.

## Prerequisites

- Workspace built on the Pi: `cd ~/robot_ws && colcon build --symlink-install`
- `pigpiod.service` enabled (the servo controller connects to it):
  ```bash
  sudo systemctl enable --now pigpiod
  ```

## Install

Run on the Pi (user `oliren`, workspace `/home/oliren/robot_ws`):

```bash
# 1. Build so the bringup package's launch file is installed
cd ~/robot_ws
colcon build --symlink-install

# 2. Install the unit
sudo cp ~/robot_ws/systemd/robot_car.service /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Enable at boot and start now
sudo systemctl enable --now robot_car.service
```

## Verify

```bash
systemctl status robot_car.service     # should be active (running)
journalctl -u robot_car.service -f     # live logs from both nodes
```

Then open `http://<pi-ip>:8080` in a browser.

## Manage

```bash
sudo systemctl restart robot_car.service   # after a deploy/rebuild
sudo systemctl stop robot_car.service      # stop both nodes
sudo systemctl disable robot_car.service   # don't start at boot
```

`deploy.sh --restart` already restarts this service after syncing:

```bash
./deploy.sh --build --restart
```

The deploy script runs its `sudo` steps over `ssh -t`, so it prompts for
`oliren`'s password interactively during deploy.

## Unattended deploys (optional)

To run `deploy.sh` without a password prompt, grant `oliren` passwordless
sudo for *only* the commands the deploy needs. On the Pi:

```bash
sudo visudo -f /etc/sudoers.d/robot_car_deploy
```

Add (adjust binary paths with `command -v cp systemctl` if they differ):

```
oliren ALL=(root) NOPASSWD: /usr/bin/cp * /etc/systemd/system/robot_car.service, /usr/bin/systemctl daemon-reload, /usr/bin/systemctl restart robot_car.service, /usr/bin/systemctl stop robot_car.service, /usr/bin/systemctl start robot_car.service
```

This is scoped to these specific commands — it is not blanket passwordless
sudo. With it in place, `ssh -t` still works (sudo simply won't prompt).

## Notes

- The unit sources `/opt/ros/jazzy/setup.bash` and
  `/home/oliren/robot_ws/install/setup.bash` before launching, because
  systemd does not run a login shell.
- `Requires=pigpiod.service` + `After=…` ensures servos have pigpiod up
  before the web server starts.
- `WorkingDirectory=/home/oliren/robot_ws` is required: `lgpio` creates a
  notification pipe (`.lgd-nfy<N>`) in the current directory when it's
  imported. Without a writable cwd the motor driver dies on startup with
  `FileNotFoundError: ... '//.lgd-nfy0'` (systemd's default cwd is `/`,
  which the service user can't write to).
- Each node is launched with `respawn=True` (launch-level) and the whole
  service has `Restart=on-failure` (systemd-level), so a crash recovers
  at both layers.
- If you run on a different user/path, edit `User=`, `HOME=`, and the two
  paths in `ExecStart` accordingly.
```
