# serial_log_with_ts

Logs the output of a serial port (e.g. the debug output of a box) to a file and to stdout,
with a PC time stamp in front of every line.

## Usage

```sh
serial_log_with_ts <port> [-b <baudrate>] [-l <log_path>] [-d <duration>]
```

| Option | Meaning |
|---|---|
| `<port>` | Serial port, e.g. `COM6` or `/dev/ttyUSB0` |
| `-b`, `--baudrate <n>` | Baudrate (default: 115200) |
| `-l`, `--log-path <file>` | Log file (default: `serial_log.txt`), overwritten if it exists |
| `-d`, `--duration <s>` | Logging time in seconds, `-1` = until Ctrl-C (default) |
| `-h` | Show help |

## Example

```sh
serial_log_with_ts COM6 -l 3004_V65_real_can.log
```

```text
2026-11-25T14:41:15.481595 : # task load: Main nr=2 prio=2 load=78.2% stackFree=6556
2026-11-25T14:41:15.500715 : # ChassisCanCount (1): message = 759083, match = 407342, lost = 0, error = 0
```

## Notes

- The time stamp is the local PC time (ISO format, microseconds) when the line has been
  received completely, not the box time.
- Empty lines are dropped, leading and trailing white space is removed, invalid UTF-8
  bytes are ignored.
- The file is flushed every 100 lines, so it may lag behind the console output while logging.
  It is complete after the end (Ctrl-C or `-d` elapsed).
- At the end the number of logged lines is printed.
- The log can be evaluated with [analyze_serial_log](analyze_serial_log.md) (CAN / LIN rates,
  task load).
