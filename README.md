# LG TV Remote

Your LG TV in the GNOME Quick Settings panel — the same place as Wi-Fi and
Dark Style, in the same style.

| TV on | TV off or unplugged |
|---|---|
| ![the widget in the panel](docs/widget.png) | ![the widget greyed out](docs/widget-offline.png) |

## What it does

- **Power** — switches the TV on and off, and waits until it really happened
- **Volume** — a proper slider; click the speaker to mute, move the slider to unmute
- **Skip** — previous and next track, for whatever is playing on the TV
- **Screencast** — throws this computer's screen onto the TV and takes it back

When the TV is off the panel dims but stays put, and the power button stays
live — that is the one moment you actually reach for a remote.

## Requirements

**None of this is installed for you.** `setup.sh` checks for each item and
stops with a message naming what is missing, rather than half-installing and
failing later.

### On this computer

| What | Version | Check / install |
|---|---|---|
| GNOME Shell | 49 or 50 | `gnome-shell --version` |
| Wayland session | — | GNOME's default; `echo $XDG_SESSION_TYPE` |
| Python | 3.11 or newer | `python3 --version` |
| PyGObject | any | `sudo dnf install python3-gobject-base` |
| OpenSSH client | any | `ssh -V` |

Built and tested on Fedora 44, GNOME Shell 50.4, Python 3.14.7.

### On the TV

| What | Why it is needed | How |
|---|---|---|
| **Rooted webOS** with Homebrew Channel | everything here is done over SSH as `root`; without root there is no way in | [webosbrew.org](https://www.webosbrew.org/) |
| **SSH key, no password** | the service runs unattended, so a password prompt would simply hang it | `ssh-copy-id root@<tv>` |
| Entry in `~/.ssh/config` | you put its name in `setup.cfg` | see below |
| **Wake-on-LAN** enabled | needed to switch the TV **on**; switching it off works without it | *Settings → Support → IP Control Settings* |

```
Host lgtv-root
    HostName 192.168.1.42
    User root
```

### Only for the screencast button

| What | Where | How |
|---|---|---|
| **Sunshine** | this computer | `flatpak install flathub dev.lizardbyte.app.Sunshine` |
| **Moonlight** | the TV | Homebrew Channel → Moonlight |

The widget starts Sunshine for you when you press the button, but it will not
install it. If you do not want the screencast button at all, set
`enabled = false` under `[cast]` in `setup.cfg` and it disappears from the panel.

## Install

```sh
git clone https://github.com/Manomenu/lgtv-remote-widget ~/repos/lgtv-remote-widget
cd ~/repos/lgtv-remote-widget
cp setup.cfg.example setup.cfg     # fill in your TV's SSH host, MAC and broadcast address
./setup.sh
```

Then **log out and back in** — GNOME only picks up new panel widgets when your
session starts.

## Changing a setting

Edit `setup.cfg`, run `./setup.sh` again. That is the whole loop; the installer
copies the file into place for you.

```sh
$EDITOR setup.cfg && ./setup.sh
```

## When something looks wrong

The widget says what it knows, and the rest is in two log files.

| What you see | What it means |
|---|---|
| **Service not running** | the background service is not up: `systemctl --user status lgtv-remote` |
| **Off**, but the TV is on | it was switched on with the physical remote; the widget catches up the moment you open the panel |
| Everything greyed but Power | the TV is off or off the network — press Power |

```sh
tail -f ~/.local/state/lgtv-remote/actions.log    # one line per button press
cat ~/.local/state/lgtv-remote/errors.log         # only the things that failed
```

## Uninstall

```sh
./uninstall.sh --dry-run    # show what would be removed
./uninstall.sh              # remove it, keep your settings and logs
./uninstall.sh --purge      # remove everything
```

## How it works, briefly

A small background service does the talking to the TV over SSH and holds one
connection open, so the buttons respond instantly. The panel widget only draws
what the service already knows — which is why switching the TV on, a job that
can take a minute and a half, never freezes your desktop.

The service is asleep while the panel is closed and wakes when you open it, so
nothing pesters the TV in the background.

For the details — the D-Bus interface, and the surprising things this TV does —
see [`docs/`](docs/).
