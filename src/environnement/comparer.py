"""comparer.py : compare deux images (pixel par pixel) et dit si elles sont identiques.
Lancé par blatten.py (dans Blender, qui fournit numpy). Usage interne: comparer.py A.png B.png [diff.png]"""
import sys

import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
a_path, b_path = args[0], args[1]


def lire(p):
    im = bpy.data.images.load(p)
    w, h = im.size
    px = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[:, :, :3]


a, b = lire(a_path), lire(b_path)
if a.shape != b.shape:
    print(f"!! images de tailles différentes: {a.shape} et {b.shape}")
    sys.exit(2)
d = np.abs(a - b).max(axis=2)
n = d.size
seuil = 2.0 / 255.0
bad = d > seuil
print(f"\nPixels différents (écart > 2/255): {bad.sum()} sur {n} ({bad.mean() * 100:.4f} %), écart max {d.max() * 255:.1f}/255")
if bad.any():
    ys, xs = np.nonzero(bad)
    print(f"zone des différences: colonnes {xs.min()}..{xs.max()}, lignes {ys.min()}..{ys.max()}")
if len(args) > 2:
    out = np.zeros((*d.shape, 4), np.float32)
    out[..., 0] = np.clip(d * 8, 0, 1)
    out[..., 3] = 1
    im = bpy.data.images.new("diff", d.shape[1], d.shape[0])
    im.pixels.foreach_set(out.ravel())
    im.filepath_raw, im.file_format = args[2], "PNG"
    im.save()
    print("carte des différences (rouge = écart x8):", args[2])
print("VERDICT:", "IDENTIQUES (le culling ne change rien à l'image)" if not bad.any() else "DIFFERENTES: voir la carte des différences")
