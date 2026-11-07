"""
essai_arbres_ez.py : arbres actuels (grappes) et arbres détaillés EZ-Tree côte à côte, à hauteur d'yeux, HORS de la scène.

Même disposition dans les deux images: épicéa, mélèze, pin cembro, feuillu, arbuste à ~20 m, et un épicéa à 7 m.
    python tools/essai_arbres_ez.py --out essai.png [--res 1280 640] [--echantillons 32]     (Blender en module Python)
Sort essai_A_actuels.png et essai_B_ez.png à côté de --out, puis les deux l'un sous l'autre dans --out.
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

# (essence, x, y, hauteur, rayon de couronne)
ARBRES = [(0, -11.0, 19.0, 9.9, 2.0), (1, -5.5, 21.0, 7.0, 2.0), (2, 0.0, 18.0, 4.4, 1.8), (3, 6.0, 20.0, 8.0, 3.0),
          (4, 10.5, 16.0, 2.5, 1.5), (0, 4.0, 7.0, 6.4, 1.5)]


def scene_de_base():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 50, 0))
    sol = bpy.context.object
    ms = bpy.data.materials.new("Sol")
    ms.use_nodes = True
    b = ms.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.13, 0.15, 0.07, 1)
    b.inputs["Roughness"].default_value = 1.0
    sol.data.materials.append(ms)
    w = bpy.data.worlds.new("Ciel")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.80, 0.83, 0.88, 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.2
    sun = bpy.data.lights.new("Soleil", "SUN")
    sun.energy, sun.angle = 1.8, math.radians(12)
    so = bpy.data.objects.new("Soleil", sun)
    so.rotation_euler = (math.radians(35), 0, math.radians(234 - 180))
    sc.collection.objects.link(so)
    cam = bpy.data.cameras.new("Cam")
    cam.lens = 16
    co = bpy.data.objects.new("Cam", cam)
    co.location, co.rotation_euler = (0, -4, 1.7), (math.radians(92), 0, 0)
    sc.collection.objects.link(co)
    sc.camera = co
    sc.view_settings.view_transform = "Standard"
    return sc


def arbres_actuels(sc):
    BB.CFG["arbres_grappes"] = True
    mt = BB._materiau_arbres()
    co_all, tri_all, col_all, off = [], [], [], 0
    rng = np.random.default_rng(3)
    for e, x, y, H, R in ARBRES:
        PV, PT, ntr, PO = BB._proto_arbre(e, 0, np.random.default_rng(1000 * e + 7))
        yaw = rng.uniform(0, 2 * np.pi)
        c, s = math.cos(yaw), math.sin(yaw)
        px, py, pz = PV[:, 0] * R, PV[:, 1] * R, PV[:, 2] * H
        co_all.append(np.stack([x + px * c - py * s, y + px * s + py * c, pz], 1))
        tri_all.append(PT + off)
        gg = np.clip(PV[:, 2], 0, 1)
        base = np.array(np.broadcast_to(BB.COULEURS_ARBRES[e], (len(PV), 3)) * ((0.55 + 0.45 * gg) * PO)[:, None])
        base[ntr:] = BB.COULEUR_TRONC
        col_all.append(base)
        off += len(PV)
    co = np.concatenate(co_all).astype(np.float32)
    ob = BB._objet_triangles("Arbres", co, np.concatenate(tri_all).astype(np.int32), [mt], lisse=True)
    col = np.concatenate(col_all).astype(np.float32)
    ca = ob.data.color_attributes.new("col", "BYTE_COLOR", "POINT")
    ca.data.foreach_set("color", np.concatenate([col, np.ones((len(co), 1), np.float32)], 1).ravel())
    sc.collection.objects.link(ob)


def arbres_ez(sc):
    modeles = BB._modeles_ez()
    a = np.array(ARBRES, float)
    sp = a[:, 0].astype(int)
    rng = np.random.default_rng(3)
    yaw = rng.uniform(0, 2 * np.pi, len(a))
    coul = BB.COULEURS_ARBRES[sp] * float(BB.CFG["arbres_modeles_eclat"])
    coll = bpy.data.collections.new("ArbresEZ")
    sc.collection.children.link(coll)
    BB.placer_arbres_ez(coll, modeles, a[:, 1], a[:, 2], np.zeros(len(a)), a[:, 3], a[:, 4], sp, yaw, coul)


def rendre(out, res, ech):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = ech
    sc.cycles.use_denoising = True
    sc.cycles.transparent_max_bounces = 32
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.filepath = out
    sc.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", type=int, nargs=2, default=(1280, 640))
    ap.add_argument("--echantillons", type=int, default=32)
    a = ap.parse_args(argv)
    base = os.path.splitext(os.path.abspath(a.out))[0]
    import time
    for nom, f in (("A_actuels", arbres_actuels), ("B_ez", arbres_ez)):
        sc = scene_de_base()
        f(sc)
        t0 = time.time()
        rendre(f"{base}_{nom}.png", tuple(a.res), a.echantillons)
        print(f"{nom}: rendu en {time.time() - t0:.0f} s")
