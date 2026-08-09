#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальный интерфейс к build.py.

    python3 ui.py

Поднимает сервер на 127.0.0.1:8765 и открывает браузер. Наружу ничего не
слушает. Форма параметров строится из parts.yaml автоматически, поэтому
новые поля в данных появляются в интерфейсе сами.
"""
import io
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
YAML_PATH = os.path.join(ROOT, "parts.yaml")
OUT = os.path.join(ROOT, "out")
HOST, PORT = "127.0.0.1", 8765

_preview_cache = {}


# =====================================================================
#  YAML: чтение с сохранением комментариев
# =====================================================================
def _yaml():
    from ruamel.yaml import YAML
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_yaml():
    with open(YAML_PATH, encoding="utf-8") as f:
        return _yaml().load(f)


def save_yaml(data):
    buf = io.StringIO()
    _yaml().dump(data, buf)
    with open(YAML_PATH, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())


# ---- плоский список редактируемых полей ----
SKIP_KEYS = {"mass_ref", "length_ref"}     # контрольные значения не правим


def flatten(node, path=()):
    """Скалярные и списочные листья -> [(путь, значение, тип)]."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in SKIP_KEYS:
                continue
            out += flatten(v, path + (str(k),))
    elif isinstance(node, list):
        if all(isinstance(x, (int, float)) for x in node) and node:
            out.append((".".join(path), ", ".join(str(x) for x in node), "list"))
        else:
            for i, v in enumerate(node):
                out += flatten(v, path + (str(i),))
    else:
        # bool проверяем первым: в Python isinstance(True, int) истинно
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
        val = [_num(x) for x in str(raw).split(",") if x.strip() != ""]
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
    """Ключи в YAML могут быть числами (номера позиций)."""
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
    s = str(x).strip().replace(",", ".")
    f = float(s)
    return int(f) if f.is_integer() else f


# =====================================================================
#  Сборка и превью
# =====================================================================
def run_build():
    p = subprocess.run([sys.executable, "build.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=300)
    log = p.stdout + (("\n" + p.stderr) if p.stderr.strip() else "")
    files = sorted(f for f in os.listdir(OUT) if f.endswith(".dxf")) \
        if os.path.isdir(OUT) else []
    return {"ok": p.returncode == 0, "log": log, "files": files}


def render_png(name):
    path = os.path.join(OUT, name)
    mt = os.path.getmtime(path)
    if _preview_cache.get(name, (None,))[0] == mt:
        return _preview_cache[name][1]

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
    data = buf.getvalue()
    _preview_cache[name] = (mt, data)
    return data


# =====================================================================
#  HTML
# =====================================================================
PAGE = """<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Сборка комплекта КМД</title>
<style>
:root{--bg:#11161d;--panel:#1a212b;--line:#2b3542;--fg:#dfe6ee;--dim:#8fa0b3;
      --acc:#4ea3ff;--ok:#4cc38a;--err:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.45 "Segoe UI",system-ui,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);
       display:flex;align-items:center;gap:14px}
h1{font-size:16px;margin:0;font-weight:600;letter-spacing:.02em}
.wrap{display:grid;grid-template-columns:390px 1fr;height:calc(100vh - 57px)}
.pane{overflow:auto;padding:16px 18px}
.pane+.pane{border-left:1px solid var(--line)}
button{background:var(--acc);color:#08101a;border:0;border-radius:5px;
       padding:8px 16px;font-weight:600;cursor:pointer;font-size:13px}
button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}
button:disabled{opacity:.5;cursor:default}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.09em;
   color:var(--dim);margin:20px 0 8px;font-weight:600}
h2:first-child{margin-top:0}
.grp{background:var(--panel);border:1px solid var(--line);border-radius:6px;
     padding:10px 12px;margin-bottom:10px}
.grp>.t{color:var(--acc);font-weight:600;margin-bottom:7px;font-size:13px}
.f{display:grid;grid-template-columns:1fr 118px;gap:6px;align-items:center;
   margin:3px 0}
.f label{color:var(--dim);font-size:12px;overflow-wrap:anywhere}
input{background:#0d1218;border:1px solid var(--line);color:var(--fg);
      border-radius:4px;padding:5px 7px;font:13px ui-monospace,monospace;
      width:100%}
input:focus{outline:1px solid var(--acc)}
pre{background:#0d1218;border:1px solid var(--line);border-radius:6px;
    padding:12px;overflow:auto;font:12px/1.5 ui-monospace,monospace;
    white-space:pre;margin:0}
.badge{padding:3px 10px;border-radius:4px;font-size:12px;font-weight:600}
.b-ok{background:rgba(76,195,138,.15);color:var(--ok)}
.b-err{background:rgba(255,107,107,.15);color:var(--err)}
.b-run{background:rgba(78,163,255,.15);color:var(--acc)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
       gap:12px;margin-top:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;
      padding:9px;text-align:center}
.card img{width:100%;background:#11161d;border-radius:4px;cursor:zoom-in}
.card .n{font-size:11px;color:var(--dim);margin-top:6px;overflow-wrap:anywhere}
.card a{color:var(--acc);text-decoration:none;font-size:12px}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;
       align-items:center;justify-content:center;z-index:9;cursor:zoom-out}
#modal img{max-width:94vw;max-height:94vh}
</style>
<header>
  <h1>Сборка комплекта КМД</h1>
  <button id="go">Собрать</button>
  <button id="save" class="ghost">Сохранить параметры</button>
  <span id="st"></span>
</header>
<div class="wrap">
  <div class="pane">
    <h2>Параметры изделия</h2>
    <div id="form"></div>
  </div>
  <div class="pane">
    <h2>Отчёт сборки</h2>
    <pre id="log">Нажмите «Собрать».</pre>
    <h2>Чертежи</h2>
    <div class="cards" id="cards"></div>
  </div>
</div>
<div id="modal"><img id="mimg"></div>
<script>
let FIELDS=[];
const st=document.getElementById('st'), log=document.getElementById('log');

function badge(cls,txt){st.innerHTML='<span class="badge '+cls+'">'+txt+'</span>'}

function group(path){           // parts.14.strip.t -> "поз.14"
  const p=path.split('.');
  if(p[0]==='parts') return p[1]==='hoops'?'поз.5…12 (хомуты)':'поз.'+p[1];
  return p[0];
}
function short(path){
  const p=path.split('.');
  return p[0]==='parts'? p.slice(2).join('.') : p.slice(1).join('.');
}

fetch('/api/fields').then(r=>r.json()).then(d=>{
  FIELDS=d.fields; const box=document.getElementById('form'); const seen={};
  FIELDS.forEach((f,i)=>{
    const g=group(f.path);
    if(!seen[g]){
      const div=document.createElement('div'); div.className='grp';
      div.innerHTML='<div class="t">'+g+'</div>'; box.appendChild(div); seen[g]=div;
    }
    const row=document.createElement('div'); row.className='f';
    row.innerHTML='<label title="'+f.path+'">'+(short(f.path)||f.path)+'</label>';
    const inp=document.createElement('input');
    inp.value=f.value; inp.dataset.i=i; seen[g].appendChild(row); row.appendChild(inp);
  });
});

function collect(){
  return [...document.querySelectorAll('#form input')].map(i=>({
    path:FIELDS[i.dataset.i].path, kind:FIELDS[i.dataset.i].kind, value:i.value}));
}
async function save(){
  badge('b-run','сохранение…');
  const r=await (await fetch('/api/save',{method:'POST',
    body:JSON.stringify({fields:collect()})})).json();
  badge(r.ok?'b-ok':'b-err', r.ok?'сохранено':'ошибка');
  if(!r.ok) log.textContent=r.error;
  return r.ok;
}
document.getElementById('save').onclick=save;

document.getElementById('go').onclick=async()=>{
  if(!await save()) return;
  badge('b-run','сборка…'); log.textContent='Идёт расчёт и аудит…';
  const r=await (await fetch('/api/build',{method:'POST'})).json();
  log.textContent=r.log||r.error||'';
  badge(r.ok?'b-ok':'b-err', r.ok?'аудит пройден':'аудит не пройден');
  const c=document.getElementById('cards'); c.innerHTML='';
  (r.files||[]).forEach(f=>{
    const d=document.createElement('div'); d.className='card';
    const t=Date.now();
    d.innerHTML='<img src="/preview/'+f+'?t='+t+'"><div class="n">'+f+'</div>'+
                '<a href="/download/'+f+'" download>скачать DXF</a>';
    d.querySelector('img').onclick=e=>{
      document.getElementById('mimg').src=e.target.src;
      document.getElementById('modal').style.display='flex';};
    c.appendChild(d);
  });
};
document.getElementById('modal').onclick=e=>e.currentTarget.style.display='none';
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
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self._send(200, "text/html; charset=utf-8", PAGE)
        if path == "/api/fields":
            fields = [{"path": p, "value": v, "kind": k}
                      for p, v, k in flatten(load_yaml())]
            return self._json({"fields": fields})
        if path.startswith("/preview/"):
            name = os.path.basename(path[len("/preview/"):])
            try:
                return self._send(200, "image/png", render_png(name))
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        if path.startswith("/download/"):
            name = os.path.basename(path[len("/download/"):])
            with open(os.path.join(OUT, name), "rb") as f:
                return self._send(200, "application/dxf", f.read())
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
                return self._json({"ok": True})
            if path == "/api/build":
                return self._json(run_build())
        except Exception as e:
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"},
                              500)
        self._send(404, "text/plain; charset=utf-8", "нет такого адреса")


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"Интерфейс: {url}   (Ctrl+C для выхода)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено")


if __name__ == "__main__":
    main()
