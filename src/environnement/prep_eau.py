"""
prep_eau.py : eau de la scène, lue dans l'image aérienne (et non tracée d'après OpenStreetMap).

Les images SWISSIMAGE n'ont que le rouge, le vert et le bleu (pas de proche infrarouge), donc pas de vrai NDWI. De plus la Lonza y est
gris-blanc (gravier et eau turbide), pas bleue. Un indice de couleur seul prendrait aussi routes, toits et éboulis. On combine donc:
  1. un indice sur l'image: pixel peu saturé (< 0,20) et clair (luminosité > 0,40), comme le lit gris-blanc de la rivière;
  2. le relief: pente faible (< 0,25), l'eau ne coule pas sur une paroi;
  3. un couloir autour des cours d'eau OpenStreetMap, utilisé SEULEMENT pour dire où chercher (±40 m pour une rivière, ±8 m pour un
     torrent): le tracé OSM n'a pas besoin d'être calé, la géométrie exacte vient de l'image et du relief;
  puis une ouverture morphologique qui supprime les formes fines (routes, sentiers).
Écrit <cache>/env/eau_masque.png (2 m, toute la zone), eau_masque_fin.png (0,5 m, emprise de l'image 50 cm si présente), les
aperçus eau_apercu_*.png (image + eau en bleu, à regarder) et l'entrée "eau_masque" de env_meta.json. La scène en fait un sol
brillant à ondulations animées (matériau du terrain), sans ruban ni maillage.
Le tracé OSM (eau.npz, eau_osm.json) est gardé comme couloir; il faut Internet la première fois.

Utilisation (via blatten.py):  python blatten.py prep-eau [--couloir 40] [--sat 0.20] [--lum 0.40] [--refresh] [--sortie dossier]
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

try:
    import imagecodecs
except ImportError:      # hors Blender (essais): Pillow
    imagecodecs = None


def lire_rgb(path):
    if imagecodecs is not None:
        a = imagecodecs.jpeg8_decode(open(path, "rb").read())
        return a[..., :3]
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    return np.asarray(Image.open(path).convert("RGB"))


def ecrire_png(path, a):
    if imagecodecs is not None:
        open(path, "wb").write(imagecodecs.png_encode(np.ascontiguousarray(a)))
    else:
        from PIL import Image
        Image.fromarray(a).save(path)

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
    ap.add_argument("--couloir", type=float, default=40.0, help="demi-largeur (m) du couloir de recherche autour d'une rivière OSM")
    ap.add_argument("--sat", type=float, default=0.20, help="saturation maximale de l'eau (le lit de la Lonza est gris-blanc)")
    ap.add_argument("--lum", type=float, default=0.40, help="luminosité minimale de l'eau")
    ap.add_argument("--pente", type=float, default=0.25, help="pente maximale (tangente)")
    ap.add_argument("--sortie", help="dossier de test: n'écrit que les images (pas env_meta.json)")
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
    larg_a, typ_a, deb_a = np.array(larg, np.float32), np.array(typ, np.int8), np.array(debut)
    sortie = a.sortie or env
    os.makedirs(sortie, exist_ok=True)
    if not a.sortie:
        np.savez_compressed(os.path.join(env, "eau.npz"), pts=P, debut=deb_a, larg=larg_a, type=typ_a, noms=np.array(noms))
    demi = {0: a.couloir, 1: 8.0, 2: 10.0}

    def couloir(x0, y1, step, H, W):
        """Bande de demi-largeur 'demi' m autour de chaque ligne OSM (carrés posés le long de la ligne, par tableau de différences)."""
        diff = np.zeros((H + 1, W + 1), np.int32)
        fin = list(deb_a[1:]) + [len(P)]
        for k, (d0, d1) in enumerate(zip(deb_a, fin)):
            q = P[d0:d1]
            if len(q) < 2:
                continue
            r = max(int(round(demi[int(typ_a[k])] / step)), 1)
            seg = np.hypot(*np.diff(q, axis=0).T)
            for (e0, n0), (e1, n1), L_ in zip(q[:-1], q[1:], seg):
                n_ = max(int(L_ / (0.7 * r * step)) + 1, 2)
                t = np.linspace(0, 1, n_)
                j = np.rint((e0 + (e1 - e0) * t - x0) / step).astype(np.int64)
                i = np.rint((y1 - (n0 + (n1 - n0) * t)) / step).astype(np.int64)
                ok = (j + r >= 0) & (j - r < W) & (i + r >= 0) & (i - r < H)
                j, i = j[ok], i[ok]
                if not len(j):
                    continue
                j0, j1_, i0, i1_ = np.clip(j - r, 0, W), np.clip(j + r + 1, 0, W), np.clip(i - r, 0, H), np.clip(i + r + 1, 0, H)
                np.add.at(diff, (i0, j0), 1)
                np.add.at(diff, (i0, j1_), -1)
                np.add.at(diff, (i1_, j0), -1)
                np.add.at(diff, (i1_, j1_), 1)
        return diff.cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)[:H, :W] > 0

    def boite(m, k):
        """moyenne glissante k x k (m: tableau float), bords répliqués"""
        r = k // 2
        p = np.pad(m, r, mode="edge").astype(np.float32)
        c = np.pad(p.cumsum(0, dtype=np.float64).cumsum(1, dtype=np.float64), ((1, 0), (1, 0)))
        return ((c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / float(k * k)).astype(np.float32)

    def masque(rgb_u8, dem, step, cor, k_ouv):
        im = rgb_u8.astype(np.float32) / 255.0
        mx, mn = im.max(2), im.min(2)
        sat = (mx - mn) / np.maximum(mx, 1e-3)
        lum = im.mean(2)
        gy, gx = np.gradient(boite(dem, 3) if step < 1 else dem, step)
        pente = np.hypot(gx, gy)
        m = (sat < a.sat) & (lum > a.lum) & (pente < a.pente) & cor
        r = (m.astype(np.float32))
        er = boite(r, k_ouv) > 0.999                  # ouverture: érosion puis dilatation (supprime routes et sentiers étroits)
        di = boite(er.astype(np.float32), k_ouv) > 0.001
        return (di & m)

    cx, cy = Ec, Nc

    def apercu(nom, rgb, m, step, x0, y1, demi_w):
        j, i = int((cx - x0) / step), int((y1 - cy) / step)
        j0, i0 = max(j - demi_w, 0), max(i - demi_w, 0)
        c = rgb[i0:i + demi_w, j0:j + demi_w].astype(np.float32) / 255.0
        mm = m[i0:i + demi_w, j0:j + demi_w]
        c[mm] = c[mm] * 0.35 + np.array([0.1, 0.4, 1.0]) * 0.65
        ecrire_png(os.path.join(sortie, nom), (c * 255).astype(np.uint8))

    res = {}
    # ---- zone entière à 2 m
    o = meta.get("ortho")
    d2 = meta.get("dem2")
    if o and d2 and os.path.exists(os.path.join(env, o["file"])) and abs(o["step"] - d2["step"]) < 1e-6 and o["shape"] == d2["shape"]:
        H, W = o["shape"]
        rgb = lire_rgb(os.path.join(env, o["file"]))
        dem = np.load(os.path.join(env, d2["file"]), mmap_mode="r")
        cor = couloir(o["x0"], o["y1"], o["step"], H, W)
        log(f"2 m: couloir {cor.mean() * 100:.1f} % de la zone")
        m = np.zeros((H, W), bool)
        for r0 in range(0, H, 1024):                    # par bandes (mémoire), avec 4 lignes de recouvrement pour la pente et l'ouverture
            ra, rb = max(r0 - 4, 0), min(r0 + 1024 + 4, H)
            mb = masque(rgb[ra:rb], np.array(dem[ra:rb], np.float32), o["step"], cor[ra:rb], 3)
            m[r0:min(r0 + 1024, H)] = mb[r0 - ra:r0 - ra + min(1024, H - r0)]
        log(f"2 m: eau {m.sum() * o['step'] ** 2 / 1e6:.2f} km2")
        apercu("eau_apercu_2m.png", rgb, m, o["step"], o["x0"], o["y1"], 500)
        # mémoire de la carte graphique: on ne garde que le rectangle qui contient de l'eau, à 4 m (l'eau proche a son masque à 0,5 m)
        ii, jj = np.nonzero(m)
        if len(ii):
            i0, i1 = max(ii.min() - 8, 0) // 2 * 2, min(ii.max() + 9, H) // 2 * 2
            j0, j1 = max(jj.min() - 8, 0) // 2 * 2, min(jj.max() + 9, W) // 2 * 2
        else:
            i0, i1, j0, j1 = 0, 2, 0, 2
        mc = m[i0:i1, j0:j1].astype(np.float32)
        mc = mc.reshape(mc.shape[0] // 2, 2, mc.shape[1] // 2, 2).mean(axis=(1, 3))
        sm = (np.clip(boite(mc, 3) * 1.3, 0, 1) * 255).astype(np.uint8)
        ecrire_png(os.path.join(sortie, "eau_masque.png"), sm)
        res["grossier"] = dict(file="eau_masque.png", x0=o["x0"] + j0 * o["step"], y1=o["y1"] - i0 * o["step"], step=o["step"] * 2,
                               shape=[int(sm.shape[0]), int(sm.shape[1])])
        log(f"2 m: masque recadré {sm.shape[1]} x {sm.shape[0]} à 4 m (au lieu de {W} x {H})")
        del rgb, m, sm, cor
    else:
        log("image 2 m ou relief 2 m absents ou de tailles différentes: pas de masque lointain")
    # ---- zone fine 0,5 m (image 50 cm)
    pf = [q for q in meta.get("ortho_patches", []) if abs(q["step"] - 0.5) < 1e-6]
    d5 = meta.get("dem05")
    if pf and d5 and os.path.exists(os.path.join(env, pf[0]["file"])):
        q = pf[0]
        H, W = q["shape"]
        rgb = lire_rgb(os.path.join(env, q["file"]))
        full = np.load(os.path.join(env, d5["file"]), mmap_mode="r")
        r0, c0 = int(round((d5["y1"] - q["y1"]) / 0.5)), int(round((q["x0"] - d5["x0"]) / 0.5))
        if r0 >= 0 and c0 >= 0 and r0 + H <= d5["shape"][0] and c0 + W <= d5["shape"][1]:
            dem = np.array(full[r0:r0 + H, c0:c0 + W], np.float32)
        else:                                            # emprise 50 cm plus grande que le relief fin: pas de contrainte de pente
            dem = np.zeros((H, W), np.float32)
            log("0,5 m: l'image dépasse le relief fin, pente ignorée")
        cor = couloir(q["x0"], q["y1"], 0.5, H, W)
        m = masque(rgb, dem, 0.5, cor, 7)
        log(f"0,5 m: eau {m.sum() * 0.25 / 1e6:.3f} km2")
        apercu("eau_apercu_50cm.png", rgb, m, 0.5, q["x0"], q["y1"], 500)
        sm = (boite(m.astype(np.float32), 5) * 255).astype(np.uint8)
        ecrire_png(os.path.join(sortie, "eau_masque_fin.png"), sm)
        res["fin"] = dict(file="eau_masque_fin.png", x0=q["x0"], y1=q["y1"], step=0.5, shape=[H, W])
    if not res:
        sys.exit("Aucun masque d'eau produit (image aérienne absente: préparer d'abord l'environnement).")
    if a.sortie:
        log(f"test: images écrites dans {sortie}, env_meta.json inchangé")
        return
    meta["eau"] = dict(file="eau.npz", lignes=len(debut), longueur_km=float(sum(np.hypot(*np.diff(p_, axis=0).T).sum() for p_ in pts) / 1000),
                       noms=sorted({x for x in noms if x}), created=time.strftime("%Y-%m-%d %H:%M"))
    meta["eau_masque"] = dict(res, couloir=a.couloir, sat=a.sat, lum=a.lum, created=time.strftime("%Y-%m-%d %H:%M"))
    json.dump(meta, open(mp, "w"), indent=1)
    log("écrit eau_masque.png" + (" et eau_masque_fin.png" if "fin" in res else "") + ". À regarder: eau_apercu_2m.png et eau_apercu_50cm.png (eau en bleu).")


main()
