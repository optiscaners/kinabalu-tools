"""
Simulate voice to can transfer with a given WaveFile.
"""
import can #  python-can
import os
import time
import sys
import wave
from importlib.metadata import PackageNotFoundError, version

try:
    VERSION = version("kinabalu-tools")
except PackageNotFoundError:
    VERSION = "unknown"

class VoiceToCanSender:

    def __init__(self):
        self.is_remote_frame = False
        self.total_send_count = 0
        self.bus = can.interface.Bus(interface="pcan", channel="PCAN_USBBUS1", fd=False, bitrate=1000000)

    def shutdown(self):
        self.bus.shutdown()

    def send_voice_packets(self, wf=None):
        self.total_send_count = 0
        msg = can.Message(is_extended_id=True, is_rx=False, is_remote_frame=self.is_remote_frame, channel=1)
        print(self.bus)
        voicepacket_id = 0x04200000
        voicepacketlast_id = 0x04400000

        i = 0
        if wf:
            frame_bytes = 4 * wf.getsampwidth() * wf.getnchannels()
            if frame_bytes > 8:
                raise ValueError(f"4 audio frames need {frame_bytes} bytes, a CAN frame holds 8 "
                                 f"(use a mono 16-bit wave file)")
            mxframes = wf.getnframes()
            cnt = 0
            i = 0
            print(f"mxframes: {mxframes}")
            while ( cnt < mxframes ):
                try:
                    data = wf.readframes(4)
                    msg.arbitration_id = voicepacket_id+i
                    msg.data = data
                    msg.dlc = len(msg.data)
                    time.sleep(0.0002)
                    self.bus.send(msg)
                    self.total_send_count += 1
                except Exception as e:
                    print(f"Error {e}, frame={i}")
                finally:
                    # readframes() already advanced the file, so advance even if send failed
                    cnt += 4
                    i += 1
                print(f"frames = [{i}] {msg}", end="\r")
        else:
            for i in range(50):
                msg.arbitration_id = voicepacket_id+i
                msg.data = bytearray([1,0,2,0,3,0,4,0])
                msg.dlc = len(msg.data)
                print(f"{self.total_send_count} {i} {msg}")
                self.bus.send(msg)
                self.total_send_count += 1

        try:
            arbitration_id = voicepacketlast_id + i
            msg2 = can.Message(arbitration_id = arbitration_id, dlc=0)
            self.bus.send(msg2)
            print(f"\n\nlast msg send {msg2}")
        except Exception as e:
            print(f"Error {e}, voicepacketlast_id: 0x{arbitration_id:x} ")

        pass


def parse_args():

    this_dir, _ = os.path.split(__file__)
    DEFAULT_WAVE_FILE = os.path.join(this_dir,"..", "data", "chirp_200Hz_800Hz_10s_a08.wav")
    cfg = {"wave" : DEFAULT_WAVE_FILE}
    try:
        cfg["wave"] = sys.argv[1]
    except IndexError:
        print(f"Using default {DEFAULT_WAVE_FILE}")
    return cfg

def main():
    cfg = parse_args()
    with wave.open(cfg.get("wave"), "rb") as wf:
        print(f"v{VERSION} frames={wf.getnframes()}, params={wf.getparams()}")

        v2c = VoiceToCanSender()
        try:
            v2c.send_voice_packets(wf)
        finally:
            v2c.shutdown()

if __name__ == "__main__":
    main()