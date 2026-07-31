# Capture tools

Object IDs appear **only in writes**, never in the state dump. And they cannot be
discovered by trying candidates: writing `noiseGateOn` across `0x1c`–`0x33` permanently
added that property to objects that never had it (24 occurrences afterwards, versus 10
for an untouched control property, and it survived a power cycle).

So the only safe source is RØDE's own app. These tools capture what it sends.

## Why an interposer

Two easier routes are closed on modern macOS:

* **USB packet capture** — Apple Silicon exposes no `XHC*` capture interface, so
  Wireshark cannot see the bus.
* **A second HID reader** — `hidapi` *seizes* the device, so you cannot open a second
  handle to observe. (RØDE's app opens non-exclusively, which is why it can run
  alongside this library.)

`hidlog.c` interposes `IOHIDDeviceSetReport` inside the app itself, logs every frame,
then calls through unchanged. It observes; it does not alter anything.

## Build and capture

The app ships with hardened runtime, so `DYLD_INSERT_LIBRARIES` is ignored until a
**copy** is re-signed ad-hoc. `/Applications` is never touched.

```bash
clang -arch arm64 -dynamiclib -framework IOKit -framework CoreFoundation \
      -o hidlog.dylib hidlog.c
codesign --force --sign - hidlog.dylib

cp -R "/Applications/RODECaster App.app" ./RODECaster-instrumented.app
codesign --force --deep --sign - ./RODECaster-instrumented.app   # strips hardened runtime

pkill -f "RODECaster App"        # the copy needs the device
DYLD_INSERT_LIBRARIES="$PWD/hidlog.dylib" \
  ./RODECaster-instrumented.app/Contents/MacOS/"RODECaster App"
```

Then **exercise every control you want mapped** — each channel's gate, compressor,
de-esser, HPF and Aphex settings, faders, mutes, outputs, headphones, pads. Breadth
beats depth: one nudge on every control across all ten strips is worth far more than
extensive fiddling with one.

Frames land in `/tmp/rode-hidlog.txt`. Then:

```bash
./harvest_objids.py /tmp/rode-hidlog.txt --json
```

which prints an objID → property map and writes `objid_map.json`.

## Reading the output

```
objID 0x1c  (4 properties)
    noiseGateOn                False, True
    noiseGateThreshold         0.44, 0.45, 0.46
```

Each objID is one addressable object. A channel's processing block is a single object
carrying many properties, so a handful of objIDs covers a lot of surface.

Cross-reference against `channelInputSource` from a state dump (`rodecaster channels`)
to tell which strip an objID belongs to.

## Safety

`hidlog.c` only logs. But while the instrumented app is running it is a normal copy of
the vendor app, so anything you click takes effect on the board — including destructive
prompts. "Advanced" on a channel is a **toggle**: clicking it when already enabled
offers to reset every parameter on that channel.
