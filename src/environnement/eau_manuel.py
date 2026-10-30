"""
eau_manuel.py : remplace le masque d'eau automatique par les polygones tracés à la main dans QGIS (couche eau_manuel de blatten_alea.gpkg).

Les masques gardent le même nom, la même grille et le même format que ceux de prep_eau (eau_masque.png à 4 m, eau_masque_fin.png à 0,5 m):
la scène n'a rien à savoir. La première fois, les masques automatiques sont copiés en eau_masque_auto.png et eau_masque_fin_auto.png.
--auto remet les masques automatiques. Hors Blender (Python de l'atelier: numpy, pillow).
Utilisation: python blatten.py eau-manuel [--gpkg chemin] [--flou 1.5] [--auto]
"""
import argparse
import datetime
import json
import os
import shutil
import sqlite3
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

Image.MAX_IMAGE_PIXELS = None


def log(*a):
    print("[eau-manuel]", *a, flush=True)


def _anneaux(b):
    """Anneaux (listes de (E, N)) d'un blob GeoPackage Polygon ou MultiPolygon (WKB, avec ou sans Z)."""
    flags = b[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((flags >> 1) & 7, 0)
    w = memoryview(b)[8 + env:]
    out = []

    def lire(p):
        bo = "<" if w[p] == 1 else ">"
        t = struct.unpack_from(bo + "I", w, p + 1)[0]
        p += 5
        z = 2 if (t // 1000 in (1, 3) or t & 0x80000000) else 0
        t = t % 1000
        d = 3 if z else 2
        if t == 3:
            nr = struct.unpack_from(bo + "I", w, p)[0]
            p += 4
            for _ in range(nr):
                n = struct.unpack_from(bo + "I", w, p)[0]
                p += 4
                a = np.frombuffer(bytes(w[p:p + 8 * d * n]), dtype=bo + "f8").reshape(n, d)[:, :2]
                p += 8 * d * n
                out.append(a)
            return p
        if t == 6:
            n = struct.unpack_from(bo + "I", w, p)[0]
            p += 4
            for _ in range(n):
                p = lire(p)
            return p
        raise ValueError(f"géométrie WKB de type {t} non prise en charge")
    lire(0)
    return out


def main():
    ap = argparse.ArgumentParser(prog="eau-manuel")
    ap.add_argument("--data", required=True)
    ap.add_argument("--gpkg")
    ap.add_argument("--flou", type=float, default=1.5, help="adoucissement des bords (m)")
    ap.add_argument("--auto", action="store_true", help="remettre les masques automatiques")
    a = ap.parse_args()
    env = os.path.join(a.data, "env")
    mp = os.path.join(env, "env_meta.json")
    meta = json.load(open(mp))
    em = meta.get("eau_masque")
    if not em:
        raise SystemExit("Pas de masque d'eau: lancer d'abord prep-eau.")
    niveaux = [n for n in ("grossier", "fin") if n in em]
    sauve = lambda f: os.path.join(env, f.replace(".png", "_auto.png"))
    if a.auto:
        for n in niveaux:
            f = em[n]["file"]
            if os.path.exists(sauve(f)):
                shutil.copy(sauve(f), os.path.join(env, f))
        em.pop("manuel", None)
        json.dump(meta, open(mp, "w"), indent=1)
        log("masques automatiques remis")
        return
    gp = a.gpkg or os.path.join(os.path.dirname(a.data.rstrip("/\\")), "QGIS", "blatten_alea.gpkg")
    if not os.path.exists(gp):
        gp = os.path.join(a.data.split("pipeline")[0], "QGIS", "blatten_alea.gpkg")
    if not os.path.exists(gp):
        raise SystemExit(f"GeoPackage introuvable: {gp} (--gpkg chemin)")
    c = sqlite3.connect(f"file:{gp}?mode=ro", uri=True)
    col = c.execute("select column_name from gpkg_geometry_columns where table_name='eau_manuel'").fetchone()[0]
    anneaux = []
    for (b,) in c.execute(f'select "{col}" from eau_manuel where "{col}" is not null'):
        anneaux += _anneaux(bytes(b))
    if not anneaux:
        raise SystemExit("La couche eau_manuel est vide.")
    log(f"{len(anneaux)} anneau(x) lus dans {gp}")
    for n in niveaux:
        q = em[n]
        f = q["file"]
        if not os.path.exists(sauve(f)):
            shutil.copy(os.path.join(env, f), sauve(f))
        H, W = q["shape"]
        step = q["step"]
        im = Image.new("L", (W, H), 0)
        dr = ImageDraw.Draw(im)
        dehors = 0
        for r in anneaux:
            xy = [((e - q["x0"]) / step, (q["y1"] - n_) / step) for e, n_ in r]
            if max(p[0] for p in xy) < 0 or min(p[0] for p in xy) > W or max(p[1] for p in xy) < 0 or min(p[1] for p in xy) > H:
                dehors += 1
                continue
            dr.polygon(xy, fill=255)
        if a.flou > 0:
            im = im.filter(ImageFilter.GaussianBlur(a.flou / step))
        m = np.asarray(im)
        im.save(os.path.join(env, f))
        log(f"{n} ({step:g} m): eau {float((m > 127).sum()) * step * step / 1e4:.1f} ha"
            + (f", {dehors} anneau(x) hors de cette grille" if dehors else ""))
    em["manuel"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    json.dump(meta, open(mp, "w"), indent=1)
    log("env_meta.json mis à jour. Regarder le résultat avec une image test (python blatten.py variantes --temps 10).")


main()
