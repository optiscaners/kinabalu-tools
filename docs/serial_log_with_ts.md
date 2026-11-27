# serial_log_with_ts

Logs the output of a serial port (e.g. the debug output of a box) to a file and to stdout,
with a PC time stamp in front of every line. At the start, the box serial number and firmware
version are queried and written as the first line of the log.

## Usage

```sh
serial_log_with_ts <port> [-b <baudrate>] [-l <log_path>] [-d <duration>] [-t <timeout>] [-n]
```

| Option | Meaning |
|---|---|
| `<port>` | Serial port, e.g. `COM6` or `/dev/ttyUSB0` |
| `-b`, `--baudrate <n>` | Baudrate (default: 115200) |
| `-l`, `--log-path <file>` | Log file, overwritten if it exists (default: `serial-<box>-<version>-<YYYYmmdd-HHMMSS>.log`) |
| `-d`, `--duration <s>` | Logging time in seconds, `-1` = until Ctrl-C (default) |
| `-t`, `--timeout <s>` | Timeout for the box query in seconds (default: 2) |
| `-n`, `--no-query` | Do not query the box (box and version are `none`) |
| `-h` | Show help |

## Example

```sh
serial_log_with_ts COM6                         # -> serial-000000003004-1.65.0-20261127-102220.log
serial_log_with_ts COM6 -l 3004_V65_real_can.log
```

```text
2026-11-27T10:22:20.481514 : # serial_log_with_ts: box=000000003004 version=1.65.0 id=Pegasus20Gen2 port=COM6 baudrate=115200
2026-11-27T10:22:21.481595 : # task load: Main nr=2 prio=2 load=78.2% stackFree=6556
2026-11-27T10:22:21.500715 : # ChassisCanCount (1): message = 759083, match = 407342, lost = 0, error = 0
```

## Box query

Before logging, the script sends the following OptiScan commands (same protocol as
[analyze_emmc](analyze_emmc.md)):

| Value | Command |
|---|---|
| `box` | `FlashRead(SerialNumber)`: 12 digit serial number, as in the ServiceTool |
| `version` | `SoftwareVersionGet`: `<major>.<minor>.<patch>[-<special>]` |
| `id` | `IdGet` |

- If the box does not answer within `-t` seconds (e.g. it is held in reset or not powered),
  `none` is used and the logging starts anyway: `serial-none-none-<date>.log`. The box
  is not asked again, so once it starts, its output (e.g. `Hello World`) is logged as usual.
- Characters other than letters, digits, `.`, `-` and `_` in the file name are replaced by `_`.
- Debug output the box sends during the query (normally less than 0.1 s) is not logged.

## Notes

- The time stamp is the local PC time (ISO format, microseconds) when the line has been
  received completely, not the box time.
- Empty lines are dropped, leading and trailing white space is removed, invalid UTF-8
  bytes are ignored.
- The file is flushed every 100 lines, so it may lag behind the console output while logging.
  It is complete after the end (Ctrl-C or `-d` elapsed).
- At the end the number of logged lines and the log file name are printed.
- The log can be evaluated with [analyze_serial_log](analyze_serial_log.md) (CAN / LIN rates,
  task load); the header line is ignored there.
