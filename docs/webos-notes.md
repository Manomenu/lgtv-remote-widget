# What this TV actually does

Everything here was measured on the hardware, not read in a manual. Each entry
exists because something did not work the obvious way, and the note saves the
next person the hour it cost to find out.

Firmware: LG webOS, rooted, reachable over SSH as `root`.
Measured: September 2026, from Fedora 44.

## `luna-send` needs `< /dev/null` and a file for its output

Two independent traps that both have to be worked around on **every** call:

1. `luna-send` loses the reply when its stdout is a pipe — and over SSH it
   always is. Write to a file on the TV and `cat` the file instead.
2. `luna-send` watches stdin and exits at end-of-file, before the reply comes
   back from the bus. Started from a script over SSH it inherits an exhausted
   pipe and returns nothing. Without `< /dev/null` a reply arrives maybe one
   time in five, which looks exactly like a flaky TV and is not.

Both are handled once, in `src/lgtvd/luna.py`.

## Key injection

### The device numbers move — look it up by name

Two probes on the same afternoon saw 7 devices and then 11, as Bluetooth
audio, a mouse and an IoT keypad appeared. A hard-coded `/dev/input/eventN`
is therefore a time bomb. Names are stable, so the injection script resolves
the device by name (`LGE M-RCU - Builtin [2]`) and falls back to the
configured path only if that name is gone.

### Not every device is read

`/dev/input/event0` (LGE RCU) advertises a full `ffffffff` capability bitmap
and accepts writes without error, but webOS never reads from it. `event4` and
`event5` both deliver. Measured by injecting `KEY_VOLUMEUP` (115) and reading
the volume back over the bus — a test whose result does not depend on anyone
watching the screen.

### "Next" and "previous" are the channel rocker

The buttons that skip tracks are **not** media keys. Recorded by listening to
every input device at once while pressing the real remote:

| Button | Device | Code |
|---|---|---|
| previous | `event4` — LGE M-RCU - Builtin [2] | **403** (`KEY_CHANNELDOWN`) |
| next | `event4` — LGE M-RCU - Builtin [2] | **402** (`KEY_CHANNELUP`) |

An earlier guess in this file — that skipping went through `KEY_FASTFORWARD`
(208) and `KEY_REWIND` (168) because `event5` lacks `KEY_NEXTSONG` — was
**wrong, and the widget did nothing because of it**. Those codes are supported
by the device and were delivered; they simply are not what the remote sends,
so nothing on the TV was listening for them. The capability bitmap says what a
device *can* carry, never what an application reacts to. The only way to learn
the second is to record a real button press.

`luna://com.webos.service.mediacontroller` does not exist on this firmware —
the service replies `Service does not exist`, so there is no higher-level media
API to use instead.

### Press length

The real remote holds a button for roughly 160 ms. Injected presses hold 120 ms
rather than the shortest possible, so an application that debounces its input
cannot mistake them for contact bounce.

## Power states

`luna://com.webos.service.tvpower/power/getPowerState` returns:

| `state` | Meaning | Treated as |
|---|---|---|
| `Active` | on | awake |
| `Screen Off` | on, panel dark | awake |
| `Screen Saver` | on, screensaver running | awake |
| `Active Standby`, `Suspend`, `Prepare Suspend` | standby | asleep |
| *(no reply, but SSH works)* | Quick Start+ standby: network alive, service bus not | asleep |

`Screen Saver` is a normal working state when the TV plays music with the
picture dark, so it counts as awake.

## Powering off is not symmetric with powering on

Off goes over SSH; on goes over Wake-on-LAN, because a TV that is off has
nothing to talk to. Magic packets get dropped, so they are repeated while
waiting for confirmation.

`powerOff` is unambiguous and safe to repeat. The fallback — injecting
`KEY_POWER` — is a *toggle*, not an off switch: repeated after the TV has gone
dark it would switch it back on. It is therefore allowed to fire at most once
per call.

## Volume

`luna://com.webos.service.audio/master/setVolume {"volume":N}` works and is what
makes a real slider possible; `getVolume` also reports `muteStatus`, which the
slider's icon uses. The scale is 0-100 but useful listening levels sit in the
low teens.

Muting is **`muteVolume {"mute": bool}`**. The symmetric-looking name suggested
by the reader (`setMuted {"muted": …}`, matching the `muteStatus` field it
returns) does not exist — nor do `setMute`, `setSoundOutputMute` or the same
call on `com.webos.service.audio` without `/master`. All of them answer
`Unknown method`, which is a reply, not a crash, so a caller that does not check
`returnValue` sees nothing wrong at all.

It is a real mute: the volume level is kept and comes back on unmute, so there
is no need to remember it on this side.

## Notifications

`createToast` works; `closeToast` does not. webOS decides when a notification
disappears and there is no way to set a duration.

## Running the service under systemd

Two sandboxing options had to be left out of the user unit, both because this
service exists to launch other programs. Both were found the same way: the
feature silently did nothing, and the log said why.

**Anything that creates a mount namespace** (`ProtectSystem`, `ProtectHome`,
`PrivateTmp`) makes root-owned files appear as `nobody:nobody` inside a *user*
unit. OpenSSH then refuses to read `/etc/ssh/ssh_config.d/*` with
"Bad owner or permissions" and exits 255 — the service loses its only way of
talking to the TV and reports it as switched off.

**`RestrictNamespaces`** blocks flatpak: bubblewrap needs namespaces of its own
to build the sandbox, so starting Sunshine dies immediately with
"bwrap: No permissions to create a new namespace" and the screencast tile never
works.

What is left — `NoNewPrivileges`, `RestrictSUIDSGID`, `RestrictRealtime`,
`LockPersonality`, `MemoryDenyWriteExecute` — was each tested against both ssh
and `flatpak run`. Measured on Fedora 44, systemd 258, OpenSSH 10.2,
flatpak 1.16.

### …and they still reached Sunshine, until it stopped being our child

Seccomp filters are inherited through `exec` and survive flatpak moving the app
into a cgroup of its own. Sunshine started as a child of this service therefore
carried **ten** seccomp filters where a terminal launch carries **one**
(`grep Seccomp_filters /proc/<pid>/status`), and with them a standing refusal of
`sched_setscheduler` from `RestrictRealtime` — which is what its capture and
encode threads use to pace frames evenly. The stream was visibly worse than the
same Sunshine started by hand.

Sunshine is now started with `systemd-run --user`, so the session manager
spawns it beside us rather than beneath us: back to one filter, and it no longer
dies when the service restarts.
