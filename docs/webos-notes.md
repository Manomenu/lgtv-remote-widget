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

## Key injection: only `event5` is real

| Device | Name | Key codes advertised | Actually delivered? |
|---|---|---|---|
| `/dev/input/event0` | LGE RCU | 767 (every code) | **No** |
| `/dev/input/event5` | LGE TONE+ - Builtin [3] | 45 | **Yes** |

`event0` advertises a full `ffffffff` capability bitmap and accepts writes
without error, but webOS never reads from it. `event5` advertises far less and
is the one the input stack consumes.

Measured by injecting `KEY_VOLUMEUP` (115) into each device and reading the
volume back over the bus — a test whose result does not depend on anyone
watching the screen.

## There is no next-track key

`event5` does **not** support `KEY_NEXTSONG` (163) or `KEY_PREVIOUSSONG` (165).
It does support `KEY_FASTFORWARD` (208) and `KEY_REWIND` (168), which is what
the physical remote sends and what players on the TV respond to. Those are the
defaults in `[keys]`; change them there if your player wants something else.

`luna://com.webos.service.mediacontroller` does not exist on this firmware —
the service replies `Service does not exist`, so there is no higher-level media
API to use instead.

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
