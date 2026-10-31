"""
verif_images.py : repère les images suspectes d'un rendu de film (sans les regarder une par une).

  - image vide, noire ou presque uniforme (rendu raté);
  - « saut » isolé: une image très différente de ses deux voisines alors que les voisines se ressemblent entre elles
    (morceau de nuage qui disparaît une image, objet qui clignote). Score = min(écart avec la précédente, avec la suivante)
    / écart entre la précédente et la suivante; suspect au-dessus de --seuil (défaut 2,5).
Comparaison sur des vignettes 192x96 en niveaux de gris. Avec --pas 2, seules les images calculées (1, 3, 5...) sont lues.

    python verif_images.py --dir D:/Blatten_render/film_bande/20261101_0038 --pas 2
Écrit verif.json dans le dossier (liste des images suspectes avec leur score). numpy + Pillow.
"""
import argparse
import time
import glob
import json
import os
import re
import sys

import numpy as np
from PIL import Image


def vignette(f):
    im = Image.open(f).convert("L").resize((192, 96), Image.BILINEAR)
    return np.asarray(im, np.float32) / 255.0


def _sauver(f, d):
    """Écriture atomique du cache (un arrêt pendant l'écriture ne le corrompt pas)."""
    try:
        tmp = f + ".tmp.npz"
        np.savez(tmp, **{str(k): v for k, v in d.items()})
        os.replace(tmp, f)
    except Exception:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="verif_images")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--pas", type=int, default=1)
    ap.add_argument("--seuil", type=float, default=2.5)
    ap.add_argument("--max-secondes", type=float, default=0, help="arrête la lecture après ce temps (cache gardé, relancer)")
    a = ap.parse_args(argv)
    files = sorted(glob.glob(os.path.join(a.dir, "frame_*.png")) + glob.glob(os.path.join(a.dir, "frame_*.jpg")))
    num = {int(re.search(r"frame_(\d+)", f).group(1)): f for f in files}
    cles = sorted(i for i in num if (i - 1) % a.pas == 0)
    if len(cles) < 3:
        print("moins de 3 images, rien à vérifier")
        return 0
    cache_f = os.path.join(a.dir, ".verif_cache.npz")
    cache = {}
    if os.path.exists(cache_f):
        try:
            z = np.load(cache_f)
            cache = {int(k): z[k] for k in z.files}
        except Exception:
            cache = {}
    V, susp = {}, []
    t0 = time.time()
    for i in cles:
        if a.max_secondes and time.time() - t0 > a.max_secondes:
            _sauver(cache_f, {**cache, **V})
            print(f"lecture interrompue ({len(V)} images lues), relancer pour continuer")
            return 2
        if i in cache:
            V[i] = cache[i]
            continue
        try:
            if os.path.getsize(num[i]) == 0:
                continue
            V[i] = vignette(num[i])
        except Exception as e:
            susp.append(dict(image=i, raison=f"illisible: {e}"))
    _sauver(cache_f, {**cache, **V})
    ks = [i for i in cles if i in V]
    for i in ks:
        v = V[i]
        if v.std() < 0.01 or v.mean() < 0.02:
            susp.append(dict(image=i, raison="image vide ou uniforme", ecart_type=round(float(v.std()), 4)))
    d = lambda x, y: float(np.abs(V[x] - V[y]).mean())
    for j in range(1, len(ks) - 1):
        p, i, s = ks[j - 1], ks[j], ks[j + 1]
        dp, ds, dps = d(p, i), d(i, s), d(p, s)
        score = min(dp, ds) / (dps + 0.002)
        if score > a.seuil and min(dp, ds) > 0.006:
            susp.append(dict(image=i, raison="saut isolé", score=round(score, 2), ecart=round(min(dp, ds), 4)))
    susp.sort(key=lambda x: x["image"])
    json.dump(dict(images=len(ks), suspectes=susp), open(os.path.join(a.dir, "verif.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{len(ks)} images vérifiées, {len(susp)} suspecte(s)" + ("".join(f"\n  {x['image']}: {x['raison']} {x.get('score', '')}" for x in susp)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
