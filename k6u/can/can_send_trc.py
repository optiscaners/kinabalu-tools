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
import sys
import time
import traceback
from pathlib import Path

logging.getLogger()

# === Defaults ===
DEFAULT_CONFIG_FILE = "examples/cansendtrc_config.json"
DEFAULT_TRC_FILE_PATH = "."

class CanTrcTx:
    def __init__(self):
        self.bus1 = None
        self.bus2 = None
        self.is_remote_frame = False
        self.timing_table = {
                (int(500e3), int(5e6)) : dict(f_clock=80000000,nom_brp=1,nom_tseg1=127,nom_tseg2=32,nom_sjw=32,data_brp=1,data_tseg1=11,data_tseg2=4,data_sjw=4),
                (int(500e3), int(1e6)) : dict(f_clock=40000000,nom_brp=1,nom_tseg1=63,nom_tseg2=16,nom_sjw=16,data_brp=4,data_tseg1=7,data_tseg2=2,data_sjw=2),
                # This one was derived from "can.BitTiming.from_sample_point(f_clock=8000000, bitrate=666666, sample_point=69.0)"
                (int(666666))          : dict(f_clock=8000000, brp=1, tseg1=7, tseg2=4, sjw=4, nof_samples=1),                
                (int(500e3))           : dict(f_clock=80000000, brp=10, tseg1=13, tseg2=2, sjw=1)

            }
        self.total_send_count = 1
        self.current_frame_count = 0

    def start_busses(self, nominalBitrate, dataBitrate=None):
        if dataBitrate:
            print("configure canFD")
            fd_identifier = (int(nominalBitrate), int(dataBitrate))
            timing_param = self.timing_table.get(fd_identifier,{})
            is_fd = True
            print (f"FD: {fd_identifier} - {timing_param}")
            
            #self.bus1 = can.interface.Bus(interface="pcan", channel="PCAN_USBBUS1", bitrate=nominalBitrate, data_bitrate=dataBitrate, **timing_param)
            #self.bus2 = can.interface.Bus(interface="pcan", channel="PCAN_USBBUS2", bitrate=nominalBitrate, data_bitrate=dataBitrate, **timing_param)
            self.bus1 = can.interface.Bus(interface="pcan", channel="PCAN_USBBUS1",  **timing_param)
            self.bus2 = can.interface.Bus(interface="pcan", channel="PCAN_USBBUS2",  **timing_param)
        else:
            print("configure can2.0")
            std_identifier = int(nominalBitrate)
            timing_param = self.timing_table.get(std_identifier,{})
            print (f"CAN2: {std_identifier} - {timing_param}")

            is_fd = False
            self.bus1 = can.interface.Bus(interface="pcan", channel="PCAN_USBBUS1", receive_own_messages = False,  **timing_param)
            self.bus2 = can.interface.Bus(interface="pcan", channel="PCAN_USBBUS2", receive_own_messages = False,  **timing_param)
            
            print (f"{std_identifier} - {timing_param}")

        print(self)

    def stop_busses(self):
        if self.bus1:
            self.bus1.shutdown()
        self.bus1 = None
        if self.bus2:
            self.bus2.shutdown()
        self.bus2 = None


    def __str__(self):
        try:
            rv = f"{self.bus1.channel_info}: {self.bus1.state} {self.bus1.protocol} {self.bus1.bitrate} {self.bus1.data_bitrate}, "\
                 f"{self.bus2.channel_info}: {self.bus2.state} {self.bus2.protocol} {self.bus2.bitrate} {self.bus2.data_bitrate}"
        except Exception as e:
            rv = f"ERROR: {e}"
        return rv

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
                        cantrx.replay_messages(messages=messages, interactive=cfg["interactive"])
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
