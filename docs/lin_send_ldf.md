# lin_send_ldf

Sends LIN frames defined in an LDF file as LIN master over a PEAK PLIN interface.
Frame layout and signal positions are taken from the LDF; signal values can be set
(and stepped through) on the command line.

## Usage

```sh
lin_send_ldf -l <ldf_file> [-r <count>] [-i] [-S <signalspec> ...]
lin_send_ldf -l <ldf_file> -D
```

| Option | Meaning |
|---|---|
| `-l`, `--ldf <file>` | LIN description file (`.ldf`) |
| `-r`, `--rpt <count>` | Number of passes over the frame list (default: 1) |
| `-i`, `--interactive` | Wait for Enter before each frame (see below) |
| `-S`, `--signal <spec>` | Set a signal value or value sequence; can be given several times |
| `-D`, `--dump-signals` | List frames and signals of the LDF and exit (no hardware needed) |
| `-h`, `--help` | Show help |

## Examples 

```sh
python lin_send_ldf.py -l examples/THERMO_LIN2_2026_07a.ldf -r 10
```

This command sends all frames defined 

## Which frames are sent

- **Without `-S`:** every unconditional frame of the LDF is sent once per pass.
  All signals have their initial value from the LDF.
- **With `-S`:** only frames that contain at least one of the given signals are sent.
  Signals without `-S` in these frames keep their LDF initial value.

## Signal spec

```
<signalname>:<item>[,<item>...]

item = <value>               single value
     | <start>:<end>         range, end included
     | <start>:<end>:<step>  range with step, end included
```

Values are integers (raw values, no physical scaling). All items of a spec are joined into one
list. Each time the frame is sent, the next value is used. After the last value the list starts
again from the first.

```sh
# Frame with "Fan_Speed" is sent 11 times with 0, 10, 20, ... 100
lin_send_ldf -l thermo.ldf -S Fan_Speed:0:100:10 -r 11

# alternate between 0 and 1, and set a second signal to 5, 7, 8, 9
lin_send_ldf -l thermo.ldf -S Heater_On:0,1 -S Mode:5,7:9 -r 8
```

Use `-D` to find signal names. It prints per frame: ID, name, length, and per signal
the bit position, width and initial value.

## Interactive mode (`-i`)

Before each frame the prompt `> Press Enter to send frame[n] ...` is shown.

- Enter sends the next frame.
- A number `N` followed by Enter sends the next `N` frames without asking.

## Timing and bus settings

| Setting | Value |
|---|---|
| PLIN hardware channel | 2 |
| Baud rate | 19200 |
| Mode | Master |
| Checksum | Enhanced (for all frames) |
| Frame interval | approx. 50 ms |

These values are fixed in the code (`LinMaster.configure()` and the `time.sleep()` in `main()`).
The frames are sent by the script one by one (software sending). The LDF schedule tables
and the PLIN hardware scheduler are not used.

`Ctrl-C` stops sending. At the end, the number of sent frames is printed.

## Requirements

- PEAK PLIN-USB interface with the PEAK PLIN driver installed. `PLinApi.dll` must be
  loadable from the DLL search path. The Python wrapper is in `k6u/lin/PlinApi/`.
- Windows only (the PLIN API is loaded with `windll`).

## Known limitations

- Channel, baud rate and frame interval cannot be set on the command line.
- Only publisher frames sent by the master. Slave responses are not requested or shown.
- Signal values are not checked against the signal width. Values that are too large fail
  when the frame is encoded.
