"""Carte des oiseaux et du glissement (python blatten.py carte-oiseaux).

Lit les trajets écrits par la scène (trajets.json: départs et une position par seconde de chaque oiseau) et l'empreinte de l'aléa
(alea_empreinte.npz: instant d'arrivée de la matière en chaque cellule), puis dessine sur l'image aérienne:
  - le front du glissement toutes les 5 s (t = 5, 10, ... de l'événement), en couleur,
  - la caméra, et pour chaque groupe d'oiseaux: arbre de départ, trajet (point toutes les secondes, étiquette toutes les 5 s), sens,
  - un quadrillage tous les 100 m et le nord.
Écrit carte_oiseaux.png et carte_oiseaux.txt (tableau: groupe, arbre, distance et cap depuis la caméra, instants de l'envol)."""
import argparse
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None


def police(n):
    for f in ("arial.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, n)
        except Exception:
            pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--trajets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rayon", type=float, default=700.0, help="demi-largeur de la carte autour de la caméra (m)")
    ap.add_argument("--px", type=float, default=1.0, help="mètres par pixel de la carte")
    a = ap.parse_args()
    T = json.load(open(a.trajets, encoding="utf-8"))
    meta = json.load(open(os.path.join(a.data, "meta.json"), encoding="utf-8"))
    E0, N0, fl = T["scene_E0"], T["scene_N0"], T["flip"]
    cx, cy, cz = T["camera"]
    cE, cN = E0 + cx, N0 + fl * cy                       # caméra en coordonnées Suisse (E, N)
    R, mpp = a.rayon, a.px
    W = int(2 * R / mpp)
    x0, y1 = cE - R, cN + R                              # coin haut-gauche

    def px(E, N):
        return ((E - x0) / mpp, (y1 - N) / mpp)

    # fond: image aérienne (2 m), assombrie pour que les couleurs ressortent
    fond = Image.new("RGB", (W, W), (60, 60, 60))
    o = meta.get("ortho")
    if o and os.path.exists(os.path.join(a.data, o["file"])):
        im = Image.open(os.path.join(a.data, o["file"])).convert("RGB")
        s = o["step"]
        j0, i0 = (x0 - o["x0"]) / s, (o["y1"] - y1) / s
        box = (int(j0), int(i0), int(j0 + 2 * R / s), int(i0 + 2 * R / s))
        fond = im.crop(box).resize((W, W), Image.BILINEAR)
        fond = Image.blend(fond, Image.new("RGB", (W, W), (0, 0, 0)), 0.35)
    img = fond.convert("RGBA")
    # front du glissement toutes les 5 s
    f = os.path.join(a.data, "alea_empreinte.npz")
    couleurs = []
    if os.path.exists(f):
        z = np.load(f)
        tarr, zx0, zy1, zs = z["tarr"], float(z["x0"]), float(z["y1"]), float(z["step"])
        # grille de la carte -> instant d'arrivée
        gx = x0 + (np.arange(W) + 0.5) * mpp
        gy = y1 - (np.arange(W) + 0.5) * mpp
        ii = np.floor((gx - zx0) / zs).astype(int)
        jj = np.floor((zy1 - gy) / zs).astype(int)
        ok = ((ii >= 0) & (ii < tarr.shape[1]))[None, :] & ((jj >= 0) & (jj < tarr.shape[0]))[:, None]
        tt = np.where(ok, tarr[np.clip(jj, 0, tarr.shape[0] - 1)[:, None], np.clip(ii, 0, tarr.shape[1] - 1)[None, :]], np.inf)
        tmax = 55.0
        lay = np.zeros((W, W, 4), np.uint8)
        pas = 5
        for k, t in enumerate(range(pas, int(tmax) + 1, pas)):
            m = np.isfinite(tt) & (tt <= t)
            mm = m.copy()
            mm[1:-1, 1:-1] = m[1:-1, 1:-1] & m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]
            bord = m & ~mm
            # contour épaissi de 1 px
            b2 = bord.copy()
            b2[1:, :] |= bord[:-1, :]
            b2[:, 1:] |= bord[:, :-1]
            h = k / max(1, tmax / pas - 1)
            c = tuple(int(255 * v) for v in _arc(h))
            lay[b2] = (*c, 255)
            couleurs.append((t, c, tt, m))
        zone = np.isfinite(tt) & (tt <= tmax)
        lay[zone & (lay[..., 3] == 0)] = (255, 80, 0, 38)
        img = Image.alpha_composite(img, Image.fromarray(lay, "RGBA"))
    d = ImageDraw.Draw(img)
    F, Fs, Fb = police(15), police(12), police(22)
    # quadrillage tous les 100 m (étiquettes en m depuis la caméra)
    for k in range(-int(R // 100), int(R // 100) + 1):
        xx = (R + k * 100) / mpp
        d.line([(xx, 0), (xx, W)], fill=(255, 255, 255, 40), width=1)
        d.line([(0, xx), (W, xx)], fill=(255, 255, 255, 40), width=1)
        if k:
            d.text((xx + 2, 2), f"{k * 100:+d} m E", fill=(255, 255, 255, 150), font=Fs)
            d.text((2, xx + 2), f"{-k * 100:+d} m N", fill=(255, 255, 255, 150), font=Fs)
    # oiseaux: groupes par instant de départ
    cols = [(0, 255, 255), (255, 255, 0), (255, 0, 255), (120, 255, 120), (255, 160, 60)]
    ois = T["oiseaux"]
    ordre = sorted(range(len(ois)), key=lambda b: ois[b]["depart"])
    # un groupe = oiseaux partis du même arbre (même point de départ à 3 m près)
    groupes = []
    for b in ordre:
        p = ois[b]["xy"][0]
        for g in groupes:
            q = ois[g[0]]["xy"][0]
            if math.hypot(p[0] - q[0], p[1] - q[1]) < 6.0:
                g.append(b)
                break
        else:
            groupes.append([b])
    lignes = ["Groupe | oiseaux | arbre: E, N (Suisse LV95 approx.) | distance caméra | cap depuis la caméra | envols (s de l'événement)"]
    cE_, cN_ = px(cE, cN)
    for gi, g in enumerate(groupes):
        col = cols[gi % len(cols)]
        p0 = ois[g[0]]["xy"][0]
        Ea, Na = E0 + p0[0], N0 + fl * p0[1]
        dist = math.hypot(p0[0] - cx, p0[1] - cy)
        cap = (math.degrees(math.atan2(p0[0] - cx, p0[1] - cy)) + 360) % 360
        deps = [ois[b]["depart"] for b in g]
        lignes.append(f"G{gi + 1} | {len(g)} | {Ea:.0f}, {Na:.0f} | {dist:.0f} m | {cap:.0f} deg | {min(deps):.1f} à {max(deps):.1f}")
        for b in g:
            xy = ois[b]["xy"]
            pts = []
            for s_, (X, Y, Z) in enumerate(xy):
                if s_ < int(ois[b]["depart"]) - 0:
                    continue
                pts.append((s_, px(E0 + X, N0 + fl * Y)))
            vis = [q for q in pts if -50 < q[1][0] < W + 50 and -50 < q[1][1] < W + 50]
            if len(vis) > 1:
                d.line([q[1] for q in vis], fill=col + (150,), width=1)
        # trajet moyen (étiquettes toutes les 5 s) = oiseau du milieu du groupe
        b = g[len(g) // 2]
        xy = ois[b]["xy"]
        for s_, (X, Y, Z) in enumerate(xy):
            if s_ < int(ois[b]["depart"]):
                continue
            q = px(E0 + X, N0 + fl * Y)
            if not (0 <= q[0] < W and 0 <= q[1] < W):
                continue
            r = 4 if s_ % 5 == 0 else 2
            d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=col + (255,))
            if s_ % 5 == 0:
                d.text((q[0] + 6, q[1] - 8), f"t={s_}", fill=col + (255,), font=Fs)
        q0 = px(Ea, Na)
        d.ellipse([q0[0] - 7, q0[1] - 7, q0[0] + 7, q0[1] + 7], outline=col + (255,), width=3)
        d.text((q0[0] + 9, q0[1] - 22), f"G{gi + 1}  envol {min(deps):.1f} s", fill=col + (255,), font=F)
        # flèche de sens (entre t = départ+3 et +4 s)
        s_ = int(ois[b]["depart"]) + 4
        if s_ + 1 < len(xy):
            qa, qb = px(E0 + xy[s_][0], N0 + fl * xy[s_][1]), px(E0 + xy[s_ + 1][0], N0 + fl * xy[s_ + 1][1])
            ang = math.atan2(qb[1] - qa[1], qb[0] - qa[0])
            for da in (2.6, -2.6):
                d.line([qb, (qb[0] + 14 * math.cos(ang + da), qb[1] + 14 * math.sin(ang + da))], fill=col + (255,), width=3)
    # caméra
    d.ellipse([cE_ - 8, cN_ - 8, cE_ + 8, cN_ + 8], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=2)
    d.text((cE_ + 11, cN_ + 4), "caméra", fill=(255, 255, 255, 255), font=F)
    # légende du glissement
    y = 8
    d.rectangle([W - 190, 0, W, 30 + 19 * len(couleurs)], fill=(0, 0, 0, 160))
    d.text((W - 184, y), "Front du glissement", fill=(255, 255, 255, 255), font=F)
    for (t, c, _, _) in couleurs:
        y += 19
        d.rectangle([W - 184, y + 22, W - 160, y + 28], fill=c + (255,))
        d.text((W - 150, y + 16), f"t = {t} s", fill=(255, 255, 255, 255), font=Fs)
    # nord, échelle
    d.text((W - 60, W - 40), "N ↑", fill=(255, 255, 255, 255), font=Fb)
    d.line([(20, W - 20), (20 + 100 / mpp, W - 20)], fill=(255, 255, 255, 255), width=4)
    d.text((20, W - 42), "100 m", fill=(255, 255, 255, 255), font=F)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    img.convert("RGB").save(a.out + ".png")
    open(a.out + ".txt", "w", encoding="utf-8").write("\n".join(lignes) + "\n")
    print("Carte:", a.out + ".png")
    print("\n".join(lignes))


def _arc(h):
    """Dégradé jaune -> rouge -> violet pour les instants 5 s à 55 s."""
    h = min(max(h, 0.0), 1.0)
    stops = [(1.0, 1.0, 0.2), (1.0, 0.55, 0.0), (0.9, 0.1, 0.1), (0.6, 0.1, 0.8), (0.3, 0.3, 1.0)]
    x = h * (len(stops) - 1)
    i = min(int(x), len(stops) - 2)
    f = x - i
    return tuple(stops[i][k] * (1 - f) + stops[i + 1][k] * f for k in range(3))


if __name__ == "__main__":
    main()
