#!/usr/bin/env python3
"""
banc_test.py : banc d'essai d'un module de matière SANS les données de Johan ni le reste de la scène.

Pourquoi : développer et comparer des matières (formes, matériaux, coût) avec la géométrie réelle de la prise de vue
(caméra à 2 m, dépôt à ~540 m, 1 pixel = 0,094 degré comme la vidéo 3840x1920), sans PLY ni swisstopo. Ce n'est PAS un
rendu de la scène: terrain synthétique (vallée, versant opposé), ciel couvert, particules synthétiques espacées comme
la simulation (espacement réglable, 6,8 m ~ stride 5). Sert à juger la FORME de la matière et son coût, pas sa couleur
finale (le contraste dépend de l'ortho et de la brume de la vraie scène).

Prérequis : pip install bpy numpy   (Blender comme module Python; version majeure = celle du projet, 5.2)
Exemples :
    python banc_test.py --module matiere_roches --t 38 --out roches_t38.png
    python banc_test.py --module rendu_matiere  --t 38 --out defaut_t38.png     # gabarit (sphères), pour comparer
    python banc_test.py --module matiere_roches --t 38 --spp 8 --res 640x360 --out rapide.png

Le module est cherché dans le dossier du script puis dans src/matiere/. Temps t en secondes (démarrage ~3 s, dépôt ~40 s).
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ terrain synthétique (repère Blender, caméra à l'origine)
def zt(x, s):
    """Altitude du sol en (x, s) avec s = distance vers le sud (-y). Versant côté caméra, fond de vallée, versant opposé."""
    a = np.where(s < 500, -0.4 * s, -200.0)
    mont = -200.0 + 0.75 * np.clip(s - 640.0, 0, None)
    z = np.where(s < 570, a, mont)
    z = np.where((s >= 500) & (s < 640), -200.0, z)
    z = z + 14.0 * np.sin(x / 140.0 + 0.002 * s) * (s > 640) + 5.0 * np.sin(x / 41.0) * np.cos(s / 57.0)
    return z


def fake_seq(spacing, seed=3):
    """Particules synthétiques: un dépôt de 4 couches en pied de versant, parties du haut du versant. Repère SIMULATION (Y haut)."""
    rng = np.random.default_rng(seed)
    d = spacing
    xs = np.arange(-1000, 1000, d)
    ss = np.arange(250, 1100, d)
    X, S = np.meshgrid(xs, ss)
    X, S = X.ravel() + rng.uniform(-d / 2, d / 2, X.size), S.ravel() + rng.uniform(-d / 2, d / 2, X.size)
    # dépôt en lentille: épaisseur max ~34 m, qui s'amincit vers tous les bords
    u = np.clip(1.0 - (X / 1000.0) ** 2, 0, 1)
    v = np.clip(np.sin(np.pi * (S - 250.0) / 850.0), 0, 1) ** 0.8
    ep = 34.0 * u * v
    pts = []
    for k in range(0, 7):
        keep = ep > (k + 0.5) * d * 0.8
        n_k = int(keep.sum())
        pts.append(np.stack([X[keep] + rng.uniform(-d / 3, d / 3, n_k), S[keep] + rng.uniform(-d / 3, d / 3, n_k),
                             k * d * 0.8 + d / 2 + rng.uniform(-d / 3, d / 3, n_k)], 1))
    xf, sf, hf = np.concatenate(pts).T
    n = xf.size
    s0 = sf + 600.0 + 700.0 * rng.uniform(0.4, 1.0, n)
    x0 = xf * rng.uniform(0.2, 0.5, n)
    delay = 3.0 + 28.0 * (sf - 300.0) / 700.0 + rng.uniform(0, 3, n)
    dur = 12.0 + rng.uniform(0, 5, n)

    def pos(t):
        p = np.clip((t - delay) / dur, 0, 1)
        e = p * p * (3 - 2 * p)
        s = s0 + (sf - s0) * e
        x = x0 + (xf - x0) * e
        h = hf + 14.0 * (1 - e) * (hf / 34.0 + 0.3)
        return np.stack([x, zt(x, s) + h, s], 1)      # sim: (x, y haut, z)

    class Seq:
        count = n
        meta = dict(stats=dict(nn_median=spacing * 0.62))

        def state(self, t):
            p = pos(t)
            v = (pos(t + 0.05) - pos(t - 0.05)) / 0.1
            return p.astype(np.float64), v.astype(np.float32)

    return Seq()


def to_blender(a):
    out = np.empty(a.shape, np.float32)
    out[:, 0] = a[:, 0]
    out[:, 1] = -a[:, 2]
    out[:, 2] = a[:, 1]
    return out


def charger(nom):
    for d in (HERE, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src", "matiere"), os.path.join(HERE, "..", "src", "matiere")):
        p = os.path.join(d, nom + ".py")
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location("matiere_banc", p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    sys.exit(f"module {nom} introuvable")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--module", default="matiere_roches")
    ap.add_argument("--t", type=float, default=38.0)
    ap.add_argument("--out", default="banc.png")
    ap.add_argument("--spp", type=int, default=24)
    ap.add_argument("--res", default="960x540", help="960x540 à 90 degrés = même densité angulaire que la vidéo 3840x1920")
    ap.add_argument("--spacing", type=float, default=6.8, help="espacement des particules (4,0 = stride 1, 6,8 = stride 5)")
    ap.add_argument("--yaw", type=float, default=0.0, help="degrés de rotation de la caméra autour de la verticale")
    ap.add_argument("--fov", type=float, default=90.0)
    ap.add_argument("--sun", type=float, default=0.0, help="force d'un soleil (0 = ciel couvert pur)")
    ap.add_argument("--target", type=float, nargs=3, default=(0.0, -560.0, -170.0), help="point visé (repère Blender)")
    a = ap.parse_args()

    import bpy
    W, H = (int(v) for v in a.res.lower().split("x"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = a.spp
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"

    # ciel couvert
    w = bpy.data.worlds.new("ciel")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.74, 0.77, 0.80, 1)
    bg.inputs["Strength"].default_value = 1.0
    if a.sun > 0:
        sun = bpy.data.objects.new("soleil", bpy.data.lights.new("soleil", "SUN"))
        sun.data.energy = a.sun
        sun.rotation_euler = (math.radians(50), 0, math.radians(30))
        sc.collection.objects.link(sun)

    # terrain
    xs = np.linspace(-2600, 2600, 260)
    ss = np.linspace(-60, 3300, 170)
    XX, SS = np.meshgrid(xs, ss)
    ZZ = zt(XX, SS)
    verts = np.stack([XX.ravel(), -SS.ravel(), ZZ.ravel()], 1).astype(np.float32)
    ny, nx = XX.shape
    idx = np.arange(nx * ny).reshape(ny, nx)
    quads = np.stack([idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]], -1).reshape(-1, 4)
    me = bpy.data.meshes.new("terrain")
    me.from_pydata(verts.tolist(), [], quads.tolist())
    for p in me.polygons:
        p.use_smooth = True
    ter = bpy.data.objects.new("Terrain", me)
    sc.collection.objects.link(ter)
    mt = bpy.data.materials.new("sol")
    mt.use_nodes = True
    nt = mt.node_tree
    bs = nt.nodes["Principled BSDF"]
    bs.inputs["Roughness"].default_value = 0.95
    tx = nt.nodes.new("ShaderNodeTexNoise")
    tx.inputs["Scale"].default_value = 0.02
    tx.inputs["Detail"].default_value = 6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.10, 0.17, 0.07, 1)     # forêt / pré
    ramp.color_ramp.elements[1].color = (0.30, 0.31, 0.19, 1)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(tc.outputs["Object"], tx.inputs["Vector"])
    nt.links.new(tx.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bs.inputs["Base Color"])
    me.materials.append(mt)

    # caméra: 90 degrés, à 2 m du sol, visant le dépôt
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.sensor_width = 36.0
    cam.data.lens = 18.0 / math.tan(math.radians(a.fov / 2))
    cam.location = (0.0, 0.0, 2.0)
    from mathutils import Vector
    tgt = Vector(a.target)
    cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.rotation_euler.z += math.radians(a.yaw)
    sc.collection.objects.link(cam)
    sc.camera = cam

    # matière
    coll = bpy.data.collections.new("Blatten")
    sc.collection.children.link(coll)
    seq = fake_seq(a.spacing)
    helpers = dict(
        to_blender=to_blender,
        frame_to_time=lambda scene, f: float(f),
        apply_height_fog=lambda mat: None,
        new_collection=lambda name: bpy.data.collections.new(name),
        build_default=lambda: None,
    )
    cfg = dict(radius=None, color=None, fog=0.6, look=None)
    mod = charger(a.module)
    t0 = time.time()
    sc.frame_start = sc.frame_end = sc.frame_current = 0
    mod.build(sc, seq, coll, cfg, print, helpers)
    mod.update(sc, a.t, seq)
    t_build = time.time() - t0
    print(f"[banc] {seq.count:,} particules, espacement {a.spacing} m, build+update {t_build:.1f} s")

    sc.render.filepath = os.path.abspath(a.out)
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"[banc] rendu {W}x{H} {a.spp} échantillons: {time.time() - t0:.1f} s -> {a.out}")


if __name__ == "__main__":
    main()
