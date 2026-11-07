"""
essai_arbres.py : banc d'essai des arbres HORS de la scène (aucune donnée nécessaire), pour régler leur aspect vite.

Rend une rangée de chaque essence (épicéa, mélèze, pin cembro, feuillu, arbuste) à 25, 60, 120 et 250 m, avec les mêmes
prototypes, couleurs et matériau que le film (src/scene/blatten_blender.py), sous un ciel couvert avec un soleil voilé.

    blender -b --python tools/essai_arbres.py -- --out essai.png [--res 1280 720] [--echantillons 32] [--proche]
    (ou avec Blender en module Python: python tools/essai_arbres.py --out essai.png)
--proche : cadrage serré sur la rangée à 25 m (détail des couronnes).
"""
import argparse
import math
import os
import sys

import numpy as np
import bpy

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, "..", "src", "scene"))
sys.path.insert(0, os.path.join(ICI, "..", "src"))
import blatten_blender as BB   # noqa: E402

# (essence, hauteur m, rayon de couronne m) typiques
ESSENCES = [(0, 24.0, 3.0), (1, 22.0, 3.4), (2, 14.0, 3.2), (3, 13.0, 4.6), (4, 3.5, 2.2)]
DISTANCES = [40.0, 90.0, 180.0, 400.0]


def lin(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def construire(proche=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    coll = sc.collection
    # sol: prairie un peu bruitée
    bpy.ops.mesh.primitive_plane_add(size=4000, location=(0, 1500, 0))
    sol = bpy.context.object
    ms = bpy.data.materials.new("Sol")
    ms.use_nodes = True
    N, L = ms.node_tree.nodes, ms.node_tree.links
    b = N["Principled BSDF"]
    b.inputs["Roughness"].default_value = 1.0
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 0.08
    cr = N.new("ShaderNodeValToRGB")
    cr.color_ramp.elements[0].color = (*lin([0.30, 0.36, 0.20]), 1)
    cr.color_ramp.elements[1].color = (*lin([0.42, 0.44, 0.30]), 1)
    L.new(nz.outputs["Fac"], cr.inputs["Fac"])
    L.new(cr.outputs["Color"], b.inputs["Base Color"])
    sol.data.materials.append(ms)
    # arbres: mêmes prototypes, couleurs et matériau que le film
    mt = BB._materiau_arbres()
    rng = np.random.default_rng(7)
    co_all, tri_all, col_all, off = [], [], [], 0
    for di, d in enumerate(DISTANCES):
        lod = 0 if d < 120 else (1 if d < 500 else (2 if d < 1500 else 3))
        for k, (e, H, R) in enumerate(ESSENCES):
            for rep in range(2):
                PV, PT, ntr, PO = BB._proto_arbre(e, lod, np.random.default_rng(1000 * e + 100 * lod + rep))
                x = (k - 2) * 0.22 * d + (rep - 0.5) * 0.09 * d
                y = d
                yaw = rng.uniform(0, 2 * np.pi)
                c, s = math.cos(yaw), math.sin(yaw)
                px, py, pz = PV[:, 0] * R, PV[:, 1] * R, PV[:, 2] * H
                co = np.stack([x + px * c - py * s, y + px * s + py * c, pz], 1)
                gg = np.clip(PV[:, 2], 0, 1)
                tone = rng.uniform(0.85, 1.15)
                base = np.broadcast_to(BB.COULEURS_ARBRES[e], (len(PV), 3)) * ((0.55 + 0.45 * gg) * PO)[:, None] * tone
                base = np.array(base)
                base[ntr:] = BB.COULEUR_TRONC
                co_all.append(co)
                tri_all.append(PT + off)
                col_all.append(base)
                off += len(PV)
    co = np.concatenate(co_all).astype(np.float32)
    tri = np.concatenate(tri_all).astype(np.int32)
    col = np.concatenate(col_all).astype(np.float32)
    ob = BB._objet_triangles("Arbres", co, tri, [mt], lisse=True)
    ca = ob.data.color_attributes.new("col", "BYTE_COLOR", "POINT")
    ca.data.foreach_set("color", np.concatenate([col, np.ones((len(co), 1), np.float32)], 1).ravel())
    coll.objects.link(ob)
    # ciel couvert lumineux + soleil voilé (élévation 55 degrés, comme le 28 mai 2025 à 15 h 24)
    w = bpy.data.worlds.new("Ciel")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.84, 0.88, 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.3
    sun = bpy.data.lights.new("Soleil", "SUN")
    sun.energy, sun.angle = 1.6, math.radians(12)
    so = bpy.data.objects.new("Soleil", sun)
    so.rotation_euler = (math.radians(35), 0, math.radians(234 - 180))
    coll.objects.link(so)
    cam = bpy.data.cameras.new("Cam")
    cam.lens = 70 if proche else 28
    cam.clip_end = 5000
    co_ = bpy.data.objects.new("Cam", cam)
    if proche:
        co_.location, co_.rotation_euler = (0, 2, 14), (math.radians(78), 0, 0)
    else:
        co_.location, co_.rotation_euler = (0, -20, 30), (math.radians(80), 0, 0)
    coll.objects.link(co_)
    sc.camera = co_
    sc.view_settings.view_transform = "Standard"
    return ob


def rendre(out, res, ech):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = ech
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.filepath = out
    sc.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", type=int, nargs=2, default=(1280, 720))
    ap.add_argument("--echantillons", type=int, default=32)
    ap.add_argument("--proche", action="store_true")
    ap.add_argument("--lisse", action="store_true", help="couronnes lisses (avant le 7 nov.)")
    a = ap.parse_args(argv)
    BB.CFG["arbres_grappes"] = not a.lisse
    construire(a.proche)
    rendre(os.path.abspath(a.out), tuple(a.res), a.echantillons)
    print("image:", a.out)
