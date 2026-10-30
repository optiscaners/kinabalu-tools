"""
Send LIN frames from an LDF file over a PLin-compatible interface.

Usage:
    python lin_send_ldf.py -l <ldf_file> [-i] [-r <repeat_count>]

Options:
    -D, --dump-signals  Show signals in ldf and exit
    -h, --help          Show this help text and exit.
    -i, --interactive   Pause between frames and wait for Enter.
    -l, --ldf           Path to the LIN description file (.ldf).
    -r, --rpt           Number of repeat passes to send.
    -S <spec>
    --signal <spec>     define a signal to be modified <signalname>:<value>|<valrange>[,<value>|<valrange>[, ...]
The script parses the LDF, configures a LIN master node, and transmits the
unconditional frames defined in the file.

Example:
    python lin_send_ldf.py -l examples/THERMO_LIN2_2026_07a.ldf -r 10 
"""

from ctypes import *
import getopt
import ldfparser
import k6u.lin.PlinApi as PLinApi
import sys
import time
import traceback

##
# Handle LIN master communication for sending frames defined in an LDF file.
#
# This class configures a PLin-compatible LIN master, initializes the
# hardware, defines a simple schedule, and transmits frame payloads over
# the configured channel.
#
# @brief LIN master wrapper for frame transmission.
# @details The class is used by the script to connect to a LIN bus,
# register the client, and send unconditional frames parsed from an LDF.
#
# Note: current implementation uses SW-Send rather then using intern HW-PLIN-Scheduler
#
class LinMaster:
    def __init__(self):
        pass

    # Configure the LIN master client name, channel, and baud rate.
    def configure(self, name = "lin_snd_trc", channel=2, baudrate=19200):
        self.name = name
        self.channel = channel

        self.hClient = PLinApi.HLINCLIENT(0)
        self.hHw = PLinApi.HLINHW(channel)
        self.HwMode = PLinApi.TLIN_HARDWAREMODE_MASTER
        self.HwBaudrate = c_ushort(baudrate)

    # Load the PLin API, register the client, connect the hardware, and define the schedule.
    def initialize(self):
        self.bus = PLinApi.PLinApi()
        if self.bus is False or not self.bus.isLoaded(): 
            raise Exception("PLIN API Not Loaded")
        
        result = self.bus.RegisterClient(self.name, None, self.hClient)
        if result is not PLinApi.TLIN_ERROR_OK: 
            raise Exception("Error RegisterClient")

        result = self.bus.ConnectClient(self.hClient, self.hHw)
        if result is not PLinApi.TLIN_ERROR_OK: 
            raise Exception("Error ConnectClient")
        
        result = self.bus.InitializeHardware(self.hClient, self.hHw, self.HwMode, self.HwBaudrate)
        if result is not PLinApi.TLIN_ERROR_OK: 
            raise Exception("Error InitializeHardware")

        result = self.bus.RegisterFrameId(self.hClient, self.hHw, 0x00, 0x3F)
        if result is not PLinApi.TLIN_ERROR_OK: 
            raise Exception("Error registering frame id client")

        #self._defineSchedule()

    # def addFrame(self, FrameId, Length):
    #     frame = PLinApi.TLINFrameEntry(
    #         FrameId = c_ubyte(FrameId),
    #         Length = c_ubyte(Length),
    #         Direction = PLinApi.TLIN_DIRECTION_PUBLISHER,
    #         ChecksumType = PLinApi.TLIN_CHECKSUMTYPE_ENHANCED
    #     )
    #     for i in range(0, Length):
    #         frame.InitialData[i] = c_ubyte(0)        
    #     self.bus.CalculateChecksum(frame)
    #     result = self.bus.SetFrameEntry(self.hClient, self.hHw, frame)
    #     if result is not PLinApi.TLIN_ERROR_OK: 
    #         raise Exception("Error SetFrameEntry - frame")        
    #     return frame
    

    def sendFrame(self, FrameId, Length, data = None):      
        frameProtectedID = c_ubyte(FrameId)
        if self.bus.GetPID(frameProtectedID) != PLinApi.TLIN_ERROR_OK:
            raise Exception("GetPIDError")        
        frameLength = c_ubyte(Length) 
        if data == None:
            frameData = (c_ubyte * 8)(*[0xaa]*Length)
        else:
            frameData = (c_ubyte * 8)(*data[:Length])
        frameChecksum = c_ubyte(Length)

        message = PLinApi.TLINMsg(
            FrameId=frameProtectedID,
            Length=frameLength,
            Direction=PLinApi.TLIN_DIRECTION_PUBLISHER,
            ChecksumType=PLinApi.TLIN_CHECKSUMTYPE_ENHANCED,            
            Data=frameData,
            Checksum = frameChecksum)
        
        if self.bus.CalculateChecksum(message) != PLinApi.TLIN_ERROR_OK:
            raise Exception("ChecksumError")
        if self.bus.Write(self.hClient, self.hHw, message) != PLinApi.TLIN_ERROR_OK:        
            raise Exception("SendError")
        pass

    # Define a simple unconditional LIN schedule for the configured frame.
    # def _defineSchedule(self):
    #     masterRequestScheduleSlot = PLinApi.TLINScheduleSlot()
    #     masterRequestScheduleSlot.Type = PLinApi.TLIN_SLOTTYPE_UNCONDITIONAL
    #     masterRequestScheduleSlot.Delay = 100
    #     masterRequestScheduleSlot.FrameId =  (c_ubyte * 8)(0x37)


    #     slaveResponseScheduleSlot = PLinApi.TLINScheduleSlot()
    #     slaveResponseScheduleSlot.Type = PLinApi.TLIN_SLOTTYPE_SLAVE_RESPONSE
    #     slaveResponseScheduleSlot.Delay = 100

    #     self.schedule = (PLinApi.TLINScheduleSlot * 1)()        
    #     self.schedule[0] = masterRequestScheduleSlot
    #     #self.schedule[1] = slaveResponseScheduleSlot
    #     self.scheduleNumber = 1

    #     result = self.bus.SetSchedule(self.hClient, self.hHw, self.scheduleNumber, self.schedule, c_int(1))
    #     if result is not PLinApi.TLIN_ERROR_OK: 
    #         raise Exception("Error SetSchedule")

    # # Print debug information about the current client filter and frame entry.
    # def info(self):
    #     lMask = c_uint64(0)
    #     result = self.bus.GetClientFilter(self.hClient, self.hHw, lMask)
    #     print(hex(lMask.value))
    #     if result is not PLinApi.TLIN_ERROR_OK: 
    #         raise Exception("Error SetSchedule")
        
    #     #for i in range(64):
    #     for i in [0x37]:
    #         lFrameEntry = PLinApi.TLINFrameEntry()
    #         lFrameEntry.FrameId = c_ubyte(i)
    #         linResult = self.bus.GetFrameEntry(self.hHw, lFrameEntry)
    #         print(f"fId: 0x{lFrameEntry.FrameId:02x} cst: {lFrameEntry.ChecksumType} flags: {lFrameEntry.Flags} {list(lFrameEntry.InitialData)}")
    #     pass

    # # Start the previously configured LIN schedule.
    # def startSchedule(self):
    #     result = self.bus.StartSchedule(self.hClient, self.hHw, self.scheduleNumber)
    #     if result is not PLinApi.TLIN_ERROR_OK:
    #         raise Exception("Error StartSchedule")

    # # Suspend the active LIN schedule.
    # def stopSchedule(self):
    #     result = self.bus.SuspendSchedule(self.hClient, self.hHw)
    #     if result is not PLinApi.TLIN_ERROR_OK:
    #         raise Exception("Error StartSchedule")


##
# Create Signal class which has an value iterator
#
# sigspec = "<signalname>:<value>|<valrange>[,<value>|<valrange>[, ...]]"
#   value = <integer>
#   valrange = <start>:<end>

class Signal:
    def __init__(self, sigspec):
        self.sigspec = sigspec
        self.name, valuespec = self.sigspec.split(":",1)
        self.values = []
        self.idx = -1
        for vspec in valuespec.split(","):
            try:
                value = int(vspec)
                self.values.append(value)
            except:
                x = vspec.split(":")
                if len(x) == 2:
                    values = range(int(x[0]), int(x[1])+1)
                if len(x) == 3:
                    values = range(int(x[0]), int(x[1])+1, int(x[2]))
                assert len(values) != 0, f"no values, invalid {vspec}"
                self.values += values
        # make an immutable tuple from list
        self.values = tuple(self.values)

    def get(self):        
        rv = 0
        if len(self.values):
            if self.idx < len(self.values)-1:
                self.idx += 1
            else:
                self.idx = 0
            rv = self.values[self.idx]
        else:
            rv = 0
        return {self.name: rv}

class FrameList:
    def __init__(self, ldf, signals):
        self.ldf = ldf
        self.signal_dict = {}
        self.frames = {}
        if len(signals):
            for s in signals:
                self.signal_dict[s.name] = s
                signal = ldf.get_signal(s.name.strip())
                fname = signal.frame.name 
                if fname not in self.frames:
                    self.frames[fname] = []
                self.frames[fname].append(s)
        else:            
            for frame in ldf.get_unconditional_frames():
                self.frames[frame.name] = []
        pass

    def get_frames(self):
        for frm_name in self.frames.keys():
            siglist = self.frames[frm_name]
            frm = self.ldf.get_frame(frm_name)
            sigs = {}
            for s in siglist:
                xx = s.get()
                sigs.update(**xx)
            payload = list(frm.encode_raw(sigs))
            yield (frm, payload)
        

def dumpLdfSignals(ldfname):
    print (ldfname)
    ldf = ldfparser.parse_ldf(ldfname)
    frames = ldf.get_unconditional_frames()
    for f in frames:
        print(f"frame: {f.frame_id} {f.name} len: {f.length}")
        for s in f.signal_map:
            bpos = s[0]
            print(f"  0x{f.frame_id:02x} {f.name}.{s[1].name}: bpos: {bpos} width: {s[1].width}: {s[1].init_value}")

    pass


# Parse command-line options for the LIN sender.
def parse_args():
    doDumpSignalsAndExit = False
    cfg = {
        "interactive": False,
        "ldf_file": None,
        "rpt_count": 1,
        "signals" : []
    }
    try:        
        opts, args = getopt.getopt(sys.argv[1:], "hl:ir:S:D", ["help", "ldf=", "interactive", "rpt=", "signal=", "dump-signals"])
        for o, v in opts:
            if o in ("-h", "--help"):
                print(__doc__)
                sys.exit(0)
            elif o in ("-l", "--ldf"):
                cfg["ldf_file"] = v
            elif o in ("-i", "--interactive"):
                cfg["interactive"] = True
            elif o in ("-r", "--rpt"):
                cfg["rpt_count"] = int(v)
            elif o in ("-S", "--signal"):
                s = Signal(v)
                cfg["signals"].append(s)
            elif o in ("-D", "--dump-signals"):                
                doDumpSignalsAndExit = True
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        sys.exit(-1)
    print(cfg)
    if doDumpSignalsAndExit:
        dumpLdfSignals(cfg["ldf_file"])
        sys.exit(0)
    return cfg

# Parse options, initialize the LIN master, and transmit frames from the selected LDF file.
def main():
    cfg = parse_args()
    currentLdf = ldfparser.parse_ldf(cfg["ldf_file"])
    currentFrameList = FrameList(currentLdf, cfg["signals"])

    LinTransmitter = LinMaster()
    LinTransmitter.configure()
    LinTransmitter.initialize()

    tx_cnt = 0
    interactive_count = 0
    rpt_cnt = cfg["rpt_count"]
    try:
        for i in range(rpt_cnt):
            #for frm in currentLdf.get_unconditional_frames():
            #    frm_data = None
            for frm, frm_data in currentFrameList.get_frames():
                if cfg.get("interactive"):
                    if interactive_count > 0:
                        interactive_count -= 1
                    elif interactive_count == 0:

                        tmp = input(f"> Press Enter to send frame[{tx_cnt}] frm: {frm.frame_id}_{frm.name}:")
                        try:
                            interactive_count = int(tmp) - 1
                        except Exception:
                            interactive_count = 0
                LinTransmitter.sendFrame(frm.frame_id, frm.length, data=frm_data)
                #LinTransmitter.sendFrame(frm.frame_id, frm.length)
                tx_cnt += 1
                print(f"send[{tx_cnt}]: {frm.frame_id}_{frm.name} {frm_data}", end="          \r")
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nCtrl-C - user abort")
    except Exception as e:
        print(f"\nERROR: {e}")
        traceback.print_exc()
    print(f"\nsent {tx_cnt} frames in {i+1} iterations from {cfg['ldf_file']}")

if __name__ == "__main__":
    main()