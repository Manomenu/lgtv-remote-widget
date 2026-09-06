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

## Notifications

`createToast` works; `closeToast` does not. webOS decides when a notification
disappears and there is no way to set a duration.
