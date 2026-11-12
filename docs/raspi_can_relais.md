# raspi_can_relais

Controls a relay board on a Raspberry Pi through GPIO: 24 relays for CAN lines (`CAN1` … `CAN24`)
and two for the vehicle supply terminals `KL15` (ignition) and `KL30` (permanent battery supply).

## Requirements

- Raspberry Pi with the relay board connected to the GPIO header
- [`gpiozero`](https://gpiozero.readthedocs.io/). It is not yet listed in the project dependencies,
  so install it separately (`uv pip install gpiozero`; on a Raspberry Pi 5 also `lgpio`).

## Usage

The command only initialises the GPIO pins and exits, which releases the pins again:

```sh
raspi_can_relais
```

To switch relays, run the module in an interactive Python session. The relays are then
available in the global `REL`:

```sh
python -i -m k6u.can.raspi_can_relais
```

```python
>>> REL.KL30.on()         # switch on KL30
>>> REL.KL15.on()         # switch on KL15
>>> REL.CAN3.on()         # switch relay CAN3
>>> REL["CAN3"].off()     # access by name works too
>>> REL.show()            # state of all CAN relays, e.g. [False, False, True, ...]
>>> REL.CAN1.blink(on_time=0.5, off_time=0.5)   # toggle in the background
```

Each relay is a [`gpiozero.LED`](https://gpiozero.readthedocs.io/en/stable/api_output.html#led)
(active high, initially off), so `on()`, `off()`, `toggle()`, `blink()` and `is_active` are available.
Whether `on()` closes or opens a CAN line depends on the wiring of the relay board.

## Pin assignment

GPIO numbers are BCM numbers, not physical header pins.

| Relay | GPIO | Relay | GPIO | Relay | GPIO |
|---|---|---|---|---|---|
| CAN1 | 4 | CAN9 | 24 | CAN17 | 1 |
| CAN2 | 14 | CAN10 | 10 | CAN18 | 5 |
| CAN3 | 15 | CAN11 | 9 | CAN19 | 6 |
| CAN4 | 17 | CAN12 | 25 | CAN20 | 12 |
| CAN5 | 18 | CAN13 | 11 | CAN21 | 13 |
| CAN6 | 27 | CAN14 | 8 | CAN22 | 19 |
| CAN7 | 22 | CAN15 | 7 | CAN23 | 16 |
| CAN8 | 23 | CAN16 | 0 | CAN24 | 26 |
| **KL15** | **2** | **KL30** | **3** | | |

On startup every relay is printed with `OK` or `FAIL <reason>`. A relay that fails is skipped;
the others still work.

## Notes

- Several pins are shared with Raspberry Pi interfaces: GPIO 2/3 (I2C, used for KL15/KL30),
  GPIO 14/15 (UART), GPIO 7–11 (SPI) and GPIO 0/1 (HAT EEPROM). Disable those interfaces
  (`raspi-config`, `/boot/firmware/config.txt`) if the relays on these pins fail or misbehave.
- Unlike the CAN relays, a failure on `KL15` or `KL30` is not caught and aborts the start.
- When the Python process ends, gpiozero releases the pins and the relays fall back to their
  idle state.
