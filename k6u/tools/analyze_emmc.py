"""
analyze_emmc.py - listet über die serielle Schnittstelle alle Dateien im Dateisystem (eMMC)
einer Edge2-Box mit Größe und Änderungsdatum auf bzw. löscht Dateien.

Usage:

    analyze_emmc <port> [--ls] [-p <path>] [-o <csvfile>] [options]
    analyze_emmc <port> --rm <pattern>... [-r] [-y] [options]
    analyze_emmc <port> --get [-p <path>] [-x <pattern>]... [-B <n>] [options]

    port            - serial port, e.g. COM6 or /dev/ttyUSB0
    --ls            - list all files with size (default command)
    -p <path>       - start directory on the box for --ls (default: /)
    -o <csvfile>    - additionally write the list as CSV (path;type;size;modified)
    --rm <pattern>  - delete files matching the pattern(s), wildcards per path segment:
                      * ? [abc], ** = any number of directories, case-insensitive
                      e.g. "/LOG/*.bin", "/**/*.tmp"
    -r              - with --rm: also delete matching directories with their content
    -y              - with --rm: do not ask for confirmation
    --get           - download all files (below -p) into <BoxSerial>-<YYYYmmdd-HHMM>.zip
    -x <pattern>    - with --get: exclude matching files / directories (repeatable),
                      a pattern without '/' matches the name in any directory, e.g. -x "*.bin"
    -B, --block-size <n> - with --get: bytes per read request (default: baudrate / 20, 512..2048)
    -b <baudrate>   - baudrate to connect with, default 115200
    -f              - switch to the fast baudrate (BaudRateSet) after connecting, back to -b at the end
    --fast-baudrate <n> - baudrate for -f (default: 1500000)
    -t <timeout>    - response timeout in seconds (default: 20)
    --keep-mode     - stay in file system mode (default: restore the previous mode)
    -v              - print every sent / received frame

Protokoll (wie ServiceToolGen2 / OptiScan):

    Frame:    0x0A '$' <base64(data)> 0x0D
    data:     <command id uint16 LE> <parameters, little endian>
    string:   <length uint16> <utf-8 bytes>
    Response: same command id, on failure command id Error (0xEE00) + failed id + text

Ablauf: ModeGet -> ModeSet(FileSystem) -> MountGet/Mount -> rekursiv FileSystemList und
FileSystemStatusGet je Datei (bzw. FileSystemUnlink, FileSystemReadStart/Read)
-> ModeSet(vorheriger Mode).
"""

# == modules ==
import argparse
import base64
import csv
import fnmatch
import struct
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime

import serial

# == globals ==

FRAME_START = 0x0A
FRAME_END = 0x0D
FRAME_TYPE_BASE64 = ord("$")

# application modes (OptiScan/Application/ApplicationModeId.h)
MODE_NORMAL = 0x10
MODE_FILE_SYSTEM = 0x20
MODE_FILE_SYSTEM_READ = 0x21
MODE_NAMES = {0x00: "None", 0x10: "Normal", 0x20: "FileSystem", 0x21: "FileSystemRead",
              0x22: "FileSystemWrite", 0x30: "Trace"}


# command ids (OptiScan/Commands/CommandId.h): (high << 8) | group
def _cmd(group, high):
    return (high << 8) | group


CMD_SOFTWARE_VERSION_GET = _cmd(0x00, 0x02)
CMD_ID_GET = _cmd(0x00, 0x03)
CMD_MODE_GET = _cmd(0x00, 0x04)
CMD_MODE_SET = _cmd(0x00, 0x05)
CMD_FLASH_READ = _cmd(0x00, 0x08)
CMD_BAUDRATE_LIST = _cmd(0x00, 0x10)
CMD_BAUDRATE_SET = _cmd(0x00, 0x11)
CMD_ERROR = _cmd(0x00, 0xEE)
CMD_FS_MOUNT = _cmd(MODE_FILE_SYSTEM, 0x05)
CMD_FS_MOUNT_GET = _cmd(MODE_FILE_SYSTEM, 0x06)
CMD_FS_LIST = _cmd(MODE_FILE_SYSTEM, 0x0A)
CMD_FS_STATUS_GET = _cmd(MODE_FILE_SYSTEM, 0x0C)
CMD_FS_UNLINK = _cmd(MODE_FILE_SYSTEM, 0x13)
CMD_FS_READ_START = _cmd(MODE_FILE_SYSTEM, 0x20)
CMD_FS_READ = _cmd(MODE_FILE_SYSTEM_READ, 0x20)

# flash sections (OptiScan/Commands/CommandFlashSection.h)
FLASH_SERIAL_NUMBER = 0x00000000
SERIAL_DIGITS = 12  # SerialNumber::getSerial_12_01(): value % 10^12

# file types (OptiScan/Commands/CommandFileInfo.h)
TYPE_REGULAR = 0x00
TYPE_DIRECTORY = 0x10

PATH_SEP = "/"

MAX_BLOCK_SIZE = 512     # default block size limit: larger blocks fail at 1500000 baud (Pegasus20)
FAST_BAUDRATE = 1500000  # highest entry of the ServiceTool baudrate list

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

    def u32(self):
        return struct.unpack("<I", self._take(4))[0]

    def rest(self):
        return self._take(len(self.data) - self.pos)

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
        # short read timeout: _read_byte() polls and checks the response deadline itself
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        self.timeout = timeout  # response (inactivity) timeout
        self.verbose = verbose
        self._rx = b""  # received bytes not yet processed
        self._rx_pos = 0
        self._deadline = 0.0
        self._reset_rx()

    def reopen(self, baudrate):
        """Close and reopen the port with a new baudrate (changing the baudrate of the open
        port is not sufficient for the USB serial adapter). Other settings are kept."""
        self.ser.close()
        self.ser.baudrate = baudrate
        self.ser.open()
        self._reset_rx()

    def answers_at(self, baudrate, timeout=2.0):
        """Reopen the port at baudrate and check with IdGet if the box answers. Used after a
        timeout at the fast baudrate: a restarted box (e.g. watchdog) is back at the slow baudrate.
        If the box does not answer, the port is set back to the previous baudrate."""
        previous = self.ser.baudrate
        self.reopen(baudrate)
        old_timeout, self.timeout = self.timeout, timeout
        try:
            self.get_id()
            return True
        except (TimeoutError, ValueError, DeviceError):
            self.reopen(previous)
            return False
        finally:
            self.timeout = old_timeout

    def _reset_rx(self):
        self.ser.reset_input_buffer()
        self._rx = b""
        self._rx_pos = 0

    def close(self):
        self.ser.close()

    def request(self, cmd_id, params=b"", resp_id=None):
        """Send a command and return a Reader on the parameters of the matching response.

        resp_id: expected response id, if it differs from cmd_id (FileSystemReadStart)."""
        expected = cmd_id if resp_id is None else resp_id
        data = struct.pack("<H", cmd_id) + params
        frame = bytes([FRAME_START, FRAME_TYPE_BASE64]) + base64.b64encode(data) + bytes([FRAME_END])
        if self.verbose:
            print(f"  >> {cmd_id:04X} {params.hex()}", file=sys.stderr)
        self.ser.write(frame)

        self._deadline = time.monotonic() + self.timeout
        while True:
            payload = self._receive_base64()
            if payload is None or len(payload) < 2:
                continue
            reader = Reader(payload)
            resp_id = reader.u16()
            if self.verbose:
                print(f"  << {resp_id:04X} {payload[2:].hex()}", file=sys.stderr)
            if resp_id == expected:
                return reader
            if resp_id == CMD_ERROR:
                failed_id = reader.u16()
                text = reader.string() if reader.can_read() else ""
                raise DeviceError(f"device error for command 0x{failed_id:04X}: {text}")
            # other frames (e.g. log messages) are ignored

    def _receive_base64(self):
        """Read one frame, return the decoded payload of a base64 frame or None for other frames."""
        # wait for frame start
        while True:
            b = self._read_byte()
            if b == FRAME_START:
                break
        buf = bytearray()
        while True:
            try:
                b = self._read_byte()
            except TimeoutError as e:
                raise TimeoutError(f"{e}; response stopped after {len(buf)} bytes of a frame") from e
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

    def _read_byte(self):
        """Next received byte. The timeout is an inactivity timeout: it is restarted whenever data
        arrives, so long responses (large read blocks, the box reads byte by byte) do not time out."""
        while self._rx_pos >= len(self._rx):
            chunk = self.ser.read(max(1, self.ser.in_waiting))
            if chunk:
                self._rx = chunk
                self._rx_pos = 0
                self._deadline = time.monotonic() + self.timeout
            elif time.monotonic() > self._deadline:
                raise TimeoutError("no response from box (check port, baudrate and cable)")
        b = self._rx[self._rx_pos]
        self._rx_pos += 1
        return b

    # -- commands --

    def get_id(self):
        r = self.request(CMD_ID_GET)
        value = r.string()
        r.end()
        return value

    def get_software_version(self):
        """Firmware version (Version3: major, minor, patch uint16, optional special string)."""
        r = self.request(CMD_SOFTWARE_VERSION_GET)
        version = f"{r.u16()}.{r.u16()}.{r.u16()}"
        if r.can_read():
            special = r.string()
            if special:
                version += f"-{special}"
        r.end()
        return version

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

    def list_baudrates(self):
        r = self.request(CMD_BAUDRATE_LIST)
        rates = []
        while r.can_read():
            rates.append(r.u32())
        return rates

    def switch_baudrate(self, baudrate):
        """Switch box and PC port to a new baudrate (BaudRateSet). The box acknowledges at the
        old baudrate, then re-initializes its UART. The new connection is checked with ModeGet."""
        if baudrate == self.ser.baudrate:
            return
        self.request(CMD_BAUDRATE_SET, struct.pack("<I", baudrate)).end()
        time.sleep(0.05)  # box: wait for output, re-init UART
        self.reopen(baudrate)
        last_error = None
        for _ in range(3):  # first frame after the switch may be garbled
            try:
                old_timeout, self.timeout = self.timeout, min(self.timeout, 2.0)
                try:
                    self.get_mode()
                finally:
                    self.timeout = old_timeout
                return
            except (TimeoutError, ValueError) as e:
                last_error = e
                self._reset_rx()
        raise TimeoutError(f"no response after switching to {baudrate} baud: {last_error}")

    def get_serial(self):
        """Box serial number as 12 digit text (as shown by the ServiceTool)."""
        r = self.request(CMD_FLASH_READ, struct.pack("<I", FLASH_SERIAL_NUMBER))
        if r.u32() != FLASH_SERIAL_NUMBER:
            raise ValueError("FlashRead: unexpected section id")
        data = r.rest()
        if len(data) != 8:
            raise ValueError(f"FlashRead: serial number has {len(data)} bytes, expected 8")
        value = struct.unpack("<Q", data)[0] % 10**SERIAL_DIGITS
        return f"{value:0{SERIAL_DIGITS}d}"

    def read_file(self, path, block_size, progress=None):
        """Read a whole file. The box is in mode FileSystemRead during the transfer and
        is switched back to FileSystem afterwards (also on error / Ctrl-C, not after a timeout:
        the box does not answer then)."""
        data = bytearray()
        timed_out = False
        try:
            r = self.request(CMD_FS_READ_START, pack_string(path) + struct.pack("<QI", 0, block_size),
                             resp_id=CMD_FS_READ)
            while True:
                offset = r.u64()
                if offset != len(data):
                    raise ValueError(f"read {path}: offset {offset}, expected {len(data)}")
                block = r.rest()
                data += block
                if progress:
                    progress(len(data))
                if len(block) < block_size:
                    break  # short block = end of file
                r = self.request(CMD_FS_READ)
        except TimeoutError:
            timed_out = True
            raise
        finally:
            if not timed_out:
                # leave mode FileSystemRead, closes the file on the box
                self.set_mode(MODE_FILE_SYSTEM)
        return bytes(data)


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


def walk(dev, path, entries, on_file, skip=None):
    """Recursively list path, append FileEntry objects, call on_file for each regular file.

    skip(path, is_dir): return True to leave out a file / a directory with its content."""
    for ftype, name in dev.list_dir(path):
        if name in (".", ".."):
            continue
        child = join_path(path, name)
        if skip and skip(child, ftype == TYPE_DIRECTORY):
            continue
        if ftype == TYPE_DIRECTORY:
            entries.append(FileEntry(child, True))
            walk(dev, child, entries, on_file, skip)
        else:
            _, size, mtime = dev.file_status(child)
            entry = FileEntry(child, False, size, mtime)
            entries.append(entry)
            on_file(entry)


def path_matches(pattern, path):
    """Match a box path against a pattern, wildcards per path segment, ** = any depth,
    case-insensitive. A pattern without '/' matches the name in any directory."""
    if PATH_SEP not in pattern:
        pattern = "**" + PATH_SEP + pattern
    pat = [s.lower() for s in pattern.split(PATH_SEP) if s]
    segs = [s.lower() for s in path.split(PATH_SEP) if s]

    def match(p, s):
        if not p:
            return not s
        if p[0] == "**":
            return any(match(p[1:], s[i:]) for i in range(len(s) + 1))
        return bool(s) and fnmatch.fnmatchcase(s[0], p[0]) and match(p[1:], s[1:])

    return match(pat, segs)


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


def zip_date_time(mtime):
    """'YYYY-MM-DD HH:MM:SS' -> zip date_time tuple (zip supports 1980..2107)."""
    try:
        dt = datetime.strptime(mtime, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return (1980, 1, 1, 0, 0, 0)
    if not 1980 <= dt.year <= 2107:
        return (1980, 1, 1, 0, 0, 0)
    return dt.timetuple()[:6]


def do_get(dev, args, serial_no):
    excluded = []

    def skip(path, is_dir):
        if any(path_matches(p, path) for p in args.exclude or ()):
            excluded.append(path + (PATH_SEP if is_dir else ""))
            return True
        return False

    entries = []
    walk(dev, args.path, entries, lambda e: None, skip)
    if excluded:
        print(f"\nExcluded {len(excluded)} entries:")
        for p in excluded:
            print(f"  {p}")
    files = [e for e in entries if not e.is_dir]
    total = sum(e.size for e in files)
    zip_name = f"{serial_no}-{datetime.now():%Y%m%d-%H%M}.zip"
    block_size = args.block_size or min(MAX_BLOCK_SIZE, max(512, dev.ser.baudrate // 20))
    print(f"\nDownloading {len(files)} files, {total} bytes into {zip_name} (block size {block_size})\n")

    done_bytes = 0
    n_ok = 0
    errors = []
    t_start = time.monotonic()
    complete = False
    with zipfile.ZipFile(zip_name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        try:
            for i, e in enumerate(files, 1):
                prefix = f"[{i}/{len(files)}] {e.path}"

                def progress(n, prefix=prefix, size=e.size):
                    pct = 100 * n // size if size else 100
                    print(f"\r{prefix}  {n}/{size} bytes ({pct}%)", end="", flush=True)

                try:
                    data = dev.read_file(e.path, block_size, progress)
                except DeviceError as ex:
                    print(f"\r{prefix}  error: {ex}")
                    errors.append(e.path)
                    continue
                info = zipfile.ZipInfo(e.path.lstrip(PATH_SEP), date_time=zip_date_time(e.mtime))
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data)
                done_bytes += len(data)
                n_ok += 1
                note = "" if len(data) == e.size else f"  (size on box {e.size})"
                print(f"\r{prefix}  {len(data)} bytes ok{note}")
            complete = True
        finally:
            # empty directories are stored as directory entries
            for d in (e for e in entries if e.is_dir):
                if not any(f.path.startswith(d.path + PATH_SEP) for f in files):
                    zf.writestr(zipfile.ZipInfo(d.path.lstrip(PATH_SEP) + "/", date_time=(1980, 1, 1, 0, 0, 0)), b"")
            secs = time.monotonic() - t_start
            rate = done_bytes / secs / 1024 if secs > 0 else 0
            print(f"\n{n_ok} of {len(files)} files, {done_bytes} bytes in {secs:.0f} s ({rate:.1f} KiB/s) "
                  f"written to {zip_name}" + ("" if complete else "  -- INCOMPLETE (aborted)"))
    if errors:
        raise DeviceError(f"{len(errors)} file(s) could not be read: {', '.join(errors)}")


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
    cmd.add_argument("--get", action="store_true",
                     help="download all files (below -p) into <BoxSerial>-<YYYYmmdd-HHMM>.zip")
    parser.add_argument("-p", "--path", default=PATH_SEP,
                        help="--ls/--get: start directory on the box (default: %(default)s)")
    parser.add_argument("-x", "--exclude", action="append", metavar="PATTERN",
                        help="--get: do not download files / directories matching the pattern (repeatable); "
                             "wildcards as --rm, a pattern without '/' matches the name in any directory")
    parser.add_argument("-B", "--block-size", type=int,
                        help="--get: bytes per read request (default: baudrate / 20, 512..2048)")
    parser.add_argument("-o", "--csv", help="--ls: additionally write the list to this CSV file")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="--rm: also delete matching directories with their content")
    parser.add_argument("-y", "--yes", action="store_true", help="--rm: do not ask for confirmation")
    parser.add_argument("-b", "--baudrate", type=int, default=115200,
                        help="baudrate to connect with (default: %(default)s)")
    parser.add_argument("-f", "--fast", action="store_true",
                        help="switch the box to the fast baudrate after connecting (BaudRateSet) "
                             "and back to -b at the end")
    parser.add_argument("--fast-baudrate", type=int, default=FAST_BAUDRATE,
                        help="baudrate for -f (default: %(default)s)")
    parser.add_argument("-t", "--timeout", type=float, default=20.0,
                        help="response timeout in seconds (default: %(default)s)")
    parser.add_argument("--keep-mode", action="store_true",
                        help="stay in file system mode (default: restore the previous mode)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every sent / received frame")
    return parser.parse_args()


def check_box_paths(args):
    """Box paths never contain ':' (FAT). A drive letter means Git Bash (MSYS) has converted
    an argument like /LOG into C:/Program Files/Git/LOG."""
    for p in [args.path, *(args.rm or ()), *(args.exclude or ())]:
        if ":" in p:
            print(f"error: '{p}' is not a box path - converted by Git Bash? Write //LOG instead of /LOG "
                  "or set MSYS_NO_PATHCONV=1", file=sys.stderr)
            sys.exit(2)


def main():
    args = parse_args()
    check_box_paths(args)
    try:
        dev = Edge2Device(args.port, args.baudrate, args.timeout, args.verbose)
    except serial.SerialException as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    old_mode = None
    rc = 0
    try:
        print(f"Box id: {dev.get_id()}")
        serial_no = dev.get_serial()
        print(f"Serial: {serial_no}")
        if args.fast and args.fast_baudrate != args.baudrate:
            print(f"Switching to {args.fast_baudrate} baud ...")
            try:
                dev.switch_baudrate(args.fast_baudrate)
            except DeviceError as e:
                rates = dev.list_baudrates()
                raise DeviceError(f"{e} (box supports {', '.join(map(str, rates))})") from e
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
        elif args.get:
            do_get(dev, args, serial_no)
        else:
            do_ls(dev, args)
    except KeyboardInterrupt:
        print("\nAborted by user (Ctrl-C).", file=sys.stderr)
        rc = 130
    except (DeviceError, TimeoutError, ValueError, serial.SerialException) as e:
        print(f"error: {e}", file=sys.stderr)
        rc = 1
        if isinstance(e, TimeoutError) and dev.ser.baudrate != args.baudrate:
            print(f"Checking if the box answers at {args.baudrate} baud ...", file=sys.stderr)
            if dev.answers_at(args.baudrate):
                print(f"error: box answers at {args.baudrate} baud again - it has restarted "
                      "(watchdog?), mode and baudrate are reset", file=sys.stderr)
                old_mode = None  # box is in its start mode, nothing to restore
    finally:
        if old_mode is not None and old_mode != MODE_FILE_SYSTEM and not args.keep_mode:
            try:
                print(f"Restoring mode {MODE_NAMES.get(old_mode, hex(old_mode))} ...")
                dev.set_mode(old_mode)
            except (DeviceError, TimeoutError, ValueError, serial.SerialException) as e:
                print(f"error: restoring mode failed: {e}", file=sys.stderr)
                rc = rc or 1
        if dev.ser.baudrate != args.baudrate:
            try:
                print(f"Restoring {args.baudrate} baud ...")
                dev.switch_baudrate(args.baudrate)
            except (DeviceError, TimeoutError, ValueError, serial.SerialException) as e:
                print(f"error: restoring baudrate failed, box stays at {dev.ser.baudrate} baud "
                      f"until reboot: {e}", file=sys.stderr)
                rc = rc or 1
        dev.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
