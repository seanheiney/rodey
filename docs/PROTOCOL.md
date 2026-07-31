# RØDECaster Pro II — USB HID control protocol

Reverse-engineered 2026-07-28/29 against a RØDECaster Pro II, firmware **1.7.3**,
`idVendor 0x19F7` / `idProduct 0x37`, on macOS (Apple Silicon).

Everything below was obtained by **observing RØDE's own app**, not by guessing:
`IOHIDDeviceSetReport` was interposed in an ad-hoc re-signed copy of the app, and
every claim here is either a captured frame or a result verified by state-dump diff.

> **This is unofficial.** RØDE publishes no host API. Firmware changes may break it.

---

## ⚠️ Safety — read before writing anything

Report ID 1 carries **single-ASCII mode commands**:

| Byte | ASCII | Effect |
|------|-------|--------|
| `0x4D` | `M` | **Enters firmware update mode** — blanks the screen |
| `0x4E` | `N` | Normal / app mode — this is the one you want |
| `0x55` | `U` | **Triggers a firmware flash** |

Sending arbitrary bytes to report 1 put a board into update mode during this work
(screen dark, audio still running, recovered by power cycling). Send **only `0x4E`**.

Note that a widely-linked open-source project probes `0x55` as a "ping". It is not a
ping. Do not run it against hardware you care about.

Do **not** sweep unknown object IDs either. Writing `noiseGateOn` across objIDs
`0x1c`–`0x33` **permanently added the property to objects that did not have it**,
confirmed against a control:

```
noiseGateOn   24 occurrences in the state dump   (swept)
compressorOn  10 occurrences                     (untouched — the true channel count)
```

The extra objects persist across reconnects. Object IDs must be **harvested from
observed writes**, never discovered by sweeping.

---

## Transport

USB interface 9, `bInterfaceClass = 3` (HID), vendor usage page `0xFF00`.
Coexists with RØDE's app (which opens non-exclusively). Note `hidapi` **seizes** the
device, so you cannot open two hidapi handles at once.

| Report ID | Direction | Size | Purpose |
|-----------|-----------|------|---------|
| 1 | host → device | 63 B | mode commands (single ASCII byte) |
| 2 | device → host | 63 B | command responses |
| 3 | host → device | 255 B | property writes, session control |
| 4 | device → host | 255 B | property notifications, state dump |

---

## Handshake — required

Nothing works before this. Property writes are silently ignored and no notifications
are emitted.

```
reportID 1 :  4e                            'N' — normal/app mode
reportID 3 :  04 00 00 00 | ad 10 a7 b0     session open / subscribe
```

The handshake also triggers a **full state dump** (below).

---

## Frame format

Property writes (report 3) and notifications (report 4) share one layout:

```
uint32_le total_len | <address> | <property name> 00 | 01 <len> <payload>
```

* **address** — `01 01 01 01 <objID>` for channel-scoped objects. Length varies
  (pads use 8 bytes). Do not hard-code the offset.
* **property name** — ASCII, camelCase, null-terminated.
* **`len`** — byte count of `payload`.

### Payload types

| `payload[0]` | Type | Encoding |
|--------------|------|----------|
| `01` | uint32 | 4 bytes little-endian (`len = 5`) |
| `02` | bool false | no further bytes (`len = 1`) |
| `03` | bool true | no further bytes (`len = 1`) |
| `04` | float64 | 8 bytes little-endian (`len = 9`) |
| `05` | string | null-terminated ASCII |

### ⚠️ Mute properties have INVERTED polarity

`channelOutputMute` and `mixMute` are effectively "output **enabled**", not "muted":

```
channelOutputMute = False  ->  channel IS muted
channelOutputMute = True   ->  channel passes audio
```

Confirmed by muting Bluetooth on the board and watching that strip go `True` → `False`.
`mixMute` follows the same convention (`mixMute[bus 0]` tracks `channelOutputMute`).

Writing `True` to "mute" a channel therefore **unmutes** it, and nothing in the name
warns you. Worse, the resting state reads mostly `True`, which looks like "everything
muted" and invites exactly the wrong conclusion — it cost a false alarm during this
work. Use `is_muted()` / `mute_value()` rather than passing raw booleans around.

### Value ranges — there are two conventions

Do not assume everything is normalised. Encoding the wrong one produces a valid frame
that silently does nothing.

| Kind | Type | Range | How to know |
|------|------|-------|-------------|
| Faders | uint32 | **0–127** | `faderMin` / `faderMax` in the dump |
| Pots / knobs | uint32 | **0–127** | `potMin` / `potMax` in the dump |
| Processing, levels, effects | float64 | **0.0–1.0** | no metadata — assumed |

Faders and pots publish their own bounds; everything else does not. What a float
`0.0–1.0` maps to in real units (dB, Hz, ms) is still unknown — see Open questions.

Example — enable the Mic 1 noise gate (objID `0x1c`):

```
14 00 00 00 | 01 01 01 01 1c | "noiseGateOn" 00 | 01 01 03
```

Example — set its threshold to 0.5:

```
23 00 00 00 | 01 01 01 01 1c | "noiseGateThreshold" 00 | 01 09 04 <f64>
```

---

## Reading state

**The device does not echo writes back to the handle that made them.** Echoes go to
*other* clients only. Since `hidapi` seizes the device, you cannot simply open a second
handle to watch.

Instead, use the **state dump**: the handshake causes the device to serialise its whole
object tree to report 4 — roughly **139 KB across 63 groups**.

### ⚠️ Drain immediately — do not sleep after the session-open

The device begins transmitting **the instant it is subscribed**, and hidapi's receive
queue is shallow. Any pause between sending the session-open and the first `read()` —
**even 300 ms** — silently loses the head of the tree, which is exactly where
`PHYSICALINTERFACE`, `FADER`, `METER` and every `CHANNEL` block live.

The failure is deeply misleading: you still receive a plausible-looking ~28 KB dump
containing the *tail* of the tree (`PADEFFECTS`, `FXPRESET`, `SIP*`), so it looks like
the device is refusing to report channel state rather than like a dropped read. This
cost hours during development and produced several confident but wrong theories
(first-sync-only, app-dependent, needs-a-power-cycle).

Correct shape:

```python
dev.write(encode_mode())          # 'N'
time.sleep(0.2)
dev.write(encode_session_open())
while ...:                        # start reading NOW, no sleep, no allocation
    dev.read(256)
```

Stop when reports stop arriving (a few hundred ms of idle), not on a fixed timer.
Collecting the full tree takes about one second when drained properly.

To verify a write: dump, write, dump again, diff.

> Do **not** verify writes by measuring audio. On a sensitive condenser the noise floor
> drifts several dB on its own, which produced two opposite wrong conclusions during
> this work — a false "confirmed" from room-noise drift, and a false "not working"
> because the gate enables correctly but does not audibly attenuate.

### Dump structure

A nested tree, not an addressed list:

```
00 GROUPNAME 00 01 02   →   propName 00 01 <len> <payload>   →   propName 00 ...
```

Groups are UPPERCASE, properties camelCase. After a group name comes `01 <len>` — a
length, not an identifier.

`CHANNEL` appears exactly **10 times**, once per strip, plus a master block
(identifiable by `masterCompellorOn`). Each channel block opens with
`channelInputSource`, a uint32 naming what is patched to that strip:

| Value | Source |
|-------|--------|
| `0` | Mic 1 |
| `1` | Mic 2 |
| `7`, `8`, `9`, `10`, `11` | USB 1, Chat, USB 2, Bluetooth, SMART Pads (exact order to confirm) |
| `0xFF` | strip empty |

So **channel identity and every value are readable from the dump** — you can tell
which strip is Mic 2 without guessing. What the dump does *not* carry is the
**object ID needed to write**; those appear only in writes and must be harvested.

---

## Object IDs

### Channels — solved

```
objID = 0x1C + strip index          strips 0..9  →  0x1C .. 0x25
```

One object carries a channel's **entire processing block** — `noiseGate*`, `hpf*`,
`compressor*`, `deesser*`, `aphex*`, `channelBypassProcessing`, `channelPan*`,
`channelDepth/Punch/Sparkle` — so ten IDs cover nearly all channel-scoped control.

Strip *order* is fixed; what is *patched* to each strip is user-configurable, so read
`channelInputSource` from a state dump to resolve strip → source.

**How this was established, and how to extend it safely.** Toggle a property the object
is already known to carry (`channelBypassProcessing`), then diff the state dump to see
which strip moved. Because the property already exists on that object, no new property
can be created — unlike sweeping arbitrary IDs, which permanently mutates the tree.
Derived from `0x1c`, `0x1f`, `0x20`, `0x22`, `0x25`; then *predicted* and confirmed on
`0x1d` and `0x1e`.

### Mix-bus routing matrix — solved

```
objID = 0x4C + 13 * sourceIndex + bus        13 buses per source
```

`sourceIndex` is the **`channelInputSource`** code (0 = Mic 1, 1 = Mic 2, 7 = USB 1,
8 = Chat, 9 = USB 2, 10 = Bluetooth, 11 = SMART Pads) — *not* the strip position,
since strips are user-assignable and these blocks are not.

| Source | Block |
|--------|-------|
| 0 Mic 1 | `0x4C`–`0x58` |
| 1 Mic 2 | `0x59`–`0x65` |
| 7 USB 1 | `0xA7`–`0xB3` |
| 8 Chat | `0xB4`–`0xC0` |
| 9 USB 2 | `0xC1`–`0xCD` |
| 10 Bluetooth | `0xCE`–`0xDA` |
| 11 SMART Pads | `0xDB`–`0xE7` |

This is the routing matrix: muting a source on a bus removes it from that send —
the mechanism behind mix-minus scoping.

Established by muting each channel on the board and observing which 13-object run
emitted, then confirmed by writing to a computed address (`source=1, bus=0` → `0x59`)
and seeing exactly one of 514 `mixMute` entries change. In a state dump the entries
appear in the same order, so dump index = `13 * source + bus`.

### Other objects

| objID | Properties |
|-------|------------|
| `0x06` | `encoderColour`, `encoderSignal` |
| `0x07` | `screenBrightness`, `screenTouched`, `selectedBank` |
| `0x09`, `0x0a` | `headphoneType` |
| `0x0d` | `outputMonAutoMuteActive` |
| `0x0f` | `systemChannelSelected`, `systemMidiControl`, `transferModeType`, `assignableMeterSource` |
| `0x27` | `echoDelay`, `echoDecay`, `echoHighCut`, `echoLowCut`, `echoMix` |

The shipped map lives at `src/rodecaster/data/objid_map.json` (104 objects, 43
properties). Extend it with `tools/harvest_objids.py` (app traffic) or
`tools/capture_board.py` (physical controls).

`systemMidiControl` toggles RØDE's **documented** MIDI control surface (SMART Pads, mic
mutes, fader levels). Where MIDI suffices, prefer it — it is supported and less likely
to break across firmware releases.

---

## Property groups (49)

```
AUDIO BUILD CHANNEL CURRENTSHOW DUCKER EFFECTS_PARAMETERS EMERGENCYMUTE ENCODER
FADER FXPRESET FXPRESETS HEADPHONE INPUTSOURCE MASTERCHANNEL METER MIXMINUSES
NETWORK OUTPUT PADBUTTON PADEFFECTS PADRECORDER PHYSICALINTERFACE PLAYER RADIO
RADIORX RADIOTX RCSYNCMIX RCSYNCMIXMINUES RECBUTTON RECORDER RECORDINGS
SHOWCONTROL SHOWS SIPADVANCED SIPCALLING SIPCALLSLOTS SIPPHONEBOOKARRAY
SIPREGISTRATION SOLOMUTEBUTTON SOUNDPADS STORAGEVOLUME STREAMERXMIXPRESET
STREAMERXSTREAMMIX SYSTEM TEST THEME WIFISCANRESULT
```

Two further groups are device-specific: the serial number (e.g. `GV0180634`) and a
build identifier.

### Selected properties

**Channel processing** — `noiseGateOn`, `noiseGateThreshold`, `noiseGateRange`,
`noiseGateHysteresis`, `noiseGateAttack`, `noiseGateHold`, `noiseGateRelease`,
`compressorOn/Threshold/Ratio/Attack/Release/Gain`,
`deesserOn/Threshold/Ratio/Frequency/Attack/Release/Gain`,
`hpfOn/Frequency/Slope`, `aphexOn/AEMix/AETune/BBDrive/BBTune`

**Mute & routing** — `channelOutputMute`, `channelWirelessMute`, `mixMute`, `mixLink`,
`emergencyMuteActive`, `outputMonMute`, `outputBTMute`, `incomingAudioRouting`,
`mutePressed`, `soloPressed`

**Levels & metering** — `faderLevel`, `faderMin`, `faderMax`, `potLevel`, `potMax`,
`meterLevelL/R`, `meterPeakL/R`, `mixLevelWithAnchor` (streams continuously as
`"<L>|<R>"` strings — filter it out when watching for control changes)

---

## Other interfaces

* **USB MIDI** (interface 7) — a *documented* control surface covering SMART Pads,
  mic mutes and fader levels, but **not** channel processing. Must be enabled on the
  board; it emits nothing by default. Safer than HID where it suffices.
* **USB mass storage** (interface 8) — microSD access.
* **SSH** — the board runs Linux (`5.10.17-rt32-yocto-preempt-rt-rode+`) with SSH
  enabled by default and pre-installed keys. Reported publicly; not used here.

---

## Faders are read-only *by design* — stop looking

`faderLevel` reads fine from the state dump (9 entries, uint32 0–127, bounds published
as `faderMin`/`faderMax`). It cannot be written, and this is a hardware design
constraint rather than an undiscovered command.

**Why:** the faders are physical and **not motorised**. Setting a level remotely would
leave the stored value disagreeing with where the slider physically sits, so the device
does not accept it. Nothing in the protocol can fix that.

The evidence is consistent with this and not with a missing feature:

* **RØDE's own app exposes no fader control.** The strongest signal available — if it
  were possible, the vendor app would do it.
* **Physical fader moves emit nothing.** Two capture sessions, no `faderLevel` traffic.
* **MIDI does not reach them.** With `systemMidiControl` enabled, CC 0–31 across MIDI
  channels 1–3 moved no fader. The 0–127 range match is a coincidence of scale.
* **Writable controls are the ones without absolute position.** `outputMonLevel` (an
  encoder) writes fine. Faders have a position software cannot move; encoders do not.

So: read `faderLevel` for metering and state display; drive gain through
channel-scoped properties instead. Do not spend time hunting for a fader write command.

## Open questions

* Complete object-ID map (harvest from app writes; do not probe).
* `noiseGateRange` / `noiseGateThreshold` semantics — writes land and the dump confirms
  the change, but no audible attenuation results, so the 0..1 mapping to dB is unknown.
* Report 1 / 2 command layer beyond mode bytes — an ACK marker `0x41` on report 2 is
  described elsewhere but was not observed here.
* Whether the session needs a keepalive for long-lived connections.
