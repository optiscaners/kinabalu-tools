# voice_to_can

Simulates a voice-over-CAN transfer by sending the samples of a wave file as CAN frames.

## Usage

```sh
voice_to_can [file.wav]
```

Without an argument the bundled test signal `k6u/data/chirp_200Hz_800Hz_10s_a08.wav`
(chirp 200–800 Hz, 10 s) is used.

## Wave file requirements

Each CAN frame carries 4 audio frames and a classic CAN frame holds at most 8 bytes, so
`4 × sample width × channels` must be ≤ 8. In practice: **mono, 16 bit** (or 8 bit).
Other formats are rejected with an error.

## Protocol

| Item | Value |
|---|---|
| Interface | PCAN, `PCAN_USBBUS1`, classic CAN, 1 Mbit/s |
| Voice packet ID | `0x04200000 + n` (extended ID), `n` = packet counter starting at 0 |
| Payload | 4 consecutive audio frames, raw little-endian PCM as stored in the wave file |
| End marker | `0x04400000 + n` (extended ID), DLC 0, sent after the last voice packet |
| Pacing | 0.2 ms sleep before each frame |

Send errors are printed with the packet index; the transfer continues with the next packet.
