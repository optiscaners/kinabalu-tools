# analyze_emmc

Lists every file of the Edge2 box file system (eMMC) with size and modification date via the
serial port, followed by the cumulated size and file count per directory. Can also delete
files selected by wildcard patterns.

Uses the same OptiScan base64 protocol as the ServiceTool
(`edge2/Desktop/ServiceToolGen2`).

## Usage

```sh
analyze_emmc <port> [--ls] [-p <path>] [-o <csvfile>] [options]
analyze_emmc <port> --rm <pattern>... [-r] [-y] [options]
```

| Option | Meaning |
|---|---|
| `<port>` | Serial port, e.g. `COM6` or `/dev/ttyUSB0` |
| `--ls` | List all files with size (default command) |
| `-p <path>` | `--ls`: start directory on the box (default: `/`) |
| `-o <csvfile>` | `--ls`: additionally write the list as CSV (`path;type;size;modified`) |
| `--rm <pattern>...` | Delete files matching one or more patterns (see below) |
| `-r` | `--rm`: also delete matching directories with their content |
| `-y` | `--rm`: do not ask for confirmation |
| `-b <baudrate>` | Baudrate (default: 115200) |
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

## Sequence

1. `IdGet`, `ModeGet`
2. `ModeSet(FileSystem)` if the box is not in file system mode
3. `FileSystemMountGet`, `FileSystemMount` if not mounted
4. Recursively `FileSystemList` per directory and `FileSystemStatusGet` per file;
   for `--rm` then `FileSystemUnlink` per file / directory
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
| FileSystemUnlink | `0x1320` |

Other frames (debug output, log messages) received in between are ignored.

## Notes

- While in file system mode the box does not run its normal application (no logging).
- The box answers file system commands only in mode `FileSystem`; the script switches the mode
  automatically.
