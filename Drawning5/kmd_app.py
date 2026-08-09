#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
КМД: сборка комплекта чертежей и распознавание растровых чертежей.

Один файл. Запуск:

    python kmd_app.py

При первом запуске он распакует рядом с собой рабочие файлы, при
необходимости доставит библиотеки Python и откроет интерфейс в браузере.

Ключи:
    --no-install   не ставить библиотеки автоматически
    --no-browser   не открывать браузер
    --force        перезаписать распакованные файлы исходными
"""
import base64
import io
import os
import subprocess
import sys
import zipfile

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kmd")
REQUIRED = ["ezdxf", "pyyaml"]
OPTIONAL = ["matplotlib", "ruamel.yaml", "opencv-python-headless", "numpy",
            "pillow", "pypdfium2", "pytesseract"]
PROBE = {"ezdxf": "ezdxf", "pyyaml": "yaml", "matplotlib": "matplotlib",
         "ruamel.yaml": "ruamel.yaml", "opencv-python-headless": "cv2",
         "numpy": "numpy", "pillow": "PIL", "pypdfium2": "pypdfium2",
         "pytesseract": "pytesseract"}


def unpack(force=False):
    data = base64.b64decode(PAYLOAD)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        os.makedirs(APP_DIR, exist_ok=True)
        for info in z.infolist():
            dest = os.path.join(APP_DIR, info.filename)
            if os.path.exists(dest) and not force:
                continue                     # правки пользователя не трогаем
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
    return APP_DIR


def missing(pkgs):
    out = []
    for p in pkgs:
        try:
            __import__(PROBE[p])
        except Exception:
            out.append(p)
    return out


PROXY_VARS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy", "FTP_PROXY", "ftp_proxy")

ATTEMPTS = (
    ("обычная установка", (), "as-is"),
    ("в профиль пользователя", ("--user",), "as-is"),
    ("без переменных прокси", (), "strip"),
    ("без переменных прокси, в профиль", ("--user",), "strip"),
    ("в обход настроек pip.ini", ("--isolated",), "strip"),
    ("в обход любого прокси", (), "bypass"),
    ("в обход прокси, в профиль", ("--user",), "bypass"),
    ("в обход прокси и настроек pip", ("--isolated",), "bypass"),
)


def _env(mode):
    """strip - убрать переменные прокси; bypass - обойти любой прокси.

    Режим bypass нужен, когда прокси задан не переменными окружения, а в
    настройках Windows или в pip.ini. Python обходит прокси при
    no_proxy='*', но только если в окружении вообще есть прокси, поэтому
    подставляется заглушка.
    """
    env = dict(os.environ)
    if mode in ("strip", "bypass"):
        for v in PROXY_VARS:
            env.pop(v, None)
    if mode == "bypass":
        env["http_proxy"] = env["HTTP_PROXY"] = "http://127.0.0.1:1"
        env["no_proxy"] = env["NO_PROXY"] = "*"
    return env


def _run(pkgs, extra=(), mode="as-is"):
    cmd = [sys.executable, "-m", "pip", "install", *extra, *pkgs]
    p = subprocess.run(cmd, env=_env(mode), capture_output=True, text=True,
                       errors="replace")
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    return p.returncode == 0, p.stdout + p.stderr


def install(pkgs):
    print("Ставлю библиотеки:", ", ".join(pkgs))
    seen = ""
    socks_tried = False
    for title, extra, mode in ATTEMPTS:
        print("  -- " + title)
        ok, out = _run(pkgs, extra, mode)
        seen += out
        if ok:
            return True
        if "SOCKS" in out and not socks_tried and mode == "bypass":
            socks_tried = True
            print("  -- доустановка PySocks в обход прокси")
            ok2, out2 = _run(["PySocks"], mode="bypass")
            seen += out2
            if ok2 and _run(pkgs)[0]:
                return True
    _hint(seen, pkgs)
    return False


def _hint(log, pkgs):
    py = '"' + sys.executable + '"'
    cmd = py + " -m pip install " + " ".join(pkgs)
    print()
    print("=" * 62)
    if "SOCKS" in log:
        print("Прокси socks5:// задан не переменной окружения, а глубже -")
        print("в настройках Windows или в файле pip.ini. Варианты:")
        print()
        print("1) Поставить PySocks, тогда прокси заработает как надо:")
        print("    " + py + ' -m pip install PySocks --proxy ""')
        print()
        print("2) Обойти прокси на время установки:")
        print("    set NO_PROXY=*")
        print("    set HTTP_PROXY=http://127.0.0.1:1")
        print("    " + cmd)
        print()
        print("3) Найти и убрать прокси в самом pip:")
        print("    " + py + " -m pip config list")
        print("    " + py + " -m pip config unset global.proxy")
        print()
        print("4) Отключить прокси в Windows: Параметры - Сеть и Интернет -")
        print("   Прокси-сервер, снять «Использовать прокси-сервер».")
    elif "SSL" in log or "CERTIFICATE" in log.upper():
        print("Соединение режет антивирус или шлюз. Попробуйте:")
        print()
        print("    " + cmd + " --trusted-host pypi.org"
              " --trusted-host files.pythonhosted.org")
    else:
        print("Выполните вручную и посмотрите текст ошибки:")
        print()
        print("    " + cmd)
    print()
    print("Если сети нет совсем: на машине с интернетом выполните")
    print("    pip download " + " ".join(pkgs) + " -d wheels")
    print("перенесите папку wheels сюда и выполните")
    print("    " + cmd + " --no-index --find-links wheels")
    print("=" * 62)


def main():
    force = "--force" in sys.argv
    print("Распаковка в", unpack(force))

    if "--no-install" not in sys.argv:
        need = missing(REQUIRED + OPTIONAL)
        if need:
            hard = [p for p in need if p in REQUIRED]
            if not install(need) and hard:
                print("\nНе удалось установить:", ", ".join(hard))
                print("Выполните вручную:")
                print(f"  {sys.executable} -m pip install " + " ".join(hard))
                input("\nEnter для выхода…")
                return 1

    still = missing(REQUIRED)
    if still:
        print("\nНе хватает:", ", ".join(still))
        print(f"  {sys.executable} -m pip install " + " ".join(still))
        input("\nEnter для выхода…")
        return 1

    sys.path.insert(0, APP_DIR)
    os.chdir(APP_DIR)
    import ui
    ui.main()
    return 0


PAYLOAD = """\
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
cHlQSwUGAAAAABoAGgA+BgAAvwwBAAAA"""


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            input("\nПроизошла ошибка. Enter для выхода…")
        except EOFError:
            pass
        sys.exit(1)
