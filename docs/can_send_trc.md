# can_send_trc

Replays CAN trace files (PCAN `.trc` format) with the timing recorded in the trace.

## Usage

```sh
can_send_trc -c <config.json> [-i] [-r <n>] <profile> [profile ...]
can_send_trc -c <config.json> -P
```

| Option | Meaning |
|---|---|
| `-c`, `--config` | JSON config file (default: `examples/cansendtrc_config.json`) |
| `-i`, `--interactive` | Wait for Enter before each frame |
| `-r`, `--rpt <n>` | Repeat the whole replay `n` times (default: 1) |
| `-P`, `--list-profiles` | List the profiles from the config file and exit |
| `-h`, `--help` | Show help |

## Config file

Example: [examples/cansendtrc_config.json](../examples/cansendtrc_config.json)

```json
{
    "TrcDir": "traces",
    "TrcFile": null,
    "CanBusses": [
        { "Hardware": "HW_A", "Id": 1, "BaudRate": 500000, "TrcFile": "hw_a_classic.trc" },
        { "Hardware": "HW_B", "Id": 2, "BaudRate": 500000, "DataBaudRate": 1000000, "TrcFile": "hw_b_fd.trc" }
    ],
    "Profiles": {
        "all": "all",
        "a": ["HW_A"]
    }
}
```

| Key | Meaning |
|---|---|
| `TrcDir` | Directory containing the trace files (default: current directory) |
| `TrcFile` | Optional. If set, this trace is replayed on every bus and overrides the per-bus `TrcFile` |
| `CanBusses[].Hardware` | Name used by the profiles to select the bus |
| `CanBusses[].Id` | Free identifier, only used in the output |
| `CanBusses[].BaudRate` | Nominal bitrate in bit/s |
| `CanBusses[].DataBaudRate` | Optional. Data bitrate in bit/s; if present, the bus is configured as CAN FD |
| `CanBusses[].TrcFile` | Trace file for this bus, relative to `TrcDir` |
| `Profiles` | Profile name → list of `Hardware` names, or the string `"all"` |

Profile selection:

- Several profiles can be given; their busses are combined.
- `all` always selects every bus, even if it is not defined in `Profiles`.
- An unknown profile name aborts with an error listing the available profiles.

## Supported bitrates

Bit timing is taken from `timing_table` in `CanTrcTx.__init__`. Only these combinations are configured:

| Mode | Nominal | Data | CAN clock |
|---|---|---|---|
| CAN 2.0 | 500 kbit/s | – | 80 MHz |
| CAN 2.0 | 666.666 kbit/s | – | 8 MHz |
| CAN FD | 500 kbit/s | 1 Mbit/s | 40 MHz |
| CAN FD | 500 kbit/s | 5 Mbit/s | 80 MHz |

For any other combination no timing parameters are passed to the PCAN driver. Add a new entry
to `timing_table` (e.g. derived with `can.BitTiming.from_sample_point(...)`) if needed.

## Hardware

- Frames are sent on `PCAN_USBBUS1`.
- `PCAN_USBBUS2` is opened with the same settings (e.g. as receiver / bus partner) but not used for sending.
- For each selected bus, the PCAN channels are opened, the trace is replayed, and the channels are closed again,
  also on errors or Ctrl-C.

## Replay behaviour

- The delay between two frames is the timestamp difference in the trace.
- In interactive mode, each frame is printed before sending. Press Enter to send it,
  or enter a number `n` to send the next `n` frames without asking.
- Send errors are reported with the frame index and the replay continues.
- Ctrl-C aborts and prints the total number of frames sent.
