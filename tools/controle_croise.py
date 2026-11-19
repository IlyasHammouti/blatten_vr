#!/usr/bin/env python3
"""Contrôle croisé avec le PC de Samy (19 nov. 2026), lecture seule. Deux vérifications:
  1) réglages: python tools/controle_croise.py reglages <render_dir>/final/<version>/reglages_effectifs.json
     compare les réglages effectifs du rendu à ceux de Samy (docs/ref/reglages_effectifs_final_v1.json); la date n'est pas comparée.
  2) image:    python tools/controle_croise.py image <frame_0021.jpg rendue ici>
     compare l'image 21 rendue sur ce PC à celle de Samy (miniature de référence docs/ref/frame_0021_ref_384x192.png).
     Différence moyenne attendue: moins de 2 niveaux sur 255 (le bruit de rendu et le débruitage changent un peu d'une carte à l'autre).
Pillow est nécessaire pour l'image (pip install pillow)."""
import json, os, sys

ICI = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(os.path.dirname(ICI), "docs", "ref")


def aplatir(d, p=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(aplatir(v, p + k + "."))
        else:
            out[p + k] = v
    return out


def reglages(chemin):
    a = aplatir(json.load(open(os.path.join(REF, "reglages_effectifs_final_v1.json"), encoding="utf-8")))
    b = json.load(open(chemin, encoding="utf-8"))
    b = aplatir(b.get("effectifs", b))
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    if not diff:
        print("REGLAGES IDENTIQUES à ceux de Samy (%d paramètres)" % len(a))
        return 0
    print("REGLAGES DIFFERENTS: %d paramètre(s)" % len(diff))
    for k in diff[:30]:
        print("  ", k, "Samy:", a.get(k), "| ici:", b.get(k))
    return 1


def image(chemin):
    from PIL import Image, ImageChops
    ref = Image.open(os.path.join(REF, "frame_0021_ref_384x192.png")).convert("RGB")
    im = Image.open(chemin).convert("RGB")
    if im.size != (3840, 1920):
        print("TAILLE INATTENDUE:", im.size, "(attendu 3840x1920)")
        return 1
    im = im.resize(ref.size, Image.LANCZOS)
    d = ImageChops.difference(ref, im).convert("L")
    h = d.histogram()
    n = sum(h)
    moy = sum(i * c for i, c in enumerate(h)) / n
    gros = sum(c for i, c in enumerate(h) if i > 25) / n * 100
    print("différence moyenne: %.2f / 255 ; pixels qui diffèrent de plus de 25 niveaux: %.2f %%" % (moy, gros))
    ok = moy < 2.0 and gros < 1.0
    print("IMAGE COMPATIBLE avec celle de Samy" if ok else "IMAGE DIFFERENTE de celle de Samy: ne pas continuer, prévenir Ilyas")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("reglages", "image"):
        sys.exit(__doc__)
    sys.exit((reglages if sys.argv[1] == "reglages" else image)(sys.argv[2]))
