"""
Replay CAN trace files from a JSON configuration.

Usage:
    can_send_trc -c <config_file.json> [-i|--interactive] [-r|--rpt <n>] <profile1> [profile2 ...]

Options:
    -h, --help          Show this help text.
    -c, --config        Path to the JSON configuration file.
    -i, --interactive   Pause after each frame and wait for Enter.    
    -P, --list-profiles Show profiles defined in config file and exit
    -r, --rpt           Repeat the replay <n> times (default: 1)

Profiles are defined in the config file. A profile maps to a list of
hardware names (or the string "all"). The built-in profile "all" selects
every bus in the config file.

The script loads a trace file, configures the selected CAN busses, and sends
messages with the timing recorded in the trace.
"""

import can
import getopt
import json
import logging
import os
import random
import sys
import time
import traceback
from pathlib import Path

from .can_bus_setup import start_bus, stop_bus

logging.getLogger()

# === Defaults ===
DEFAULT_CONFIG_FILE = "examples/cansendtrc_config.json"
DEFAULT_TRC_FILE_PATH = "."

class CanTrcTx:
    def __init__(self, pcan_channels=("PCAN_USBBUS1", "PCAN_USBBUS2")):
        self.bus1 = None
        self.bus2 = None
        self.pcan_channels = pcan_channels
        self.is_remote_frame = False
        self.total_send_count = 1
        self.current_frame_count = 0

    def start_busses(self, nominalBitrate, dataBitrate=None):
        """bus1 sends; on Windows bus2 is opened on the second PCAN channel (e.g. to ACK frames).
        On Linux only one bus is used (presume-ack on)."""
        self.bus1 = start_bus(nominalBitrate, dataBitrate, pcan_channel=self.pcan_channels[0])
        if sys.platform == "win32" and len(self.pcan_channels) > 1:
            self.bus2 = start_bus(nominalBitrate, dataBitrate, pcan_channel=self.pcan_channels[1])

    def stop_busses(self):
        stop_bus(self.bus1)
        stop_bus(self.bus2)
        self.bus1 = None
        self.bus2 = None

    def read_trc_file(self, fn):
        mlist  = list(can.TRCReader(fn))    
        return mlist

    def replay_messages(self, messages, interactive = False):
        last_ts = None
        delay = 0.01
        t0 = time.time()
        m_first = messages[0]
        m_last = messages[-1]
        interactive_count = 0
        print(f"is_remote_frame: {self.is_remote_frame} {self.bus1.protocol}")
        for i, msg in enumerate(messages):
            try:
                msg.is_remote_frame = self.is_remote_frame                
                if last_ts == None:
                    last_ts = msg.timestamp
                else:
                    delay = msg.timestamp - last_ts
                    last_ts = msg.timestamp
                    delay = 0
                    if delay > 0:
                        time.sleep(delay)
                    else: 
                        delay = 0.01
                if interactive:
                    if interactive_count > 0:
                        interactive_count -= 1
                    elif interactive_count == 0:
                        print(msg)
                        tmp = input(f"Enter to send frame[{i}] len={len(msg.data)} {msg.data[:8]} ...>:") 
                        try:
                            interactive_count = int(tmp)-1
                        except ValueError:
                            interactive_count = 0
                    print(f"\nTotal {self.total_send_count: 8d}  Frame[{i}]: {msg}")
                else:
                    print(f"Total {self.total_send_count: 8d} Frame[{i}] len={len(msg.data)}\r", end="")
                self.bus1.send(msg, timeout=delay)
                self.total_send_count += 1
                self.current_frame_count = i
            except can.CanError as e:
                print(f"Sendefehler: frame:{i} error: {e}")
                traceback.print_exc()
        t1 = time.time()            
        print(f"real duration: {t1 - t0}s")
        print(f"first: {m_first}")
        print(f"last: {m_last}")

    def replay_random_messages(self, iterations = 100, len = 64, interactive = False):
        msg = can.Message(is_extended_id=True, is_rx=False, is_remote_frame=self.is_remote_frame, channel=1)
        msg.dlc = len
        voicepacket_id = 0
        t0 = time.time()            
        tx_err = 0

        is_fd = bus.protocol in (can.CanProtocol.CAN_FD, can.CanProtocol.CAN_FD_NON_ISO)
        if is_fd: 
            len = 64
        else:
            len = 8
        for i in range(iterations):
            msg.arbitration_id = 0x01 #voicepacket_id+i
            #msg.arbitration_id = random.randrange(1,0xffffff)
            msg.data = random.randbytes(len)            
            time.sleep(0.1)
            try:
                self.bus1.send(msg)
            except Exception as e :
                tx_err += 1
                print(f"TxErr: {tx_err} {e}")
                time.sleep(0.1)
            if i % 25 == 0:
                print(f".", end="")
                #print(f"frames: {i}\r", end="")
        t1 = time.time()            
        print(f"real duration: {t1 - t0}s")

def load_config_json(fn):
    rv = {}
    with open(fn) as f:
        rv = json.loads(f.read())
        print(f"loaded configfile: {fn}")
    return rv

def select_busses(profiles, names):
    """Return the list of hardware names selected by the given profiles, or "all"."""
    selected = []
    for name in names:
        if name in profiles:
            busses = profiles[name]
        elif name == "all":
            busses = "all"
        else:
            print(f"Error: unknown profile '{name}', available: {', '.join(profiles) or '-'}")
            sys.exit(1)
        if busses == "all":
            return "all"
        selected += [busses] if isinstance(busses, str) else list(busses)
    return selected

def parse_args():
    cfg = {
        "arguments": [],
        "busses": [],
        "config_file": DEFAULT_CONFIG_FILE,
        "interactive": False,
        "list_profiles_and_exit" : False,
        "profiles": {},
        "selected_busses": "all",
        "trc_file_path": DEFAULT_TRC_FILE_PATH,
        "trc_file": None,
        "rpt_cnt" : 1
    }
    print(f"sys.argv: {sys.argv}")
    opts, args = getopt.getopt(sys.argv[1:], "hc:iPr:", ["help", "config=", "interactive", "list-profiles", "rpt="])
    
    for o, v in opts:
        if o in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif o in ("-c", "--config"):
            cfg["config_file"] = v
        elif o in ("-i", "--interactive"):
            cfg["interactive"] = True
        elif o in ("-P", "--list-profiles"):
            cfg["list_profiles_and_exit"] = True
        elif o in ("-r", "--rpt"):
            if int(v) < 1:
                print(f"Option {o} : {int(v)} - invalid value, skip option and keep old value {cfg['rpt_cnt']}")
            else:
                cfg["rpt_cnt"] = int(v)
            
    
    cfg["arguments"] = args

    config_data = load_config_json(cfg["config_file"])
    cfg["trc_file_path"] = config_data.get("TrcDir", DEFAULT_TRC_FILE_PATH)
    cfg["profiles"] = config_data.get("Profiles", {})
    cfg["busses"] = config_data.get("CanBusses", [])
    cfg["trc_file"] = config_data.get("TrcFile", None)

    if cfg["list_profiles_and_exit"]:
        cnt = 0
        r = ""
        for k,v in cfg["profiles"].items():
            print(f"{r:>}{cnt:>2d} {k} : {v}")
            cnt += 1
        sys.exit(0)

    if len(args) < 1:
        print("Error: No profile given\n")
        print(__doc__)
        sys.exit(1)
    cfg["selected_busses"] = select_busses(cfg["profiles"], args)
    print(cfg)
    return cfg

def main():
    try:
        cantrx = CanTrcTx()
        cfg = parse_args()
        for rpt in range(cfg["rpt_cnt"]):
            for bus in cfg["busses"]:
                hw = bus["Hardware"]
                bus_id = bus["Id"]
                nominalBitrate = bus["BaudRate"]
                dataBitrate = bus.get("DataBaudRate", None)
                trcfile = cfg.get("trc_file") or bus.get("TrcFile")
                if hw in cfg["selected_busses"] or cfg["selected_busses"] == "all":
                    trcfn = Path(cfg["trc_file_path"]) / trcfile
                    try:
                        print(f"\nTesting[{rpt}]: {hw} {bus_id} {nominalBitrate} {dataBitrate}")
                        cantrx.start_busses(nominalBitrate=nominalBitrate, dataBitrate=dataBitrate)
                        print(f"Load {trcfn}")
                        messages = cantrx.read_trc_file(trcfn)
                        print(f"==>: {hw} {bus_id} {os.path.basename(trcfn)}: {len(messages)}")
                        #cantrx.replay_messages(messages=messages, interactive=cfg["interactive"])
                        cantrx.replay_random_messages(iterations = 10000, len = 64, interactive=cfg["interactive"])
                    except Exception as e:
                        print(f"ERROR: {e} rpt: {rpt} {bus} trc: {trcfn} frm_idx: {cantrx.current_frame_count} total:{cantrx.total_send_count}")
                        traceback.print_exc()
                    finally:
                        cantrx.stop_busses()

    except KeyboardInterrupt:
        print(f"\n ==== \n User Abort w/ Ctrl-c : Total Frames: {cantrx.total_send_count}\n ==== ")
    finally:
        cantrx.stop_busses()

if __name__ == "__main__":
    main()
    print("exit")
