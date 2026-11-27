# analyze_emmc

Lists every file of the Edge2 box file system (eMMC) with size and modification date via the
serial port, followed by the cumulated size and file count per directory. Can also delete
files selected by wildcard patterns, or download all files into a zip file.

Uses the same OptiScan base64 protocol as the ServiceTool
(`edge2/Desktop/ServiceToolGen2`).

## Usage

```sh
analyze_emmc <port> [--ls] [-p <path>] [-o <csvfile>] [options]
analyze_emmc <port> --rm <pattern>... [-r] [-y] [options]
analyze_emmc <port> --get [-p <path>] [-x <pattern>]... [-B <n>] [options]
```

| Option | Meaning |
|---|---|
| `<port>` | Serial port, e.g. `COM6` or `/dev/ttyUSB0` |
| `--ls` | List all files with size (default command) |
| `-p <path>` | `--ls` / `--get`: start directory on the box (default: `/`) |
| `-o <csvfile>` | `--ls`: additionally write the list as CSV (`path;type;size;modified`) |
| `--rm <pattern>...` | Delete files matching one or more patterns (see below) |
| `-r` | `--rm`: also delete matching directories with their content |
| `-y` | `--rm`: do not ask for confirmation |
| `--get` | Download all files (below `-p`) into `<BoxSerial>-<YYYYmmdd-HHMM>.zip` |
| `-x <pattern>` | `--get`: exclude matching files / directories (repeatable, see below) |
| `-B`, `--block-size <n>` | `--get`: bytes per read request (default: baudrate / 20, at least 512, at most 2048) |
| `-b <baudrate>` | Baudrate to connect with (default: 115200) |
| `-f` | Switch the box to the fast baudrate after connecting, back to `-b` at the end (see below) |
| `--fast-baudrate <n>` | Baudrate for `-f` (default: 1500000) |
| `-t <timeout>` | Response timeout in seconds (default: 20): time without any data from the box |
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

## Deleting files (`--rm`)

```sh
analyze_emmc COM6 --rm "/LOG/*.bin"             # all .bin files directly in /LOG
analyze_emmc COM6 --rm "/**/*.tmp" /config.json # all .tmp files anywhere + one file
analyze_emmc COM6 --rm /LOG/OLD -r              # directory /LOG/OLD with its content
```

Patterns are matched per path segment (a `*` does not cross a `/`):

| Wildcard | Matches |
|---|---|
| `*` | Any characters within a name |
| `?` | One character |
| `[abc]` | One of the characters |
| `**` | Any number of directories (also none) |

- Matching is case-insensitive (FAT file system); a pattern without leading `/` is taken
  from the root.
- Quote patterns, so the shell does not expand them locally (bash).
- The matching files are listed with size first, deletion needs a confirmation `y`
  (skip with `-y`).
- A matching directory is skipped unless `-r` is given; with `-r` its files are deleted
  first, then the sub directories (deepest first) and the directory itself.
- A failed deletion is reported, the remaining entries are still deleted; exit code is 1.

## Downloading files (`--get`)

```sh
analyze_emmc COM6 --get            # all files -> 000000003004-20261123-1436.zip
analyze_emmc COM6 --get -p /LOG    # only files below /LOG
analyze_emmc COM6 --get -x "*.bin" -x /LOG/OLD   # without .bin files and without /LOG/OLD
```

Exclude patterns (`-x`, repeatable) use the same wildcards as `--rm`:

- A pattern without `/` matches the name in any directory: `-x "*.bin"`, `-x TMP`.
- A pattern with `/` is matched from the root: `-x /LOG/OLD`, `-x "/LOG/*.bin"`.
- A matching directory is excluded with its whole content and is not even listed.
- The excluded entries are printed before the download starts.

- The zip file is written to the current directory. `<BoxSerial>` is the 12 digit serial
  number from the flash (`FlashRead` section `SerialNumber`, same as in the ServiceTool and
  the MQTT topics), the time stamp is the local PC time at the start of the download.
- Paths in the zip are the box paths without leading `/`; the modification date of the box
  file is kept. Empty directories are stored as directory entries.
- A file that cannot be read is reported and skipped, the other files are still downloaded;
  exit code is 1.
- On Ctrl-C the zip file is closed properly but is incomplete (marked in the output).
- The transfer rate is limited by the baudrate: at 115200 baud roughly 8 KiB/s. Use `-f` for
  larger downloads.

## Fast baudrate (`-f`)

```sh
analyze_emmc COM6 --get -f
```

The script connects at `-b` (115200) and then sends `BaudRateSet(1500000)`, like the ServiceTool
does before an init. The box acknowledges at the old baudrate and then switches its UART.
The script closes the PC port, reopens it at the new baudrate and checks the connection with `ModeGet`.
The default block size for `--get` is limited to 2048 bytes (larger blocks failed at 1500000 baud with the Pegasus20 box).

- At the end (also after an error or Ctrl-C) the box is switched back to `-b`, so the next
  connection at 115200 works. If that fails, the box stays at the fast baudrate until it is
  rebooted. Connect with `-b 1500000` in that case.
- If the box does not support the baudrate, the script stops with an error and prints the
  supported baudrates (`BaudRateList`).
- The USB serial adapter must support the fast baudrate.
- If the box stops answering at the fast baudrate, the script checks whether it answers at `-b`
  again. If so, the box has restarted (e.g. watchdog of the Main task, 10 s in the Pegasus20
  firmware, which reads files byte by byte); mode and baudrate are then reset by the box.
  Try a smaller `--block-size` in that case. The timeout message shows how many
  bytes of the response were received before it stopped.

## Sequence

1. `IdGet`, `FlashRead(SerialNumber)`, with `-f` `BaudRateSet(<fast>)`, then `ModeGet`
2. `ModeSet(FileSystem)` if the box is not in file system mode
3. `FileSystemMountGet`, `FileSystemMount` if not mounted
4. Recursively `FileSystemList` per directory and `FileSystemStatusGet` per file;
   for `--rm` then `FileSystemUnlink` per file / directory;
   for `--get` per file `FileSystemReadStart` (switches the box to mode `FileSystemRead`),
   `FileSystemRead` until a block is shorter than the block size, then `ModeSet(FileSystem)`
5. `ModeSet(<previous mode>)` (also after an error or Ctrl-C), unless `--keep-mode`
6. With `-f`: `BaudRateSet(<-b>)`

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
| FileSystemUnlink | `0x1320` |
| FlashRead | `0x0800` |
| BaudRateList / BaudRateSet | `0x1000` / `0x1100` (parameter: baudrate uint32) |
| FileSystemReadStart | `0x2020` (response id is `FileSystemRead`) |
| FileSystemRead | `0x2021` |

Other frames (debug output, log messages) received in between are ignored.

## Notes

- **Git Bash:** arguments starting with `/` without wildcards (e.g. `-p /LOG`, `-x /LOG/OLD`)
  are converted to Windows paths (`C:/Program Files/Git/LOG`). The script detects this and
  stops with an error. Write `//LOG` instead, or set `MSYS_NO_PATHCONV=1`. PowerShell and cmd
  are not affected.

- While in file system mode the box does not run its normal application (no logging).
- The box answers file system commands only in mode `FileSystem`; the script switches the mode
  automatically.
