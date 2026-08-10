#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальный интерфейс: сборка комплекта из parts.yaml и распознавание
растровых чертежей (изображение или PDF) в DXF.

    python3 ui.py

Слушает только 127.0.0.1. Ничего не отправляет наружу.
"""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
YAML_PATH = os.path.join(ROOT, "parts.yaml")
OUT = os.path.join(ROOT, "out")
HOST, PORT = "127.0.0.1", 8765

sys.path.insert(0, ROOT)

_preview = {}
_jobs = {}
TMP = os.path.join(tempfile.gettempdir(), "kmd_ui")
os.makedirs(TMP, exist_ok=True)


# =====================================================================
#  Самодиагностика окружения
# =====================================================================
def doctor():
    rows = []

    def probe(mod, need, why, pip=None):
        try:
            m = __import__(mod)
            rows.append({"name": mod, "ok": True, "need": need, "why": why,
                         "info": str(getattr(m, "__version__", ""))})
        except Exception:
            rows.append({"name": mod, "ok": False, "need": need, "why": why,
                         "info": f"pip install {pip or mod}"})

    probe("ezdxf", True, "запись DXF")
    probe("yaml", True, "чтение parts.yaml", "pyyaml")
    probe("matplotlib", False, "превью чертежей")
    probe("ruamel.yaml", False, "сохранение комментариев в parts.yaml",
          "ruamel.yaml")
    probe("cv2", False, "распознавание растра", "opencv-python-headless")
    probe("numpy", False, "распознавание растра")
    probe("pypdfium2", False, "чтение PDF")
    probe("pytesseract", False, "чтение чисел с чертежа")
    exe = shutil.which("tesseract")
    if not exe:
        for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.isfile(c):
                exe = c
                break
    if exe:
        rows.append({"name": "tesseract (движок OCR)", "ok": True,
                     "need": False, "why": "чтение чисел с чертежа",
                     "info": exe})
    else:
        rows.append({"name": "tesseract (движок OCR)", "ok": False,
                     "need": False,
                     "why": "чтение чисел; без него геометрия распознаётся, "
                            "а масштаб задаётся вручную",
                     "info": "Это отдельная программа, не пакет Python. "
                             "Windows: скачать установщик Tesseract-OCR "
                             "(сборка UB Mannheim) и поставить в папку по "
                             "умолчанию. Linux: sudo apt install tesseract-ocr"})
    return rows


PIP_FOR = {
    "ezdxf": "ezdxf", "yaml": "pyyaml", "matplotlib": "matplotlib",
    "ruamel.yaml": "ruamel.yaml", "cv2": "opencv-python-headless",
    "numpy": "numpy", "pypdfium2": "pypdfium2", "pytesseract": "pytesseract",
    "PIL": "pillow",
}


def missing_pips():
    """Список пакетов pip, которых не хватает."""
    out = []
    for row in doctor():
        if not row["ok"] and row["name"] in PIP_FOR:
            out.append(PIP_FOR[row["name"]])
    if "pillow" not in out:
        try:
            __import__("PIL")
        except Exception:
            out.append("pillow")
    return out


PROXY_VARS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy", "FTP_PROXY", "ftp_proxy")


VENDOR = os.path.join(ROOT, "vendor")


def _pip_env(mode):
    """as-is - как есть; strip - убрать прокси; bypass - обойти любой прокси;
    socks - оставить прокси, но подложить встроенный PySocks.

    Режим bypass нужен, когда прокси задан не переменными окружения, а в
    настройках Windows или в pip.ini: снятие переменных там не помогает.
    Python обходит прокси при no_proxy='*', но только если в окружении
    вообще есть прокси, поэтому подставляется заглушка.

    Режим socks - для случая, когда прокси socks5:// действительно нужен
    для выхода в сеть. Скачать PySocks через сломанный pip нельзя, он
    лежит в комплекте и подкладывается в PYTHONPATH.
    """
    env = dict(os.environ)
    if mode in ("strip", "bypass"):
        for v in PROXY_VARS:
            env.pop(v, None)
    if mode == "bypass":
        env["http_proxy"] = env["HTTP_PROXY"] = "http://127.0.0.1:1"
        env["no_proxy"] = env["NO_PROXY"] = "*"
    if mode == "socks" and os.path.isdir(VENDOR):
        old = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = VENDOR + (os.pathsep + old if old else "")
    return env


def _pip_run(pkgs, extra=(), mode="as-is", timeout=1800):
    cmd = [sys.executable, "-m", "pip", "install", *extra, *pkgs]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           env=_pip_env(mode), timeout=timeout,
                           errors="replace")
        return p.returncode == 0, "> " + " ".join(cmd) + "\n" + p.stdout + p.stderr
    except Exception as e:
        return False, f'> {" ".join(cmd)}\n{type(e).__name__}: {e}\n'


ATTEMPTS = (
    ("обычная установка", (), "as-is"),
    ("через встроенный PySocks", (), "socks"),
    ("через встроенный PySocks, в профиль", ("--user",), "socks"),
    ("в профиль пользователя", ("--user",), "as-is"),
    ("без переменных прокси", (), "strip"),
    ("без переменных прокси, в профиль", ("--user",), "strip"),
    ("в обход настроек pip.ini", ("--isolated",), "strip"),
    ("в обход любого прокси", (), "bypass"),
    ("в обход прокси, в профиль", ("--user",), "bypass"),
    ("в обход прокси и настроек pip", ("--isolated",), "bypass"),
)


def pip_install(pkgs):
    """Ставит пакеты, перебирая способы обхода типичных препятствий.

    Самая частая беда на Windows - прокси socks5://, для которого не
    установлен PySocks: pip падает с «Missing dependencies for SOCKS
    support» ещё до обращения к сети. Прокси при этом может быть задан
    переменной окружения, настройками Windows или файлом pip.ini -
    перебираются все три случая.
    """
    if not pkgs:
        return {"ok": True, "log": "Всё уже установлено."}
    log = ""
    socks_tried = False
    for title, extra, mode in ATTEMPTS:
        log += f"\n=== {title} ===\n"
        ok, out = _pip_run(pkgs, extra, mode)
        log += out
        if ok:
            if mode == "socks":
                # закрепляем PySocks в окружении, чтобы дальше pip работал
                # через прокси сам, без подкладывания встроенной копии
                ok2, out2 = _pip_run(["PySocks"], extra, "socks")
                log += "\n=== закрепление PySocks в окружении ===\n" + out2
            return {"ok": True, "log": log}
        if "SOCKS" in out and not socks_tried and mode == "bypass":
            socks_tried = True
            log += "\n=== доустановка PySocks в обход прокси ===\n"
            ok2, out2 = _pip_run(["PySocks"], mode="bypass")
            log += out2
            if ok2:
                ok3, out3 = _pip_run(pkgs)
                log += "\n=== повтор основной установки ===\n" + out3
                if ok3:
                    return {"ok": True, "log": log}
    log += _diagnose(log, pkgs)
    return {"ok": False, "log": log}


TESS_URL = ("https://github.com/UB-Mannheim/tesseract/wiki")


def install_tesseract():
    """Ставит движок OCR штатным менеджером пакетов системы.

    Сам файл не скачивается: на Windows это делает winget, на Linux -
    apt, на macOS - brew. Если менеджера нет, возвращается ссылка на
    установщик.
    """
    if shutil.which("tesseract"):
        return {"ok": True, "log": "Движок уже установлен."}
    cmds = []
    if os.name == "nt":
        if shutil.which("winget"):
            cmds.append([shutil.which("winget"), "install", "--id",
                         "UB-Mannheim.TesseractOCR", "-e",
                         "--accept-package-agreements",
                         "--accept-source-agreements"])
        if shutil.which("choco"):
            cmds.append([shutil.which("choco"), "install", "tesseract", "-y"])
    elif sys.platform == "darwin":
        if shutil.which("brew"):
            cmds.append([shutil.which("brew"), "install", "tesseract"])
    else:
        if shutil.which("apt-get"):
            cmds.append(["sudo", "apt-get", "install", "-y", "tesseract-ocr"])
    if not cmds:
        return {"ok": False, "log":
                "Автоматически поставить нечем: не найден winget, choco, "
                "brew или apt.\n\nСкачайте установщик вручную:\n    "
                + TESS_URL +
                "\n\nСтавьте в папку по умолчанию - программа найдёт движок "
                "сама, прописывать PATH не нужно."}
    log = ""
    for cmd in cmds:
        log += "> " + " ".join(cmd) + "\n"
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=1800, errors="replace")
            log += p.stdout + p.stderr
            if p.returncode == 0:
                return {"ok": True, "log": log +
                        "\n\nГотово. Перезапустите программу."}
        except Exception as e:
            log += f"{type(e).__name__}: {e}\n"
    return {"ok": False, "log": log + "\n\nНе вышло. Установщик вручную:\n    "
            + TESS_URL}


def _diagnose(log, pkgs):
    py = f'"{sys.executable}"'
    cmd = f"{py} -m pip install " + " ".join(pkgs)
    tips = ["\n" + "=" * 62, "Установить не удалось. Что делать:"]
    if "SOCKS" in log:
        tips += [
            "",
            "Прокси socks5:// задан не переменной окружения, а глубже -",
            "в настройках Windows или в файле pip.ini. Варианты:",
            "",
            "1) Поставить PySocks, тогда прокси заработает как надо:",
            f"    {py} -m pip install PySocks --proxy \"\"",
            "",
            "2) Обойти прокси на время установки:",
            "    set NO_PROXY=*",
            "    set HTTP_PROXY=http://127.0.0.1:1",
            f"    {cmd}",
            "",
            "3) Найти и убрать прокси в самом pip:",
            f"    {py} -m pip config list",
            f"    {py} -m pip config unset global.proxy",
            "",
            "4) Отключить прокси в Windows: Параметры - Сеть и Интернет -",
            "   Прокси-сервер, снять «Использовать прокси-сервер».",
        ]
    elif "SSL" in log or "CERTIFICATE" in log.upper():
        tips += ["", "Соединение режет антивирус или шлюз. Попробуйте:", "",
                 f"    {cmd} --trusted-host pypi.org "
                 "--trusted-host files.pythonhosted.org"]
    else:
        tips += ["", "Выполните вручную и посмотрите текст ошибки:", "",
                 f"    {cmd}"]
    tips += ["", "Если сети нет совсем: на машине с интернетом выполните",
             f'    pip download {" ".join(pkgs)} -d wheels',
             "перенесите папку wheels сюда и выполните",
             f"    {cmd} --no-index --find-links wheels"]
    return "\n".join(tips) + "\n"


# =====================================================================
#  YAML: ruamel сохраняет комментарии, PyYAML - запасной вариант
# =====================================================================
def _ruamel():
    from ruamel.yaml import YAML
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def yaml_backend():
    try:
        import ruamel.yaml  # noqa: F401  # проверка наличия
        return "ruamel"
    except Exception:
        return "pyyaml"


def load_yaml():
    if yaml_backend() == "ruamel":
        with open(YAML_PATH, encoding="utf-8") as f:
            return _ruamel().load(f)
    import yaml
    with open(YAML_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(data):
    shutil.copy(YAML_PATH, YAML_PATH + ".bak")
    if yaml_backend() == "ruamel":
        buf = io.StringIO()
        _ruamel().dump(data, buf)
        text = buf.getvalue()
    else:
        import yaml
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    with open(YAML_PATH, "w", encoding="utf-8") as f:
        f.write(text)


SKIP_KEYS = {"mass_ref", "length_ref"}


def flatten(node, path=()):
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in SKIP_KEYS:
                continue
            out += flatten(v, path + (str(k),))
    elif isinstance(node, list):
        if node and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                        for x in node):
            out.append((".".join(path), ", ".join(str(x) for x in node), "list"))
        else:
            for i, v in enumerate(node):
                out += flatten(v, path + (str(i),))
    else:
        if isinstance(node, bool):
            kind = "bool"
        elif isinstance(node, (int, float)):
            kind = "num"
        else:
            kind = "str"
        out.append((".".join(path), node, kind))
    return out


def set_path(data, dotted, raw, kind):
    keys = dotted.split(".")
    node = data
    for k in keys[:-1]:
        node = node[int(k)] if isinstance(node, list) else node[_key(node, k)]
    last = keys[-1]
    if kind == "list":
        val = [_num(x) for x in str(raw).split(",") if x.strip()]
    elif kind == "bool":
        val = str(raw).strip().lower() in ("true", "1", "да", "yes", "on")
    elif kind == "num":
        val = _num(raw)
    else:
        val = raw
    if isinstance(node, list):
        node[int(last)] = val
    else:
        node[_key(node, last)] = val


def _key(node, k):
    if k in node:
        return k
    try:
        ik = int(k)
        if ik in node:
            return ik
    except ValueError:
        pass
    return k


def _num(x):
    f = float(str(x).strip().replace(",", "."))
    return int(f) if f.is_integer() else f


# =====================================================================
#  Сборка комплекта
# =====================================================================
def run_build():
    p = subprocess.run([sys.executable, "build.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    log = p.stdout + (("\n" + p.stderr) if p.stderr.strip() else "")
    files = sorted(f for f in os.listdir(OUT)) if os.path.isdir(OUT) else []
    return {"ok": p.returncode == 0, "log": log,
            "files": [f for f in files if f.endswith(".dxf")]}


def render_png(name):
    path = os.path.join(OUT, name)
    mt = os.path.getmtime(path)
    if _preview.get(name, (None,))[0] == mt:
        return _preview[name][1]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import ezdxf
    import ezdxf.bbox
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    bb = ezdxf.bbox.extents(msp, fast=False)
    w = max(bb.extmax.x - bb.extmin.x, 1.0)
    h = max(bb.extmax.y - bb.extmin.y, 1.0)
    k = 7.5 / max(w, h)
    fig = plt.figure(figsize=(max(w * k, 2.2), max(h * k, 2.2)))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("#11161d")
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(
        msp, finalize=True)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor="#11161d")
    plt.close(fig)
    _preview[name] = (mt, buf.getvalue())
    return _preview[name][1]


# =====================================================================
#  Распознавание
# =====================================================================
MISSING_MSG = """Для распознавания не хватает библиотек: {names}

Откройте вкладку «Окружение» и нажмите «Установить недостающее».
Если установка не проходит, там же напечатаны команды для ручной
установки."""


def _render_dxf(path):
    """Картинка построенного DXF - чтобы результат было видно сразу."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import ezdxf
        import ezdxf.bbox
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        bb = ezdxf.bbox.extents(msp, fast=False)
        w = max(bb.extmax.x - bb.extmin.x, 1.0)
        h = max(bb.extmax.y - bb.extmin.y, 1.0)
        k = 8.0 / max(w, h)
        fig = plt.figure(figsize=(max(w * k, 2.5), max(h * k, 2.5)))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor("#11161d")
        Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(
            msp, finalize=True)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, facecolor="#11161d")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return b""


def recognize(body):
    try:
        from vector import raster
    except ImportError as e:
        need = [r["name"] for r in doctor()
                if not r["ok"] and r["name"] in ("cv2", "numpy", "PIL",
                                                 "pypdfium2", "ezdxf")]
        return {"ok": False,
                "error": MISSING_MSG.format(names=", ".join(need) or str(e))}

    token = body.get("token")
    if token and token in _jobs and not body.get("data"):
        src = _jobs[token]["src"]              # пересчёт без повторной загрузки
    else:
        token = uuid.uuid4().hex[:12]
        name = os.path.basename(body.get("name") or "page.png")
        src = os.path.join(TMP, token + "_" + name)
        with open(src, "wb") as f:
            f.write(base64.b64decode(body["data"].split(",")[-1]))

    res = raster.vectorize(
        src,
        dpi=int(body.get("dpi") or 200),
        page=int(body.get("page") or 0),
        min_len=int(body.get("min_len") or 25),
        do_ocr=bool(body.get("ocr", True)),
        scale_override=float(body["scale"]) if body.get("scale") else None,
    )
    dxf = os.path.join(TMP, token + ".dxf")
    raster.to_dxf(res, dxf, put_text=bool(body.get("with_text", True)))
    _jobs[token] = {"src": src, "dxf": dxf, "png": raster.overlay_png(res),
                    "dxfpng": _render_dxf(dxf)}

    return {"ok": True, "token": token, "summary": raster.summary(res),
            "options": res["options"], "lines": res.get("line_options", []),
            "scale": round(res["scale"], 5),
            "pages": raster.page_count(src), "has_ocr": raster.HAS_OCR}


# =====================================================================
#  HTML
# =====================================================================
PAGE = r"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>КМД: сборка и распознавание</title>
<style>
:root{--bg:#11161d;--panel:#1a212b;--line:#2b3542;--fg:#dfe6ee;--dim:#8fa0b3;
      --acc:#4ea3ff;--ok:#4cc38a;--err:#ff6b6b;--warn:#e6b34a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.45 "Segoe UI",system-ui,sans-serif}
header{padding:10px 18px;border-bottom:1px solid var(--line);
       display:flex;align-items:center;gap:10px;flex-wrap:wrap}
h1{font-size:15px;margin:0 14px 0 0;font-weight:600}
.tab{background:transparent;border:1px solid var(--line);color:var(--dim);
     padding:6px 14px;border-radius:5px;cursor:pointer;font-size:13px}
.tab.on{background:var(--panel);color:var(--fg);border-color:var(--acc)}
button.go{background:var(--acc);color:#08101a;border:0;border-radius:5px;
          padding:7px 15px;font-weight:600;cursor:pointer;font-size:13px}
button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line);
             border-radius:5px;padding:7px 14px;cursor:pointer;font-size:13px}
.wrap{display:grid;grid-template-columns:400px 1fr;height:calc(100vh - 53px)}
.pane{overflow:auto;padding:16px 18px}
.pane+.pane{border-left:1px solid var(--line)}
h2{font-size:11px;text-transform:uppercase;letter-spacing:.09em;
   color:var(--dim);margin:18px 0 8px;font-weight:600}
h2:first-child{margin-top:0}
.grp{background:var(--panel);border:1px solid var(--line);border-radius:6px;
     padding:10px 12px;margin-bottom:10px}
.grp>.t{color:var(--acc);font-weight:600;margin-bottom:7px;font-size:13px}
.f{display:grid;grid-template-columns:1fr 120px;gap:6px;align-items:center;
   margin:3px 0}
.f label{color:var(--dim);font-size:12px;overflow-wrap:anywhere}
input,select{background:#0d1218;border:1px solid var(--line);color:var(--fg);
   border-radius:4px;padding:5px 7px;font:13px ui-monospace,monospace;width:100%}
input[type=checkbox]{width:auto}
pre{background:#0d1218;border:1px solid var(--line);border-radius:6px;
    padding:12px;overflow:auto;font:12px/1.5 ui-monospace,monospace;
    white-space:pre;margin:0}
.badge{padding:3px 10px;border-radius:4px;font-size:12px;font-weight:600}
.b-ok{background:rgba(76,195,138,.15);color:var(--ok)}
.b-err{background:rgba(255,107,107,.15);color:var(--err)}
.b-run{background:rgba(78,163,255,.15);color:var(--acc)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
       gap:12px;margin-top:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;
      padding:9px;text-align:center}
.card img{width:100%;background:#11161d;border-radius:4px;cursor:zoom-in}
.card .n{font-size:11px;color:var(--dim);margin:6px 0}
a{color:var(--acc);text-decoration:none;font-size:12px}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.88);display:none;
       align-items:center;justify-content:center;z-index:9;cursor:zoom-out}
#modal img{max-width:96vw;max-height:96vh}
.dz{border:1px dashed var(--line);border-radius:8px;padding:26px 14px;
    text-align:center;color:var(--dim);cursor:pointer;background:var(--panel)}
.dz.hot{border-color:var(--acc);color:var(--fg)}
table.doc{width:100%;border-collapse:collapse;font-size:12px}
table.doc td{padding:4px 6px;border-bottom:1px solid var(--line);
             vertical-align:top}
.hint{color:var(--dim);font-size:12px;margin:6px 0 0}
.ovwrap img{width:100%;border:1px solid var(--line);border-radius:6px;
            cursor:zoom-in;background:#fff}
</style>
<header>
  <h1>КМД</h1>
  <button class="tab on" data-t="build">Сборка комплекта</button>
  <button class="tab" data-t="recog">Распознавание чертежа</button>
  <button class="tab" data-t="doc">Окружение</button>
  <span style="flex:1"></span>
  <span id="st"></span>
</header>

<div class="wrap" id="v-build">
  <div class="pane">
    <div style="display:flex;gap:8px;margin-bottom:14px">
      <button class="go" id="go">Собрать</button>
      <button class="ghost" id="save">Сохранить</button>
    </div>
    <h2>Параметры изделия</h2>
    <div id="form"><span class="hint">загрузка…</span></div>
  </div>
  <div class="pane">
    <h2>Отчёт сборки</h2>
    <pre id="log">Нажмите «Собрать».</pre>
    <h2>Чертежи</h2>
    <div class="cards" id="cards"></div>
  </div>
</div>

<div class="wrap" id="v-recog" style="display:none">
  <div class="pane">
    <h2>Исходный чертёж</h2>
    <div class="dz" id="dz">Перетащите сюда PNG, JPG или PDF<br>
      <span style="font-size:12px">или нажмите для выбора файла</span></div>
    <input type="file" id="file" accept=".png,.jpg,.jpeg,.tif,.tiff,.bmp,.pdf"
           style="display:none">
    <div class="grp" style="margin-top:12px">
      <div class="t">Разбор</div>
      <div class="f"><label>DPI для PDF</label><input id="dpi" value="200"></div>
      <div class="f"><label>страница PDF (с 0)</label><input id="page" value="0"></div>
      <div class="f"><label>мин. длина линии, px</label><input id="minlen" value="25"></div>
      <div class="f"><label>читать числа (OCR)</label>
        <input type="checkbox" id="ocr" checked></div>
      <div class="f"><label>переносить числа в DXF</label>
        <input type="checkbox" id="wtext" checked></div>
    </div>
    <div class="grp">
      <div class="t">Масштаб</div>
      <div class="f"><label>калибровать по размеру</label>
        <select id="opt"><option value="">— автоподбор —</option></select></div>
      <div class="f"><label>калибровать по линии</label>
        <select id="lineopt"><option value="">— не выбрана —</option></select></div>
      <div class="f"><label>её длина, мм</label>
        <input id="linemm" placeholder="напр. 300"></div>
      <div class="f"><label>мм на пиксель</label>
        <input id="scale" placeholder="авто"></div>
      <p class="hint">Автоподбор ищет кластер одинаковых отношений
        «значение размера / расстояние между выносными линиями». Если он
        ошибся, выберите заведомо верный размер из списка.<br><br>
        Без движка OCR числа не читаются. Тогда выберите линию, длину
        которой знаете, и впишите её в миллиметрах — масштаб посчитается
        по ней.</p>
    </div>
    <button class="go" id="rgo" style="width:100%">Распознать</button>
    <div id="dl" style="margin-top:12px"></div>
  </div>
  <div class="pane">
    <h2>Построенный чертёж</h2>
    <div class="ovwrap" id="dxfview"><span class="hint">Здесь появится
      готовый DXF после распознавания.</span></div>
    <h2>Что распознано на исходнике</h2>
    <div class="ovwrap" id="ov"><span class="hint">Загрузите файл.</span></div>
    <h2>Отчёт</h2>
    <pre id="rlog">—</pre>
  </div>
</div>

<div class="wrap" id="v-doc" style="display:none;grid-template-columns:1fr">
  <div class="pane"><h2>Проверка окружения</h2>
    <div id="warn" style="display:none;background:rgba(255,107,107,.12);
         border:1px solid var(--err);border-radius:6px;padding:12px 14px;
         margin-bottom:14px">
      <b style="color:var(--err)">Библиотеки не установлены</b><br>
      <span class="hint" style="margin:0">Без них не работают ни сборка
      комплекта, ни распознавание. Нажмите кнопку ниже.</span>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center">
      <button class="go" id="inst">Установить пакеты Python</button>
      <button class="ghost" id="instt">Установить движок OCR</button>
      <span class="hint" style="margin:0">Первая кнопка ставит библиотеки
        Python, вторая - движок tesseract через менеджер пакетов системы.</span>
    </div>
    <pre id="ilog" style="display:none;margin-bottom:12px"></pre>
    <table class="doc" id="doctbl"></table>
    <p class="hint">Обязательные компоненты помечены как «НУЖЕН». Остальные
      расширяют возможности: без matplotlib не будет превью, без OpenCV и
      tesseract не работает распознавание.</p>
  </div>
</div>

<div id="modal"><img id="mimg"></div>
<script>
const $=s=>document.querySelector(s), st=$('#st');
function badge(c,t){st.innerHTML='<span class="badge '+c+'">'+t+'</span>'}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  ['build','recog','doc'].forEach(t=>
    $('#v-'+t).style.display = t===b.dataset.t ? 'grid':'none');
});
function zoom(src){$('#mimg').src=src;$('#modal').style.display='flex'}
$('#modal').onclick=e=>e.currentTarget.style.display='none';

function drawDoc(rows){
  $('#doctbl').innerHTML=rows.map(r=>
    '<tr><td style="color:'+(r.ok?'var(--ok)':(r.need?'var(--err)':'var(--warn)'))+
    '">'+(r.ok?'есть':(r.need?'НУЖЕН':'нет'))+'</td><td><b>'+r.name+
    '</b></td><td style="color:var(--dim)">'+r.why+'</td><td><code>'+
    (r.info||'')+'</code></td></tr>').join('');
  const bad=rows.filter(r=>!r.ok&&r.need);
  const opt=rows.filter(r=>!r.ok&&!r.need);
  const w=$('#warn');
  if(bad.length){
    w.style.display='block';
    w.style.borderColor='var(--err)';
    w.style.background='rgba(255,107,107,.12)';
    w.innerHTML='<b style="color:var(--err)">Не установлены обязательные '+
      'библиотеки: '+bad.map(r=>r.name).join(', ')+'</b><br>'+
      '<span class="hint" style="margin:0">Без них не работают ни сборка '+
      'комплекта, ни распознавание. Нажмите кнопку ниже.</span>';
    badge('b-err','не установлено: '+bad.map(r=>r.name).join(', '));
    if(!window.__jumped){window.__jumped=1;
      document.querySelector('.tab[data-t="doc"]').click();}
  } else if(opt.length){
    w.style.display='block';
    w.style.borderColor='var(--warn)';
    w.style.background='rgba(230,179,74,.10)';
    w.innerHTML='<b style="color:var(--warn)">Всё основное установлено</b>'+
      '<br><span class="hint" style="margin:0">Не хватает только: '+
      opt.map(r=>r.name).join(', ')+'. Программа работает, но с '+
      'ограничением — смотрите столбец с пояснением.</span>';
    badge('b-ok','готово, есть необязательные пропуски');
  } else {
    w.style.display='none';
    badge('b-ok','окружение готово');
  }
}
fetch('/api/doctor').then(r=>r.json()).then(d=>drawDoc(d.rows));
$('#instt').onclick=async()=>{
  badge('b-run','ставлю движок OCR…');
  const box=$('#ilog');box.style.display='block';
  box.textContent='Идёт установка движка, это может занять несколько минут…';
  const r=await (await fetch('/api/tesseract',{method:'POST'})).json();
  box.textContent=r.log; drawDoc(r.rows);
  badge(r.ok?'b-ok':'b-err', r.ok?'движок установлен — перезапустите':'не вышло');
};
$('#inst').onclick=async()=>{
  badge('b-run','установка…');
  const box=$('#ilog');box.style.display='block';
  box.textContent='Идёт установка, это может занять пару минут…';
  const r=await (await fetch('/api/install',{method:'POST'})).json();
  box.textContent=r.log;
  drawDoc(r.rows);
  if(r.ok && r.installed){
    badge('b-ok','установлено — перезапустите программу');
    box.textContent+='\n\nГотово. Закройте окно консоли и запустите заново.';
  } else if(r.ok){
    badge('b-ok','ставить было нечего');
    box.textContent='Все пакеты Python уже установлены.\n\n'+
      'Если в таблице ниже что-то помечено как отсутствующее — это не '+
      'пакет Python, а отдельная программа. Её кнопка не ставит, '+
      'смотрите пояснение в строке.';
  } else badge('b-err','установка не удалась');
};

let FIELDS=[];
const grp=p=>{const a=p.split('.');
  return a[0]==='parts'?(a[1]==='hoops'?'поз.5…12 (хомуты)':'поз.'+a[1]):a[0]};
const shortn=p=>{const a=p.split('.');
  return (a[0]==='parts'?a.slice(2):a.slice(1)).join('.')||p};
fetch('/api/fields').then(r=>r.json()).then(d=>{
  if(d.error){$('#form').innerHTML='<pre>'+d.error+'</pre>';return}
  FIELDS=d.fields;const box=$('#form');box.innerHTML='';const seen={};
  FIELDS.forEach((f,i)=>{const g=grp(f.path);
    if(!seen[g]){const v=document.createElement('div');v.className='grp';
      v.innerHTML='<div class="t">'+g+'</div>';box.appendChild(v);seen[g]=v}
    const row=document.createElement('div');row.className='f';
    row.innerHTML='<label title="'+f.path+'">'+shortn(f.path)+'</label>';
    const inp=document.createElement('input');inp.value=f.value;inp.dataset.i=i;
    seen[g].appendChild(row);row.appendChild(inp);});
  if(d.backend!=='ruamel')
    badge('b-run','ruamel не установлен: комментарии в parts.yaml не сохранятся');
});
const collect=()=>[...document.querySelectorAll('#form input')].map(i=>
  ({path:FIELDS[i.dataset.i].path,kind:FIELDS[i.dataset.i].kind,value:i.value}));
async function save(){badge('b-run','сохранение…');
  const r=await (await fetch('/api/save',{method:'POST',
    body:JSON.stringify({fields:collect()})})).json();
  badge(r.ok?'b-ok':'b-err',r.ok?'сохранено':'ошибка');
  if(!r.ok)$('#log').textContent=r.error;return r.ok}
$('#save').onclick=save;
$('#go').onclick=async()=>{ if(!await save())return;
  badge('b-run','сборка…');$('#log').textContent='Идёт расчёт и аудит…';
  const r=await (await fetch('/api/build',{method:'POST'})).json();
  $('#log').textContent=r.log||r.error||'';
  badge(r.ok?'b-ok':'b-err',r.ok?'аудит пройден':'аудит не пройден');
  const c=$('#cards');c.innerHTML='';const t=Date.now();
  (r.files||[]).forEach(f=>{const d=document.createElement('div');d.className='card';
    d.innerHTML='<img src="/preview/'+f+'?t='+t+'"><div class="n">'+f+
      '</div><a href="/download/'+f+'" download>скачать DXF</a>';
    d.querySelector('img').onclick=e=>zoom(e.target.src);c.appendChild(d)});};

let FILE=null,TOKEN=null;
const dz=$('#dz');
dz.onclick=()=>$('#file').click();
dz.ondragover=e=>{e.preventDefault();dz.classList.add('hot')};
dz.ondragleave=()=>dz.classList.remove('hot');
dz.ondrop=e=>{e.preventDefault();dz.classList.remove('hot');
              pick(e.dataTransfer.files[0])};
$('#file').onchange=e=>pick(e.target.files[0]);
function pick(f){if(!f)return;FILE=f;TOKEN=null;
  dz.innerHTML='<b>'+f.name+'</b><br><span style="font-size:12px">'+
    Math.round(f.size/1024)+' КБ — нажмите «Распознать»</span>'}

$('#rgo').onclick=async()=>{
  if(!FILE&&!TOKEN){badge('b-err','файл не выбран');return}
  badge('b-run','распознавание…');$('#rlog').textContent='Идёт разбор…';
  const body={dpi:$('#dpi').value,page:$('#page').value,
    min_len:$('#minlen').value,ocr:$('#ocr').checked,
    with_text:$('#wtext').checked,
    scale:$('#scale').value||($('#opt').value||'')};
  const lpx=parseFloat($('#lineopt').value), lmm=parseFloat($('#linemm').value);
  if(lpx>0 && lmm>0) body.scale=String(lmm/lpx);
  if(FILE){body.name=FILE.name;
    body.data=await new Promise(res=>{const fr=new FileReader();
      fr.onload=()=>res(fr.result);fr.readAsDataURL(FILE)});}
  else body.token=TOKEN;
  const r=await (await fetch('/api/recognize',{method:'POST',
    body:JSON.stringify(body)})).json();
  if(!r.ok){badge('b-err','ошибка');$('#rlog').textContent=r.error;return}
  TOKEN=r.token;FILE=null;
  badge('b-ok','распознано');
  $('#rlog').textContent=r.summary+(r.has_ocr?'':
    '\n\nOCR недоступен: не установлен tesseract. Масштаб задайте вручную.');
  const t=Date.now();
  $('#dxfview').innerHTML='<img src="/recog/'+r.token+'.dxfpng?t='+t+'">';
  $('#dxfview').querySelector('img').onclick=e=>zoom(e.target.src);
  $('#ov').innerHTML='<img src="/recog/'+r.token+'.png?t='+t+'">';
  $('#ov').querySelector('img').onclick=e=>zoom(e.target.src);
  $('#lineopt').innerHTML='<option value="">— не выбрана —</option>'+
    (r.lines||[]).map(o=>'<option value="'+o.px+'">'+o.kind+' '+o.px+
      ' px</option>').join('');
  $('#opt').innerHTML='<option value="">— автоподбор —</option>'+
    (r.options||[]).map(o=>'<option value="'+o.scale+'">размер '+o.value+
      ' = '+o.px+' px  →  '+o.scale+' мм/px</option>').join('');
  $('#dl').innerHTML='<a class="go" style="display:block;text-align:center;'+
    'padding:11px;font-size:15px" href="/recog/'+r.token+
    '.dxf" download>⬇ Скачать готовый DXF</a>'+
    '<p class="hint">Поменяйте масштаб и нажмите «Распознать» ещё раз — '+
    'файл пересоберётся без повторной загрузки.</p>';
};
</script></html>"""


# =====================================================================
#  Сервер
# =====================================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                return self._send(200, "text/html; charset=utf-8", PAGE)
            if path == "/api/doctor":
                return self._json({"rows": doctor()})
            if path == "/api/fields":
                fields = [{"path": p, "value": v, "kind": k}
                          for p, v, k in flatten(load_yaml())]
                return self._json({"fields": fields, "backend": yaml_backend()})
            if path.startswith("/preview/"):
                return self._send(200, "image/png",
                                  render_png(os.path.basename(path[9:])))
            if path.startswith("/download/"):
                with open(os.path.join(OUT, os.path.basename(path[10:])),
                          "rb") as f:
                    return self._send(200, "application/dxf", f.read())
            if path.startswith("/recog/"):
                tok, ext = os.path.splitext(os.path.basename(path[7:]))
                job = _jobs.get(tok)
                if not job:
                    return self._send(404, "text/plain; charset=utf-8",
                                      "результат устарел")
                if ext == ".png":
                    return self._send(200, "image/png", job["png"])
                if ext == ".dxfpng":
                    return self._send(200, "image/png", job.get("dxfpng") or b"")
                with open(job["dxf"], "rb") as f:
                    return self._send(200, "application/dxf", f.read())
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}",
                               "trace": traceback.format_exc()}, 500)
        self._send(404, "text/plain; charset=utf-8", "нет такого адреса")

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or "{}") if n else {}
        try:
            if path == "/api/save":
                data = load_yaml()
                for f in body.get("fields", []):
                    set_path(data, f["path"], f["value"], f["kind"])
                save_yaml(data)
                return self._json({"ok": True, "backend": yaml_backend()})
            if path == "/api/build":
                return self._json(run_build())
            if path == "/api/tesseract":
                r = install_tesseract()
                r["rows"] = doctor()
                return self._json(r)
            if path == "/api/install":
                need = missing_pips()
                r = pip_install(need)
                r["installed"] = bool(need)
                r["rows"] = doctor()
                return self._json(r)
            if path == "/api/recognize":
                return self._json(recognize(body))
        except Exception as e:
            return self._json({"ok": False,
                               "error": f"{type(e).__name__}: {e}\n\n"
                                        + traceback.format_exc()})
        self._send(404, "text/plain; charset=utf-8", "нет такого адреса")


def ensure_deps():
    """Доставляет библиотеки, если их нет.

    Вызывается при любом способе запуска: пользователь может открыть
    ui.py напрямую, минуя загрузчик, и тогда проверки бы не было вовсе.
    """
    need = missing_pips()
    if not need or "--no-install" in sys.argv:
        return
    print("Не хватает библиотек:", ", ".join(need))
    print("Ставлю, это может занять пару минут...\n")
    r = pip_install(need)
    print(r["log"][-4000:])
    if r["ok"]:
        print("\nГотово.")
    else:
        print("\nАвтоматически не вышло. Интерфейс запустится, но часть")
        print("возможностей будет недоступна. Откройте вкладку «Окружение».")


def main():
    ensure_deps()
    print("\nПроверка окружения:")
    for r in doctor():
        mark = "  есть " if r["ok"] else ("  НУЖЕН" if r["need"] else "  нет  ")
        print(f'{mark} {r["name"]:<22} {r["info"]}')
    srv = port = None
    for p in range(PORT, PORT + 20):        # 8765 может быть занят
        try:
            srv = ThreadingHTTPServer((HOST, p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        print(f"\nНе удалось занять ни один порт из {PORT}…{PORT + 19}.")
        print("Закройте другую копию программы и запустите снова.")
        return
    url = f"http://{HOST}:{port}/"
    print(f"\nИнтерфейс: {url}   (Ctrl+C для выхода)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено")


if __name__ == "__main__":
    main()
