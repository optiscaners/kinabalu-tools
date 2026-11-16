"""
Open and close a single CAN bus on Linux (SocketCAN) or Windows (PCAN).

Usage:
    from can_bus_setup import start_bus, stop_bus

    bus = start_bus(500000, 5000000, pcan_channel="PCAN_USBBUS1")
    try:
        bus.send(msg)
    finally:
        stop_bus(bus)

On Linux the interface is configured with 'sudo ip link set ...' (bitrate,
data bitrate, fd, presume-ack) before the SocketCAN bus is opened; the
pcan_channel argument is ignored there. On Windows the PCAN bit timing is
looked up in TIMING_TABLE.
"""

import subprocess
import sys

import can

# PCAN bit timings, keyed by nominal bitrate (CAN classic) or
# (nominal bitrate, data bitrate) (CAN FD).
TIMING_TABLE = {
    (int(500e3), int(5e6)): dict(f_clock=80000000, nom_brp=1, nom_tseg1=127, nom_tseg2=32, nom_sjw=32,
                                 data_brp=1, data_tseg1=11, data_tseg2=4, data_sjw=4),
    (int(500e3), int(1e6)): dict(f_clock=40000000, nom_brp=1, nom_tseg1=63, nom_tseg2=16, nom_sjw=16,
                                 data_brp=4, data_tseg1=7, data_tseg2=2, data_sjw=2),
    # Derived from "can.BitTiming.from_sample_point(f_clock=8000000, bitrate=666666, sample_point=69.0)"
    int(666666): dict(f_clock=8000000, brp=1, tseg1=7, tseg2=4, sjw=4, nof_samples=1),
    int(500e3): dict(f_clock=80000000, brp=10, tseg1=13, tseg2=2, sjw=1),
}


def _is_linux():
    return sys.platform.startswith("linux")


def _run_ip_link(*args, check=True):
    """Run 'sudo ip link set <args>' and raise RuntimeError on failure (unless check=False)."""
    cmd = ["sudo", "ip", "link", "set", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"command failed: {' '.join(cmd)}: {e}") from e
    if result.returncode != 0:
        msg = f"command failed ({result.returncode}): {' '.join(cmd)}: {result.stderr.strip()}"
        if check:
            raise RuntimeError(msg)
        print(f"WARNING: {msg}")
    return result


def _start_on_linux(channel, nominal_bitrate, data_bitrate=None, presume_ack="on"):
    fd = bool(data_bitrate)
    print(f"LINUX configure {channel} {'canFD' if fd else 'canCLASSIC'}")
    link_args = ["type", "can", "bitrate", str(int(nominal_bitrate))]
    if fd:
        link_args += ["dbitrate", str(int(data_bitrate)), "fd", "on"]
    else:
        link_args += ["fd", "off"]
    link_args += ["presume-ack", presume_ack]

    _run_ip_link(channel, "down")
    _run_ip_link(channel, *link_args)
    _run_ip_link(channel, "up")
    return can.interface.Bus(interface="socketcan", channel=channel, fd=fd)


def _start_on_windows(channel, nominal_bitrate, data_bitrate=None, receive_own_messages=False):
    if data_bitrate:
        key = (int(nominal_bitrate), int(data_bitrate))
        print(f"WIN32 configure {channel} canFD")
    else:
        key = int(nominal_bitrate)
        print(f"WIN32 configure {channel} canCLASSIC")
    timing_param = TIMING_TABLE.get(key, {})
    if not timing_param:
        print(f"WARNING: no PCAN timing for {key}, using driver defaults")
    print(f"{key} - {timing_param}")
    return can.interface.Bus(interface="pcan", channel=channel,
                             receive_own_messages=receive_own_messages, **timing_param)


def start_bus(nominal_bitrate, data_bitrate=None, pcan_channel="PCAN_USBBUS1",
              socketcan_channel="can0", presume_ack="on", receive_own_messages=False):
    """Configure and open one CAN bus; CAN FD if data_bitrate is given.

    pcan_channel is used on Windows, socketcan_channel on Linux.
    Returns the can.BusABC instance.
    """
    result = None
    if _is_linux():
        result = _start_on_linux(socketcan_channel, nominal_bitrate, data_bitrate, presume_ack)
    elif sys.platform == "win32":
        result =  _start_on_windows(pcan_channel, nominal_bitrate, data_bitrate, receive_own_messages)
    else: 
        raise RuntimeError(f"unsupported platform: {sys.platform}")
    return result


def stop_bus(bus):
    """Shut down a bus returned by start_bus(); on Linux also set the interface down.

    Accepts None, so it is safe to call in 'finally' blocks.
    """
    if bus is not None:
        bus.shutdown()
        if _is_linux():
            _run_ip_link(bus.channel, "down", check=False)
    else:
        pass
    return
