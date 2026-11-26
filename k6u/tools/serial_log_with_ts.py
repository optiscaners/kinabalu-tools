"""
serial_log_with_ts.py - öffnet eine serielle Schnittstelle und fügt jeder Zeile einen Zeitstempel hinzu.

Usage:

    serial_log_with_ts.py <port> [-b <baudrate>] [-l <log_path>] [-d <duration>]

    port         - serial port, e.g. COM6 or /dev/ttyUSB0
    -b baudrate  - default 115200
    -l log_path  - default serial_log.txt
    -d duration  - logging time in seconds, -1 = until Ctrl-C (default)
"""
import argparse
import serial
import sys
import time

from datetime import datetime

def log_serial(port, baudrate=9600, log_path="serial_log.log", duration=60):
    line_count = 0
    fn = log_path
    ser = serial.Serial(port, baudrate, timeout=1)
    try:
        with open(log_path, "w", newline="") as f:
            start = time.time()
            while duration < 0 or time.time() - start < duration:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                oline = f"{datetime.now().isoformat()} : {line}" 
                f.write(oline+"\n")
                print(oline)                
                line_count += 1
                if line_count % 100 == 0:
                    f.flush()
                    sys.stdout.flush()
    except KeyboardInterrupt:
        safe_print(f"\n ==== \n User Abort w/ Ctrl-c : Total Lines: {line_count}\n ==== ")
    finally:
        ser.close()
    safe_print(f"Logged {line_count} lines to {fn}")


def safe_print(msg):
    # stdout may be unusable after Ctrl-C (closed pipe / interrupted console write)
    try:
        print(msg, flush=True)
    except OSError:
        pass

def parse_args():
    parser = argparse.ArgumentParser(
        description="Log a serial port with a timestamp on every line.")
    parser.add_argument("port", help="serial port, e.g. COM6 or /dev/ttyUSB0")
    parser.add_argument("-b", "--baudrate", type=int, default=115200,
                        help="baudrate (default: %(default)s)")
    parser.add_argument("-l", "--log-path", default="serial_log.txt",
                        help="log file (default: %(default)s)")
    parser.add_argument("-d", "--duration", type=float, default=-1,
                        help="logging time in seconds, -1 = until Ctrl-C (default: %(default)s)")
    return parser.parse_args()


def main():
    args = parse_args()
    log_serial(args.port, args.baudrate, log_path=args.log_path, duration=args.duration)

if __name__ == "__main__":
    main()

