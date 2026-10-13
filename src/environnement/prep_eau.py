"""
prep_eau.py : cours d'eau (rivières, torrents, canaux) d'après OpenStreetMap, pour les rubans d'eau animés de la scène.

Interroge l'API Overpass (une seule fois, résultat gardé dans <cache>/env/eau_osm.json) pour la zone autour de la caméra,
convertit en LV95 et écrit <cache>/env/eau.npz: pts (E, N de tous les sommets), debut (indice du premier sommet de chaque ligne,
dans le sens du courant: OSM oriente les cours d'eau vers l'aval), larg (largeur en m), type (0 rivière, 1 torrent, 2 canal).
La largeur vient de la balise "width" si elle existe, sinon d'une valeur par défaut (rivière 12 m, torrent 3 m, canal 4 m).
Limite: les surfaces d'eau (lacs) ne sont pas traitées. Les largeurs sont à ajuster d'après l'image si besoin (--larg-riviere).

Utilisation (via blatten.py):  python blatten.py prep-eau [--rayon 4700] [--larg-riviere 12] [--refresh]
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
ROOT = os.environ.get("BLATTEN_ROOT") or os.path.dirname(os.path.dirname(HERE))
SERVEURS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]


def log(*a):
    print("[eau]", *a, flush=True)


def lv95_to_wgs84(E, N):
    y, x = (E - 2600000.0) / 1e6, (N - 1200000.0) / 1e6
    lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return lat * 100.0 / 36.0, lon * 100.0 / 36.0


def wgs84_to_lv95(lat, lon):
    p = (np.asarray(lat) * 3600.0 - 169028.66) / 10000.0
    l = (np.asarray(lon) * 3600.0 - 26782.5) / 10000.0
    E = 2600072.37 + 211455.93 * l - 10938.51 * l * p - 0.36 * l * p * p - 44.54 * l ** 3
    N = 1200147.07 + 308807.95 * p + 3745.25 * l * l + 76.63 * p * p - 194.56 * l * l * p + 119.79 * p ** 3
    return E, N


def main():
    ap = argparse.ArgumentParser(prog="prep_eau")
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--swisstopo")   # ignoré
    ap.add_argument("--rayon", type=float, default=4700.0)
    ap.add_argument("--larg-riviere", type=float, default=12.0)
    ap.add_argument("--larg-torrent", type=float, default=3.0)
    ap.add_argument("--refresh", action="store_true", help="refaire la requête OpenStreetMap")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    a = ap.parse_args(argv)
    env = os.path.join(a.data, "env")
    mp = os.path.join(env, "env_meta.json")
    meta = json.load(open(mp))
    try:
        cam = json.load(open(os.path.join(ROOT, "camera.json")))["cam"]
    except Exception:
        sys.exit("camera.json introuvable")
    Ec, Nc = meta["scene_E0"] + cam[0], meta["scene_N0"] + meta["flip"] * cam[1]
    raw = os.path.join(env, "eau_osm.json")
    if a.refresh or not os.path.exists(raw):
        la0, lo0 = lv95_to_wgs84(Ec - a.rayon, Nc - a.rayon)
        la1, lo1 = lv95_to_wgs84(Ec + a.rayon, Nc + a.rayon)
        q = f'[out:json][timeout:90];way["waterway"~"^(river|stream|canal)$"]({la0:.5f},{lo0:.5f},{la1:.5f},{lo1:.5f});out geom tags;'
        data, err = None, []
        for srv in SERVEURS:
            try:
                req = urllib.request.Request(srv, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": "blatten-vr/1.0 (projet Dynarisk)"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.load(r)
                break
            except Exception as e:
                err.append(f"{srv}: {e}")
        if data is None:
            sys.exit("OpenStreetMap injoignable:\n  " + "\n  ".join(err))
        json.dump(data, open(raw, "w"))
        log(f"{len(data.get('elements', []))} cours d'eau reçus d'OpenStreetMap")
    data = json.load(open(raw))
    pts, debut, larg, typ, noms = [], [], [], [], []
    n = 0
    for el in data.get("elements", []):
        g = el.get("geometry")
        if not g or len(g) < 2:
            continue
        tg = el.get("tags", {})
        kind = {"river": 0, "stream": 1, "canal": 2}.get(tg.get("waterway"), 1)
        w = None
        try:
            w = float(str(tg.get("width", "")).replace("m", "").strip())
        except ValueError:
            pass
        if w is None:
            w = {0: a.larg_riviere, 1: a.larg_torrent, 2: 4.0}[kind]
        E, N = wgs84_to_lv95([p["lat"] for p in g], [p["lon"] for p in g])
        debut.append(n)
        pts.append(np.stack([E, N], 1))
        n += len(g)
        larg.append(w)
        typ.append(kind)
        noms.append(tg.get("name", ""))
    if not pts:
        sys.exit("Aucun cours d'eau dans la zone.")
    P = np.concatenate(pts)
    np.savez_compressed(os.path.join(env, "eau.npz"), pts=P, debut=np.array(debut), larg=np.array(larg, np.float32), type=np.array(typ, np.int8), noms=np.array(noms))
    meta["eau"] = dict(file="eau.npz", lignes=len(debut), longueur_km=float(sum(np.hypot(*np.diff(p, axis=0).T).sum() for p in pts) / 1000),
                       noms=sorted({x for x in noms if x}), created=time.strftime("%Y-%m-%d %H:%M"))
    json.dump(meta, open(mp, "w"), indent=1)
    log(f"{len(debut)} lignes, {meta['eau']['longueur_km']:.1f} km. Noms: {', '.join(meta['eau']['noms'][:10])}")
    log("écrit eau.npz")


main()
