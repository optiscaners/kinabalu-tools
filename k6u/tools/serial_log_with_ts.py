"""
serial_log_with_ts.py - öffnet eine serielle Schnittstelle und fügt jeder Zeile einen Zeitstempel hinzu.

Usage:

    serial_log_with_ts <port> [-b <baudrate>] [-l <log_path>] [-d <duration>] [-t <timeout>] [-n]

    port         - serial port, e.g. COM6 or /dev/ttyUSB0
    -b baudrate  - default 115200
    -l log_path  - default serial-<box>-<version>-<YYYYmmdd-HHMMSS>.log
    -d duration  - logging time in seconds, -1 = until Ctrl-C (default)
    -t timeout   - timeout for the box query in seconds (default 2)
    -n           - do not query the box

Zu Beginn werden Box-Seriennummer (FlashRead SerialNumber), Firmware-Version (SoftwareVersionGet)
und Box-Id (IdGet) abgefragt und als erste Zeile in das Log geschrieben. Antwortet die Box nicht
(z.B. im Reset gehalten), wird "none" eingetragen und trotzdem geloggt.
"""
import argparse
import re
import sys
import time
from datetime import datetime

from k6u.tools.analyze_emmc import DeviceError, Edge2Device

NONE = "none"


def query_box(dev, timeout):
    """Return (serial, version, box_id), "none" for values the box did not deliver."""
    serial_no = version = box_id = NONE
    dev.timeout = timeout
    try:
        serial_no = dev.get_serial()
    except (TimeoutError, ValueError, DeviceError) as e:
        safe_print(f"box query: no serial number ({e})", file=sys.stderr)
        return serial_no, version, box_id  # box in reset / not connected: no further waiting
    try:
        version = dev.get_software_version()
    except (TimeoutError, ValueError, DeviceError) as e:
        safe_print(f"box query: no firmware version ({e})", file=sys.stderr)
    try:
        box_id = dev.get_id()
    except (TimeoutError, ValueError, DeviceError) as e:
        safe_print(f"box query: no box id ({e})", file=sys.stderr)
    return serial_no, version, box_id


def default_log_path(serial_no, version, start):
    def clean(text):
        return re.sub(r"[^\w.-]", "_", text)
    return f"serial-{clean(serial_no)}-{clean(version)}-{start:%Y%m%d-%H%M%S}.log"


def log_serial(port, baudrate=115200, log_path=None, duration=-1, timeout=2.0, query=True):
    line_count = 0
    start_time = datetime.now()
    dev = Edge2Device(port, baudrate, timeout)
    ser = dev.ser
    try:
        if query:
            serial_no, version, box_id = query_box(dev, timeout)
        else:
            serial_no = version = box_id = NONE
        if log_path is None:
            log_path = default_log_path(serial_no, version, start_time)
        ser.timeout = 1  # readline timeout, so -d and Ctrl-C are checked
        with open(log_path, "w", newline="") as f:
            header = (f"{datetime.now().isoformat()} : # serial_log_with_ts: box={serial_no} "
                      f"version={version} id={box_id} port={port} baudrate={baudrate}")
            f.write(header + "\n")
            print(header)
            start = time.time()
            while duration < 0 or time.time() - start < duration:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                oline = f"{datetime.now().isoformat()} : {line}"
                f.write(oline + "\n")
                print(oline)
                line_count += 1
                if line_count % 100 == 0:
                    f.flush()
                    sys.stdout.flush()
    except KeyboardInterrupt:
        safe_print(f"\n ==== \n User Abort w/ Ctrl-c : Total Lines: {line_count}\n ==== ")
    finally:
        dev.close()
    if log_path:
        safe_print(f"Logged {line_count} lines to {log_path}")


def safe_print(msg, file=None):
    # stdout may be unusable after Ctrl-C (closed pipe / interrupted console write)
    try:
        print(msg, file=file or sys.stdout, flush=True)
    except OSError:
        pass


def parse_args():
    parser = argparse.ArgumentParser(
        description="Log a serial port with a timestamp on every line.")
    parser.add_argument("port", help="serial port, e.g. COM6 or /dev/ttyUSB0")
    parser.add_argument("-b", "--baudrate", type=int, default=115200,
                        help="baudrate (default: %(default)s)")
    parser.add_argument("-l", "--log-path", default=None,
                        help="log file (default: serial-<box>-<version>-<YYYYmmdd-HHMMSS>.log)")
    parser.add_argument("-d", "--duration", type=float, default=-1,
                        help="logging time in seconds, -1 = until Ctrl-C (default: %(default)s)")
    parser.add_argument("-t", "--timeout", type=float, default=2.0,
                        help="timeout for the box query in seconds (default: %(default)s)")
    parser.add_argument("-n", "--no-query", action="store_true",
                        help="do not query box serial number and firmware version")
    return parser.parse_args()


def main():
    args = parse_args()
    log_serial(args.port, args.baudrate, log_path=args.log_path, duration=args.duration,
               timeout=args.timeout, query=not args.no_query)


if __name__ == "__main__":
    main()
