#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Peresborka payload vnutri kmd_app.py iz soderzhimogo kataloga kmd/.

Sravnivaetsya SODERZHIMOE faylov, a ne szhatye bayty: raznye versii zlib
dayut raznyy potok DEFLATE iz odnih i teh zhe dannyh, poetomu sborka na
Windows i na Ubuntu nikogda ne sovpala by pobaytno.
"""
import argparse
import base64
import hashlib
import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "kmd")
APP_FILE = os.path.join(ROOT, "kmd_app.py")

MARKER = 'PAYLOAD = """\\\n'
FENCE = '"""'
WRAP = 76
ZIP_DATE = (1980, 1, 1, 0, 0, 0)

SKIP_DIRS = {"__pycache__", ".pytest_cache", "out", ".git"}
SKIP_EXT = {".pyc", ".pyo", ".pyd", ".dxf", ".log"}
SKIP_NAMES = {".DS_Store", "parts.yaml.bak"}


def collect():
    found = []
    for base, dirs, files in os.walk(SRC_DIR):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name in SKIP_NAMES:
                continue
            if os.path.splitext(name)[1] in SKIP_EXT:
                continue
            full = os.path.join(base, name)
            found.append((os.path.relpath(full, SRC_DIR).replace(os.sep, "/"),
                          full))
    return sorted(found)


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, full in files:
            info = zipfile.ZipInfo(rel, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(full, "rb") as f:
                z.writestr(info, f.read())
    return buf.getvalue()


def encode(blob):
    raw = base64.b64encode(blob).decode("ascii")
    return "\n".join(raw[i:i + WRAP] for i in range(0, len(raw), WRAP))


def split_app():
    with open(APP_FILE, encoding="utf-8") as f:
        text = f.read()
    start = text.find(MARKER)
    if start < 0:
        sys.exit("V kmd_app.py ne nayden marker PAYLOAD")
    body = start + len(MARKER)
    end = text.find(FENCE, body)
    if end < 0:
        sys.exit("Ne naydeno zakrytie bloka PAYLOAD")
    return text[:body], text[body:end], text[end:]


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def disk_state(files):
    state = {}
    for rel, full in files:
        with open(full, "rb") as f:
            state[rel] = sha(f.read())
    return state


def payload_state(current):
    data = base64.b64decode("".join(current.split()))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: sha(z.read(n)) for n in z.namelist()}


def state_digest(state):
    joined = "".join(k + state[k] for k in sorted(state))
    return sha(joined.encode("ascii"))[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    files = collect()
    head, current, tail = split_app()

    want = disk_state(files)
    digest = state_digest(want)
    try:
        have = payload_state(current)
    except Exception:
        have = {}
        print("payload ne chitaetsya", file=sys.stderr)

    if have == want:
        print("payload sinhronen: %d faylov, sha %s" % (len(files), digest))
        return 0

    if args.check:
        print("payload razoshelsya s katalogom kmd/", file=sys.stderr)
        for name in sorted(set(want) - set(have)):
            print("  net v bandle:     %s" % name, file=sys.stderr)
        for name in sorted(set(have) - set(want)):
            print("  lishnee v bandle: %s" % name, file=sys.stderr)
        for name in sorted(set(want) & set(have)):
            if want[name] != have[name]:
                print("  ustarelo:         %s" % name, file=sys.stderr)
        print("\n  pochinite: python tools/build_bundle.py", file=sys.stderr)
        return 1

    payload = encode(make_zip(files)) + "\n"
    with open(APP_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + payload + tail)
    print("kmd_app.py peresobran: %d faylov, sha %s" % (len(files), digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())