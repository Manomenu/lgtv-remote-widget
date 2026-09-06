# D-Bus interface

The service owns `org.maniumek.LgtvRemote` on the **session** bus, exports
`/org/maniumek/LgtvRemote` and implements `org.maniumek.LgtvRemote1`.

Everything the widget shows comes from properties; everything it does goes
through methods. Methods return immediately — they queue the work and the
result arrives as a property change. Nothing ever blocks the caller, which is
the whole reason the service exists.

## Properties

| Name | Type | Values |
|---|---|---|
| `PowerState` | `s` | `active`, `screen-off`, `screen-saver`, `standby`, `offline`, `turning-on`, `turning-off` |
| `Volume` | `i` | 0-100, or `-1` when unknown |
| `Muted` | `b` | |
| `CastState` | `s` | `streaming`, `ready`, `stopped`, `starting`, `stopping` |
| `CastEnabled` | `b` | whether `cast.enabled` is on; the widget hides its tile when it is not |
| `LastError` | `s` | text of the last failure, empty after a successful command |

Changes are announced with the standard
`org.freedesktop.DBus.Properties.PropertiesChanged`.

## Methods

| Method | Signature | Notes |
|---|---|---|
| `SetPower` | `b → ()` | State goes to `turning-on`/`turning-off` first; a cold start can take 90 s. A no-op when the TV is already in the requested state — including `SetPower false` while it is `standby` or `offline`, which returns success without doing anything |
| `SetVolume` | `i → ()` | Coalesced — only the newest value is sent, at most every 120 ms |
| `SetMute` | `b → ()` | |
| `MediaKey` | `s → ()` | `next` or `previous`; anything else is an error |
| `SetCast` | `b → ()` | Asynchronous, like `SetPower`; fails outright when `CastEnabled` is false |
| `SetActive` | `b → ()` | Tells the service whether anyone is looking. Polling runs only while this is true (or an operation is in flight) — see below |
| `Refresh` | `() → ()` | Poll now and poll faster for the next minute |

## Polling

The service does **not** poll the TV in the background. Nothing would read the
result: the widget is the only consumer, and when its panel is closed nobody
sees it. A 30-second poll would mean nearly three thousand connections a day to
refresh a number no one is reading.

The panel therefore calls `SetActive(true)` when it opens — which polls at once
and then every `poll_active` seconds — and `SetActive(false)` when it closes.
Operations in flight (`turning-on`, `turning-off`) keep polling regardless,
because powering a TV on takes up to 90 seconds and has to finish even if the
panel was closed right after the click.

Set `[daemon] poll_idle` to a non-zero number of seconds if you want a
background poll anyway — for a script of your own reading the properties, say.

## Driving it from a terminal

```sh
busctl --user introspect org.maniumek.LgtvRemote /org/maniumek/LgtvRemote
busctl --user get-property org.maniumek.LgtvRemote /org/maniumek/LgtvRemote \
       org.maniumek.LgtvRemote1 PowerState
busctl --user call org.maniumek.LgtvRemote /org/maniumek/LgtvRemote \
       org.maniumek.LgtvRemote1 MediaKey s next
```

Watch state change live:

```sh
gdbus monitor --session --dest org.maniumek.LgtvRemote
```
