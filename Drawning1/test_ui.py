# -*- coding: utf-8 -*-
"""Проверка интерфейса целиком: поля -> правка -> сохранение -> сборка -> превью."""
import json
import shutil
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, ".")
import ui  # noqa: E402

B = "http://127.0.0.1:8799"
srv = ThreadingHTTPServer(("127.0.0.1", 8799), ui.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(p):
    return urllib.request.urlopen(B + p, timeout=600).read()


def post(p, obj=None):
    d = json.dumps(obj or {}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        B + p, data=d, headers={"Content-Type": "application/json"}), timeout=600)
    return json.loads(r.read())


shutil.copy("parts.yaml", "/tmp/parts.orig")
try:
    print("1) GET /  ->", len(get("/")), "байт HTML")

    fields = json.loads(get("/api/fields"))["fields"]
    kinds = {}
    for f in fields:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    print("2) полей:", len(fields), kinds)

    # правка: диаметр хомутов 8 -> 10
    for f in fields:
        if f["path"] == "parts.hoops.bar.d":
            f["value"] = "10"
    print("3) save ->", post("/api/save", {"fields": fields}))
    src = open("parts.yaml", encoding="utf-8").read()
    print("   комментариев в yaml:", src.count("#"),
          "| нашли 'd: 10':", "d: 10, cls: А240" in src)

    r = post("/api/build")
    print("4) build ok =", r["ok"], "| файлов:", len(r["files"]))
    for line in r["log"].splitlines():
        if line.strip().startswith(("5 ", "9 ", "13 ")) or "прошли аудит" in line \
                or "НЕ ПРОЙДЕН" in line:
            print("   ", line.strip())

    png = get("/preview/" + r["files"][0])
    print("5) превью", r["files"][0], "->", len(png), "байт,",
          "PNG" if png[:4] == b"\x89PNG" else "НЕ PNG")
    print("6) download ->", len(get("/download/" + r["files"][0])), "байт")
    print("7) 404 ->", end=" ")
    try:
        get("/api/nope")
    except urllib.error.HTTPError as e:
        print(e.code)
finally:
    shutil.copy("/tmp/parts.orig", "parts.yaml")
    srv.shutdown()
    print("\nparts.yaml восстановлен")
