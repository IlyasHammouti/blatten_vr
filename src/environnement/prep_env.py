"""
prep_env.py : prépare l'environnement réaliste (relief + image aérienne swisstopo)
et le cale sur le repère du terrain de Johan Gaume.

Entrées
  - swisstopo/swissalti3d_2m/*.tif   dalles swissALTI3D (modèle de terrain, GeoTIFF LV95)
  - swisstopo/swissimage_2m/*.tif    dalles SWISSIMAGE (image aérienne, GeoTIFF LV95)
  - cache/Terrain_mesh_*m.blend      maillage du terrain de Johan (commande terrain)
  - cache/meta.json                  (prep_particules.py)
Sorties (cache/env/)
  - dem_8m.npy      relief de toute la zone, pas 8 m
  - dem_2m.npy      relief fin autour de la scène (rayon --radius), pas 2 m
  - ortho_2m.jpg    image aérienne autour de la scène
  - env_meta.json   position de la scène en coordonnées suisses LV95 (calage), emprises, qualité

Calage : le repère de Johan est un repère local. On cherche la translation (E0, N0) qui fait
coïncider son terrain avec swissALTI3D (recherche globale par corrélation rapide, puis affinage).
Un bon calage donne un écart (RMS) de quelques mètres seulement et un pic net.

Lancement (via Blender, qui fournit numpy et le maillage en cache) :
  blender -b -P prep_env.py -- [--swisstopo DIR] [--data cache] [--radius 8000]
Les bibliothèques tifffile et imagecodecs sont cherchées dans le dossier .pylibs/ de la racine (installées
par installer_bibliotheques.py).
"""
import argparse
import glob
import json
import math
import os
import re
import sys
import time
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
ROOT = os.environ.get("BLATTEN_ROOT") or os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, ".pylibs"))   # installé par "python blatten.py setup"
try:
    import tifffile
except ImportError:
    sys.exit("tifffile introuvable: lancer d'abord l'installation des bibliothèques (commande setup).")
try:
    import imagecodecs
except ImportError:
    imagecodecs = None


def log(*a):
    print("[env]", *a, flush=True)


# ----------------------------------------------------------------------------------
# Lecture des dalles GeoTIFF
# ----------------------------------------------------------------------------------
def tile_info(path):
    """(x0 gauche, y1 haut, taille pixel, largeur, hauteur) en LV95, sans décoder les pixels."""
    with tifffile.TiffFile(path) as tf:
        pg = tf.pages[0]
        w, h = pg.imagewidth, pg.imagelength
        tags = pg.tags
        if "ModelPixelScaleTag" in tags and "ModelTiepointTag" in tags:
            sc = tags["ModelPixelScaleTag"].value
            tp = tags["ModelTiepointTag"].value
            sx = float(sc[0])
            x0 = float(tp[3]) - float(tp[0]) * sx
            y1 = float(tp[4]) + float(tp[1]) * float(sc[1])
            return x0, y1, sx, w, h
    m = re.search(r"_(\d{4})-(\d{4})_", os.path.basename(path))  # repli: nom de dalle, coin bas-gauche
    if not m:
        raise ValueError(f"{path}: pas de géoréférencement")
    e, n = int(m.group(1)) * 1000.0, int(m.group(2)) * 1000.0
    return e, n + 1000.0, 1000.0 / w, w, h


def read_pixels(path, rgb=False):
    with tifffile.TiffFile(path) as tf:
        a = tf.pages[0].asarray()
    if rgb:
        if a.ndim == 3 and a.shape[0] in (3, 4) and a.shape[-1] not in (3, 4):
            a = np.moveaxis(a, 0, -1)
        if a.ndim == 2:
            a = np.repeat(a[..., None], 3, axis=2)
        return np.ascontiguousarray(a[..., :3])
    a = a.astype(np.float32)
    if a.ndim == 3:
        a = a[..., 0]
    a[(a < -1000) | (a > 9000)] = np.nan   # valeurs "sans données" (-9999)
    return a


def reduce_block(a, f):
    if f <= 1:
        return a
    h, w = a.shape[:2]
    h2, w2 = h // f * f, w // f * f
    a = a[:h2, :w2]
    if a.ndim == 2:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return np.nanmean(a.reshape(h2 // f, f, w2 // f, f), axis=(1, 3)).astype(np.float32)
    c = a.shape[2]
    return a.reshape(h2 // f, f, w2 // f, f, c).mean(axis=(1, 3), dtype=np.float32)


def list_tiles(folder):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "*.tif*"))):
        try:
            x0, y1, s, w, h = tile_info(p)
        except Exception as e:
            log("dalle ignorée", os.path.basename(p), e)
            continue
        out.append(dict(path=p, x0=x0, y1=y1, s=s, w=w, h=h))
    return out


def mosaic(tiles, x0, y1, W, H, step, rgb=False, fill=None):
    """Assemble les dalles dans une grille de pas `step` (m), origine coin haut-gauche (x0, y1)."""
    shape = (H, W, 3) if rgb else (H, W)
    arr = np.full(shape, np.nan if not rgb else 0, np.float32 if not rgb else np.uint8)
    cover = np.zeros((H, W), bool)
    n = 0
    for t in tiles:
        tx1 = t["x0"] + t["w"] * t["s"]
        ty0 = t["y1"] - t["h"] * t["s"]
        if tx1 <= x0 or t["x0"] >= x0 + W * step or t["y1"] <= y1 - H * step or ty0 >= y1:
            continue
        a = read_pixels(t["path"], rgb)
        f = max(1, int(round(step / t["s"])))
        a = reduce_block(a, f)
        if rgb:
            a = np.clip(a, 0, 255).astype(np.uint8)
        ix = int(round((t["x0"] - x0) / step))
        iy = int(round((y1 - t["y1"]) / step))
        h, w = a.shape[:2]
        sx0, sy0 = max(0, -ix), max(0, -iy)
        dx0, dy0 = max(0, ix), max(0, iy)
        ww, hh = min(w - sx0, W - dx0), min(h - sy0, H - dy0)
        if ww <= 0 or hh <= 0:
            continue
        arr[dy0:dy0 + hh, dx0:dx0 + ww] = a[sy0:sy0 + hh, sx0:sx0 + ww]
        cover[dy0:dy0 + hh, dx0:dx0 + ww] = True
        n += 1
    return arr, cover, n


def fill_nan(a):
    """Comble les trous (dalles manquantes comprises) par pondération en 1/distance des plus proches
    valeurs valides dans les 4 directions. Rapide (quelques balayages), sans traitement par itérations."""
    nanm = np.isnan(a)
    if not nanm.any():
        return a
    num = np.zeros(a.shape, np.float32)
    den = np.zeros(a.shape, np.float32)

    def sweep(av, nv, dv, reverse, ch=256):
        for r0 in range(0, av.shape[0], ch):
            blk = av[r0:r0 + ch]
            if reverse:
                blk = blk[:, ::-1]
            valid = ~np.isnan(blk)
            w = blk.shape[1]
            ar = np.arange(w, dtype=np.int32)[None, :]
            idx = np.maximum.accumulate(np.where(valid, ar, -1), axis=1)
            ok = idx >= 0
            vals = np.take_along_axis(blk, np.clip(idx, 0, None), axis=1)
            dist = np.maximum((ar - idx).astype(np.float32), 1.0)
            wgt = np.where(ok & ~valid, 1.0 / dist, 0.0).astype(np.float32)
            cn = np.where(ok, vals, 0.0).astype(np.float32) * wgt
            if reverse:
                cn, wgt = cn[:, ::-1], wgt[:, ::-1]
            nv[r0:r0 + ch] += cn
            dv[r0:r0 + ch] += wgt

    for rev in (False, True):
        sweep(a, num, den, rev)                       # le long des lignes
        sweep(a.T, num.T, den.T, rev)                 # le long des colonnes
    with np.errstate(all="ignore"):
        fill = num / den
    out = np.where(nanm, fill, a).astype(a.dtype)
    rest = np.isnan(out)
    if rest.any():
        out[rest] = np.nanmean(a)
    return out


def bilinear(arr, x0, y1, step, E, N):
    u = (E - x0) / step - 0.5
    v = (y1 - N) / step - 0.5
    H, W = arr.shape
    u = np.clip(u, 0, W - 1.001)
    v = np.clip(v, 0, H - 1.001)
    i, j = np.floor(v).astype(int), np.floor(u).astype(int)
    fy, fx = v - i, u - j
    return ((1 - fy) * ((1 - fx) * arr[i, j] + fx * arr[i, j + 1]) +
            fy * ((1 - fx) * arr[i + 1, j] + fx * arr[i + 1, j + 1]))


# ----------------------------------------------------------------------------------
# Terrain de Johan
# ----------------------------------------------------------------------------------
def johan_points(data_dir):
    """Sommets du maillage du terrain de Johan, repère recentré de la scène (X, Y, Z=altitude)."""
    import bpy
    best = None
    for f in glob.glob(os.path.join(data_dir, "Terrain_mesh_*m.blend")):
        m = re.search(r"_mesh_([\d.]+)m\.blend$", f)
        if m and (best is None or float(m.group(1)) < best[0]):
            best = (float(m.group(1)), f)
    if best is None:
        sys.exit("Maillage du terrain de Johan introuvable (commande terrain).")
    log("terrain de Johan:", os.path.basename(best[1]))
    with bpy.data.libraries.load(best[1]) as (src, dst):
        dst.meshes = list(src.meshes)[:1]
    me = dst.meshes[0]
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    # Le terrain de Johan est une dalle épaisse (~150 m): deux nappes parallèles. Selon l'orientation du VDB,
    # la nappe de dessus (celle qui suit le relief réel) a ses normales vers le bas ou vers le haut.
    # On garde la nappe la plus haute, hors parois verticales.
    nrm = np.empty(n * 3, np.float32)
    try:
        me.vertex_normals.foreach_get("vector", nrm)
    except Exception:
        me.calc_normals() if hasattr(me, "calc_normals") else None
        me.vertex_normals.foreach_get("vector", nrm)
    nz = nrm.reshape(-1, 3)[:, 2]
    up, dn = nz > 0.25, nz < -0.25
    top = up if co[up, 2].mean() > co[dn, 2].mean() else dn
    log(f"{n:,} sommets, {top.sum():,} sur la nappe supérieure du terrain "
        f"(normales vers le {'haut' if top is up else 'bas'})")
    return co[top], np.abs(nz[top]), best[0]


def fft_corr(D, A):
    """out[i, j] = somme A[r, c] * D[r + i, c + j], pour les décalages entièrement valides."""
    H, W = D.shape
    h, w = A.shape
    s = (H + h, W + w)
    F = np.fft.rfft2(D, s)
    G = np.fft.rfft2(A, s)
    return np.fft.irfft2(F * np.conj(G), s)[:H - h + 1, :W - w + 1]


def coarse_search(dem, x0, y1, step, X, Y, Z, flip, cell, min_overlap=0.97):
    """Recherche globale de (E0, N0) par corrélation (FFT), tolérante aux trous du relief (NaN).
    Renvoie dict(E0, N0, mse, ratio) ou None."""
    f = max(1, int(round(cell / step)))
    D = reduce_block(dem, f).astype(np.float64)
    V = (~np.isnan(D)).astype(np.float64)
    D = np.where(V > 0, D, 0.0)
    cs = step * f
    yy = flip * Y
    xmin, ytop = X.min(), yy.max()
    cj = np.floor((X - xmin) / cs).astype(int)
    ri = np.floor((ytop - yy) / cs).astype(int)
    h, w = ri.max() + 1, cj.max() + 1
    cnt = np.bincount(ri * w + cj, minlength=h * w).astype(np.float64)
    sm = np.bincount(ri * w + cj, weights=Z, minlength=h * w)
    M = (cnt > 0).astype(np.float64).reshape(h, w)
    T = np.divide(sm, cnt, out=np.zeros_like(sm), where=cnt > 0).reshape(h, w)
    if D.shape[0] < h or D.shape[1] < w:
        return None
    nm = M.sum()
    cross = fft_corr(D, M * T)
    sq = fft_corr(D * D, M)
    tt = fft_corr(V, M * T * T)
    overlap = fft_corr(V, M)
    with np.errstate(all="ignore"):
        mse = (tt - 2 * cross + sq) / overlap
    mse[overlap < min_overlap * nm] = np.inf          # décalages dont l'emprise sort du relief ou tombe dans un trou
    if not np.isfinite(mse).any():
        return None
    k = np.unravel_index(np.argmin(mse), mse.shape)
    best = mse[k]
    msk = mse.copy()
    r = max(8, int(150 / cs))
    msk[max(0, k[0] - r):k[0] + r + 1, max(0, k[1] - r):k[1] + r + 1] = np.inf
    second = msk.min()
    di, dj = k
    return dict(E0=x0 + dj * cs - xmin, N0=y1 - di * cs - ytop, mse=float(best),
                ratio=float(second / max(best, 1e-9)), flip=flip, cs=cs)


def rms_at(grid, E0, N0, flip, X, Y, Z):
    arr, x0, y1, step = grid
    d = Z - bilinear(arr, x0, y1, step, E0 + X, N0 + flip * Y)
    return d


def refine(grid, E0, N0, flip, X, Y, Z, span, step):
    best = None
    offs = np.arange(-span, span + 1e-9, step)
    for dn in offs:
        for de in offs:
            d = rms_at(grid, E0 + de, N0 + dn, flip, X, Y, Z)
            d = d[~np.isnan(d)]
            if len(d) < 100:
                continue
            d = d - np.median(d)   # décalage vertical éventuel (datum) retiré
            v = float(np.mean(np.minimum(np.abs(d), 4.0)))   # écart absolu tronqué: insensible aux falaises
            if best is None or v < best[0]:
                best = (v, E0 + de, N0 + dn)
    return best


# ----------------------------------------------------------------------------------
# Retouche de l'image aérienne: déséclairage (ombres cuites) puis homogénéisation des dalles
# ----------------------------------------------------------------------------------
def _lin(u8):
    return (u8.astype(np.float32) / 255.0) ** 2.2


def _srgb8(lin):
    return np.clip(np.power(np.clip(lin, 0.0, 1.0), 1 / 2.2) * 255.0 + 0.5, 0, 255).astype(np.uint8)


def illumination(dem, r0, r1, step, az, el):
    """Éclairement relatif (1 = surface plane) d'un relief pour un soleil (azimut depuis le nord, élévation)."""
    a, b = max(r0 - 1, 0), min(r1 + 1, dem.shape[0])
    blk = np.asarray(dem[a:b], np.float32)
    gy, gx = np.gradient(blk, step)
    gy = gy[r0 - a: r1 - a]
    gx = gx[r0 - a: r1 - a]
    n = np.sqrt(gx * gx + gy * gy + 1.0)
    e, z = math.radians(el), math.radians(az)
    s = (math.sin(z) * math.cos(e), math.cos(z) * math.cos(e), math.sin(e))
    # lignes vers le sud (indice croissant): dz/dN = -gy
    f = (gx * (-s[0]) + gy * (s[1]) + s[2]) / n / math.sin(e)
    return f.astype(np.float32)


def delight(img, dem, step, strength=0.65, az=180.0, el=55.0, chunk=512):
    """Retire en partie l'ombrage du soleil de la prise de vue (dalles de SWISSIMAGE, vol de milieu de journée)."""
    out = np.empty_like(img)
    for r0 in range(0, img.shape[0], chunk):
        r1 = min(r0 + chunk, img.shape[0])
        f = np.clip(illumination(dem, r0, r1, step, az, el), 0.30, 1.6)
        lin = _lin(img[r0:r1]) / (f[..., None] ** strength)
        out[r0:r1] = _srgb8(lin)
    return out


def harmonize(img, block=500, strength=0.7, clip=(0.75, 1.33)):
    """Corrige les écarts de teinte entre dalles (années, dates de vol): gain par bloc de 1 km, interpolé sans marche."""
    H, W, _ = img.shape
    nby, nbx = H // block, W // block
    if nby < 2 or nbx < 2:
        return img
    med = np.zeros((nby, nbx, 3), np.float32)
    for j in range(nby):
        for i in range(nbx):
            b = img[j * block:(j + 1) * block:4, i * block:(i + 1) * block:4].reshape(-1, 3).astype(np.float32)
            lum = b.mean(1)
            lo, hi = np.percentile(lum, [15, 85])
            m = (lum >= lo) & (lum <= hi)
            med[j, i] = np.median(b[m], axis=0) if m.any() else b.mean(0)
    target = np.median(med.reshape(-1, 3), axis=0)
    gain = np.clip(target / np.maximum(med, 1.0), clip[0], clip[1]) ** strength
    log(f"  homogénéisation: gains par bloc de {gain.min():.2f} à {gain.max():.2f}")
    cx = (np.arange(W) + 0.5) / block - 0.5
    cy = (np.arange(H) + 0.5) / block - 0.5
    i0 = np.clip(np.floor(cx).astype(int), 0, nbx - 1); i1 = np.clip(i0 + 1, 0, nbx - 1)
    fx = np.clip(cx - i0, 0, 1).astype(np.float32)
    j0 = np.clip(np.floor(cy).astype(int), 0, nby - 1); j1 = np.clip(j0 + 1, 0, nby - 1)
    fy = np.clip(cy - j0, 0, 1).astype(np.float32)
    out = np.empty_like(img)
    for r0 in range(0, H, 512):
        r1 = min(r0 + 512, H)
        jj0, jj1, ff = j0[r0:r1], j1[r0:r1], fy[r0:r1]
        gx0 = gain[jj0][:, i0] * (1 - fx)[None, :, None] + gain[jj0][:, i1] * fx[None, :, None]
        gx1 = gain[jj1][:, i0] * (1 - fx)[None, :, None] + gain[jj1][:, i1] * fx[None, :, None]
        g = gx0 * (1 - ff)[:, None, None] + gx1 * ff[:, None, None]
        out[r0:r1] = np.clip(img[r0:r1].astype(np.float32) * g + 0.5, 0, 255).astype(np.uint8)
    return out


def retouch_ortho(raw, dem, step, delight_strength=0.65, harm_strength=0.7):
    log("  retouche de l'image: déséclairage puis homogénéisation")
    x = delight(raw, dem, step, delight_strength) if delight_strength > 0 else raw
    return harmonize(x, strength=harm_strength) if harm_strength > 0 else x


# ----------------------------------------------------------------------------------
# Haute résolution (swissALTI3D 0,5 m, SWISSIMAGE 10 cm) autour de la caméra
# ----------------------------------------------------------------------------------
def latest_per_tile(tiles):
    """Une seule dalle par carré de 1 km: la plus récente (au cas où plusieurs années sont présentes)."""
    best = {}
    for t in tiles:
        m = re.search(r"_(\d{4})_(\d{4}-\d{4})_", os.path.basename(t["path"]))
        k, y = (m.group(2), int(m.group(1))) if m else (os.path.basename(t["path"]), 0)
        if k not in best or y > best[k][0]:
            best[k] = (y, t)
    return [v[1] for v in best.values()]


def hires_step(a, out):
    """Relief 0,5 m (dem_05m.npy) et images locales (ortho_50cm.jpg, ortho_10cm.jpg) centrées sur la caméra.
    Réutilise le calage déjà fait (env_meta.json): ne refait ni la recherche ni le relief 2 m.
    Écrit dans env_meta.json les clés "dem05" et "ortho_patches"."""
    mp = os.path.join(out, "env_meta.json")
    meta = json.load(open(mp))
    t0 = time.time()
    alti = latest_per_tile(list_tiles(os.path.join(a.swisstopo, "swissalti3d_05m")))
    if not alti:
        log("pas de dalle swissALTI3D 0,5 m (dossier swissalti3d_05m): haute résolution ignorée")
        return
    gx0 = min(t["x0"] for t in alti)
    gy1 = max(t["y1"] for t in alti)
    gx1 = max(t["x0"] + t["w"] * t["s"] for t in alti)
    gy0 = min(t["y1"] - t["h"] * t["s"] for t in alti)
    step = 0.5
    W, H = int(round((gx1 - gx0) / step)), int(round((gy1 - gy0) / step))
    log(f"{len(alti)} dalles 0,5 m: E {gx0:.0f}..{gx1:.0f} N {gy0:.0f}..{gy1:.0f} ({W}x{H} pixels)")
    dem, cov, n = mosaic(alti, gx0, gy1, W, H, step)
    log(f"relief 0,5 m: {n} dalles, trous: {(~cov).mean() * 100:.2f} %")
    dem = fill_nan(dem)
    np.save(os.path.join(out, "dem_05m.npy"), dem)
    meta["dem05"] = dict(file="dem_05m.npy", x0=gx0, y1=gy1, step=step, shape=[H, W])

    # centre des images locales: la caméra (camera.json ou --camera), arrondie à 10 m
    cam = a.camera
    if not cam:
        cp = os.path.join(ROOT, "camera.json")
        if os.path.exists(cp):
            cam = json.load(open(cp)).get("cam")
    patches = []
    if a.skip_ortho:
        log("--skip-ortho: images locales ignorées")
    elif imagecodecs is None:
        log("imagecodecs manquant: images locales ignorées")
    elif not cam:
        log("pas de caméra (camera.json): images locales ignorées")
    else:
        imgs = latest_per_tile(list_tiles(os.path.join(a.swisstopo, "swissimage_10cm")))
        if not imgs:
            log("pas de dalle SWISSIMAGE 10 cm (dossier swissimage_10cm): images locales ignorées")
        else:
            Ec = round((meta["scene_E0"] + cam[0]) / 10.0) * 10.0
            Nc = round((meta["scene_N0"] + meta["flip"] * cam[1]) / 10.0) * 10.0
            ref = None
            mo = meta.get("ortho")
            if mo and os.path.exists(os.path.join(out, mo["file"])):
                ref = imagecodecs.jpeg8_decode(open(os.path.join(out, mo["file"]), "rb").read())
            specs = sorted(((float(x.split(":")[0]), float(x.split(":")[1])) for x in a.ortho_locales.split(",")), reverse=True)
            for pstep, half in specs:                       # du plus grossier au plus fin
                S = int(round(2 * half / pstep))
                x0, y1 = Ec - half, Nc + half
                img, cv, nt = mosaic(imgs, x0, y1, S, S, pstep, rgb=True)
                if nt == 0:
                    log(f"  image {pstep * 100:g} cm: aucune dalle ne couvre {half:g} m autour de la caméra, ignorée")
                    continue
                if (~cv).any():
                    mean = img[cv].reshape(-1, 3).mean(0)
                    img[~cv] = mean.astype(np.uint8)
                    log(f"  image {pstep * 100:g} cm: {(~cv).mean() * 100:.1f} % hors dalles (couleur moyenne)")
                ii = (np.arange(S, dtype=np.float32) + 0.5) * pstep
                Ee = (x0 + ii)[None, :] + np.zeros((S, 1), np.float32)
                Nn = (y1 - ii)[:, None] + np.zeros((1, S), np.float32)
                dem_p = bilinear(dem, gx0, gy1, step, Ee, Nn).astype(np.float32)
                del Ee, Nn
                img = delight(img, dem_p, pstep, a.deslight)
                del dem_p
                if ref is not None:   # raccord de teinte avec l'image 2 m (années et dates de vol différentes)
                    f = max(1, int(round(2.0 / pstep)))
                    dn = reduce_block(img, f).astype(np.float32)
                    ix = int(round((x0 - mo["x0"]) / 2.0)); iy = int(round((mo["y1"] - y1) / 2.0))
                    h, w = dn.shape[:2]
                    if ix >= 0 and iy >= 0 and iy + h <= ref.shape[0] and ix + w <= ref.shape[1]:
                        rc = ref[iy:iy + h, ix:ix + w].reshape(-1, 3).astype(np.float32)
                        g = np.clip(np.median(rc, axis=0) / np.maximum(np.median(dn.reshape(-1, 3), axis=0), 1.0), 0.7, 1.4)
                        img = np.clip(img.astype(np.float32) * g + 0.5, 0, 255).astype(np.uint8)
                        log(f"  image {pstep * 100:g} cm: gain de raccord avec l'image 2 m {g.round(3).tolist()}")
                name = f"ortho_{int(round(pstep * 100))}cm.jpg"
                data = imagecodecs.jpeg8_encode(img, level=93)
                with open(os.path.join(out, name), "wb") as fh:
                    fh.write(data)
                patches.append(dict(file=name, x0=x0, y1=y1, step=pstep, shape=[S, S]))
                log(f"  {name}: {S}x{S} pixels, {len(data) / 1e6:.0f} Mo, centre E {Ec:.0f} N {Nc:.0f}")
            del ref
    meta["ortho_patches"] = patches
    meta["hires_created"] = time.strftime("%Y-%m-%d %H:%M")
    with open(mp, "w") as fh:
        json.dump(meta, fh, indent=2)
    log(f"haute résolution terminée en {time.time() - t0:.0f} s")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(prog="prep_env")
    ap.add_argument("--swisstopo", default=os.path.join(ROOT, "data", "swisstopo"))
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--radius", type=float, default=8000.0, help="rayon (m) du relief 2 m et de l'image autour de la scène")
    ap.add_argument("--e0", type=float); ap.add_argument("--n0", type=float)
    ap.add_argument("--flip", type=int, choices=[1, -1], help="force le sens nord (1: Y Blender vers le nord)")
    ap.add_argument("--skip-ortho", action="store_true")
    ap.add_argument("--retouche-ortho", action="store_true", help="refait seulement la retouche de l'image (ortho_2m_brut.jpg + dem_2m.npy), sans recalage")
    ap.add_argument("--deslight", type=float, default=0.75, help="force du déséclairage de l'image (0 = aucun)")
    ap.add_argument("--harmonise", type=float, default=0.7, help="force de l'homogénéisation des dalles (0 = aucune)")
    ap.add_argument("--hires", action="store_true", help="seulement la haute résolution (relief 0,5 m, images 10 cm) autour de la caméra, sur le calage existant")
    ap.add_argument("--camera", type=float, nargs=3, metavar=("X", "Y", "Z"), help="caméra (repère Blender), sinon camera.json")
    ap.add_argument("--ortho-locales", default="0.5:1000,0.1:200", help="images locales pas:demi-côté en m (défaut 0.5:1000,0.1:200)")
    ap.add_argument("--johan-points", help="fichier .npy (X, Y, Z, |nz|) de la nappe supérieure du terrain de Johan, au lieu de lire le maillage")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(a.data, "env")
    os.makedirs(out, exist_ok=True)
    t0 = time.time()

    if a.hires:
        hires_step(a, out)
        return

    if a.retouche_ortho:  # seulement l'image: part de ortho_2m_brut.jpg et du relief 2 m déjà calculés
        mp = os.path.join(out, "env_meta.json")
        meta = json.load(open(mp))
        brut = os.path.join(out, "ortho_2m_brut.jpg")
        if not os.path.exists(brut):
            brut = os.path.join(out, meta["ortho"]["file"])
            log("pas d'ortho_2m_brut.jpg: on part de l'image actuelle (déjà retouchée ?)")
        raw = imagecodecs.jpeg8_decode(open(brut, "rb").read())
        dem2 = np.load(os.path.join(out, meta["dem2"]["file"]), mmap_mode="r")
        img = retouch_ortho(raw, dem2, meta["dem2"]["step"], a.deslight, a.harmonise)
        with open(os.path.join(out, "ortho_2m.jpg"), "wb") as fh:
            fh.write(imagecodecs.jpeg8_encode(img, level=93))
        log(f"image retouchée écrite en {time.time() - t0:.0f} s")
        return

    alti = list_tiles(os.path.join(a.swisstopo, "swissalti3d_2m"))
    if not alti:
        sys.exit(f"Aucune dalle swissALTI3D dans {a.swisstopo}\\swissalti3d_2m")
    log(f"{len(alti)} dalles swissALTI3D")
    gx0 = min(t["x0"] for t in alti)
    gy1 = max(t["y1"] for t in alti)
    gx1 = max(t["x0"] + t["w"] * t["s"] for t in alti)
    gy0 = min(t["y1"] - t["h"] * t["s"] for t in alti)
    log(f"emprise LV95: E {gx0:.0f}..{gx1:.0f}  N {gy0:.0f}..{gy1:.0f}")

    # 1) relief de toute la zone à 8 m
    W8, H8 = int(round((gx1 - gx0) / 8)), int(round((gy1 - gy0) / 8))
    dem8, cov8, n8 = mosaic(alti, gx0, gy1, W8, H8, 8.0)
    log(f"relief 8 m: {W8}x{H8}, {n8} dalles, trous: {(~cov8).mean() * 100:.1f} %")
    dem8 = fill_nan(dem8)
    np.save(os.path.join(out, "dem_8m.npy"), dem8)

    # 2) calage sur le terrain de Johan
    if a.johan_points:
        arr = np.load(a.johan_points).astype(np.float64)
        P, NZ = arr[:, :3], arr[:, 3]
        log(f"points du terrain de Johan relus: {len(P):,}")
    else:
        P, NZ, vox = johan_points(a.data)
    X, Y, Z = P[:, 0], P[:, 1], P[:, 2]
    log(f"emprise de la face supérieure: X {X.min():.0f}..{X.max():.0f}  Y {Y.min():.0f}..{Y.max():.0f}  Z {Z.min():.0f}..{Z.max():.0f}")
    rng = np.random.default_rng(0)
    gentle = np.nonzero(NZ > 0.7)[0]          # pentes < 45 degrés: altitude fiable pour le calage
    sel = rng.choice(gentle, size=min(40000, len(gentle)), replace=False)
    Xs, Ys, Zs = X[sel], Y[sel], Z[sel]
    g8 = (dem8, gx0, gy1, 8.0)

    if a.e0 is not None and a.n0 is not None:
        E0, N0, flip = a.e0, a.n0, (a.flip or 1)
        info = dict(method="imposé")
    else:
        res = []
        for fl in ([a.flip] if a.flip else [1, -1]):
            r = coarse_search(dem8, gx0, gy1, 8.0, X, Y, Z, fl, 16.0)
            if r is None:
                log("terrain de Johan plus grand que la zone téléchargée: élargir le rectangle")
                sys.exit(1)
            log(f"  sens nord {fl:+d}: RMS grossier {np.sqrt(r['mse']):.1f} m, pic/second {r['ratio']:.2f}, "
                f"E0 {r['E0']:.0f} N0 {r['N0']:.0f}")
            res.append(r)
        r = min(res, key=lambda q: q["mse"])
        flip = r["flip"]
        v, E0, N0 = refine(g8, r["E0"], r["N0"], flip, Xs, Ys, Zs, 40.0, 4.0)
        log(f"  affinage 8 m: écart tronqué {v:.2f} m, E0 {E0:.1f} N0 {N0:.1f}")
        info = dict(method="corrélation", coarse_ratio=r["ratio"], coarse_rms=float(np.sqrt(r["mse"])))
        info["rms_other_flip"] = float(np.sqrt(max(q["mse"] for q in res))) if len(res) > 1 else None

    # 3) relief fin et image autour de la scène
    ec = E0 + 0.5 * (X.min() + X.max())
    nc = N0 + flip * 0.5 * (Y.min() + Y.max())
    R = a.radius
    wx0 = max(gx0, np.floor((ec - R) / 1000) * 1000)
    wy1 = min(gy1, np.ceil((nc + R) / 1000) * 1000)
    wx1 = min(gx1, np.ceil((ec + R) / 1000) * 1000)
    wy0 = max(gy0, np.floor((nc - R) / 1000) * 1000)
    W2, H2 = int(round((wx1 - wx0) / 2)), int(round((wy1 - wy0) / 2))
    dem2, cov2, n2 = mosaic(alti, wx0, wy1, W2, H2, 2.0)
    log(f"relief 2 m: {W2}x{H2}, {n2} dalles, trous: {(~cov2).mean() * 100:.1f} %")
    dem2 = fill_nan(dem2)
    np.save(os.path.join(out, "dem_2m.npy"), dem2)
    g2 = (dem2, wx0, wy1, 2.0)
    if "coarse_ratio" in info:
        v, E0, N0 = refine(g2, E0, N0, flip, Xs, Ys, Zs, 8.0, 1.0)
        v, E0, N0 = refine(g2, E0, N0, flip, Xs, Ys, Zs, 1.0, 0.25)
        log(f"  affinage 2 m: écart tronqué {v:.2f} m, E0 {E0:.2f} N0 {N0:.2f}")
    d = rms_at(g2, E0, N0, flip, Xs, Ys, Zs)
    dz = float(np.median(d))
    d = d - dz
    mad = float(np.median(np.abs(d)))
    rms = float(np.sqrt(np.mean(d * d)))
    w3 = float(np.mean(np.abs(d) < 3) * 100)
    log(f"calage final: E0 {E0:.2f} N0 {N0:.2f} sens {flip:+d} décalage vertical {dz:+.2f} m")
    log(f"  qualité (pentes douces): écart médian {mad:.2f} m, RMS {rms:.2f} m, {w3:.0f} % des points à moins de 3 m")
    if mad > 5:
        log("ATTENTION: écart élevé, le calage est douteux (terrain de Johan différent d'une édition swissALTI3D ?)")

    # 4) image aérienne
    ortho = None
    if not a.skip_ortho:
        imgs = list_tiles(os.path.join(a.swisstopo, "swissimage_2m"))
        if not imgs:
            log("pas de dalle SWISSIMAGE: image aérienne ignorée")
        elif imagecodecs is None:
            log("imagecodecs manquant: image aérienne ignorée")
        else:
            log(f"{len(imgs)} dalles SWISSIMAGE")
            img, cov, n = mosaic(imgs, wx0, wy1, W2, H2, 2.0, rgb=True)
            if (~cov).any():
                mean = img[cov].reshape(-1, 3).mean(0) if cov.any() else np.array([90, 95, 80])
                img[~cov] = mean.astype(np.uint8)
            log(f"image 2 m: {W2}x{H2}, {n} dalles, trous: {(~cov).mean() * 100:.1f} %")
            with open(os.path.join(out, "ortho_2m_brut.jpg"), "wb") as fh:
                fh.write(imagecodecs.jpeg8_encode(img, level=93))
            img = retouch_ortho(img, dem2, 2.0, a.deslight, a.harmonise)
            data = imagecodecs.jpeg8_encode(img, level=93)
            with open(os.path.join(out, "ortho_2m.jpg"), "wb") as fh:
                fh.write(data)
            ortho = dict(file="ortho_2m.jpg", x0=wx0, y1=wy1, step=2.0, shape=[H2, W2])
            log(f"ortho_2m.jpg: {len(data) / 1e6:.0f} Mo")

    meta = dict(
        scene_E0=E0, scene_N0=N0, flip=flip, dz=dz, mad=mad, rms=rms, within3=w3, calage=info,
        dem8=dict(file="dem_8m.npy", x0=gx0, y1=gy1, step=8.0, shape=[H8, W8]),
        dem2=dict(file="dem_2m.npy", x0=wx0, y1=wy1, step=2.0, shape=[H2, W2]),
        ortho=ortho, created=time.strftime("%Y-%m-%d %H:%M"),
    )
    with open(os.path.join(out, "env_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    log(f"terminé en {time.time() - t0:.0f} s, résultats dans {out}")
    if os.path.isdir(os.path.join(a.swisstopo, "swissalti3d_05m")):
        hires_step(a, out)
    else:
        log("RAPPEL: relief et image à 2 m. Pour la haute résolution: python blatten.py download (listes 0,5 m et 10 cm), "
            "puis python blatten.py prep-env --hires")


if __name__ == "__main__":
    main()
