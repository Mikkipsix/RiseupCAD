# -*- coding: utf-8 -*-
"""Сквозная проверка интерфейса: параметры, сборка, распознавание."""
import base64
import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, ".")
import ui  # noqa: E402

B = "http://127.0.0.1:8799"
srv = ThreadingHTTPServer(("127.0.0.1", 8799), ui.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

get = lambda p: urllib.request.urlopen(B + p, timeout=900).read()


def post(p, obj=None):
    d = json.dumps(obj or {}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        B + p, data=d, headers={"Content-Type": "application/json"}),
        timeout=900)
    return json.loads(r.read())


SAMPLE = sys.argv[1] if len(sys.argv) > 1 else None
shutil.copy("parts.yaml", "/tmp/parts.orig")
try:
    print("1) страница:", len(get("/")), "байт")

    doc = json.loads(get("/api/doctor"))["rows"]
    miss = [r["name"] for r in doc if not r["ok"]]
    print("2) окружение: не установлено ->", miss or "всё на месте")

    d = json.loads(get("/api/fields"))
    kinds = {}
    for f in d["fields"]:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    print(f'3) параметры: {len(d["fields"])} полей {kinds}, '
          f'бэкенд yaml = {d["backend"]}')

    for f in d["fields"]:
        if f["path"] == "parts.hoops.bar.d":
            f["value"] = "10"
    save = post("/api/save", {"fields": d["fields"]})
    print("4) сохранение:", save)
    if not save.get("ok"):
        raise AssertionError(f"UI save failed: {save}")
    src = open("parts.yaml", encoding="utf-8").read()
    print("   комментариев:", src.count("#"), "| d=10 записан:",
          "d: 10, cls: А240" in src)

    r = post("/api/build")
    print("5) сборка ok =", r["ok"], "| файлов:", len(r["files"]))
    if not r.get("ok"):
        raise AssertionError(f"UI build failed: {r}")
    for ln in r["log"].splitlines():
        if "!!" in ln or "прошли аудит" in ln or "НЕ ПРОЙДЕН" in ln:
            print("    ", ln.strip())

    png = get("/preview/" + r["files"][0])
    print("6) превью:", len(png), "байт,",
          "PNG" if png[:4] == b"\x89PNG" else "НЕ PNG")
    if png[:4] != b"\x89PNG":
        raise AssertionError("UI preview is not a PNG")

    if SAMPLE:
        data = "data:image/png;base64," + base64.b64encode(
            open(SAMPLE, "rb").read()).decode()
        rr = post("/api/recognize", {"name": SAMPLE.split("/")[-1],
                                     "data": data})
        if not rr.get("ok"):
            print("7) распознавание: ОШИБКА\n", rr.get("error"))
            raise AssertionError(f"UI recognition failed: {rr.get('error')}")
        print("7) распознавание:")
        for ln in rr["summary"].splitlines():
            print("    ", ln)
        print("    вариантов калибровки:", len(rr["options"]))
        ov = get("/recog/%s.png" % rr["token"])
        dxf = get("/recog/%s.dxf" % rr["token"])
        print("8) наложение:", len(ov), "байт | DXF:", len(dxf), "байт,",
              "секция ENTITIES есть" if b"ENTITIES" in dxf else "БИТЫЙ")
        if ov[:4] != b"\x89PNG":
            raise AssertionError("Recognition overlay is not a PNG")
        if b"ENTITIES" not in dxf:
            raise AssertionError("Recognition DXF has no ENTITIES section")
        if rr["options"]:
            o = rr["options"][0]
            r2 = post("/api/recognize", {"token": rr["token"],
                                         "scale": o["scale"]})
            if not r2.get("ok"):
                raise AssertionError(f"UI recalculation failed: {r2}")
            print(f'9) пересчёт по размеру {o["value"]}: масштаб '
                  f'{r2["scale"]} мм/px')
    print("10) 404:", end=" ")
    try:
        get("/api/nope")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        print(e.code)
    else:
        raise AssertionError("/api/nope unexpectedly returned 200")
finally:
    shutil.copy("/tmp/parts.orig", "parts.yaml")
    srv.shutdown()
    print("\nparts.yaml восстановлен")
