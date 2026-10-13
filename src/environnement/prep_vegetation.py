"""
prep_vegetation.py : arbres d'après le modèle de surface swissSURFACE3D (0,5 m) moins le relief nu.

Hauteur de canopée = surface - relief 0,5 m. Les bâtiments (prep-batiments) sont retirés, les sommets de canopée locaux
(>= 3 m) deviennent des arbres (position, hauteur, rayon de couronne, pente du sol). Les blocs de roche isolés sont écartés
par un critère de peuplement (un arbre isolé doit dépasser 7 m). L'essence vient du taux de mélange des forêts de l'OFEV
(swisstopo/waldmischungsgrad, 10 m: part de feuillus) et de l'altitude (épicéa, mélèze, pin cembro).
Écrit <cache>/env/vegetation.npz et l'entrée "vegetation" de env_meta.json.

Utilisation (via blatten.py):  python blatten.py prep-vegetation [--hmin 3]
"""
import argparse
import glob
import json
import os
import re
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
ROOT = os.environ.get("BLATTEN_ROOT") or os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, ".pylibs"))
try:
    import tifffile
except ImportError:
    tifffile = None
try:
    import imagecodecs
except ImportError:
    imagecodecs = None


def log(*a):
    print("[vegetation]", *a, flush=True)


def lire_dalle(path):
    with tifffile.TiffFile(path) as tf:
        pg = tf.pages[0]
        a = pg.asarray().astype(np.float32)
        sc, tp = pg.tags["ModelPixelScaleTag"].value, pg.tags["ModelTiepointTag"].value
        step = float(sc[0])
        x0 = float(tp[3]) - float(tp[0]) * step
        y1 = float(tp[4]) + float(tp[1]) * float(sc[1])
    if a.ndim == 3:
        a = a[..., 0]
    a[(a < -1000) | (a > 9000)] = np.nan
    return a, x0, y1, step


def lire_fenetre(path, ex0, ey0, ex1, ey1):
    """Fenêtre [ex0,ex1] x [ey0,ey1] (LV95) d'un GeoTIFF tuilé (ex. le raster national à 10 m), décodée tuile par tuile
    pour ne pas charger tout le pays. Rend (tableau, x0, y1, pas)."""
    with tifffile.TiffFile(path) as tf:
        pg = tf.pages[0]
        sc, tp = pg.tags["ModelPixelScaleTag"].value, pg.tags["ModelTiepointTag"].value
        st = float(sc[0])
        gx0 = float(tp[3]) - float(tp[0]) * st
        gy1 = float(tp[4]) + float(tp[1]) * float(sc[1])
        W, H = pg.imagewidth, pg.imagelength
        j0, j1 = max(int((ex0 - gx0) // st), 0), min(int((ex1 - gx0) // st) + 1, W)
        i0, i1 = max(int((gy1 - ey1) // st), 0), min(int((gy1 - ey0) // st) + 1, H)
        if j1 <= j0 or i1 <= i0:
            return None
        out = np.full((i1 - i0, j1 - j0), 255, np.uint8)
        if not pg.is_tiled:
            a = pg.asarray()
            if a.ndim == 3:
                a = a[..., 0]
            out[:] = a[i0:i1, j0:j1]
        else:
            tw, tl = pg.tilewidth, pg.tilelength
            ntx = (W + tw - 1) // tw
            fh = tf.filehandle
            for ty in range(i0 // tl, (i1 - 1) // tl + 1):
                for tx in range(j0 // tw, (j1 - 1) // tw + 1):
                    k = ty * ntx + tx
                    fh.seek(pg.dataoffsets[k])
                    data = fh.read(pg.databytecounts[k])
                    seg = pg.decode(data, k)[0]
                    seg = np.asarray(seg).reshape(seg.shape[-3:] if seg.ndim >= 3 else seg.shape)
                    if seg.ndim == 3:
                        seg = seg[..., 0]
                    sy0, sx0 = ty * tl, tx * tw
                    a0, a1 = max(sy0, i0), min(sy0 + seg.shape[0], i1)
                    b0, b1 = max(sx0, j0), min(sx0 + seg.shape[1], j1)
                    if a1 > a0 and b1 > b0:
                        out[a0 - i0:a1 - i0, b0 - j0:b1 - j0] = seg[a0 - sy0:a1 - sy0, b0 - sx0:b1 - sx0]
        return out, gx0 + j0 * st, gy1 - i0 * st, st


def choisir_essences(alt, h, pfeuillus, rng):
    """0 épicéa, 1 mélèze, 2 pin cembro, 3 feuillus (bouleau, sorbier, aulne)."""
    n = len(alt)
    u, v = rng.random(n), rng.random(n)
    sp = np.zeros(n, np.int8)
    p_ep = np.interp(alt, [1700, 2050], [0.65, 0.07])
    p_ml = np.interp(alt, [1700, 2050], [0.30, 0.50])
    sp[(u >= p_ep) & (u < p_ep + p_ml)] = 1
    sp[u >= p_ep + p_ml] = 2
    sp[(sp == 2) & (h > 20)] = 1                       # un pin cembro dépasse rarement 20 m
    sp[v < pfeuillus] = 3
    return sp


def flou(a):
    """Lissage binomial 5x5 (équivalent d'un flou gaussien de ~1 pixel)."""
    k = np.array([1, 4, 6, 4, 1], np.float32) / 16
    p = np.pad(a, 2, mode="edge")
    t = sum(k[i] * p[:, i:i + a.shape[1]] for i in range(5))
    return sum(k[i] * t[i:i + a.shape[0], :] for i in range(5))


def maxima_locaux(a, r=2):
    p = np.pad(a, r, mode="constant", constant_values=-1e9)
    m = np.full(a.shape, -1e9, np.float32)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            m = np.maximum(m, p[r + dy:r + dy + a.shape[0], r + dx:r + dx + a.shape[1]])
    return a >= m


def masque_batiments(env, meta, shape, x0, y1, step):
    """Pixels recouverts par un bâtiment (projection des triangles), élargis d'un pixel."""
    p = os.path.join(env, "batiments.npz")
    mk = np.zeros(shape, bool)
    if not os.path.exists(p):
        log("pas de bâtiments préparés: les toits risquent d'être pris pour des arbres (lancer prep-batiments d'abord)")
        return mk
    z = np.load(p)
    V, T = z["v"].astype(np.float64), z["t"]
    E = meta["scene_E0"] + V[:, 0]
    N = meta["scene_N0"] + meta["flip"] * V[:, 1]
    c = (E - x0) / step
    r = (y1 - N) / step
    for tri in T:
        cc, rr = c[tri], r[tri]
        j0, j1 = int(np.floor(cc.min())), int(np.ceil(cc.max()))
        i0, i1 = int(np.floor(rr.min())), int(np.ceil(rr.max()))
        if j1 < 0 or i1 < 0 or j0 >= shape[1] or i0 >= shape[0]:
            continue
        j0, i0 = max(j0, 0), max(i0, 0)
        j1, i1 = min(j1, shape[1] - 1), min(i1, shape[0] - 1)
        mk[i0:i1 + 1, j0:j1 + 1] = True      # boîte englobante du triangle (un peu large: sûr pour exclure les toits)
    out = mk.copy()
    out[1:] |= mk[:-1]; out[:-1] |= mk[1:]; out[:, 1:] |= mk[:, :-1]; out[:, :-1] |= mk[:, 1:]
    return out


def main():
    ap = argparse.ArgumentParser(prog="prep_vegetation")
    ap.add_argument("--swisstopo", default=os.path.join(ROOT, "data", "swisstopo"))
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--max-year", type=int, default=2024, help="année maximale du modèle de surface (événement: 2025)")
    ap.add_argument("--hmin", type=float, default=3.0, help="hauteur minimale d'un arbre (m)")
    ap.add_argument("--vert", type=float, default=0.0, help="part de vert minimale (G / (R+G+B)) de l'image aérienne; 0 = pas de filtre (défaut: les pentes à l'ombre seraient écartées)")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    if tifffile is None:
        sys.exit("tifffile absent: lancer l'installation (menu 2).")
    env = os.path.join(a.data, "env")
    mp = os.path.join(env, "env_meta.json")
    meta = json.load(open(mp))
    d5 = meta.get("dem05")
    if not d5:
        sys.exit("Pas de relief 0,5 m: faire d'abord la préparation de la haute résolution (menu 7).")
    t0 = time.time()
    dem = np.load(os.path.join(env, d5["file"]))
    x0, y1, step = d5["x0"], d5["y1"], d5["step"]
    H, W = dem.shape
    dsm = np.full((H, W), np.nan, np.float32)
    n = 0
    for p in sorted(glob.glob(os.path.join(a.swisstopo, "swisssurface3d_raster_05m", "*.tif*"))):
        m = re.search(r"_(\d{4})_", os.path.basename(p))
        if m and int(m.group(1)) > a.max_year:
            log(f"ignorée (postérieure à {a.max_year}): {os.path.basename(p)}")
            continue
        t, tx0, ty1, ts = lire_dalle(p)
        if abs(ts - step) > 1e-6:
            log(f"{os.path.basename(p)}: pas {ts} m au lieu de {step} m, ignorée")
            continue
        j, i = int(round((tx0 - x0) / step)), int(round((y1 - ty1) / step))
        i0, j0 = max(i, 0), max(j, 0)
        i1, j1 = min(i + t.shape[0], H), min(j + t.shape[1], W)
        if i1 <= i0 or j1 <= j0:
            continue
        dsm[i0:i1, j0:j1] = t[i0 - i:i1 - i, j0 - j:j1 - j]
        n += 1
    if not n:
        sys.exit("Aucune dalle de modèle de surface (menu 21: télécharger la canopée).")
    couv = np.isfinite(dsm).mean() * 100
    log(f"{n} dalle(s) de surface, {couv:.0f} % de la zone 0,5 m couverte ({time.time() - t0:.0f} s)")
    nd = np.where(np.isfinite(dsm), dsm - dem, 0.0).astype(np.float32)
    nd = np.clip(nd, 0, 60)
    nd[masque_batiments(env, meta, nd.shape, x0, y1, step)] = 0
    ns = flou(nd)
    cand = maxima_locaux(ns, 3) & (ns >= a.hmin)
    # peuplement: part de pixels hauts (>= 2 m) dans un rayon de 3 m. Un bloc de roche isolé n'est pas un arbre.
    dense = (ns >= 2.0).astype(np.int32)
    c = np.pad(dense, ((7, 6), (7, 6))).cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
    k = 13
    dens = (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k])[:H, :W] / float(k * k)
    ii, jj = np.nonzero(cand & ((dens >= 0.18) | (ns >= 7.0)))
    h = ns[ii, jj].astype(np.float32)
    E = x0 + (jj + 0.5) * step
    N = y1 - (ii + 0.5) * step
    log(f"{cand.sum():,} sommets de canopée >= {a.hmin:g} m, {len(h):,} gardés (peuplement)")
    if a.vert > 0:
        o = meta.get("ortho")
        if o and imagecodecs is not None and os.path.exists(os.path.join(env, o["file"])):
            img = imagecodecs.jpeg8_decode(open(os.path.join(env, o["file"]), "rb").read())
            oj = np.clip(((E - o["x0"]) / o["step"]).astype(int), 0, img.shape[1] - 1)
            oi = np.clip(((o["y1"] - N) / o["step"]).astype(int), 0, img.shape[0] - 1)
            px = img[oi, oj, :3].astype(np.float32)
            ok = px[:, 1] / np.maximum(px.sum(1), 1.0) >= a.vert
            log(f"filtre vert >= {a.vert:g}: {ok.sum():,} gardés, {(~ok).sum():,} écartés")
            ii, jj, h, E, N = ii[ok], jj[ok], h[ok], E[ok], N[ok]
    zg = dem[ii, jj].astype(np.float32) + meta.get("dz", 0.0)
    # pente du sol (tangente) sur 2 m autour de l'arbre
    i2, j2 = np.clip(ii, 4, H - 5), np.clip(jj, 4, W - 5)
    gx = (dem[i2, j2 + 4] - dem[i2, j2 - 4]) / (8 * step)
    gy = (dem[i2 + 4, j2] - dem[i2 - 4, j2]) / (8 * step)
    pente = np.hypot(gx, gy).astype(np.float32)
    # essences
    pf = np.full(len(h), -1.0)
    fm = glob.glob(os.path.join(a.swisstopo, "waldmischungsgrad", "*.tif*"))
    if fm:
        w = lire_fenetre(fm[0], x0, y1 - H * step, x0 + W * step, y1)
        if w is not None:
            arr, wx0, wy1, wst = w
            vals = arr[np.clip(((wy1 - N) / wst).astype(int), 0, arr.shape[0] - 1), np.clip(((E - wx0) / wst).astype(int), 0, arr.shape[1] - 1)].astype(np.float32)
            bon = vals <= 100
            pf = np.where(bon, vals / 100.0, -1.0)
            log(f"taux de mélange OFEV lu: part de feuillus moyenne {pf[bon].mean() * 100:.0f} % ({bon.mean() * 100:.0f} % des arbres couverts)")
    else:
        log("taux de mélange OFEV absent (menu 21 le télécharge): feuillus estimés d'après l'altitude")
    defaut = np.interp(zg, [1500, 1800], [0.20, 0.04])
    pf = np.where(pf >= 0, pf, defaut)
    rng = np.random.default_rng(11)
    sp = choisir_essences(zg, h, pf, rng)
    coef = np.array([[0.15, 0.5, 4.5], [0.18, 0.7, 4.5], [0.24, 0.8, 5.0], [0.28, 1.0, 6.0]], np.float32)   # a*h + b, plafond
    r = np.minimum(coef[sp, 0] * h + coef[sp, 1], coef[sp, 2]).astype(np.float32)
    X = (E - meta["scene_E0"]).astype(np.float32)
    Y = (meta["flip"] * (N - meta["scene_N0"])).astype(np.float32)
    np.savez_compressed(os.path.join(env, "vegetation.npz"), x=X, y=Y, z=zg, h=h, r=r, pente=pente, sp=sp)
    meta["vegetation"] = dict(file="vegetation.npz", arbres=int(len(h)), hmin=a.hmin, vert=a.vert, melange=bool(fm), max_year=a.max_year,
                              created=time.strftime("%Y-%m-%d %H:%M"))
    json.dump(meta, open(mp, "w"), indent=1)
    log(f"{len(h):,} arbres, hauteur médiane {np.median(h):.1f} m, max {h.max():.1f} m")
    log("essences: " + ", ".join(f"{nom} {int((sp == i).sum()):,}" for i, nom in enumerate(("épicéa", "mélèze", "pin cembro", "feuillus"))))
    log(f"écrit vegetation.npz ({time.time() - t0:.0f} s)")


main()
