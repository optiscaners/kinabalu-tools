# box_status

Monitors the online status of a list of boxes via MQTT and shows it in a full-screen,
htop-like terminal view.

## Usage

```sh
box_status [-C <configfile>]
```

| Option | Meaning |
|---|---|
| `-C <configfile>` | YAML config file (default: `box_status.yml` in the current directory) |
| `-h` | Show help |

## Examples

```sh
box_status                                  # uses ./box_status.yml
box_status -C examples/box_status.yml
```

## Config file

See [examples/box_status.yml](../examples/box_status.yml).

```yaml
server:
  host: broker.myestino.de
  port: 1884
  # optional: username, password, keepalive (s), client_id
boxes:
  - topic: FwTest
    box: "990000002001"
    name: Testbox 1        # optional
```

For each box two topics are subscribed:

| Topic | Payload |
|---|---|
| `<topic>/<box>/Status/Connection` | `Online` or `Offline` |
| `<topic>/<box>/Status/Connection/<date-string>` | JSON connection info, sent by the box when it connects |

Example connection info message:

```text
topic:   Daimler/000000003004/Status/Connection/2026-11-17T11:06:55Z
payload: {"Id":"Pegasus20Gen2","Version":"0.1.4","StartTime":"2026-11-17T11:06:20Z","StartupCounter":651453,
          "SmuResetCounter":0, ...}
```

From this payload `Id`, `Version`, `SmuResetCounter` and `StartupCounter` are shown; other fields are ignored.
This is the same as

```sh
mosquitto_sub -h broker.myestino.de -p 1884 -t "FwTest/990000002001/Status/Connection" \
              -t "FwTest/990000002001/Status/Connection/+"
```

Quote box numbers so YAML reads them as text (leading zeros are kept).

## Display

| Column | Content |
|---|---|
| STATUS | `Online` (green), `Offline` (red), `?` = no message received yet |
| SINCE | Time since the last status change |
| LAST MSG | Time since the last status message for this box |
| ID | `Id` from the connection info message (`-` = none received yet) |
| VERS | Firmware `Version` from the connection info message |
| SMU RST | `SmuResetCounter` from the connection info message |
| STUC | `StartupCounter` from the connection info message |

The header shows the broker connection state and counts of online/offline/unknown boxes.
The client reconnects automatically and re-subscribes after a reconnect.

| Key | Action |
|---|---|
| `q` / `Esc` | Quit |
| `s` | Cycle sort order: config order → status (offline first) → topic/box |
| `c` | Clear all states incl. ID/VERS/SMU RST/STUC (wait for new messages) |
| Up/Down, PgUp/PgDn, Home | Scroll |

## Notes

- If the status topics are published as *retained*, the current state appears immediately
  after start; otherwise boxes stay `?` until their next status message.
- The connection info message is not retained: ID, VERS, SMU RST and STUC stay `-` until a box
  (re)connects to the broker while `box_status` is running.
- Messages with an empty payload, `null` or `(null)` are ignored, the display keeps the
  last value.
- A UTF-8 BOM at the start of a payload (as sent by the boxes) is removed before parsing.
- On Windows `windows-curses` is required (installed automatically as a dependency).
