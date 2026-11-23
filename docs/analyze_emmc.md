# analyze_emmc

Lists every file of the Edge2 box file system (eMMC) with size and modification date via the
serial port, followed by the cumulated size and file count per directory.

Uses the same OptiScan base64 protocol as the ServiceTool
(`edge2/Desktop/ServiceToolGen2`).

## Usage

```sh
analyze_emmc <port> [-b <baudrate>] [-p <path>] [-o <csvfile>] [-t <timeout>] [--keep-mode] [-v]
```

| Option | Meaning |
|---|---|
| `<port>` | Serial port, e.g. `COM6` or `/dev/ttyUSB0` |
| `-b <baudrate>` | Baudrate (default: 115200) |
| `-p <path>` | Start directory on the box (default: `/`) |
| `-o <csvfile>` | Additionally write the list as CSV (`path;type;size;modified`) |
| `-t <timeout>` | Response timeout in seconds (default: 20) |
| `--keep-mode` | Stay in file system mode after the listing |
| `-v` | Print every sent / received frame (hex) to stderr |
| `-h` | Show help |

## Examples

```sh
analyze_emmc COM6
analyze_emmc COM6 -p /LOG -o emmc.csv
```

```text
Box id: 000000003004
Mode:   Normal
Switching to mode FileSystem ...

        SIZE  MODIFIED             PATH
     1000000  2026-11-23 09:05:07  /LOG/a.bin
        1234  2026-11-23 09:05:07  /config.json
Restoring mode Normal ...

        SIZE   FILES  DIRECTORY (incl. sub directories)
     1001234       2  /
     1000000       1  /LOG

Total: 2 files, 1 directories, 1001234 bytes
```

## Sequence

1. `IdGet`, `ModeGet`
2. `ModeSet(FileSystem)` if the box is not in file system mode
3. `FileSystemMountGet`, `FileSystemMount` if not mounted
4. Recursively `FileSystemList` per directory and `FileSystemStatusGet` per file
5. `ModeSet(<previous mode>)` (also after an error or Ctrl-C), unless `--keep-mode`

## Protocol

| Item | Format |
|---|---|
| Frame | `0x0A` `'$'` base64(data) `0x0D` |
| data | command id (uint16) + parameters, little endian |
| string | length (uint16) + UTF-8 bytes |
| Response | same command id; on failure `Error` (`0xEE00`) + failed command id + text |

| Command | Id |
|---|---|
| IdGet | `0x0300` |
| ModeGet / ModeSet | `0x0400` / `0x0500` |
| FileSystemMount / FileSystemMountGet | `0x0520` / `0x0620` |
| FileSystemList | `0x0A20` |
| FileSystemStatusGet | `0x0C20` |

Other frames (debug output, log messages) received in between are ignored.

## Notes

- While in file system mode the box does not run its normal application (no logging).
- The box answers file system commands only in mode `FileSystem`; the script switches the mode
  automatically.
