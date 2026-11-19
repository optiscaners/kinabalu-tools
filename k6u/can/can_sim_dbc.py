"""
Simulate the CAN traffic described by a DBC file with random payload.

Every cyclic message of the DBC is sent with its cycle time (GenMsgCycleTime).
The first transmission of a message is delayed by GenMsgStartDelayTime, or by a
random phase within one cycle if the attribute is missing, so that messages with
the same cycle time do not all hit the bus at the same moment (like real ECUs).
Messages without cycle time (event / spontaneous messages) are sent one after
another, one message every EVENT_INTERVAL_S (1 s), starting 1 s after start.
After the last event message the sequence starts again with the first one.

Usage:
    can_sim_dbc -c <channel> -b <nominal bitrate> [-d <data bitrate>] [-a on|off] [-t <s>] <file.dbc>

Options:
    -h, --help              Show this help text.
    -c, --channel           CAN channel: CAN0, CAN1, ... (Linux: can0, ...; Windows: PCAN_USBBUS1, ...)
                            A name starting with PCAN_ is used as is on Windows.
    -b, --bitrate           Nominal bitrate, e.g. 500000, 500k, 1M
    -d, --dbitrate          Data bitrate (CAN FD), e.g. 2M, 5M. Default: none -> CAN classic
    -a, --tx-self-ack       on|off: acknowledge own frames (Linux presume-ack). Default: on
    -t, --duration          Stop after <s> seconds. Default: run until Ctrl-C
    -q, --txqueuelen        Linux interface tx queue length. Default: 1000

Example:
    can_sim_dbc -c CAN0 -b 500k -d 2M NRG_CANFD_CAN_2024_07a.dbc
"""

import asyncio
import getopt
import random
import sys
import time

import can
import cantools

from k6u.can import can_bus_setup

# === Defaults ===
DEFAULT_TX_SELF_ACK = "on"
DEFAULT_TXQUEUELEN = 1000
DBC_ENCODING = "cp1252"
STATUS_INTERVAL_S = 10.0
# Retry interval while the transmit queue is full.
TX_RETRY_INTERVAL_S = 0.0005
CLASSIC_MAX_LEN = 8
MAX_NAMES_SHOWN = 10
# Interval between two event messages (messages without cycle time).
EVENT_INTERVAL_S = 1.0


class DbcFrame:
    """One DBC message prepared for transmission (cycle_s is None for event messages)."""

    def __init__(self, name, msg, cycle_s, start_delay_s):
        self.name = name
        self.msg = msg
        self.cycle_s = cycle_s
        self.start_delay_s = start_delay_s
        self.length = len(msg.data)


class CanDbcSim:
    def __init__(self, channel):
        self.bus = None
        self.channel = channel
        self.is_fd = False
        self.brs = False
        self.total_send_count = 0
        self.tx_retry_count = 0
        self.tx_drop_count = 0
        self.max_late_s = 0.0
        self.stop_event = None

    def start_bus(self, nominal_bitrate, data_bitrate=None, tx_self_ack=DEFAULT_TX_SELF_ACK,
                  txqueuelen=DEFAULT_TXQUEUELEN):
        if sys.platform == "win32" and tx_self_ack == "on":
            print("WARNING: TxSelfAck is only supported on Linux (presume-ack), ignored on Windows")
        else:
            pass
        self.bus = can_bus_setup.start_bus(self.channel, nominal_bitrate, data_bitrate, 
                                           tx_self_ack, txqueuelen=txqueuelen)
        self.is_fd = bool(data_bitrate)
        self.brs = bool(data_bitrate)

    def stop_bus(self):
        can_bus_setup.stop_bus(self.bus)
        self.bus = None

    def _make_message(self, m, truncated):
        """Build the can.Message for DBC message m (payload zero, filled at send time)."""
        length = m.length
        is_fd = m.is_fd or length > CLASSIC_MAX_LEN
        if not self.is_fd and is_fd:
            truncated.append(f"{m.name}({m.length})")
            length = min(length, CLASSIC_MAX_LEN)
            is_fd = False
        else:
            pass
        if is_fd:
            # round up to a valid CAN FD frame length (12, 16, 20, 24, 32, 48, 64)
            length = can.util.dlc2len(can.util.len2dlc(length))
        else:
            pass
        return can.Message(arbitration_id=m.frame_id,
                           is_extended_id=m.is_extended_frame,
                           is_fd=is_fd,
                           bitrate_switch=is_fd and self.brs,
                           data=bytes(length))

    def load_dbc(self, fn):
        """Return (cyclic DbcFrames, event DbcFrames) of the DBC file."""
        print(f"load DBC {fn}")
        frames = []
        event_frames = []
        truncated = []
        db = cantools.database.load_file(fn, database_format="dbc", encoding=DBC_ENCODING, strict=False)
        for m in db.messages:
            msg = self._make_message(m, truncated)
            if m.cycle_time is None or m.cycle_time <= 0:
                event_frames.append(DbcFrame(m.name, msg, None, None))
            else:
                cycle_s = m.cycle_time / 1000.0
                start_delay_ms = _dbc_attribute(m, "GenMsgStartDelayTime", 0)
                if start_delay_ms > 0:
                    start_delay_s = start_delay_ms / 1000.0
                else:
                    start_delay_s = random.uniform(0.0, cycle_s)
                frames.append(DbcFrame(m.name, msg, cycle_s, start_delay_s))
        print(f"loaded {fn}: {len(db.messages)} messages, {len(frames)} cyclic, {len(event_frames)} event")
        if event_frames:
            names = [f.name for f in event_frames]
            more = f" ... (+{len(names) - MAX_NAMES_SHOWN})" if len(names) > MAX_NAMES_SHOWN else ""
            print(f"event messages, one every {EVENT_INTERVAL_S}s: "
                  f"{', '.join(names[:MAX_NAMES_SHOWN])}{more}")
        else:
            pass
        if truncated:
            print(f"WARNING: CAN classic bus, {len(truncated)} FD messages truncated to 8 bytes: {', '.join(truncated)}")
        else:
            pass
        return frames, event_frames

    def _send_now(self, msg):
        """Try to send msg once without blocking. Returns True on success."""
        result = False
        try:
            self.bus.send(msg, timeout=0)
            result = True
        except can.CanOperationError:
            # transmit queue full (ENOBUFS) -> caller retries
            result = False
        return result

    async def _send_with_retry(self, frame, retry_until):
        """Send frame with random payload, retry while the queue is full until retry_until."""
        loop = asyncio.get_running_loop()
        frame.msg.data = random.randbytes(frame.length)
        sent = self._send_now(frame.msg)
        while not sent and loop.time() < retry_until and not self.stop_event.is_set():
            self.tx_retry_count += 1
            #await asyncio.sleep(TX_RETRY_INTERVAL_S)
            sent = self._send_now(frame.msg)
        if sent:
            self.total_send_count += 1
        else:
            self.tx_drop_count += 1

    async def _event_sender(self, event_frames, t_start):
        """Send the event messages one after another, one every EVENT_INTERVAL_S, in a loop."""
        loop = asyncio.get_running_loop()
        deadline = t_start + EVENT_INTERVAL_S
        index = 0
        while not self.stop_event.is_set():
            delay = deadline - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                pass
            await self._send_with_retry(event_frames[index], deadline + EVENT_INTERVAL_S)
            index = (index + 1) % len(event_frames)
            deadline += EVENT_INTERVAL_S            
            if deadline < loop.time():
                # fell behind: continue from now instead of bursting
                deadline = loop.time()
            else:
                pass

    async def _cyclic_sender(self, frame, t_start):
        """Send one DBC message with random payload on absolute deadlines (no drift)."""
        loop = asyncio.get_running_loop()
        deadline = t_start + frame.start_delay_s
        while not self.stop_event.is_set():
            delay = deadline - loop.time()
            if delay > 0:
                #await asyncio.sleep(delay)
                await asyncio.sleep(1/1000.)
                pass
            else:
                pass
            late = loop.time() - deadline
            if late > self.max_late_s:
                self.max_late_s = late
            else:
                pass
            # retry while the queue is full, but at most until the next cycle is due
            await self._send_with_retry(frame, deadline + frame.cycle_s)
            deadline += frame.cycle_s
            if deadline < loop.time():
                # fell behind more than one cycle: skip missed cycles instead of bursting them
                missed = int((loop.time() - deadline) / frame.cycle_s) + 1
                self.tx_drop_count += missed
                deadline += missed * frame.cycle_s
            else:
                pass

    async def _status_printer(self, t_start):
        loop = asyncio.get_running_loop()
        last_count = 0
        last_t = t_start
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=STATUS_INTERVAL_S)
            except TimeoutError:
                pass
            now = loop.time()
            rate = (self.total_send_count - last_count) / (now - last_t)
            last_count = self.total_send_count
            last_t = now
            print(f"t={now - t_start:8.1f}s  sent={self.total_send_count:9d}  {rate:7.0f} fr/s  "
                  f"retry={self.tx_retry_count}  drop={self.tx_drop_count}  "
                  f"max_late={self.max_late_s * 1000:6.2f}ms\r", end="")
            self.max_late_s = 0.0

    async def run(self, frames, event_frames, duration=None):
        self.stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        t_start = loop.time()
        load = _bus_frames_per_second(frames, event_frames)
        print(f"simulating {len(frames)} cyclic and {len(event_frames)} event messages, "
              f"expected {load:.0f} frames/s"
              f"{'' if duration is None else f' for {duration}s'} (Ctrl-C to stop)")
        tasks = [asyncio.create_task(self._cyclic_sender(f, t_start), name=f.name) for f in frames]
        if event_frames:
            tasks.append(asyncio.create_task(self._event_sender(event_frames, t_start), name="events"))
        else:
            pass
        tasks.append(asyncio.create_task(self._status_printer(t_start), name="status"))
        try:
            if duration is None:
                await asyncio.gather(*tasks)
            else:
                await asyncio.sleep(duration)
        finally:
            self.stop_event.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            print(f"\nreal duration: {loop.time() - t_start:.1f}s  total frames: {self.total_send_count}  "
                  f"dropped: {self.tx_drop_count}")


def _dbc_attribute(message, name, default):
    """Return the value of a DBC message attribute (e.g. GenMsgStartDelayTime) or default."""
    result = default
    attr = None
    if message.dbc is not None:
        attr = message.dbc.attributes.get(name)
    else:
        pass
    if attr is not None:
        result = attr.value
    else:
        pass
    return result


def _bus_frames_per_second(frames, event_frames):
    result = sum(1.0 / f.cycle_s for f in frames)
    if event_frames:
        result += 1.0 / EVENT_INTERVAL_S
    else:
        pass
    return result

def parse_bitrate(value):
    """Parse '500000', '500k', '2M' -> int."""
    v = value.strip().lower()
    factor = 1
    if v.endswith("k"):
        factor = 1000
        v = v[:-1]
    elif v.endswith("m"):
        factor = 1000000
        v = v[:-1]
    else:
        pass
    return int(float(v) * factor)

def usage_error(text):
    print(f"Error: {text}\n")
    print(__doc__)
    sys.exit(1)


def parse_args():
    cfg = {
        "channel": None,
        "nominal_bitrate": None,
        "data_bitrate": None,
        "tx_self_ack": DEFAULT_TX_SELF_ACK,
        "duration": None,
        "txqueuelen": DEFAULT_TXQUEUELEN,
        "dbc_file": None,
    }
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hc:b:d:a:t:q:",
                                   ["help", "channel=", "bitrate=", "dbitrate=", "tx-self-ack=",
                                    "duration=", "txqueuelen="])
    except getopt.GetoptError as e:
        usage_error(str(e))

    try:
        for o, v in opts:
            if o in ("-h", "--help"):
                print(__doc__)
                sys.exit(0)
            elif o in ("-c", "--channel"):
                cfg["channel"] = v
            elif o in ("-b", "--bitrate"):
                cfg["nominal_bitrate"] = parse_bitrate(v)
            elif o in ("-d", "--dbitrate"):
                cfg["data_bitrate"] = parse_bitrate(v)
            elif o in ("-a", "--tx-self-ack"):
                if v.lower() in ("on", "off"):
                    cfg["tx_self_ack"] = v.lower()
                else:
                    usage_error(f"{o} expects on|off, got '{v}'")
            elif o in ("-t", "--duration"):
                cfg["duration"] = float(v)
            elif o in ("-q", "--txqueuelen"):
                cfg["txqueuelen"] = int(v)
            else:
                pass
    except ValueError as e:
        usage_error(f"invalid value: {e}")

    if cfg["channel"] is None:
        usage_error("no channel given (-c)")
    elif cfg["nominal_bitrate"] is None:
        usage_error("no nominal bitrate given (-b)")
    elif len(args) != 1:
        usage_error("exactly one DBC file expected")
    else:
        cfg["dbc_file"] = args[0]
    print(cfg)
    return cfg


def main():
    cfg = parse_args()
    sim = CanDbcSim(cfg["channel"])
    try:
        sim.start_bus(cfg["nominal_bitrate"], cfg["data_bitrate"], cfg["tx_self_ack"], cfg["txqueuelen"])
        frames, event_frames = sim.load_dbc(cfg["dbc_file"])
        if frames or event_frames:
            asyncio.run(sim.run(frames, event_frames, cfg["duration"]))
        else:
            print("no messages in DBC, nothing to send")
    except KeyboardInterrupt:
        print(f"\n ==== \n User Abort w/ Ctrl-c : Total Frames: {sim.total_send_count}\n ==== ")
    finally:
        sim.stop_bus()


if __name__ == "__main__":
    main()
    print("exit")
