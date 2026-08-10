# -*- coding: utf-8 -*-
"""OCR numbers, dimension pairing, calibration and constrained solving."""
from __future__ import annotations
import math, os, shutil
from dataclasses import dataclass, field
import cv2
import numpy as np


def _probe_ocr():
    try:
        import pytesseract
    except Exception:
        return False, None
    exe = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    if shutil.which(exe) is None and not os.path.isfile(exe):
        for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.isfile(c):
                pytesseract.pytesseract.tesseract_cmd = c
                return True, pytesseract
        return False, None
    return True, pytesseract

HAS_OCR, pytesseract = _probe_ocr()
NUM_CFG = "--psm 11 -c tessedit_char_whitelist=0123456789"
MIN_VALUE, MIN_CONF, PAD = 10, 35.0, 20

@dataclass
class Num:
    value: int; x: float; y: float; w: float; h: float; conf: float; vertical: bool

@dataclass
class Dim:
    value: int; vertical: bool; a: float; b: float; line: float
    num: Num = None; ia: int = -1; ib: int = -1; meta: dict = field(default_factory=dict)


def ocr_scales(bw, target=44.0):
    kh = cv2.getStructuringElement(cv2.MORPH_RECT,(25,1)); kv=cv2.getStructuringElement(cv2.MORPH_RECT,(1,25))
    lines=cv2.max(cv2.morphologyEx(bw,cv2.MORPH_OPEN,kh),cv2.morphologyEx(bw,cv2.MORPH_OPEN,kv))
    txt=cv2.subtract(bw,cv2.dilate(lines,np.ones((3,3),np.uint8)))
    n,_,st,_=cv2.connectedComponentsWithStats(txt,8)
    hs=[st[i,3] for i in range(1,n) if 4<=st[i,3]<=60 and 2<=st[i,2]<=60 and st[i,4]>=12]
    if not hs: return (2,3)
    k=max(2,min(6,int(round(target/max(float(np.median(hs)),1.0)))))
    return tuple(sorted({max(2,k-1),k,min(6,k+1)}))


def _prep(bw,k):
    img=cv2.resize(255-bw,None,fx=k,fy=k,interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(img,PAD,PAD,PAD,PAD,cv2.BORDER_CONSTANT,value=255)


def _boxes(img):
    if pytesseract is None: return []
    try: d=pytesseract.image_to_data(img,config=NUM_CFG,output_type=pytesseract.Output.DICT)
    except Exception: return []
    out=[]
    for i,t0 in enumerate(d["text"]):
        t="".join(ch for ch in t0 if ch.isdigit())
        try: conf=float(d["conf"][i])
        except (TypeError,ValueError): conf=-1
        if t and conf>=MIN_CONF and len(t)<=5:
            out.append((int(t),d["left"][i],d["top"][i],d["width"][i],d["height"][i],conf))
    return out


def ocr_numbers(bw,min_h=7,max_h=70,scales=None):
    if not HAS_OCR: return []
    found=[]
    for k in (scales or ocr_scales(bw)):
        img=_prep(bw,k); H=img.shape[0]
        for v,x,y,w,h,c in _boxes(img):
            found.append(Num(v,(x+w/2-PAD)/k,(y+h/2-PAD)/k,w/k,h/k,c,False))
        for v,x,y,w,h,c in _boxes(cv2.rotate(img,cv2.ROTATE_90_CLOCKWISE)):
            rx,ry=x+w/2,y+h/2
            found.append(Num(v,(ry-PAD)/k,(H-1-rx-PAD)/k,h/k,w/k,c,True))
    hh,ww=bw.shape; out=[]
    for f in sorted(found,key=lambda n:-n.conf):
        if f.value<MIN_VALUE or not(0<=f.x<ww and 0<=f.y<hh): continue
        if not(min_h<=max(f.w,f.h)<=max_h*3): continue
        if any(math.hypot(f.x-g.x,f.y-g.y)<12 for g in out): continue
        out.append(f)
    return out


def _candidates(nb,segs,reach=9.0):
    """Return every geometrically plausible pair on the dimension's normal axis."""
    want="h" if nb.vertical else "v"
    # For a vertical dimension, extension lines are horizontal and their
    # separation is measured on Y. For a horizontal dimension, extension
    # lines are vertical and their separation is measured on X.
    if want=="h":
        cur=nb.y
        line=nb.x
    else:
        cur=nb.x
        line=nb.y
    reach_n=max(reach,1.6*(nb.w if nb.vertical else nb.h))
    cands=[]
    for s in segs:
        if getattr(s,"kind",None)!=want: continue
        if want=="v": pos,a0,a1=s.x1,min(s.y1,s.y2),max(s.y1,s.y2)
        else: pos,a0,a1=s.y1,min(s.x1,s.x2),max(s.x1,s.x2)
        if a1-a0<6 or not(a0-reach_n<=line<=a1+reach_n): continue
        cands.append(round(float(pos),1))
    cands=sorted(set(cands)); out=[]
    for i,p in enumerate(cands):
        for q in cands[i+1:]:
            span=q-p
            if span<8: continue
            center=(p+q)/2
            symmetry=abs(cur-center)/max(span,1e-6)
            inside=bool(p-2<=cur<=q+2)
            out.append({"a":p,"b":q,"span_px":span,"symmetry":symmetry,"inside":inside,
                        "center_error_px":abs(cur-center),"line":line})
    return out


def _estimate_scale(numbers,segs):
    """Estimate mm/px from a consistent cluster of large dimensions."""
    obs=[]
    for nb in numbers:
        if nb.value<1000: continue
        for c in _candidates(nb,segs):
            k=nb.value/c["span_px"]
            if 0.2<k<100: obs.append((nb.value,k,c))
    if len(obs)<2: return None
    best=None
    for _,k0,_ in obs:
        cluster=[o for o in obs if abs(o[1]-k0)/max(k0,1e-9)<=0.08]
        score=(len(cluster),sum(math.log1p(o[0]) for o in cluster))
        if best is None or score>best[0]: best=(score,cluster)
    cluster=best[1]
    if len(cluster)<2: return None
    num=sum(o[0]*o[2]["span_px"] for o in cluster)
    den=sum(o[2]["span_px"]**2 for o in cluster)
    return num/den if den else None


def build_dims(numbers,segs,reach=9.0,scale=None,diagnostics=False):
    """Pair dimension numbers with extension lines using scale when available."""
    if scale is None: scale=_estimate_scale(numbers,segs)
    out=[]
    for nb in numbers:
        cands=_candidates(nb,segs,reach)
        if not cands: continue
        target=(nb.value/scale) if scale else None
        for c in cands:
            c["target_error"]=(abs(c["span_px"]-target)/target) if target else None
            if target:
                c["score"]=(c["target_error"],0 if c["inside"] else 1,c["symmetry"],c["span_px"])
            else:
                c["score"]=(0 if c["inside"] else 1,c["center_error_px"],c["symmetry"],c["span_px"])
        valid=[c for c in cands if target is None or c["target_error"]<=0.12]
        pool=valid or cands
        best=min(pool,key=lambda c:c["score"])
        d=Dim(nb.value,nb.vertical,best["a"],best["b"],best["line"],nb,
              meta={"scale_used":scale,"candidate_count":len(cands),"selected":best,
                    "candidates":sorted(cands,key=lambda c:c["score"])[:12]})
        out.append(d)
    return out


def calibrate(dims,rel_tol=0.05,allow_single=True):
    if not dims: return None
    if len(dims)==1:
        if not allow_single: return None
        d=dims[0]; k=d.value/(d.b-d.a)
        return {"scale":k,"n":1,"rms":0.0,"single":True,"used":{id(d)},"rejected":[],
                "matches":[{"value":d.value,"px":round(d.b-d.a,1),"mm":float(d.value),"resid":0.0}]}
    ks=[(d,d.value/(d.b-d.a)) for d in dims if d.b>d.a]
    if not ks: return None
    best=None
    for _,k0 in ks:
        inl=[(d,k) for d,k in ks if abs(k-k0)<=k0*rel_tol]
        score=(len(inl),sum(d.value for d,_ in inl))
        if best is None or score>best[0]: best=(score,inl)
    inl=best[1]
    if len(inl)<2: return None
    num=sum(d.value*(d.b-d.a) for d,_ in inl); den=sum((d.b-d.a)**2 for d,_ in inl)
    k=num/den
    matches=[{"value":d.value,"px":round(d.b-d.a,1),"mm":round((d.b-d.a)*k,1),"resid":round((d.b-d.a)*k-d.value,1)} for d,_ in inl]
    matches.sort(key=lambda m:-m["value"])
    rms=math.sqrt(sum(m["resid"]**2 for m in matches)/len(matches))
    used={id(d) for d,_ in inl}
    return {"scale":k,"matches":matches,"rms":round(rms,2),"n":len(matches),"used":used,
            "rejected":sorted({d.value for d in dims if id(d) not in used})}


def cluster(values,tol=4.0):
    if not values:return [],{}
    order=sorted(range(len(values)),key=lambda i:values[i]); centers=[]; idx={}; cur=[order[0]]; start=values[order[0]]
    for i in order[1:]:
        if values[i]-start<=tol: cur.append(i)
        else:
            centers.append(float(np.mean([values[j] for j in cur])))
            for j in cur: idx[j]=len(centers)-1
            cur=[i]; start=values[i]
    centers.append(float(np.mean([values[j] for j in cur])))
    for j in cur: idx[j]=len(centers)-1
    return centers,idx


def nearest(centers,v,tol):
    if not centers:return -1
    i=int(np.argmin([abs(c-v) for c in centers])); return i if abs(centers[i]-v)<=tol else -1


def solve_axis(centers_px,constraints,scale,weight=40.0):
    n=len(centers_px)
    if not n:return [],[]
    rows=[];rhs=[]
    for i in range(n):
        r=np.zeros(n);r[i]=1;rows.append(r);rhs.append(centers_px[i]*scale)
    for i,j,v in constraints:
        r=np.zeros(n);r[j]=weight;r[i]=-weight;rows.append(r);rhs.append(weight*v)
    sol,*_=np.linalg.lstsq(np.array(rows),np.array(rhs),rcond=None)
    resid=[(i,j,v,round(float(sol[j]-sol[i])-v,3)) for i,j,v in constraints]
    return [float(x) for x in sol],resid


def refine_dims(numbers,segs,scale,rel_tol=0.04,reach=9.0):
    """Strict scale-aware second pass; preserves diagnostic candidates."""
    out=[]
    for nb in numbers:
        cands=_candidates(nb,segs,reach)
        if not cands:continue
        target=nb.value/scale
        valid=[c for c in cands if abs(c["span_px"]-target)/max(target,1e-9)<=rel_tol]
        if not valid:continue
        best=min(valid,key=lambda c:(0 if c["inside"] else 1,abs(c["span_px"]-target)/target,c["symmetry"]))
        out.append(Dim(nb.value,nb.vertical,best["a"],best["b"],best["line"],nb,
                       meta={"scale_used":scale,"candidate_count":len(cands),"selected":best,
                             "candidates":sorted(cands,key=lambda c:(abs(c["span_px"]-target)/target,0 if c["inside"] else 1))[:12]}))
    return out
