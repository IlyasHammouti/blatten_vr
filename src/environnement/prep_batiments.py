"""
prep_batiments.py : bâtiments 3D swisstopo (swissBUILDINGS3D 2.0, DXF) vers un fichier compact calé sur la scène.

Lit les .dxf.zip de <swisstopo>/swissbuildings3d_2 SANS les décompresser, garde pour chaque emplacement le millésime
le plus récent AVANT l'événement (28 mai 2025), et écrit <cache>/env/batiments.npz + une entrée "batiments" dans
<cache>/env/env_meta.json (les autres fichiers de env/ ne sont pas modifiés).

Repère: X = E - scene_E0, Y = flip * (N - scene_N0), Z = altitude + dz (même calage que le relief).

Utilisation (via blatten.py, menu "Préparer les bâtiments 3D"):  python blatten.py prep-batiments
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import time
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
ROOT = os.environ.get("BLATTEN_ROOT") or os.path.dirname(os.path.dirname(HERE))

IGNORER = {"Gebaeude unsichtbar"}      # bâtiments enterrés / non visibles


def log(*a):
    print("[batiments]", *a, flush=True)


def lire_dxf(texte):
    """Lecteur DXF minimal: les POLYLINE de type polyface (swissBUILDINGS3D). Rend une liste (calque, sommets Nx3, triangles Mx3)."""
    lignes = texte.splitlines()
    n = len(lignes)
    i = 0
    out = []
    cur = None          # polyline en cours: dict(layer, pts, tris)
    vt = None           # sommet en cours
    ent = None
    while i + 1 < n:
        code = lignes[i].strip()
        val = lignes[i + 1].strip()
        i += 2
        if code == "0":
            if vt is not None and cur is not None:
                _fin_sommet(cur, vt)
                vt = None
            ent = val
            if val == "POLYLINE":
                if cur is not None and cur["pts"]:
                    out.append(cur)
                cur = dict(layer="", pts=[], tris=[], poly=True)
            elif val == "VERTEX":
                vt = dict(x=0.0, y=0.0, z=0.0, fl=0, idx=[])
            elif val == "SEQEND":
                if cur is not None and cur["pts"]:
                    out.append(cur)
                cur = None
            elif val in ("ENDSEC", "EOF"):
                if cur is not None and cur["pts"]:
                    out.append(cur)
                cur = None
            continue
        if cur is None:
            continue
        if vt is not None:
            if code == "10": vt["x"] = float(val)
            elif code == "20": vt["y"] = float(val)
            elif code == "30": vt["z"] = float(val)
            elif code == "70": vt["fl"] = int(val)
            elif code in ("71", "72", "73", "74"): vt["idx"].append(abs(int(val)))
        elif ent == "POLYLINE" and code == "8":
            cur["layer"] = val
    if vt is not None and cur is not None:
        _fin_sommet(cur, vt)
    if cur is not None and cur["pts"]:
        out.append(cur)
    res = []
    for c in out:
        if c["pts"] and c["tris"]:
            res.append((c["layer"], np.array(c["pts"], np.float64), np.array(c["tris"], np.int32)))
    return res


def _fin_sommet(cur, vt):
    if vt["fl"] & 128 and not vt["fl"] & 64:         # enregistrement de face (indices 1-based)
        ix = [k - 1 for k in vt["idx"] if k]
        for j in range(1, len(ix) - 1):
            cur["tris"].append((ix[0], ix[j], ix[j + 1]))
    else:
        cur["pts"].append((vt["x"], vt["y"], vt["z"]))


def dalles(dossier):
    """{emplacement: [(millésime, chemin)]} d'après les noms swissbuildings3d_2_AAAA-MM_<feuille>_2056_5728.dxf.zip."""
    d = {}
    for p in glob.glob(os.path.join(dossier, "*.zip")):
        m = re.search(r"_(\d{4}-\d{2})_([\d-]+)_2056", os.path.basename(p))
        if m:
            d.setdefault(m.group(2), []).append((m.group(1), p))
    return d


def main():
    ap = argparse.ArgumentParser(prog="prep_batiments")
    ap.add_argument("--swisstopo", default=os.path.join(ROOT, "data", "swisstopo"))
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--avant", default="2025-05", help="millésime maximal (AAAA-MM), défaut 2025-05 (événement le 28 mai 2025)")
    ap.add_argument("--rayon", type=float, default=7000.0, help="ne garde que les bâtiments à moins de ce rayon (m) de la scène")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    env = os.path.join(a.data, "env")
    mp = os.path.join(env, "env_meta.json")
    if not os.path.exists(mp):
        sys.exit("env_meta.json introuvable: lancer d'abord 'Préparer relief + image aérienne'.")
    meta = json.load(open(mp))
    E0, N0, flip, dz = meta["scene_E0"], meta["scene_N0"], meta["flip"], meta.get("dz", 0.0)
    dossier = os.path.join(a.swisstopo, "swissbuildings3d_2")
    ds = dalles(dossier)
    if not ds:
        sys.exit(f"Aucune dalle swissBUILDINGS3D dans {dossier}. Télécharger d'abord (menu: HAUTE RESOLUTION).")
    t0 = time.time()
    batis = []   # (calque, sommets LV95, triangles, millésime)
    for feuille, lst in sorted(ds.items()):
        ok = [(v, p) for v, p in lst if v <= a.avant]
        if not ok:
            log(f"feuille {feuille}: aucun millésime avant {a.avant}, ignorée")
            continue
        v, p = max(ok)
        with zipfile.ZipFile(p) as z:
            nom = next(n for n in z.namelist() if n.lower().endswith(".dxf"))
            txt = z.read(nom).decode("latin-1")
        b = lire_dxf(txt)
        log(f"feuille {feuille} ({v}): {len(b)} bâtiments ({time.time() - t0:.0f} s)")
        batis += [(c, pts, tr, v) for c, pts, tr in b]
    # doublons entre feuilles voisines: même centre à moins de 1 m, on garde le plus récent
    cent = np.array([pts[:, :2].mean(0) for _, pts, _, _ in batis])
    cle = {}
    garde = []
    for k, (c, pts, tr, v) in enumerate(batis):
        kk = (round(cent[k, 0]), round(cent[k, 1]), len(tr))
        if kk in cle and batis[cle[kk]][3] >= v:
            continue
        if kk in cle:
            garde[garde.index(cle[kk])] = k
        else:
            garde.append(k)
        cle[kk] = k
    batis = [batis[k] for k in garde]
    V, T, ranges, lay = [], [], [], []
    noms = {}
    off = 0
    n_ign = 0
    for c, pts, tr, v in batis:
        cx, cy = pts[:, 0].mean() - E0, flip * (pts[:, 1].mean() - N0)
        if c in IGNORER or np.hypot(cx, cy) > a.rayon:
            n_ign += 1
            continue
        X = pts[:, 0] - E0
        Y = flip * (pts[:, 1] - N0)
        Z = pts[:, 2] + dz
        V.append(np.stack([X, Y, Z], 1).astype(np.float32))
        T.append(tr + off)
        ranges.append((len(T[-1]), cx, cy))
        lay.append(noms.setdefault(c, len(noms)))
        off += len(pts)
    if not V:
        sys.exit("Aucun bâtiment dans le rayon demandé.")
    V = np.concatenate(V)
    tri = np.concatenate(T).astype(np.int32)
    nb = np.array([r[0] for r in ranges], np.int32)
    ctr = np.array([[r[1], r[2]] for r in ranges], np.float32)
    np.savez_compressed(os.path.join(env, "batiments.npz"), v=V, t=tri, ntri=nb, centre=ctr, calque=np.array(lay, np.int16),
                        noms=np.array(list(noms.keys())))
    meta["batiments"] = dict(file="batiments.npz", count=int(len(nb)), triangles=int(len(tri)), avant=a.avant,
                             millesimes=sorted({b[3] for b in batis}), calques=list(noms.keys()),
                             created=time.strftime("%Y-%m-%d %H:%M"))
    json.dump(meta, open(mp, "w"), indent=1)
    zs = V[:, 2]
    log(f"{len(nb)} bâtiments, {len(tri):,} triangles, {n_ign} ignorés (hors rayon ou enterrés); altitudes {zs.min():.0f} à {zs.max():.0f} m")
    log("calques:", ", ".join(f"{k} ({int((np.array(lay) == i).sum())})" for k, i in noms.items()))
    log(f"écrit {os.path.join(env, 'batiments.npz')} ({time.time() - t0:.0f} s)")


main()
