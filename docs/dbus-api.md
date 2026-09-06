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
| `Refresh` | `() → ()` | Poll now and poll faster for the next minute |

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
