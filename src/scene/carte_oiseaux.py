"""Carte des oiseaux et du glissement, vue du ciel (python blatten.py carte-oiseaux).

Entrées: trajets.json (écrit par la scène: départs et une position par seconde de chaque oiseau) et l'empreinte de l'aléa
(alea_empreinte.npz: instant d'arrivée de la matière en chaque cellule, coordonnées suisses LV95).
Sorties (dossier --out):
  carte_oiseaux.png          orthophoto en couleurs, emprise de la masse toutes les 5 s (contours + aplats légers, étiquetés),
                             caméra, départs et trajets des oiseaux (point par seconde, étiquette toutes les 5 s), axes en LV95
  carte_oiseaux.txt          tableau des groupes (arbre de départ, distance et cap depuis la caméra, envols)
  couches/*.geojson          couches vecteur en LV95 (EPSG:2056) pour QGIS: emprise_5s (polygones, champ t),
                             oiseaux_trajets (lignes), oiseaux_departs (points), camera (point)
  couches/fond_ortho.jpg+.jgw fond orthophoto géoréférencé (fichier monde, LV95)
"""
import argparse
import json
import math
import os

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2056"}}


def _geojson(chemin, feats):
    json.dump({"type": "FeatureCollection", "crs": CRS, "features": feats}, open(chemin, "w", encoding="utf-8"))


def _groupes(ois):
    ordre = sorted(range(len(ois)), key=lambda b: ois[b]["depart"])
    gr = []
    for b in ordre:
        p = ois[b]["xy"][0]
        for g in gr:
            q = ois[g[0]]["xy"][0]
            if math.hypot(p[0] - q[0], p[1] - q[1]) < 6.0:
                g.append(b)
                break
        else:
            gr.append([b])
    return gr


def _anneaux_vers_polygones(anneaux):
    """Anneaux matplotlib (extérieurs et trous d'orientation opposée) -> liste de polygones [ext, trou, ...]."""
    def aire(r):
        x, y = r[:, 0], r[:, 1]
        return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    polys = []
    for r in anneaux:
        if len(r) < 4:
            continue
        a = aire(r)
        if abs(a) < 1.0:
            continue
        if not polys or (a > 0) == (aire(polys[0][0]) > 0):
            polys.append([r])
        else:
            polys[-1].append(r)
    return polys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--trajets", required=True)
    ap.add_argument("--out", required=True, help="dossier de sortie")
    ap.add_argument("--marge", type=float, default=200.0)
    ap.add_argument("--tmax", type=float, default=55.0)
    a = ap.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import patheffects as pe

    os.makedirs(os.path.join(a.out, "couches"), exist_ok=True)
    T = json.load(open(a.trajets, encoding="utf-8"))
    meta = json.load(open(os.path.join(a.data, "meta.json"), encoding="utf-8"))
    E0, N0, fl = T["scene_E0"], T["scene_N0"], T["flip"]
    cx, cy, _ = T["camera"]
    cE, cN = E0 + cx, N0 + fl * cy
    ois = T["oiseaux"]
    for o in ois:
        o["EN"] = np.array([[E0 + p[0], N0 + fl * p[1]] for p in o["xy"]])

    # emprise de la masse
    z = None
    f = os.path.join(a.data, "alea_empreinte.npz")
    if os.path.exists(f):
        z = np.load(f)
        tarr = np.array(z["tarr"], np.float64)
        zx0, zy1, zs = float(z["x0"]), float(z["y1"]), float(z["step"])
        ny, nx = tarr.shape
        gE = zx0 + (np.arange(nx) + 0.5) * zs
        gN = zy1 - (np.arange(ny) + 0.5) * zs
        tt = np.where(np.isfinite(tarr) & (tarr <= a.tmax), tarr, 1e9)

    # étendue: caméra + emprise + trajets, plus une marge
    pts = [[cE, cN]] + [p for o in ois for p in o["EN"][int(o["depart"]):].tolist()]
    if z is not None:
        jj, ii = np.nonzero(tt < 1e9)
        if len(ii):
            pts += [[gE[ii].min(), gN[jj].min()], [gE[ii].max(), gN[jj].max()]]
    P = np.array(pts)
    e0, e1 = P[:, 0].min() - a.marge, P[:, 0].max() + a.marge
    n0, n1 = P[:, 1].min() - a.marge, P[:, 1].max() + a.marge

    # fond: orthophoto en couleurs, découpée sur l'étendue (aussi exportée géoréférencée pour QGIS)
    fond = None
    o = meta.get("ortho")
    if o and os.path.exists(os.path.join(a.data, o["file"])):
        im = Image.open(os.path.join(a.data, o["file"])).convert("RGB")
        s = float(o["step"])
        box = (int((e0 - o["x0"]) / s), int((o["y1"] - n1) / s), int(math.ceil((e1 - o["x0"]) / s)), int(math.ceil((o["y1"] - n0) / s)))
        fond = im.crop(box)
        fe0, fn1 = o["x0"] + box[0] * s, o["y1"] - box[1] * s
        fe1, fn0 = fe0 + fond.width * s, fn1 - fond.height * s
        fond.save(os.path.join(a.out, "couches", "fond_ortho.jpg"), quality=92)
        open(os.path.join(a.out, "couches", "fond_ortho.jgw"), "w").write(
            f"{s}\n0\n0\n{-s}\n{fe0 + s / 2}\n{fn1 - s / 2}\n")

    larg = 16.0
    fig, ax = plt.subplots(figsize=(larg, larg * (n1 - n0) / (e1 - e0) + 0.6), dpi=150)
    if fond is not None:
        ax.imshow(np.asarray(fond), extent=(fe0, fe1, fn0, fn1), interpolation="bilinear", zorder=0)
    else:
        ax.set_facecolor("#555")
    halo = [pe.withStroke(linewidth=3, foreground="black")]

    feats = []
    if z is not None:
        niveaux = list(range(5, int(a.tmax) + 1, 5))
        cmap = plt.get_cmap("plasma_r")
        cols = [cmap(0.1 + 0.85 * k / max(1, len(niveaux) - 1)) for k in range(len(niveaux))]
        # aplats très légers par tranche de 5 s, contours nets
        ax.contourf(gE, gN, tt, levels=[0] + niveaux, colors=cols, alpha=0.18, zorder=1)
        cs = ax.contour(gE, gN, tt, levels=niveaux, colors=cols, linewidths=1.8, zorder=2)
        lab = ax.clabel(cs, fmt=lambda v: f"{v:.0f} s", fontsize=9, inline=True)
        for t_ in lab:
            t_.set_path_effects(halo)
            t_.set_color("white")
        for t in niveaux:
            cf = plt.figure().add_subplot()
            c2 = cf.contourf(gE, gN, tt, levels=[-1, t])
            anneaux = [r for p in c2.get_paths() for r in p.to_polygons()]
            plt.close(cf.figure)
            polys = _anneaux_vers_polygones(anneaux)
            if polys:
                feats.append({"type": "Feature", "properties": {"t": t},
                              "geometry": {"type": "MultiPolygon",
                                           "coordinates": [[[[round(x, 1), round(y, 1)] for x, y in r] for r in p] for p in polys]}})
        _geojson(os.path.join(a.out, "couches", "emprise_5s.geojson"), feats)

    # oiseaux
    gr = _groupes(ois)
    gcol = ["#00e5ff", "#ffe600", "#ff4dff", "#7dff6b", "#ff9a3c"]
    lignes = ["Groupe | oiseaux | arbre de départ E, N (LV95) | distance à la caméra | cap depuis la caméra | envols (s de l'événement)"]
    f_tr, f_dep = [], []
    for gi, g in enumerate(gr):
        col = gcol[gi % len(gcol)]
        p0 = ois[g[0]]["EN"][0]
        dist = math.hypot(p0[0] - cE, p0[1] - cN)
        cap = (math.degrees(math.atan2(p0[0] - cE, p0[1] - cN)) + 360) % 360
        deps = [ois[b]["depart"] for b in g]
        lignes.append(f"G{gi + 1} | {len(g)} | {p0[0]:.0f}, {p0[1]:.0f} | {dist:.0f} m | {cap:.0f} deg | {min(deps):.1f} à {max(deps):.1f}")
        f_dep.append({"type": "Feature", "properties": {"groupe": f"G{gi + 1}", "oiseaux": len(g), "envol_debut": round(min(deps), 2),
                                                        "envol_fin": round(max(deps), 2), "distance_camera_m": round(dist),
                                                        "cap_depuis_camera": round(cap)},
                      "geometry": {"type": "Point", "coordinates": [round(p0[0], 1), round(p0[1], 1)]}})
        for b in g:
            k0 = int(ois[b]["depart"])
            tr = ois[b]["EN"][k0:]
            ax.plot(tr[:, 0], tr[:, 1], "-", color=col, lw=0.7, alpha=0.55, zorder=3)
            f_tr.append({"type": "Feature", "properties": {"groupe": f"G{gi + 1}", "envol": round(ois[b]["depart"], 2), "t_debut": k0},
                         "geometry": {"type": "LineString", "coordinates": [[round(x, 1), round(y, 1)] for x, y in tr]}})
        # trajet de référence du groupe: points chaque seconde, étiquettes toutes les 5 s, flèche de sens
        b = g[len(g) // 2]
        k0 = int(ois[b]["depart"])
        tr = ois[b]["EN"]
        ax.plot(tr[k0:, 0], tr[k0:, 1], "-", color=col, lw=2.2, zorder=4, path_effects=[pe.withStroke(linewidth=4, foreground="black")])
        ax.scatter(tr[k0:, 0], tr[k0:, 1], s=9, color=col, edgecolors="black", linewidths=0.4, zorder=5)
        for s_ in range(k0, len(tr)):
            if s_ % 5 == 0:
                ax.scatter([tr[s_, 0]], [tr[s_, 1]], s=40, color=col, edgecolors="black", zorder=6)
                ax.annotate(f"{s_} s", tr[s_], xytext=(5, 4), textcoords="offset points", color=col, fontsize=8.5,
                            weight="bold", path_effects=halo, zorder=7)
        s_ = min(k0 + 4, len(tr) - 2)
        ax.annotate("", xy=tr[s_ + 1], xytext=tr[s_], arrowprops=dict(arrowstyle="-|>", color=col, lw=2.5, mutation_scale=22), zorder=7)
        ax.scatter([p0[0]], [p0[1]], s=180, marker="*", color=col, edgecolors="black", linewidths=1.2, zorder=8)
        ax.annotate(f"G{gi + 1}: {len(g)} oiseaux, envol {min(deps):.1f}-{max(deps):.1f} s", p0, xytext=(9, -14),
                    textcoords="offset points", color="white", fontsize=10, weight="bold", path_effects=halo, zorder=8)
    _geojson(os.path.join(a.out, "couches", "oiseaux_trajets.geojson"), f_tr)
    _geojson(os.path.join(a.out, "couches", "oiseaux_departs.geojson"), f_dep)
    _geojson(os.path.join(a.out, "couches", "camera.geojson"),
             [{"type": "Feature", "properties": {"nom": "camera", "altitude": round(T["camera"][2], 1)},
               "geometry": {"type": "Point", "coordinates": [round(cE, 1), round(cN, 1)]}}])

    # caméra, habillage
    ax.scatter([cE], [cN], s=220, marker="^", color="white", edgecolors="black", linewidths=1.5, zorder=9)
    ax.annotate("caméra", (cE, cN), xytext=(10, 6), textcoords="offset points", color="white", fontsize=11, weight="bold",
                path_effects=halo, zorder=9)
    ax.set_xlim(e0, e1)
    ax.set_ylim(n0, n1)
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.tick_params(labelsize=8)
    ax.set_xlabel("E (LV95, m)")
    ax.set_ylabel("N (LV95, m)")
    ax.grid(color="white", alpha=0.15, lw=0.5)
    L = 200.0 if (e1 - e0) < 3000 else 500.0
    xb, yb = e0 + 0.04 * (e1 - e0), n0 + 0.04 * (n1 - n0)
    ax.plot([xb, xb + L], [yb, yb], color="white", lw=4, path_effects=[pe.withStroke(linewidth=6, foreground="black")], zorder=10)
    ax.annotate(f"{L:.0f} m", (xb + L / 2, yb), xytext=(0, 6), textcoords="offset points", ha="center", color="white",
                fontsize=10, weight="bold", path_effects=halo, zorder=10)
    xn, yn = e1 - 0.05 * (e1 - e0), n1 - 0.09 * (n1 - n0)
    ax.annotate("N", xy=(xn, yn + 0.05 * (n1 - n0)), xytext=(xn, yn), ha="center", color="white", fontsize=14, weight="bold",
                arrowprops=dict(arrowstyle="-|>", color="white", lw=2.5), path_effects=halo, zorder=10)
    ax.set_title("Blatten: emprise de la masse toutes les 5 s (temps de l'événement) et fuite des oiseaux", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(a.out, "carte_oiseaux.png"))
    open(os.path.join(a.out, "carte_oiseaux.txt"), "w", encoding="utf-8").write("\n".join(lignes) + "\n")
    print("Carte:", os.path.join(a.out, "carte_oiseaux.png"))
    print("Couches QGIS (LV95):", os.path.join(a.out, "couches"))
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
