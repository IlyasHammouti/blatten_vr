"""
prep_vegetation.py : arbres d'après le modèle de surface swissSURFACE3D (0,5 m) moins le relief nu.

Hauteur de canopée = surface - relief 0,5 m. Les bâtiments (prep-batiments) sont retirés, les sommets de canopée locaux
(>= 3 m) deviennent des arbres (position, hauteur, rayon de couronne, pente du sol). Les blocs de roche isolés sont écartés
par un critère de peuplement (un arbre isolé doit dépasser 7 m). L'essence vient du taux de mélange des forêts de l'OFEV
(swisstopo/waldmischungsgrad, 10 m: part de feuillus) et de l'altitude (épicéa, mélèze, pin cembro).
Au-delà de l'emprise 0,5 m, jusqu'à --rayon (4600 m) autour de la caméra, les arbres viennent du modèle de surface à 2 m
(swisstopo/swisssurface3d_raster_2m, menu 21), moins précis (peuplements plutôt qu'arbres isolés).
Tous les arbres gardent leur taille réelle, quelle que soit la distance (seul le détail du maillage baisse, côté scène).
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


def flou3(a):
    """Lissage [1 2 1] séparable (pour la grille à 2 m, où le 5x5 écraserait les couronnes)."""
    p = np.pad(a, 1, mode="edge")
    t = 0.25 * p[:, :-2] + 0.5 * p[:, 1:-1] + 0.25 * p[:, 2:]
    return 0.25 * t[:-2] + 0.5 * t[1:-1] + 0.25 * t[2:]


def mosaique(dossier, x0, y1, W, H, step, max_year, motif_res=None):
    """Assemble les dalles d'un dossier sur la grille (x0, y1, step, H x W). Rend (tableau, nombre de dalles)."""
    dsm = np.full((H, W), np.nan, np.float32)
    n = 0
    for p in sorted(glob.glob(os.path.join(dossier, "*.tif*"))):
        m = re.search(r"_(\d{4})_", os.path.basename(p))
        if m and int(m.group(1)) > max_year:
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
    return dsm, n


def detecter(nd, step, hmin, fin):
    """Sommets de canopée (indices i, j, hauteur). fin=True: grille 0,5 m (arbres isolés), sinon grille 2 m (peuplements)."""
    H, W = nd.shape
    if fin:
        ns, rm, k, seuil = flou(nd), 3, 13, 0.18
    else:
        ns, rm, k, seuil = flou3(nd), 1, 5, 0.30
    cand = maxima_locaux(ns, rm) & (ns >= hmin)
    dense = (ns >= 2.0).astype(np.int32)
    a, b = k // 2 + 1, k // 2
    c = np.pad(dense, ((a, b), (a, b))).cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
    dens = (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k])[:H, :W] / float(k * k)
    ii, jj = np.nonzero(cand & ((dens >= seuil) | (ns >= 7.0)))
    return ii, jj, ns[ii, jj].astype(np.float32), int(cand.sum())


def part_verte(meta, env, E, N):
    """Part de vert G/(R+G+B) de l'image aérienne aux points (E, N): image 0,5 m là où elle existe, sinon image 2 m."""
    out = np.full(len(E), np.nan, np.float32)
    srcs = [o for o in (meta.get("ortho_patches") or []) if abs(o["step"] - 0.5) < 1e-6] + ([meta["ortho"]] if meta.get("ortho") else [])
    for o in srcs:
        f = os.path.join(env, o["file"])
        if not os.path.exists(f):
            continue
        H_, W_ = o["shape"]
        j = np.floor((E - o["x0"]) / o["step"]).astype(np.int64)
        i = np.floor((o["y1"] - N) / o["step"]).astype(np.int64)
        ok = np.isnan(out) & (j >= 0) & (j < W_) & (i >= 0) & (i < H_)
        if not ok.any():
            continue
        img = imagecodecs.jpeg8_decode(open(f, "rb").read())
        px = img[i[ok], j[ok], :3].astype(np.float32)
        out[ok] = px[:, 1] / np.maximum(px.sum(1), 1.0)
        del img
    return out


def pente_sol(dem, ii, jj, step, demi=8.0):
    H, W = dem.shape
    d = max(int(round(demi / 2 / step)), 1)
    i2, j2 = np.clip(ii, d, H - d - 1), np.clip(jj, d, W - d - 1)
    gx = (dem[i2, j2 + d] - dem[i2, j2 - d]) / (2 * d * step)
    gy = (dem[i2 + d, j2] - dem[i2 - d, j2]) / (2 * d * step)
    return np.hypot(gx, gy).astype(np.float32)


def melange(fm, E, N, ex0, ey0, ex1, ey1):
    """Part de feuillus (0..1) du raster OFEV aux points (E, N); -1 si inconnu."""
    pf = np.full(len(E), -1.0)
    if not fm or not len(E):
        return pf
    w = lire_fenetre(fm[0], ex0, ey0, ex1, ey1)
    if w is None:
        return pf
    arr, wx0, wy1, wst = w
    vals = arr[np.clip(((wy1 - N) / wst).astype(int), 0, arr.shape[0] - 1), np.clip(((E - wx0) / wst).astype(int), 0, arr.shape[1] - 1)].astype(np.float32)
    bon = vals <= 100
    return np.where(bon, vals / 100.0, -1.0)


def main():
    ap = argparse.ArgumentParser(prog="prep_vegetation")
    ap.add_argument("--swisstopo", default=os.path.join(ROOT, "data", "swisstopo"))
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--max-year", type=int, default=2024, help="année maximale du modèle de surface (événement: 2025)")
    ap.add_argument("--hmin", type=float, default=3.0, help="hauteur minimale d'un arbre (m)")
    ap.add_argument("--rayon", type=float, default=4600.0, help="rayon (m) autour de la caméra des arbres lointains (modèle à 2 m); 0 = emprise 0,5 m seulement")
    ap.add_argument("--arbustes", type=float, default=0.37, help="arbustes (aulne vert, 0,8 à 3 m) sur la zone 0,5 m: part de vert minimale de l'image aérienne (évite les blocs de roche); 0 = pas d'arbustes")
    ap.add_argument("--vert", type=float, default=0.0, help="part de vert minimale de l'image aérienne; 0 = pas de filtre (défaut: les pentes à l'ombre seraient écartées)")
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
    dz = meta.get("dz", 0.0)
    try:
        cam = json.load(open(os.path.join(ROOT, "camera.json")))["cam"]
    except Exception:
        cam = [0.0, 0.0, 0.0]
    Ec, Nc = meta["scene_E0"] + cam[0], meta["scene_N0"] + meta["flip"] * cam[1]
    fm = glob.glob(os.path.join(a.swisstopo, "waldmischungsgrad", "*.tif*"))
    if not fm:
        log("taux de mélange OFEV absent (menu 21 le télécharge): feuillus estimés d'après l'altitude")
    zones = []     # (E, N, h, zg, pente, pf)

    # ---- zone fine 0,5 m
    dem = np.load(os.path.join(env, d5["file"]))
    x0, y1, step = d5["x0"], d5["y1"], d5["step"]
    H, W = dem.shape
    dsm, n = mosaique(os.path.join(a.swisstopo, "swisssurface3d_raster_05m"), x0, y1, W, H, step, a.max_year)
    if not n:
        sys.exit("Aucune dalle de modèle de surface (menu 21: télécharger la canopée).")
    log(f"zone fine 0,5 m: {n} dalle(s), {np.isfinite(dsm).mean() * 100:.0f} % couverte ({time.time() - t0:.0f} s)")
    nd = np.clip(np.where(np.isfinite(dsm), dsm - dem, 0.0).astype(np.float32), 0, 60)
    nd[masque_batiments(env, meta, nd.shape, x0, y1, step)] = 0
    del dsm
    ii, jj, h, nc = detecter(nd, step, a.hmin, True)
    log(f"  {nc:,} sommets >= {a.hmin:g} m, {len(h):,} gardés (peuplement)")
    E = x0 + (jj + 0.5) * step
    N = y1 - (ii + 0.5) * step
    if a.vert > 0:
        o = meta.get("ortho")
        if o and imagecodecs is not None and os.path.exists(os.path.join(env, o["file"])):
            img = imagecodecs.jpeg8_decode(open(os.path.join(env, o["file"]), "rb").read())
            oj = np.clip(((E - o["x0"]) / o["step"]).astype(int), 0, img.shape[1] - 1)
            oi = np.clip(((o["y1"] - N) / o["step"]).astype(int), 0, img.shape[0] - 1)
            px = img[oi, oj, :3].astype(np.float32)
            ok = px[:, 1] / np.maximum(px.sum(1), 1.0) >= a.vert
            log(f"  filtre vert >= {a.vert:g}: {ok.sum():,} gardés")
            ii, jj, h, E, N = ii[ok], jj[ok], h[ok], E[ok], N[ok]
    zones.append((E, N, h, dem[ii, jj].astype(np.float32) + dz, pente_sol(dem, ii, jj, step), melange(fm, E, N, x0, y1 - H * step, x0 + W * step, y1)))
    n_fin = len(h)
    ext = (x0, y1 - H * step, x0 + W * step, y1)
    arb = None
    if a.arbustes > 0 and imagecodecs is not None:
        ns = flou(nd)
        bas = (ns >= 0.8) & (ns < 3.5)
        cand = maxima_locaux(ns, 3) & bas
        dens = np.pad(bas.astype(np.int32), ((7, 6), (7, 6))).cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
        k = 13
        dens = (dens[k:, k:] - dens[:-k, k:] - dens[k:, :-k] + dens[:-k, :-k])[:H, :W] / float(k * k)
        ii_, jj_ = np.nonzero(cand & (dens >= 0.5))
        Es, Ns = x0 + (jj_ + 0.5) * step, y1 - (ii_ + 0.5) * step
        vv = part_verte(meta, env, Es, Ns)
        ok = np.nan_to_num(vv, nan=0.0) >= a.arbustes
        pe = pente_sol(dem, ii_, jj_, step)
        zs = dem[ii_, jj_].astype(np.float32) + dz
        ok &= (pe < 0.75) & (zs > 1500) & (zs < 2350)
        arb = (Es[ok], Ns[ok], ns[ii_, jj_][ok].astype(np.float32), zs[ok], pe[ok])
        log(f"  arbustes: {len(arb[0]):,} (sur {len(ii_):,} bosquets bas; vert >= {a.arbustes:g}, pente < 37 degrés)")
    elif a.arbustes > 0:
        log("  arbustes ignorés (imagecodecs absent)")
    # masque de canopée (grille 2 m): sert à remplacer, dans l'image aérienne, la cime des arbres par un sol de forêt
    f4 = max(int(round(2.0 / step)), 1)
    h4, w4 = H // f4 * f4, W // f4 * f4
    m_fin = (flou(nd) >= 2.0).astype(np.float32)[:h4, :w4].reshape(h4 // f4, f4, w4 // f4, f4).mean(axis=(1, 3))
    mask_grid = (m_fin, x0, y1)
    del nd
    del dem

    # ---- zone lointaine 2 m
    d2 = meta.get("dem2")
    dossier2 = os.path.join(a.swisstopo, "swisssurface3d_raster_2m")
    if a.rayon > 0 and d2 and glob.glob(os.path.join(dossier2, "*.tif*")):
        s2 = d2["step"]
        gx0, gy1 = d2["x0"], d2["y1"]
        wx0 = max(np.floor((Ec - a.rayon - gx0) / s2) * s2 + gx0, gx0)
        wy1 = min(gy1 - np.floor((gy1 - (Nc + a.rayon)) / s2) * s2, gy1)
        Wf = int(min(2 * a.rayon / s2, d2["shape"][1] - (wx0 - gx0) / s2))
        Hf = int(min(2 * a.rayon / s2, d2["shape"][0] - (gy1 - wy1) / s2))
        full = np.load(os.path.join(env, d2["file"]), mmap_mode="r")
        r0, c0 = int(round((gy1 - wy1) / s2)), int(round((wx0 - gx0) / s2))
        dem2 = np.array(full[r0:r0 + Hf, c0:c0 + Wf], np.float32)
        dsm2, n2 = mosaique(dossier2, wx0, wy1, Wf, Hf, s2, a.max_year)
        log(f"zone lointaine 2 m: {n2} dalle(s), {np.isfinite(dsm2).mean() * 100:.0f} % couverte, rayon {a.rayon:.0f} m")
        nd2 = np.clip(np.where(np.isfinite(dsm2), dsm2 - dem2, 0.0).astype(np.float32), 0, 60)
        del dsm2
        nd2[masque_batiments(env, meta, nd2.shape, wx0, wy1, s2)] = 0
        m2 = (flou3(nd2) >= 2.0).astype(np.float32)
        oi_, oj_ = int(round((x0 - wx0) / s2)), int(round((wy1 - y1) / s2))
        mf, hh, ww = mask_grid[0], mask_grid[0].shape[0], mask_grid[0].shape[1]
        if oi_ >= 0 and oj_ >= 0 and oj_ + hh <= m2.shape[0] and oi_ + ww <= m2.shape[1]:
            m2[oj_:oj_ + hh, oi_:oi_ + ww] = mf
            mask_grid = (m2, wx0, wy1)
        ii, jj, h, nc = detecter(nd2, s2, a.hmin, False)
        log(f"  {nc:,} sommets >= {a.hmin:g} m, {len(h):,} gardés")
        E = wx0 + (jj + 0.5) * s2
        N = wy1 - (ii + 0.5) * s2
        hors = ~((E >= ext[0]) & (E <= ext[2]) & (N >= ext[1]) & (N <= ext[3]))     # déjà couvert à 0,5 m
        hors &= np.hypot(E - Ec, N - Nc) <= a.rayon
        ii, jj, h, E, N = ii[hors], jj[hors], h[hors], E[hors], N[hors]
        zones.append((E, N, h, dem2[ii, jj] + dz, pente_sol(dem2, ii, jj, s2), melange(fm, E, N, wx0, wy1 - Hf * s2, wx0 + Wf * s2, wy1)))
        log(f"  {len(h):,} arbres hors de l'emprise 0,5 m")
    else:
        log("pas de zone lointaine (modèle de surface 2 m absent: menu 21, ou --rayon 0)")

    E, N, h, zg, pente, pf = [np.concatenate([z[k] for z in zones]) for k in range(6)]
    # toutes les couronnes gardent leur taille réelle (pas d'amincissement ni d'agrandissement avec la distance)
    rng = np.random.default_rng(11)
    defaut = np.interp(zg, [1500, 1800], [0.20, 0.04])
    pf = np.where(pf >= 0, pf, defaut)
    sp = choisir_essences(zg, h, pf, rng)
    coef = np.array([[0.15, 0.5, 4.5], [0.18, 0.7, 4.5], [0.24, 0.8, 5.0], [0.28, 1.0, 6.0]], np.float32)   # a*h + b, plafond
    r = np.minimum(coef[sp, 0] * h + coef[sp, 1], coef[sp, 2]).astype(np.float32)
    if arb is not None and len(arb[0]):
        Es, Ns, hs, zs, ps = arb
        if len(hs) > 600000:                                                               # plafond du budget: tirage au hasard, rayons inchangés
            oks = rng.random(len(hs)) < 600000.0 / len(hs)
            Es, Ns, hs, zs, ps = Es[oks], Ns[oks], hs[oks], zs[oks], ps[oks]
        rs = np.minimum(0.55 * hs + 0.5, 2.2).astype(np.float32)
        E, N, h, zg, pente = (np.concatenate([u, v]) for u, v in ((E, Es), (N, Ns), (h, hs), (zg, zs), (pente, ps)))
        sp = np.concatenate([sp, np.full(len(hs), 4, np.int8)])
        r = np.concatenate([r, rs])
        log(f"  {len(hs):,} arbustes gardés")
    X = (E - meta["scene_E0"]).astype(np.float32)
    Y = (meta["flip"] * (N - meta["scene_N0"])).astype(np.float32)
    np.savez_compressed(os.path.join(env, "vegetation.npz"), x=X, y=Y, z=zg.astype(np.float32), h=h, r=r, pente=pente, sp=sp)
    if imagecodecs is not None:
        mg, mx0, my1 = mask_grid
        png = imagecodecs.png_encode((np.clip(mg, 0, 1) * 255).astype(np.uint8))
        with open(os.path.join(env, "canopee_masque.png"), "wb") as fh:
            fh.write(png)
        meta["canopee_masque"] = dict(file="canopee_masque.png", x0=float(mx0), y1=float(my1), step=2.0, shape=[int(mg.shape[0]), int(mg.shape[1])])
        log(f"masque de canopée écrit ({mg.shape[1]} x {mg.shape[0]} à 2 m, {mg.mean() * 100:.0f} % couvert)")
    meta["vegetation"] = dict(file="vegetation.npz", arbres=int(len(h)), arbres_fins=int(n_fin), hmin=a.hmin, vert=a.vert, melange=bool(fm),
                              rayon=a.rayon, max_year=a.max_year, created=time.strftime("%Y-%m-%d %H:%M"))
    json.dump(meta, open(mp, "w"), indent=1)
    log(f"{len(h):,} arbres, hauteur médiane {np.median(h):.1f} m, max {h.max():.1f} m")
    log("essences: " + ", ".join(f"{nom} {int((sp == i).sum()):,}" for i, nom in enumerate(("épicéa", "mélèze", "pin cembro", "feuillus", "arbustes"))))
    log(f"écrit vegetation.npz ({time.time() - t0:.0f} s)")


main()
