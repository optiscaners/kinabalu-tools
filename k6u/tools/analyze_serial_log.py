"""
analyze_serial_log.py - berechnet aus einem Box-Log (serial_log_with_ts) die Nachrichten- und
Match-Raten pro Sekunde der CAN- und LIN-Zähler.

Usage:

    analyze_serial_log <logfile> [-s] [-d <sep>]

    logfile   - log written by serial_log_with_ts ("-" = stdin)
    -s        - print only the CAN / LIN sums
    -d <sep>  - column separator (default: ", ")

Ausgewertete Zeilen (alle Zeilen mit "match ="):

    2026-11-25T14:41:56.056832 : # SamLinCount (4): header = 4990, match = 0, init = 1, error = 0
    2026-11-25T14:41:15.500715 : # ChassisCanCount (1): message = 759083, match = 407342, lost = 0, error = 0

Klasse = Wort nach "#". Für zwei aufeinanderfolgende Zeilen einer Klasse:

    delta_t               = ts2 - ts1
    nb_msg_per_second     = (header2 - header1) / delta_t    (LIN)
                          = (message2 - message1) / delta_t  (CAN)
    nb_matches_per_second = (match2 - match1) / delta_t

Ausgabe je Zeile:   ts2, Klasse, nb_msg_per_second, nb_matches_per_second
Je Block (alle Klassen einmal) zusätzlich die Summen der Klassen "*Can*Count" und "*Lin*Count":

    ts2, CAN, sum(nb_msg_per_second), sum(nb_matches_per_second)
    ts2, LIN, sum(nb_msg_per_second), sum(nb_matches_per_second)

ts2 der Summenzeile ist der Zeitstempel der letzten Zeile des Blocks. Ein Block endet, wenn alle
Klassen einen neuen Wert haben (spätestens, wenn eine Klasse erneut auftritt). Wird ein Zähler
kleiner (Box-Neustart), wird das Paar übersprungen.

Task load: die load-Werte aller Tasks (ohne IDLE) eines Blocks ("# task load: <Task> nr=.. load=..%") werden
summiert und als "<ts> : # task load: ALL nr=xx prio=xx load=<Summe>% stackFree=xx" ausgegeben.

Zeilen mit "Hello World" (Box-Start) und die task load-Zeilen von Main und Gsm werden
unverändert ausgegeben.
"""

# == modules ==
import argparse
import errno
import fnmatch
import re
import sys
from datetime import datetime

# == globals ==

LINE_RE = re.compile(
    r"^(?P<ts>\S+)\s*:\s*#\s*(?P<cls>\w+)[^:]*:\s*(?P<fields>.*\bmatch\s*=.*)$")
FIELD_RE = re.compile(r"(\w+)\s*=\s*(-?\d+)")

GROUPS = (("CAN", "*Can*Count"), ("LIN", "*Lin*Count"))
MSG_FIELDS = ("message", "header")  # CAN, LIN
HELLO = "Hello World"  # box start message, copied to stdout
TASK_LOAD_EXCLUDE = ("IDLE",)  # tasks not included in the ALL load sum
TASK_LOAD_COPY = ("Main", "Gsm")  # task load lines copied unchanged to stdout
TASK_LOAD_HEADER_RE = re.compile(r"^\S+\s*:\s*#\s*task load:\s*(?P<count>\d+)\s+tasks\b")
TASK_LOAD_RE = re.compile(
    r"^(?P<ts>\S+)\s*:\s*#\s*task load:\s*(?P<task>.+?)\s+nr=\S+\s+prio=\S+\s+load=(?P<load>[\d.]+)%")

# == functions ==


class TaskLoadSum:
    """Sum of the load values of all tasks per task load block. A block ends when a task
    appears again; the sum line gets the time stamp of the last task line of the block."""

    def __init__(self):
        self.loads = {}   # task -> load of the current block
        self.ts = None
        self.tasks = set()  # all tasks seen so far
        self.expected = None  # task count from the block header line

    def add(self, line):
        """Return True if line is a task load line."""
        m = TASK_LOAD_HEADER_RE.match(line.strip())
        if m:  # "task load: 6 tasks, 5190 ms" starts a new block
            self.flush()
            self.expected = int(m.group("count"))
            return True
        m = TASK_LOAD_RE.match(line.strip())
        if not m:
            return False
        task = m.group("task")
        if task in TASK_LOAD_COPY:
            print(line.rstrip("\r\n"))
        if task in self.loads:
            self.flush()
        self.loads[task] = float(m.group("load"))
        self.ts = m.group("ts")
        self.tasks.add(task)
        if self.expected and len(self.loads) == self.expected:
            self.flush()  # all tasks of the block received
        return True

    def flush(self):
        # only complete blocks (e.g. not a truncated last block)
        complete = len(self.loads) == self.expected if self.expected else set(self.loads) >= self.tasks
        if self.loads and complete:
            load = sum(v for t, v in self.loads.items() if t not in TASK_LOAD_EXCLUDE)
            print(f"{self.ts} : # task load: ALL nr=xx prio=xx load={load:.1f}% "
                  f"stackFree=xx")
        self.loads = {}
        self.expected = None


def parse_line(line):
    """Return (ts, cls, msg, match) or None for other lines."""
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    fields = dict((k, int(v)) for k, v in FIELD_RE.findall(m.group("fields")))
    msg = next((fields[f] for f in MSG_FIELDS if f in fields), None)
    if msg is None or "match" not in fields:
        return None
    try:
        ts = datetime.fromisoformat(m.group("ts"))
    except ValueError:
        return None
    return ts, m.group("cls"), msg, fields["match"]


def group_of(cls):
    for name, pattern in GROUPS:
        if fnmatch.fnmatchcase(cls, pattern):
            return name
    return None


def fmt_rate(value):
    return f"{value:.1f}"


class Analyzer:
    def __init__(self, sep, sums_only):
        self.sep = sep
        self.sums_only = sums_only
        self.last = {}           # cls -> (ts, msg, match)
        self.block = {}          # cls -> (ts2, msg_rate, match_rate) of the current block
        self.block_ts = None
        self.reset_reported = False

    def out(self, *cols):
        print(self.sep.join(str(c) for c in cols))

    def flush_block(self):
        # sums only for complete blocks (not after a counter reset / at the end of the log)
        if self.block and set(self.block) >= set(self.last):
            for name, _ in GROUPS:
                rates = [(r[1], r[2]) for c, r in self.block.items() if group_of(c) == name]
                if rates:
                    self.out(self.block_ts.isoformat(), name,
                             fmt_rate(sum(r[0] for r in rates)), fmt_rate(sum(r[1] for r in rates)))
        self.block = {}
        self.block_ts = None
        self.reset_reported = False

    def add(self, ts, cls, msg, match, lineno):
        prev = self.last.get(cls)
        self.last[cls] = (ts, msg, match)
        if cls in self.block:
            self.flush_block()
        if prev is None:
            return
        ts1, msg1, match1 = prev
        dt = (ts - ts1).total_seconds()
        if dt <= 0:
            print(f"line {lineno}: {cls}: time not increasing, skipped", file=sys.stderr)
            return
        if msg < msg1 or match < match1:
            if not self.reset_reported:
                print(f"line {lineno}: {cls}: counter reset (box restart?), block skipped", file=sys.stderr)
                self.reset_reported = True
            return
        msg_rate = (msg - msg1) / dt
        match_rate = (match - match1) / dt
        self.block[cls] = (ts, msg_rate, match_rate)
        self.block_ts = ts
        if not self.sums_only:
            self.out(ts.isoformat(), cls, fmt_rate(msg_rate), fmt_rate(match_rate))
        if set(self.block) >= set(self.last):
            self.flush_block()  # all classes of the block received


def parse_args():
    parser = argparse.ArgumentParser(
        description="Message and match rates per second of the CAN / LIN counters in a box log.")
    parser.add_argument("logfile", help="log written by serial_log_with_ts ('-' = stdin)")
    parser.add_argument("-s", "--sums-only", action="store_true", help="print only the CAN / LIN sums")
    parser.add_argument("-d", "--sep", default=", ", help="column separator (default: '%(default)s')")
    return parser.parse_args()


def main():
    args = parse_args()
    analyzer = Analyzer(args.sep, args.sums_only)
    task_load = TaskLoadSum()
    f = sys.stdin if args.logfile == "-" else open(args.logfile, encoding="utf-8", errors="replace")
    try:
        analyzer.out("ts2", "class", "nb_msg_per_second", "nb_matches_per_second")
        for lineno, line in enumerate(f, 1):
            if HELLO in line:  # box start message, copied unchanged
                print(line.rstrip("\r\n"))
                continue
            if task_load.add(line):
                continue
            rec = parse_line(line)
            if rec:
                analyzer.add(*rec, lineno)
        analyzer.flush_block()
        task_load.flush()
    except OSError as e:
        # output pipe closed (e.g. | head): BrokenPipeError, on Windows EINVAL
        if not (isinstance(e, BrokenPipeError) or e.errno == errno.EINVAL):
            raise
        sys.stderr.close()
    finally:
        if f is not sys.stdin:
            f.close()


if __name__ == "__main__":
    main()
