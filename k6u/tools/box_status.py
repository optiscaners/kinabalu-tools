"""
box_status.py - Überwacht den Online-Status von Boxen über MQTT (Anzeige ähnlich htop)

Usage:

    box_status [-C <configfile>] [-h]

    -C <configfile> - YAML config file (default: ./box_status.yml)
    -h              - show help and exit

Für jede Box wird das Topic "<topic>/<box>/Status/Connection" abonniert,
Inhalt ist "Online" oder "Offline".

Config file (YAML):

    server:
      host: broker.myestino.de
      port: 1884
      # optional: username, password, keepalive, client_id
    boxes:
      - topic: FwTest
        box: "990000002001"
        name: Prüfstand 1          # optional

Tasten: q = beenden, s = Sortierung wechseln, c = Liste leeren (Status zurücksetzen)
"""

# == modules ==
import curses
import getopt
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
import yaml

# == globals ==

DEFAULT_CONFIG = Path("box_status.yml")
STATUS_SUFFIX = "Status/Connection"
SORT_MODES = ["config", "status", "box"]

# == classes ==


# state of one monitored box
class Box:
    def __init__(self, topic, box, name=""):
        self.topic = topic
        self.box = box
        self.name = name
        self.status = None  # None = no message received yet
        self.since = None  # time of last status change
        self.last_msg = None  # time of last message

    @property
    def mqtt_topic(self):
        return f"{self.topic}/{self.box}/{STATUS_SUFFIX}"

    def update(self, payload):
        now = time.time()
        if payload != self.status:
            self.status = payload
            self.since = now
        self.last_msg = now

    def reset(self):
        self.status = None
        self.since = None
        self.last_msg = None


# MQTT connection and status table
class BoxMonitor:
    def __init__(self, server, boxes):
        self.server = server
        self.boxes = boxes
        self.by_topic = {b.mqtt_topic: b for b in boxes}
        self.lock = threading.Lock()
        self.connected = False
        self.conn_info = "connecting ..."

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=server.get("client_id", ""))
        if server.get("username"):
            self.client.username_pw_set(server["username"], server.get("password"))
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def start(self):
        self.client.connect_async(self.server["host"], int(self.server.get("port", 1883)),
                                  int(self.server.get("keepalive", 60)))
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def on_connect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            if reason_code.is_failure:
                self.connected = False
                self.conn_info = f"connect failed: {reason_code}"
                return
            self.connected = True
            self.conn_info = "connected"
        # (re)subscribe after every connect, retained messages deliver the current state
        client.subscribe([(t, 0) for t in self.by_topic])

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.connected = False
            self.conn_info = f"disconnected: {reason_code}, reconnecting ..."

    def on_message(self, client, userdata, msg):
        box = self.by_topic.get(msg.topic)
        if box is None:
            return
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        with self.lock:
            box.update(payload)

    def reset(self):
        with self.lock:
            for b in self.boxes:
                b.reset()


# == functions ==


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    server = cfg.get("server") or {}
    if "host" not in server:
        raise ValueError("config: 'server.host' missing")
    boxes = []
    for i, entry in enumerate(cfg.get("boxes") or []):
        if "topic" not in entry or "box" not in entry:
            raise ValueError(f"config: boxes[{i}] needs 'topic' and 'box'")
        boxes.append(Box(str(entry["topic"]), str(entry["box"]), str(entry.get("name", ""))))
    if not boxes:
        raise ValueError("config: no boxes defined")
    return server, boxes


def fmt_age(t, now):
    if t is None:
        return "-"
    s = int(now - t)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    if s < 86400:
        return f"{s // 3600}h{s % 3600 // 60:02d}m"
    return f"{s // 86400}d{s % 86400 // 3600:02d}h"


def sorted_boxes(boxes, mode):
    if mode == "status":
        order = {"Offline": 0, None: 1, "Online": 2}
        return sorted(boxes, key=lambda b: (order.get(b.status, 1), b.topic, b.box))
    if mode == "box":
        return sorted(boxes, key=lambda b: (b.topic, b.box))
    return list(boxes)


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)  # online
    curses.init_pair(2, curses.COLOR_RED, -1)  # offline
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # unknown
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN)  # header / footer bar


def status_attr(status):
    if status == "Online":
        return curses.color_pair(1) | curses.A_BOLD
    if status == "Offline":
        return curses.color_pair(2) | curses.A_BOLD
    return curses.color_pair(3)


def put(win, y, x, text, attr=0):
    # write clipped to the window, ignore the error curses raises for the last cell
    h, w = win.getmaxyx()
    if y >= h or x >= w:
        return
    try:
        win.addnstr(y, x, text, w - x, attr)
    except curses.error:
        pass


def draw(win, monitor, sort_mode, scroll):
    now = time.time()
    h, w = win.getmaxyx()
    win.erase()

    with monitor.lock:
        boxes = sorted_boxes(monitor.boxes, sort_mode)
        rows = [(b.topic, b.box, b.name, b.status, b.since, b.last_msg) for b in boxes]
        connected = monitor.connected
        conn_info = monitor.conn_info

    n_on = sum(1 for r in rows if r[3] == "Online")
    n_off = sum(1 for r in rows if r[3] == "Offline")
    n_unk = len(rows) - n_on - n_off

    srv = monitor.server
    put(win, 0, 0, f" box_status - {srv['host']}:{srv.get('port', 1883)}", curses.A_BOLD)
    put(win, 0, max(0, w - 20), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    put(win, 1, 0, " Broker: ")
    put(win, 1, 9, conn_info, curses.color_pair(1 if connected else 2) | curses.A_BOLD)
    put(win, 2, 0, " Boxes: ")
    x = 8
    for label, attr in ((f"{len(rows)} total", curses.A_BOLD),
                        (f"{n_on} online", status_attr("Online")),
                        (f"{n_off} offline", status_attr("Offline")),
                        (f"{n_unk} unknown", status_attr(None))):
        put(win, 2, x, label, attr)
        x += len(label) + 3
    put(win, 3, 0, f" Sort: {sort_mode}")

    # table
    w_topic = max([5] + [len(r[0]) for r in rows])
    w_box = max([3] + [len(r[1]) for r in rows])
    w_name = max([4] + [len(r[2]) for r in rows])
    hdr = f" {'TOPIC':<{w_topic}}  {'BOX':<{w_box}}  {'NAME':<{w_name}}  {'STATUS':<8}  {'SINCE':>8}  {'LAST MSG':>8}"
    put(win, 5, 0, hdr.ljust(w), curses.color_pair(4))

    body_top = 6
    body_h = max(0, h - body_top - 1)
    scroll = max(0, min(scroll, len(rows) - body_h))
    for i, (topic, box, name, status, since, last_msg) in enumerate(rows[scroll:scroll + body_h]):
        y = body_top + i
        put(win, y, 0, f" {topic:<{w_topic}}  {box:<{w_box}}  {name:<{w_name}}  ")
        x = 1 + w_topic + 2 + w_box + 2 + w_name + 2
        put(win, y, x, f"{status or '?':<8}", status_attr(status))
        put(win, y, x + 8, f"  {fmt_age(since, now):>8}  {fmt_age(last_msg, now):>8}")

    footer = " q:Quit  s:Sort  c:Clear  Up/Down/PgUp/PgDn:Scroll"
    if len(rows) > body_h:
        footer += f"   [{scroll + 1}-{min(len(rows), scroll + body_h)}/{len(rows)}]"
    put(win, h - 1, 0, footer.ljust(w - 1), curses.color_pair(4))
    win.refresh()
    return scroll, body_h


def run_ui(stdscr, monitor):
    curses.curs_set(0)
    init_colors()
    stdscr.timeout(500)  # refresh at least twice per second
    sort_mode = 0
    scroll = 0
    while True:
        scroll, body_h = draw(stdscr, monitor, SORT_MODES[sort_mode], scroll)
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            break
        elif key in (ord("s"), ord("S")):
            sort_mode = (sort_mode + 1) % len(SORT_MODES)
        elif key in (ord("c"), ord("C")):
            monitor.reset()
        elif key == curses.KEY_UP:
            scroll -= 1
        elif key == curses.KEY_DOWN:
            scroll += 1
        elif key == curses.KEY_PPAGE:
            scroll -= body_h
        elif key == curses.KEY_NPAGE:
            scroll += body_h
        elif key == curses.KEY_HOME:
            scroll = 0
        elif key == curses.KEY_RESIZE:
            curses.update_lines_cols()


def main():
    config_file = DEFAULT_CONFIG
    try:
        opts, args = getopt.getopt(sys.argv[1:], "C:h")
    except getopt.GetoptError as e:
        print(f"error: {e}", file=sys.stderr)
        print(__doc__)
        sys.exit(2)
    for o, a in opts:
        if o == "-C":
            config_file = Path(a)
        elif o == "-h":
            print(__doc__)
            sys.exit(0)

    try:
        server, boxes = load_config(config_file)
    except FileNotFoundError:
        print(f"error: config file '{config_file}' not found (use -C <configfile>)", file=sys.stderr)
        sys.exit(1)
    except (ValueError, yaml.YAMLError) as e:
        print(f"error: {config_file}: {e}", file=sys.stderr)
        sys.exit(1)

    monitor = BoxMonitor(server, boxes)
    monitor.start()
    try:
        curses.wrapper(run_ui, monitor)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
