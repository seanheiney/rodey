#!/usr/bin/env python3
"""
Build an object-ID map for the RØDECaster Pro II by parsing frames captured from
RØDE's own app.

Why observation rather than probing: object IDs appear only in writes, never in the
state dump. And sweeping candidate IDs is destructive — writing `noiseGateOn` across
0x1c-0x33 permanently added that property to objects that never had it (24 occurrences
afterwards, against 10 for an untouched control property). So the only safe source of
truth is what the app itself sends.

Capture procedure:

  1. build the interposer and an ad-hoc re-signed copy of the app (see tools/README)
  2. launch the copy with DYLD_INSERT_LIBRARIES=hidlog.dylib
  3. exercise every control you want mapped - each one the app touches is logged
  4. run this script over /tmp/rode-hidlog.txt

The more of the app's UI you exercise, the more complete the map.

    ./harvest_objids.py [logfile] [--json]
"""
import sys, re, json, struct
from collections import defaultdict

LOG = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
      else "/tmp/rode-hidlog.txt"


def parse_frames(path):
    """Yield (reportID, payload) for each logged host->device frame."""
    rid = None
    for line in open(path, errors="replace"):
        m = re.search(r"reportID=(\d+)", line)
        if m:
            rid = int(m.group(1))
            continue
        m = re.search(r"hex\s*:\s*([0-9a-f ]+)", line)
        if m and rid is not None:
            raw = bytes.fromhex(m.group(1).replace(" ", ""))
            # the logged buffer leads with the report ID byte
            if raw and raw[0] == rid:
                raw = raw[1:]
            yield rid, raw
            rid = None


def decode(payload):
    """(objID, name, typed value) for a property frame, else None."""
    if len(payload) < 10:
        return None
    ln = struct.unpack_from("<I", payload, 0)[0]
    body = payload[4:4 + ln] if ln <= len(payload) - 4 else payload[4:]
    if len(body) < 6 or body[:4] != b"\x01\x01\x01\x01":
        return None
    obj = body[4]
    end = body.find(b"\x00", 5)
    if end < 0:
        return None
    try:
        name = body[5:end].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not name or not name[0].islower():
        return None

    tail = body[end + 1:]
    value = None
    if len(tail) >= 3 and tail[0] == 0x01:
        n, p = tail[1], tail[2:]
        if n == 1 and p:
            value = {2: False, 3: True}.get(p[0], p[0])
        elif n == 9 and len(p) >= 9 and p[0] == 0x04:
            value = round(struct.unpack("<d", p[1:9])[0], 6)
        elif p and p[0] == 0x05:
            value = p[1:].split(b"\x00")[0].decode("ascii", "replace")
    return obj, name, value


def main():
    try:
        frames = list(parse_frames(LOG))
    except FileNotFoundError:
        sys.exit(f"no capture log at {LOG} - run the interposer first")

    by_obj = defaultdict(lambda: defaultdict(list))
    modes, skipped = [], 0
    for rid, payload in frames:
        if rid == 1:
            modes.append(payload[:1].hex())
            continue
        d = decode(payload)
        if not d:
            skipped += 1
            continue
        obj, name, value = d
        by_obj[obj][name].append(value)

    print(f"log      : {LOG}")
    print(f"frames   : {len(frames)}  decoded={sum(len(v) for o in by_obj.values() for v in o.values())}  unparsed={skipped}")
    if modes:
        print(f"reportID1: {sorted(set(modes))}  (4e='N' normal mode; 4d/55 are DANGEROUS)")
    print(f"objects  : {len(by_obj)}\n")

    for obj in sorted(by_obj):
        props = by_obj[obj]
        print(f"objID 0x{obj:02x}  ({len(props)} properties)")
        for name in sorted(props):
            vals = [v for v in props[name] if v is not None]
            uniq = sorted({repr(v) for v in vals})[:4]
            print(f"    {name:<26} {', '.join(uniq) if uniq else '-'}")
        print()

    if "--json" in sys.argv:
        out = {f"0x{o:02x}": {n: v for n, v in p.items()} for o, p in by_obj.items()}
        path = "objid_map.json"
        json.dump(out, open(path, "w"), indent=2, default=str)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
