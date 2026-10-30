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

For each box the topic `<topic>/<box>/Status/Connection` is subscribed; the payload is
`Online` or `Offline`. This is the same as

```sh
mosquitto_sub -h broker.myestino.de -p 1884 -t "FwTest/990000002001/Status/Connection"
```

Quote box numbers so YAML reads them as text (leading zeros are kept).

## Display

| Column | Content |
|---|---|
| STATUS | `Online` (green), `Offline` (red), `?` = no message received yet |
| SINCE | Time since the last status change |
| LAST MSG | Time since the last message for this box |

The header shows the broker connection state and counts of online/offline/unknown boxes.
The client reconnects automatically and re-subscribes after a reconnect.

| Key | Action |
|---|---|
| `q` / `Esc` | Quit |
| `s` | Cycle sort order: config order → status (offline first) → topic/box |
| `c` | Clear all states (wait for new messages) |
| Up/Down, PgUp/PgDn, Home | Scroll |

## Notes

- If the status topics are published as *retained*, the current state appears immediately
  after start; otherwise boxes stay `?` until their next status message.
- On Windows `windows-curses` is required (installed automatically as a dependency).
