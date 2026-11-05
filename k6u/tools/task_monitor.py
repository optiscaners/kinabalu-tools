"""
task_monitor.py - Decodes task monitor data (watchdog state and log id call stack per task)

Usage:

    task_monitor [-s <srcdir>]... [-c] [-o <outfile>] [-h] <file>

    <file>          - task monitor data, detected by its first bytes:
                      0xFA 0xCE: data (Ram_TaskMonitor.bin or flash read "TaskMonitor" of the ServiceTool)
                      "TM":      flash format data (data flash file header + data)
                      otherwise: text dump ("Task List: ...")
    -s <srcdir>     - firmware source directory scanned for log id names; may be given
                      several times (e.g. Common, Firmware and the project directory)
    -c              - compact: show only used log id slots (default: all slots)
    -o <outfile>    - write result to file instead of stdout
    -h              - show help and exit

Binary input is decoded into the text format of the C# TaskMonitorDataViewer. A text dump is
passed through and annotated. With -s, every log id is resolved to
"<library>/<module>/<part>/<action>" using the MODULE(), OPTISCAN_SYSTEM_LOG_DECL_PART()
and OPTISCAN_SYSTEM_LOG_DECL_ACTION() declarations found in the sources.
"""

# == modules ==
import getopt
import re
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path

# == globals ==

MAGIC = (0xFA, 0xCE)
VERSION_MAJOR = 2
HEADER_FORMAT = "<BBBBIII"  # magic0, magic1, major, minor, task count, watchdog size, log size
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
WATCHDOG_FORMAT = "<IIIII"  # has timeout, is enabled, is serviced, is test enabled, timeout [ms]
WATCHDOG_SIZE = struct.calcsize(WATCHDOG_FORMAT)

# data flash file header (DataFlashFileHeader): magic "TM", data size, unused (0)
FLASH_MAGIC = b"TM"
FLASH_HEADER_FORMAT = "<2sHI"
FLASH_HEADER_SIZE = struct.calcsize(FLASH_HEADER_FORMAT)

# firmware TaskIdentity::Category (the C# viewer still names 1 "Idle")
CATEGORIES = {0: "None", 1: "Main", 2: "Task", 3: "Isr2", 4: "Isr1"}

# library base ids from Log.h
LIB_BASES = {"IdUnspecific": 0, "IdSpecific": 1}
APP_LIB = (1, 0x3F)

SOURCE_EXTENSIONS = {".h", ".hpp", ".c", ".cpp"}
SKIP_DIRS = {".git", "build", "__pycache__"}
SKIP_DIR_PREFIXES = ("cmake-build", "_PACKAGE")

NUM = r"(0x[0-9A-Fa-f]+|\d+)"
RE_LIB = re.compile(
    r"#\s*define\s+(\w+)\s+OPTISCAN_SYSTEM_LOG_ID_DECL_LIB\(\s*OPTISCAN_SYSTEM_LOG\(\s*(\w+)\s*\)\s*,\s*"
    + NUM
    + r"\s*\)"
)
RE_APP = re.compile(r"#\s*define\s+(\w+)\s+OPTISCAN_SYSTEM_LOG\(\s*IdApplication\s*\)")
RE_MODULE_DEF = re.compile(
    r"#\s*define\s+MODULE\(\s*\w+\s*,\s*\w+\s*\).*OPTISCAN_SYSTEM_LOG_ID_DECL_MODULE\(\s*(\w+)\s*,"
)
RE_MODULE = re.compile(r"^\s*MODULE\(\s*(\w+)\s*,\s*" + NUM + r"\s*\)")
RE_PART = re.compile(r"OPTISCAN_SYSTEM_LOG_DECL_PART\(\s*([\w:]+)\s*,\s*(\w+)\s*,\s*" + NUM + r"\s*\)")
RE_ACTION = re.compile(r"OPTISCAN_SYSTEM_LOG_DECL_ACTION\(\s*([\w:]+)\s*,\s*(\w+)\s*,\s*" + NUM + r"\s*\)")
RE_TEXT_ID = re.compile(
    r"^(\s*Id \d+: (True|False), (True|False), 0x([0-9A-Fa-f]{2}), 0x([0-9A-Fa-f]{2}), "
    r"0x([0-9A-Fa-f]{2}), 0x([0-9A-Fa-f]{2}))\s*$"
)

# == classes ==


# log id names collected from firmware sources
class LogNames:
    def __init__(self):
        self.libs = {}  # (specific, lib) -> set of names
        self.modules = {}  # (specific, lib, module) -> set of names
        self.parts = {}  # (specific, lib, module, part) -> set of names
        self.actions = {}  # (specific, lib, module, part, action) -> set of names

    @staticmethod
    def _add(table, key, name):
        table.setdefault(key, set()).add(name)

    def scan(self, src_dirs):
        files = [
            (f, list(clean_lines(f.read_text(encoding="utf-8", errors="replace")))) for f in iter_sources(src_dirs)
        ]

        # 1) library ids: name -> (specific, lib)
        lib_ids = {}
        for _, lines in files:
            for line in lines:
                if m := RE_LIB.search(line):
                    if m.group(2) in LIB_BASES:
                        lib_ids[m.group(1)] = (LIB_BASES[m.group(2)], int(m.group(3), 0))
                elif m := RE_APP.search(line):
                    lib_ids[m.group(1)] = APP_LIB
        for name, key in lib_ids.items():
            self._add(self.libs, key, strip_suffix(name, ("LibId", "AppId", "Id")))

        # 2) modules: "<name>ModuleId" -> set of (specific, lib, module)
        module_ids = {}
        for _, lines in files:
            lib = None
            for line in lines:
                if m := RE_MODULE_DEF.search(line):
                    lib = lib_ids.get(m.group(1))
                elif lib is not None and (m := RE_MODULE.match(line)):
                    key = (*lib, int(m.group(2), 0))
                    module_ids.setdefault(m.group(1) + "ModuleId", set()).add(key)
                    self._add(self.modules, key, m.group(1))

        # 3) parts: name -> set of keys, kept per file to resolve "Class::Part" locally first
        part_ids = {}
        file_parts = {}
        for f, lines in files:
            for line in lines:
                if m := RE_PART.search(line):
                    for module in module_ids.get(last_name(m.group(1)), ()):
                        key = (*module, int(m.group(3), 0))
                        part_ids.setdefault(m.group(2), set()).add(key)
                        file_parts.setdefault(f.stem, {}).setdefault(m.group(2), set()).add(key)
                        self._add(self.parts, key, m.group(2))

        # 4) actions: parent is a part or (without part) a module
        for f, lines in files:
            for line in lines:
                if m := RE_ACTION.search(line):
                    parent = last_name(m.group(1))
                    action = int(m.group(3), 0)
                    parents = file_parts.get(f.stem, {}).get(parent) or part_ids.get(parent)
                    if not parents:
                        parents = {(*module, 0) for module in module_ids.get(parent, ())}
                    for key in parents:
                        self._add(self.actions, (*key, action), m.group(2))

    def describe(self, specific, lib, module, part, action):
        def name(table, key, value):
            names = table.get(key)
            return "|".join(sorted(names)) if names else f"0x{value:02X}"

        result = [
            name(self.libs, (specific, lib), lib),
            name(self.modules, (specific, lib, module), module),
        ]
        if part != 0 or (specific, lib, module, 0) in self.parts:
            result.append(name(self.parts, (specific, lib, module, part), part))
        result.append(name(self.actions, (specific, lib, module, part, action), action))
        return "/".join(result)


# == functions ==


def iter_sources(src_dirs):
    for src_dir in src_dirs:
        stack = [Path(src_dir)]
        while stack:
            for p in sorted(stack.pop().iterdir()):
                if p.is_dir():
                    if p.name not in SKIP_DIRS and not p.name.startswith(SKIP_DIR_PREFIXES):
                        stack.append(p)
                elif p.suffix.lower() in SOURCE_EXTENSIONS:
                    yield p


# strips comments and "#if 0" blocks, other preprocessor conditions are ignored
def clean_lines(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    skip = 0
    for line in text.splitlines():
        line = line.split("//", 1)[0]
        s = line.strip()
        if skip:
            if re.match(r"#\s*if", s):
                skip += 1
            elif re.match(r"#\s*endif", s):
                skip -= 1
            elif skip == 1 and re.match(r"#\s*(else|elif)\b", s):
                skip = 0
            continue
        if re.match(r"#\s*if\s+0\b", s):
            skip = 1
            continue
        yield line


def last_name(name):
    return name.rsplit("::", 1)[-1]


def strip_suffix(name, suffixes):
    for suffix in suffixes:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def split_log_id(log_id):
    return (
        (log_id >> 31) & 0x1,
        (log_id >> 30) & 0x1,
        (log_id >> 24) & 0x3F,
        (log_id >> 16) & 0xFF,
        (log_id >> 8) & 0xFF,
        log_id & 0xFF,
    )


def format_identity(identity):
    category = (identity >> 24) & 0xFF
    core = (identity >> 16) & 0xFF
    sub_id = identity & 0xFFFF
    return f"Core{core}, {CATEGORIES.get(category, f'0x{category:02X}')}, {sub_id}"


def format_log_id(index, fields, names):
    active, specific, lib, module, part, action = fields
    line = (
        f"    Id {index}: {bool(active)}, {bool(specific)}, 0x{lib:02X}, 0x{module:02X}, 0x{part:02X}, 0x{action:02X}"
    )
    if names is not None and any(fields[1:]):
        line += f"  -> {names.describe(specific, lib, module, part, action)}"
    return line


# strips the data flash file header, trailing bytes after the data are ignored (as in the C# viewer)
def unwrap_flash_format(data):
    if len(data) < FLASH_HEADER_SIZE:
        raise ValueError(f"file too short for flash format header ({len(data)} bytes)")
    magic, data_size, unused = struct.unpack_from(FLASH_HEADER_FORMAT, data, 0)
    if magic != FLASH_MAGIC:
        raise ValueError(f"flash format magic mismatch {magic!r} (expected {FLASH_MAGIC!r})")
    if unused != 0:
        raise ValueError(f"flash format unused mismatch 0x{unused:08X} (expected 0)")
    if len(data) < FLASH_HEADER_SIZE + data_size:
        raise ValueError(f"flash format data too short ({len(data) - FLASH_HEADER_SIZE} of {data_size} bytes)")
    return data[FLASH_HEADER_SIZE : FLASH_HEADER_SIZE + data_size]


def decode_binary(data, names, compact):
    if len(data) < HEADER_SIZE + 4:
        raise ValueError(f"file too short ({len(data)} bytes)")
    magic0, magic1, major, minor, task_count, wd_size, log_size = struct.unpack_from(HEADER_FORMAT, data, 0)
    if (magic0, magic1) != MAGIC:
        raise ValueError(f"invalid magic 0x{magic0:02X} 0x{magic1:02X} (expected 0xFA 0xCE)")
    if wd_size not in (0, WATCHDOG_SIZE):
        raise ValueError(f"invalid task watchdog size {wd_size}")
    if log_size % 4 != 0:
        raise ValueError(f"invalid task log size {log_size}")
    task_size = 4 + wd_size + log_size
    expected = HEADER_SIZE + 4 + task_count * task_size
    if len(data) < expected:
        raise ValueError(f"file too short ({len(data)} bytes, expected {expected} for {task_count} tasks)")
    if len(data) > expected:
        raise ValueError(f"EOF expected ({len(data) - expected} trailing bytes after {task_count} tasks)")

    (timestamp,) = struct.unpack_from("<I", data, HEADER_SIZE)
    out = ["Header:"]
    out.append(f" Magic: 0x{magic0:02X}, 0x{magic1:02X}")
    out.append(f" Version: {major}.{minor}")
    if major != VERSION_MAJOR:
        out.append(f" Warning: decoder is written for version {VERSION_MAJOR}.x")
    out.append(f" Task Count: {task_count}")
    out.append(f" Task Watchdog Size: {wd_size}")
    out.append(f" Task Log Size: {log_size}")
    stamp = datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%S")
    out.append(f"Timestamp: {timestamp} ({stamp})")

    out.append("Task List:")
    capacity = (log_size - 4) // 4 if log_size else 0
    offset = HEADER_SIZE + 4
    for task in range(task_count):
        (identity,) = struct.unpack_from("<I", data, offset)
        offset += 4
        out.append(f" Task {task}:")
        out.append(f"  Identity: {format_identity(identity)}")
        if wd_size:
            has_timeout, is_enabled, is_serviced, is_test, timeout_ms = struct.unpack_from(
                WATCHDOG_FORMAT, data, offset
            )
            offset += wd_size
            out.append("  Watchdog Data:")
            out.append(f"   Has Timeout: {bool(has_timeout)}")
            out.append(f"   Is Enabled: {bool(is_enabled)}")
            out.append(f"   Is Serviced: {bool(is_serviced)}")
            out.append(f"   Is Test Enabled: {bool(is_test)}")
            out.append(f"   Timeout [ms]: {timeout_ms}")
        if log_size:
            (depth,) = struct.unpack_from("<I", data, offset)
            ids = struct.unpack_from(f"<{capacity}I", data, offset + 4)
            offset += log_size
            out.append("  Log Data:")
            if depth > capacity:
                out.append(f"   Stack Depth: {depth} (exceeds capacity {capacity}, deeper ids not stored)")
            else:
                out.append(f"   Stack Depth: {depth}")
            out.append("   Log Id List:")
            if compact:
                used = max((i + 1 for i, v in enumerate(ids) if v), default=0)
                count = min(capacity, max(depth, used))
            else:
                count = capacity
            for i in range(count):
                out.append(format_log_id(i, split_log_id(ids[i]), names))
    return out


def annotate_text(text, names):
    out = []
    for line in text.splitlines():
        m = RE_TEXT_ID.match(line)
        if m and names is not None:
            specific = m.group(3) == "True"
            fields = [int(m.group(i), 16) for i in range(4, 8)]
            if specific or any(fields):
                line = f"{m.group(1)}  -> {names.describe(int(specific), *fields)}"
        out.append(line)
    return out


def barf_and_exit(retcode, diag=None):
    if diag:
        print(diag)
    print(__doc__)
    sys.exit(retcode)


# == main ==
def main():
    src_dirs = []
    compact = False
    out_file = None

    try:
        opts, args = getopt.getopt(sys.argv[1:], "s:o:ch")
    except getopt.GetoptError as e:
        barf_and_exit(-1, f"Error: {e}")

    for o, v in opts:
        if o == "-s":
            src_dirs.append(Path(v))
        elif o == "-o":
            out_file = Path(v)
        elif o == "-c":
            compact = True
        elif o == "-h":
            barf_and_exit(0)

    if len(args) != 1:
        barf_and_exit(-2, "Error: exactly one input file is required")
    for d in src_dirs:
        if not d.is_dir():
            barf_and_exit(-3, f"Error: source directory not found: {d}")

    in_file = Path(args[0])
    try:
        data = in_file.read_bytes()
    except OSError as e:
        barf_and_exit(-4, f"Error: {e}")

    names = None
    if src_dirs:
        names = LogNames()
        names.scan(src_dirs)

    try:
        if data[:2] == bytes(MAGIC):
            lines = decode_binary(data, names, compact)
        elif data[:2] == FLASH_MAGIC:
            lines = decode_binary(unwrap_flash_format(data), names, compact)
        else:
            text = data.decode("utf-8", errors="replace")
            if "Task List:" not in text:
                raise ValueError("neither a binary task monitor dump nor a text dump")
            lines = annotate_text(text, names)
    except ValueError as e:
        print(f"Error: {in_file}: {e}", file=sys.stderr)
        sys.exit(1)

    result = "\n".join(lines) + "\n"
    if out_file:
        out_file.write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
