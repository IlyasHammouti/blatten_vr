"""
prep_sol.py : image aérienne « nettoyée » pour le sol de la scène (méthode classique, rien n'est inventé).

Problèmes de l'image aérienne une fois posée sous les arbres 3D:
  - elle contient déjà les arbres vus d'en haut et leurs ombres (portées vers le nord-ouest à l'heure de la prise de vue):
    entre les arbres 3D, le sol paraît noir, et des ombres tombent du mauvais côté (« sol noir sous la canopée »);
  - l'image 10 cm porte une fine trame régulière et du bruit JPEG, visibles sous nos pieds.

Traitement, pour chaque image (2 m, 50 cm, 10 cm), écrit à côté de l'original avec le suffixe _sol (l'original ne change pas):
  1. zone à remplacer = cimes (masque de canopée de prep-vegetation, élargi de 1,5 m) + ombres des arbres (pixels nettement plus
     sombres que le sol voisin, à moins de 8 m d'une cime);
  2. ombres: remplacées par la couleur moyenne du sol découvert voisin (rayon 6 m, sinon 25 m, sinon une couleur de sous-bois);
     cimes: moitié ce sol voisin assombri comme un sous-bois, moitié la couleur d'origine éclaircie (la teinte verte reste);
     dans les deux cas, 30 % des variations fines de l'image sont gardées (pas d'aplat);
  3. trame de l'image 10 cm: méthode « flou » (jusqu'au 12 nov.): flou de 2 pixels, qui efface aussi presque tout le détail
     (variance du laplacien de 172 à 5); méthode « grille » (13 nov., défaut): on retire seulement la trame, périodique
     de 5 pixels (50 cm), par repliement (médiane de chaque case des 5 x 5 dans des tuiles de 200 pixels, retirée de l'image
     quand son amplitude dépasse le bruit), puis un flou d'un seul pixel pour le bruit JPEG: le détail d'origine reste
     (laplacien 94 au lieu de 5; la trame passe de 100 % à 6 %).

    python prep_sol.py --env DOSSIER_ENV [--sombre 0.72] [--lisse 1.0] [--seulement ortho_10cm.jpg]
                       [--methode grille|flou] [--suffixe _sol_net]
Bibliothèques: numpy, Pillow.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def log(*a):
    print("[prep-sol]", *a, flush=True)


def flou(a, r, passes=3):
    """Flou approximativement gaussien (3 moyennes glissantes) de rayon r pixels, séparable, bords répliqués."""
    r = int(round(r))
    if r < 1:
        return a
    out = a.astype(np.float32, copy=True)
    for _ in range(passes):
        for ax in (0, 1):
            p = np.concatenate([np.repeat(np.take(out, [0], axis=ax), r + 1, axis=ax), out,
                                np.repeat(np.take(out, [-1], axis=ax), r, axis=ax)], axis=ax)
            c = np.cumsum(p, axis=ax, dtype=np.float64)
            n = out.shape[ax]
            hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=ax)
            lo = np.take(c, np.arange(0, n), axis=ax)
            out = ((hi - lo) / (2 * r + 1)).astype(np.float32)
    return out


def masque_sur_grille(info_m, masque, info_i, forme):
    """Masque de canopée (grille à 2 m) rééchantillonné (bilinéaire) sur la grille d'une image (x0, y1, step)."""
    H, W = forme
    xs = info_i["x0"] + (np.arange(W) + 0.5) * info_i["step"]
    ys = info_i["y1"] - (np.arange(H) + 0.5) * info_i["step"]
    cx = (xs - info_m["x0"]) / info_m["step"] - 0.5
    cy = (info_m["y1"] - ys) / info_m["step"] - 0.5
    Hm, Wm = masque.shape
    x0 = np.clip(np.floor(cx).astype(np.int64), 0, Wm - 2)
    y0 = np.clip(np.floor(cy).astype(np.int64), 0, Hm - 2)
    fx = np.clip(cx - x0, 0, 1).astype(np.float32)
    fy = np.clip(cy - y0, 0, 1).astype(np.float32)
    dedans = ((cx >= -0.5) & (cx <= Wm - 0.5))[None, :] & ((cy >= -0.5) & (cy <= Hm - 0.5))[:, None]
    m = masque.astype(np.float32)
    out = np.empty((H, W), np.float32)
    for i0 in range(0, H, 512):          # par bandes: mémoire modeste
        sl = slice(i0, min(H, i0 + 512))
        a = m[y0[sl]][:, x0]
        b = m[y0[sl]][:, x0 + 1]
        c = m[y0[sl] + 1][:, x0]
        d = m[y0[sl] + 1][:, x0 + 1]
        ffy = fy[sl][:, None]
        out[sl] = (a * (1 - fx) + b * fx) * (1 - ffy) + (c * (1 - fx) + d * fx) * ffy
    out[~dedans] = 0.0
    return out


def degrille(rgb, tuile=200, P=5, seuil=1.5, hp_sigma=6.0):
    """Retire la trame périodique (période P pixels, P = 5 sur l'image 10 cm) sans toucher au reste: pour chaque canal, hautes
    fréquences (image moins flou gaussien), puis dans chaque tuile médiane de chacune des P x P cases (position modulo P):
    c'est le motif périodique; il est retiré si son amplitude dépasse `seuil` (niveaux sur 255), sinon la tuile n'a pas de trame.
    rgb: (H, W, 3) uint8. Rend un uint8 de même forme."""
    a = rgb.astype(np.float32)
    H, W = a.shape[:2]
    out = a.copy()
    ii, jj = np.mgrid[0:tuile, 0:tuile]
    for k in range(3):
        c = a[..., k]
        hp = c - flou(c, hp_sigma)
        res = np.zeros_like(c)
        for i0 in range(0, H, tuile):
            for j0 in range(0, W, tuile):
                i1, j1 = min(H, i0 + tuile), min(W, j0 + tuile)
                t = hp[i0:i1, j0:j1]
                key = ((ii[:i1 - i0, :j1 - j0] + i0) % P) * P + (jj[:i1 - i0, :j1 - j0] + j0) % P
                pat = np.array([np.median(t[key == q]) if np.any(key == q) else 0.0 for q in range(P * P)], np.float32)
                pat -= np.median(pat)
                if np.abs(pat).max() >= seuil:
                    res[i0:i1, j0:j1] = pat[key]
        out[..., k] = c - res
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def traiter(rgb, can, step, sombre=0.72, lisse=1.0):
    """rgb: (H, W, 3) uint8; can: (H, W) 0..1 (canopée); step: m par pixel. Rend (image uint8, part remplacée)."""
    px = lambda m: max(1.0, m / step)
    img = rgb.astype(np.float32) / 255.0
    L = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    cime = can > 0.5
    zone = flou(cime.astype(np.float32), px(1.5), passes=1) > 0.02          # cimes élargies de 1,5 m
    pres = flou(cime.astype(np.float32), px(8.0), passes=1) > 0.02          # à moins de 8 m d'une cime
    libre = (~zone).astype(np.float32)
    Lloc = flou(L * libre, px(10.0)) / np.maximum(flou(libre, px(10.0)), 1e-3)
    ombre = pres & (L < 0.62 * Lloc)
    m = zone | ombre
    w = (~m).astype(np.float32)
    # couleur du sol découvert voisin (6 m, sinon 25 m, sinon sous-bois)
    fond = np.empty_like(img)
    p6, p25 = flou(w, px(6.0)), flou(w, px(25.0))
    sous_bois = np.array([0.20, 0.25, 0.14], np.float32)
    for k in range(3):
        c6 = flou(img[..., k] * w, px(6.0)) / np.maximum(p6, 1e-4)
        c25 = flou(img[..., k] * w, px(25.0)) / np.maximum(p25, 1e-4)
        a6 = np.clip((p6 - 0.02) / 0.10, 0, 1)
        a25 = np.clip((p25 - 0.01) / 0.08, 0, 1)
        fond[..., k] = a6 * c6 + (1 - a6) * (a25 * c25 + (1 - a25) * sous_bois[k])
    del p6, p25
    fin = (L - flou(L, px(2.0)))[..., None] * 0.3                             # garde un peu du grain d'origine
    # cimes: moitié sol voisin assombri (sous-bois), moitié couleur d'origine éclaircie (garde la teinte verte de la végétation);
    # ombres hors des cimes: sol voisin presque tel quel (ce sont des ombres « du mauvais côté »: les arbres 3D font les leurs)
    eclairci = np.power(np.clip(img, 0, 1), 0.65) * 0.92
    rem_cime = np.clip(0.55 * fond * sombre + 0.45 * eclairci + fin, 0, 1)
    rem_ombre = np.clip(fond * 0.93 + fin, 0, 1)
    mc = flou(zone.astype(np.float32), px(1.0), passes=2)[..., None]         # transitions douces sur ~1 m
    mo = flou((ombre & ~zone).astype(np.float32), px(1.0), passes=2)[..., None]
    out = img * (1 - mc - mo).clip(0, 1) + rem_cime * mc + rem_ombre * mo
    if lisse > 0:
        for k in range(3):
            out[..., k] = flou(out[..., k], lisse, passes=2)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), float(m.mean())


def traiter_par_tuiles(rgb, can, step, sombre, lisse, tuile=2048):
    """traiter() par tuiles qui se recouvrent (les flous vont jusqu'à 25 m): mémoire bornée même pour l'image 2 m (8500 x 8500)."""
    H, W = rgb.shape[:2]
    if H * W <= 20e6:
        return traiter(rgb, can, step, sombre, lisse)
    marge = int(3 * 25.0 / step) + 3 * int(max(lisse, 1)) + 8
    out = np.empty_like(rgb)
    parts = []
    for i0 in range(0, H, tuile):
        for j0 in range(0, W, tuile):
            i1, j1 = min(H, i0 + tuile), min(W, j0 + tuile)
            a0, b0, a1, b1 = max(0, i0 - marge), max(0, j0 - marge), min(H, i1 + marge), min(W, j1 + marge)
            o, part = traiter(rgb[a0:a1, b0:b1], can[a0:a1, b0:b1], step, sombre, lisse)
            out[i0:i1, j0:j1] = o[i0 - a0:i0 - a0 + (i1 - i0), j0 - b0:j0 - b0 + (j1 - j0)]
            parts.append(part * (i1 - i0) * (j1 - j0))
    return out, sum(parts) / (H * W)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="prep_sol")
    ap.add_argument("--env", required=True, help="dossier env (env_meta.json, ortho_*.jpg, canopee_masque.png)")
    ap.add_argument("--sombre", type=float, default=0.72, help="assombrissement du sol sous les arbres (1 = couleur du sol voisin)")
    ap.add_argument("--lisse", type=float, default=1.0, help="flou final en pixels pour les images 50 cm et 10 cm (0 = aucun)")
    ap.add_argument("--seulement", nargs="*", help="ne traiter que ces fichiers (essais)")
    ap.add_argument("--methode", choices=("grille", "flou"), default="grille",
                    help="image 10 cm: grille = retire seulement la trame de 5 pixels (détail gardé), flou = flou de 2 pixels (avant le 13 nov.)")
    ap.add_argument("--suffixe", default="_sol_net", help="suffixe du fichier écrit (défaut _sol_net; l'ancien _sol n'est pas touché)")
    ap.add_argument("--fenetre", type=float, nargs=4, metavar=("E0", "N0", "E1", "N1"),
                    help="essais: ne traiter qu'une fenêtre (coordonnées LV95) et l'écrire en *_sol_essai.jpg")
    a = ap.parse_args(argv)
    meta = json.load(open(os.path.join(a.env, "env_meta.json"), encoding="utf-8"))
    cm = meta.get("canopee_masque")
    if not cm or not os.path.exists(os.path.join(a.env, cm["file"])):
        sys.exit("pas de masque de canopée (prep-vegetation): rien à faire")
    masque = np.asarray(Image.open(os.path.join(a.env, cm["file"])).convert("L"), np.float32) / 255.0
    # flou final: rien sur l'image 2 m, 1 pixel sur le 50 cm, 1,5 pixel sur le 10 cm (sa trame régulière)
    # méthode grille: la trame est retirée avant, le flou ne sert plus qu'au bruit JPEG (1 pixel partout)
    fin = 1.0 if a.methode == "grille" else 1.5
    images = [dict(meta["ortho"], lisse=0.0)] + [dict(p, lisse=a.lisse * (fin if p["step"] < 0.2 else 1.0))
                                                 for p in meta.get("ortho_patches", [])]
    for info in images:
        if a.seulement and info["file"] not in a.seulement:
            continue
        src = os.path.join(a.env, info["file"])
        if not os.path.exists(src):
            log(f"absent: {src}")
            continue
        t0 = time.time()
        im = Image.open(src).convert("RGB")
        rgb = np.asarray(im)
        if a.methode == "grille" and info["step"] < 0.2:
            rgb = degrille(rgb)
            log(f"{info['file']}: trame de 5 pixels retirée ({time.time() - t0:.0f} s)")
        inf = dict(info)
        if a.fenetre:
            E0, N0, E1, N1 = a.fenetre
            c0, c1 = int((E0 - info["x0"]) / info["step"]), int((E1 - info["x0"]) / info["step"])
            r0, r1 = int((info["y1"] - N1) / info["step"]), int((info["y1"] - N0) / info["step"])
            c0, r0 = max(c0, 0), max(r0, 0)
            rgb = rgb[r0:r1, c0:c1]
            inf.update(x0=info["x0"] + c0 * info["step"], y1=info["y1"] - r0 * info["step"])
        can = masque_sur_grille(cm, masque, inf, rgb.shape[:2])
        out, part = traiter_par_tuiles(rgb, can, info["step"], a.sombre, info["lisse"])
        nom = os.path.splitext(info["file"])[0] + ("_sol_essai.jpg" if a.fenetre else a.suffixe + ".jpg")
        Image.fromarray(out).save(os.path.join(a.env, nom), quality=93)
        log(f"{info['file']} -> {nom}: {100 * part:.0f} % remplacé (cimes et ombres), {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
