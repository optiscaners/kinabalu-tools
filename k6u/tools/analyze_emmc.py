"""
analyze_emmc.py - listet über die serielle Schnittstelle alle Dateien im Dateisystem (eMMC)
einer Edge2-Box mit Größe und Änderungsdatum auf bzw. löscht Dateien.

Usage:

    analyze_emmc <port> [--ls] [-p <path>] [-o <csvfile>] [options]
    analyze_emmc <port> --rm <pattern>... [-r] [-y] [options]

    port            - serial port, e.g. COM6 or /dev/ttyUSB0
    --ls            - list all files with size (default command)
    -p <path>       - start directory on the box for --ls (default: /)
    -o <csvfile>    - additionally write the list as CSV (path;type;size;modified)
    --rm <pattern>  - delete files matching the pattern(s), wildcards per path segment:
                      * ? [abc], ** = any number of directories, case-insensitive
                      e.g. "/LOG/*.bin", "/**/*.tmp"
    -r              - with --rm: also delete matching directories with their content
    -y              - with --rm: do not ask for confirmation
    -b <baudrate>   - default 115200
    -t <timeout>    - response timeout in seconds (default: 20)
    --keep-mode     - stay in file system mode (default: restore the previous mode)
    -v              - print every sent / received frame

Protokoll (wie ServiceToolGen2 / OptiScan):

    Frame:    0x0A '$' <base64(data)> 0x0D
    data:     <command id uint16 LE> <parameters, little endian>
    string:   <length uint16> <utf-8 bytes>
    Response: same command id, on failure command id Error (0xEE00) + failed id + text

Ablauf: ModeGet -> ModeSet(FileSystem) -> MountGet/Mount -> rekursiv FileSystemList und
FileSystemStatusGet je Datei (bzw. FileSystemUnlink) -> ModeSet(vorheriger Mode).
"""

# == modules ==
import argparse
import base64
import csv
import fnmatch
import struct
import sys
import time
from dataclasses import dataclass

import serial

# == globals ==

FRAME_START = 0x0A
FRAME_END = 0x0D
FRAME_TYPE_BASE64 = ord("$")

# application modes (OptiScan/Application/ApplicationModeId.h)
MODE_NORMAL = 0x10
MODE_FILE_SYSTEM = 0x20
MODE_NAMES = {0x00: "None", 0x10: "Normal", 0x20: "FileSystem", 0x21: "FileSystemRead",
              0x22: "FileSystemWrite", 0x30: "Trace"}


# command ids (OptiScan/Commands/CommandId.h): (high << 8) | group
def _cmd(group, high):
    return (high << 8) | group


CMD_ID_GET = _cmd(0x00, 0x03)
CMD_MODE_GET = _cmd(0x00, 0x04)
CMD_MODE_SET = _cmd(0x00, 0x05)
CMD_ERROR = _cmd(0x00, 0xEE)
CMD_FS_MOUNT = _cmd(MODE_FILE_SYSTEM, 0x05)
CMD_FS_MOUNT_GET = _cmd(MODE_FILE_SYSTEM, 0x06)
CMD_FS_LIST = _cmd(MODE_FILE_SYSTEM, 0x0A)
CMD_FS_STATUS_GET = _cmd(MODE_FILE_SYSTEM, 0x0C)
CMD_FS_UNLINK = _cmd(MODE_FILE_SYSTEM, 0x13)

# file types (OptiScan/Commands/CommandFileInfo.h)
TYPE_REGULAR = 0x00
TYPE_DIRECTORY = 0x10

PATH_SEP = "/"

# == classes ==


class DeviceError(Exception):
    """Error response (CommandId::Error) of the box."""


class Reader:
    """Little endian reader for a decoded base64 payload."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def can_read(self):
        return self.pos < len(self.data)

    def _take(self, n):
        if self.pos + n > len(self.data):
            raise ValueError("response too short")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self):
        return self._take(1)[0]

    def u16(self):
        return struct.unpack("<H", self._take(2))[0]

    def u64(self):
        return struct.unpack("<Q", self._take(8))[0]

    def string(self):
        return self._take(self.u16()).decode("utf-8", errors="replace")

    def datetime(self):
        year = self.u16()
        mon, day, hour, minute, sec = self._take(5)
        return f"{year:04d}-{mon:02d}-{day:02d} {hour:02d}:{minute:02d}:{sec:02d}"

    def end(self):
        if self.can_read():
            raise ValueError(f"unexpected {len(self.data) - self.pos} bytes at end of response")


def pack_string(text):
    raw = text.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


class Edge2Device:
    """OptiScan base64 protocol over a serial port."""

    def __init__(self, port, baudrate, timeout, verbose=False):
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        self.timeout = timeout
        self.verbose = verbose
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def request(self, cmd_id, params=b""):
        """Send a command and return a Reader on the parameters of the matching response."""
        data = struct.pack("<H", cmd_id) + params
        frame = bytes([FRAME_START, FRAME_TYPE_BASE64]) + base64.b64encode(data) + bytes([FRAME_END])
        if self.verbose:
            print(f"  >> {cmd_id:04X} {params.hex()}", file=sys.stderr)
        self.ser.write(frame)

        deadline = time.monotonic() + self.timeout
        while True:
            payload = self._receive_base64(deadline)
            if payload is None or len(payload) < 2:
                continue
            reader = Reader(payload)
            resp_id = reader.u16()
            if self.verbose:
                print(f"  << {resp_id:04X} {payload[2:].hex()}", file=sys.stderr)
            if resp_id == cmd_id:
                return reader
            if resp_id == CMD_ERROR:
                failed_id = reader.u16()
                text = reader.string() if reader.can_read() else ""
                raise DeviceError(f"device error for command 0x{failed_id:04X}: {text}")
            # other frames (e.g. log messages) are ignored

    def _receive_base64(self, deadline):
        """Read one frame, return the decoded payload of a base64 frame or None for other frames."""
        # wait for frame start
        while True:
            b = self._read_byte(deadline)
            if b == FRAME_START:
                break
        buf = bytearray()
        while True:
            b = self._read_byte(deadline)
            if b == FRAME_END:
                break
            if b == FRAME_START:  # frame restarted, resync
                buf.clear()
                continue
            buf.append(b)
        if not buf or buf[0] != FRAME_TYPE_BASE64:
            return None  # debug / text frame
        try:
            return base64.b64decode(bytes(buf[1:]), validate=True)
        except ValueError:
            return None

    def _read_byte(self, deadline):
        while True:
            b = self.ser.read(1)
            if b:
                return b[0]
            if time.monotonic() > deadline:
                raise TimeoutError("no response from box (check port, baudrate and cable)")

    # -- commands --

    def get_id(self):
        r = self.request(CMD_ID_GET)
        value = r.string()
        r.end()
        return value

    def get_mode(self):
        r = self.request(CMD_MODE_GET)
        value = r.u8()
        r.end()
        return value

    def set_mode(self, mode):
        self.request(CMD_MODE_SET, bytes([mode])).end()

    def is_mounted(self):
        r = self.request(CMD_FS_MOUNT_GET)
        value = r.u8() != 0
        r.end()
        return value

    def mount(self):
        self.request(CMD_FS_MOUNT).end()

    def list_dir(self, path):
        r = self.request(CMD_FS_LIST, pack_string(path))
        entries = []
        while r.can_read():
            ftype = r.u8()
            name = r.string()
            entries.append((ftype, name))
        return entries

    def file_status(self, path):
        r = self.request(CMD_FS_STATUS_GET, pack_string(path))
        ftype = r.u8()
        r.string()  # name
        size = r.u64()
        mtime = r.datetime()
        r.end()
        return ftype, size, mtime

    def unlink(self, path):
        """Delete a file or an empty directory."""
        self.request(CMD_FS_UNLINK, pack_string(path)).end()


@dataclass
class FileEntry:
    path: str
    is_dir: bool
    size: int = 0
    mtime: str = ""


# == functions ==


def join_path(directory, name):
    if directory.endswith(PATH_SEP):
        return directory + name
    return directory + PATH_SEP + name


def walk(dev, path, entries, on_file):
    """Recursively list path, append FileEntry objects, call on_file for each regular file."""
    for ftype, name in dev.list_dir(path):
        if name in (".", ".."):
            continue
        child = join_path(path, name)
        if ftype == TYPE_DIRECTORY:
            entries.append(FileEntry(child, True))
            walk(dev, child, entries, on_file)
        else:
            _, size, mtime = dev.file_status(child)
            entry = FileEntry(child, False, size, mtime)
            entries.append(entry)
            on_file(entry)


def dir_totals(entries, root):
    """Cumulated size and file count per directory (incl. sub directories)."""
    totals = {root: [0, 0]}
    for e in entries:
        if e.is_dir:
            totals.setdefault(e.path, [0, 0])
            continue
        d = e.path.rsplit(PATH_SEP, 1)[0] or PATH_SEP
        while True:
            t = totals.setdefault(d, [0, 0])
            t[0] += e.size
            t[1] += 1
            if d == root or len(d) <= len(root):
                break
            d = d.rsplit(PATH_SEP, 1)[0] or PATH_SEP
    return totals


def find_matches(dev, pattern, cache):
    """Return [(path, type)] matching pattern, wildcards per path segment, ** = any depth."""
    if not pattern.startswith(PATH_SEP):
        pattern = PATH_SEP + pattern
    segments = [s for s in pattern.split(PATH_SEP) if s]
    found = {}

    def listing(path):
        if path not in cache:
            try:
                cache[path] = [(t, n) for t, n in dev.list_dir(path) if n not in (".", "..")]
            except DeviceError:
                cache[path] = []  # directory does not exist
        return cache[path]

    def match(base, segs):
        if not segs:
            return
        seg, rest = segs[0], segs[1:]
        if seg == "**":
            match(base, rest)  # zero directories
            for ftype, name in listing(base):
                if ftype == TYPE_DIRECTORY:
                    match(join_path(base, name), segs)  # one or more directories
            return
        for ftype, name in listing(base):
            if fnmatch.fnmatchcase(name.lower(), seg.lower()):
                child = join_path(base, name)
                if not rest:
                    found[child] = ftype
                elif ftype == TYPE_DIRECTORY:
                    match(child, rest)

    match(PATH_SEP, segments)
    return sorted(found.items())


def do_ls(dev, args):
    entries = []
    print()
    print(f"{'SIZE':>12}  {'MODIFIED':<19}  PATH")
    try:
        walk(dev, args.path, entries,
             lambda e: print(f"{e.size:>12}  {e.mtime:<19}  {e.path}", flush=True))
    finally:
        files = [e for e in entries if not e.is_dir]
        if files:
            print()
            print(f"{'SIZE':>12}  {'FILES':>6}  DIRECTORY (incl. sub directories)")
            for d, (size, count) in sorted(dir_totals(entries, args.path).items()):
                print(f"{size:>12}  {count:>6}  {d}")
            print()
            print(f"Total: {len(files)} files, {len(entries) - len(files)} directories, "
                  f"{sum(e.size for e in files)} bytes")
        if args.csv and entries:
            write_csv(args.csv, entries)
            print(f"CSV written to {args.csv}")


def do_rm(dev, args):
    cache = {}
    matches = {}
    for pattern in args.rm:
        found = find_matches(dev, pattern, cache)
        if not found:
            print(f"no match: {pattern}")
        matches.update(found)

    # build delete list: files, and with -r directories (content first, deepest first)
    to_delete = []  # FileEntry
    for path, ftype in sorted(matches.items()):
        if ftype == TYPE_DIRECTORY:
            if not args.recursive:
                print(f"skipping directory {path} (use -r)")
                continue
            content = []
            walk(dev, path, content, lambda e: None)
            to_delete.extend(e for e in content if not e.is_dir)
            to_delete.extend(sorted((e for e in content if e.is_dir), key=lambda e: -e.path.count(PATH_SEP)))
            to_delete.append(FileEntry(path, True))
        else:
            _, size, mtime = dev.file_status(path)
            to_delete.append(FileEntry(path, False, size, mtime))
    # remove duplicates (overlapping patterns), keep order
    seen = set()
    to_delete = [e for e in to_delete if not (e.path in seen or seen.add(e.path))]
    if not to_delete:
        print("nothing to delete")
        return

    files = [e for e in to_delete if not e.is_dir]
    print()
    print(f"{'SIZE':>12}  {'MODIFIED':<19}  PATH")
    for e in to_delete:
        if e.is_dir:
            print(f"{'<DIR>':>12}  {'':<19}  {e.path}")
        else:
            print(f"{e.size:>12}  {e.mtime:<19}  {e.path}")
    summary = (f"{len(files)} files ({sum(e.size for e in files)} bytes), "
               f"{len(to_delete) - len(files)} directories")
    if not args.yes:
        answer = input(f"\nDelete {summary}? [y/N] ").strip().lower()
        if answer not in ("y", "yes", "j", "ja"):
            print("nothing deleted")
            return

    n_ok = 0
    for e in to_delete:
        try:
            dev.unlink(e.path)
            n_ok += 1
            print(f"deleted {e.path}")
        except DeviceError as ex:
            print(f"error: {e.path}: {ex}", file=sys.stderr)
    print(f"\nDeleted {n_ok} of {len(to_delete)} entries")
    if n_ok != len(to_delete):
        raise DeviceError("not all entries could be deleted")


def write_csv(path, entries):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["path", "type", "size", "modified"])
        for e in entries:
            w.writerow([e.path, "dir" if e.is_dir else "file", "" if e.is_dir else e.size, e.mtime])


def parse_args():
    parser = argparse.ArgumentParser(
        description="List or delete files of the Edge2 box file system (eMMC) via serial port.")
    parser.add_argument("port", help="serial port, e.g. COM6 or /dev/ttyUSB0")
    cmd = parser.add_mutually_exclusive_group()
    cmd.add_argument("--ls", action="store_true", help="list all files with size (default)")
    cmd.add_argument("--rm", nargs="+", metavar="PATTERN",
                     help="delete files matching the pattern(s); wildcards * ? [..] per path segment, "
                          "** = any number of directories, case-insensitive, e.g. \"/LOG/*.bin\"")
    parser.add_argument("-p", "--path", default=PATH_SEP,
                        help="--ls: start directory on the box (default: %(default)s)")
    parser.add_argument("-o", "--csv", help="--ls: additionally write the list to this CSV file")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="--rm: also delete matching directories with their content")
    parser.add_argument("-y", "--yes", action="store_true", help="--rm: do not ask for confirmation")
    parser.add_argument("-b", "--baudrate", type=int, default=115200, help="baudrate (default: %(default)s)")
    parser.add_argument("-t", "--timeout", type=float, default=20.0,
                        help="response timeout in seconds (default: %(default)s)")
    parser.add_argument("--keep-mode", action="store_true",
                        help="stay in file system mode (default: restore the previous mode)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every sent / received frame")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        dev = Edge2Device(args.port, args.baudrate, args.timeout, args.verbose)
    except serial.SerialException as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    old_mode = None
    rc = 0
    try:
        print(f"Box id: {dev.get_id()}")
        old_mode = dev.get_mode()
        print(f"Mode:   {MODE_NAMES.get(old_mode, hex(old_mode))}")
        if old_mode != MODE_FILE_SYSTEM:
            print("Switching to mode FileSystem ...")
            dev.set_mode(MODE_FILE_SYSTEM)
        if not dev.is_mounted():
            print("Mounting file system ...")
            dev.mount()
        if args.rm:
            do_rm(dev, args)
        else:
            do_ls(dev, args)
    except KeyboardInterrupt:
        print("\nAborted by user (Ctrl-C).", file=sys.stderr)
        rc = 130
    except (DeviceError, TimeoutError, ValueError, serial.SerialException) as e:
        print(f"error: {e}", file=sys.stderr)
        rc = 1
    finally:
        if old_mode is not None and old_mode != MODE_FILE_SYSTEM and not args.keep_mode:
            try:
                print(f"Restoring mode {MODE_NAMES.get(old_mode, hex(old_mode))} ...")
                dev.set_mode(old_mode)
            except (DeviceError, TimeoutError, ValueError, serial.SerialException) as e:
                print(f"error: restoring mode failed: {e}", file=sys.stderr)
                rc = rc or 1
        dev.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
