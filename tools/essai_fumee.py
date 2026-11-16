"""essai_fumee.py : essai de fumée simulée (Mantaflow, le simulateur de gaz de Blender) à la place du nuage procédural.

But: juger si une vraie simulation donne un nuage plus crédible (volutes, front qui roule) avant d'y passer des jours.
Ce n'est PAS branché sur le film: scène à part (relief gris, fumée, caméra du film tournée vers l'événement), basse résolution.

Principe
  - Domaine de gaz couvrant tout le parcours de la matière (3,3 x 3,05 x 2 km), résolution --res cellules sur le grand côté
    (128 -> cellules de 26 m, 192 -> 17 m, 256 -> 13 m).
  - Émetteur: 3 000 particules de Johan tirées au hasard, chacune porte un petit tétraèdre; la fumée sort en proportion du carré
    de la vitesse (comme les sources du nuage actuel) et part avec une part de la vitesse de la matière (--elan).
  - Obstacle: le relief (grille de 30 m).
  - Flottabilité --alpha: négatif = le nuage est plus lourd que l'air (courant de densité qui épouse la pente), positif = il monte.
  - Sorties dans --out: images fixes à t = 20, 30, 40 s (fumee_tXX.png), suite clip_NNNN.png toutes les 0,5 s, cache VDB (cache/).

Lancé par: python blatten.py essai-fumee [--res 128] [--fps 15] [--fin 45] [--alpha -0.2] [--tourbillons 0.2] [--elan 0.7]
Jamais essayé sur le PC (écrit le 17 nov. dans le cloud, où Mantaflow ne tourne pas): premier lancement = test de la chaîne.
"""
import json
import math
import os
import sys
import time

import bpy
import numpy as np


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    d = dict(res=128, fps=15, fin=45.0, alpha=-0.2, tourbillons=0.2, elan=0.7, densite=0.03, data="", out="", echant=48,
             largeur=1280, sans_rendu=0, k=3000, sans_simu=0)
    i = 0
    while i < len(a):
        k = a[i].lstrip("-").replace("-", "_")
        if k in d:
            d[k] = type(d[k])(a[i + 1])
            i += 2
        else:
            raise SystemExit(f"option inconnue: {a[i]}")
    return d


A = args()
D = A["data"]
OUT = A["out"]
os.makedirs(OUT, exist_ok=True)
fps = int(A["fps"])
em = json.load(open(os.path.join(D, "env", "env_meta.json")))
dem = np.load(os.path.join(D, "env", em["dem8"]["file"]), mmap_mode="r")
g = em["dem8"]


def zsol(X, Y):
    E = em["scene_E0"] + X
    N = em["scene_N0"] + em["flip"] * Y
    c = (E - g["x0"]) / g["step"]
    r = (g["y1"] - N) / g["step"]
    c0 = np.clip(np.floor(c).astype(int), 0, dem.shape[1] - 2)
    r0 = np.clip(np.floor(r).astype(int), 0, dem.shape[0] - 2)
    fc, fr = c - c0, r - r0
    return (dem[r0, c0] * (1 - fc) * (1 - fr) + dem[r0, c0 + 1] * fc * (1 - fr) + dem[r0 + 1, c0] * (1 - fc) * fr
            + dem[r0 + 1, c0 + 1] * fc * fr + em.get("dz", 0))


meta = json.load(open(os.path.join(D, "meta.json")))
FICH = [f["file"] for f in meta["files"]]
_c = {}


def arr(i):
    if i not in _c:
        if len(_c) > 3:
            _c.pop(next(iter(_c)))
        _c[i] = np.load(os.path.join(D, FICH[i]), mmap_mode="r")
    return _c[i]


K = int(A["k"])
rng = np.random.default_rng(3)
IDX = np.sort(rng.choice(arr(0).shape[0], K, replace=False))


def etat(t):
    """Positions et vitesses (repère de la scène, Z haut) des K particules à l'instant t (un fichier par seconde, Hermite)."""
    i = min(int(t), len(FICH) - 2)
    f = t - i
    a0, a1 = arr(i)[IDX], arr(i + 1)[IDX]
    p0, v0, p1, v1 = (x.astype(np.float64) for x in (a0[:, :3], a0[:, 3:6], a1[:, :3], a1[:, 3:6]))
    f2, f3 = f * f, f * f * f
    P = (2 * f3 - 3 * f2 + 1) * p0 + (f3 - 2 * f2 + f) * v0 + (-2 * f3 + 3 * f2) * p1 + (f3 - f2) * v1
    V = (6 * f2 - 6 * f) * (p0 - p1) + (3 * f2 - 4 * f + 1) * v0 + (3 * f2 - 2 * f) * v1

    def tb(a):
        return np.stack([a[:, 0], -a[:, 2], a[:, 1]], 1)
    return tb(P), tb(V)


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = fps
sc.frame_start, sc.frame_end = 1, int(A["fin"] * fps) + 1

# --- domaine
X0, X1, Y0, Y1, Z0, Z1 = -1300, 2000, -1600, 1450, 1350, 3350
bpy.ops.mesh.primitive_cube_add(size=1, location=((X0 + X1) / 2, (Y0 + Y1) / 2, (Z0 + Z1) / 2))
dom = bpy.context.object
dom.name = "Domaine"
dom.scale = (X1 - X0, Y1 - Y0, Z1 - Z0)
if not A["sans_simu"]:
    md = dom.modifiers.new("Fluide", "FLUID")
    md.fluid_type = "DOMAIN"
    ds = md.domain_settings
    ds.domain_type = "GAS"
    ds.resolution_max = int(A["res"])
    ds.use_adaptive_domain = True
    ds.adapt_margin = 4
    ds.adapt_threshold = 0.002
    ds.cache_type = "REPLAY"
    ds.cache_directory = os.path.join(OUT, "cache")
    ds.cache_data_format = "OPENVDB"
    ds.cache_frame_start, ds.cache_frame_end = sc.frame_start, sc.frame_end
    ds.alpha, ds.beta, ds.vorticity = float(A["alpha"]), 0.0, float(A["tourbillons"])
    ds.use_dissolve_smoke = False
    ds.use_adaptive_timesteps = True
    ds.cfl_condition = 4.0
    ds.timesteps_max, ds.timesteps_min = 4, 1
    ds.use_collision_border_bottom = True
    for b in ("front", "back", "left", "right", "top"):
        setattr(ds, f"use_collision_border_{b}", False)

# --- relief: solide fermé (obstacle de la simulation, et décor gris du rendu)
pas = 30.0
xs = np.arange(X0, X1 + pas, pas)
ys = np.arange(Y0, Y1 + pas, pas)
XX, YY = np.meshgrid(xs, ys)
ZZ = zsol(XX, YY)
nx, ny = len(xs), len(ys)
top = np.stack([XX, YY, ZZ], -1).reshape(-1, 3)
bot = top.copy()
bot[:, 2] = Z0 - 50
V = np.concatenate([top, bot])
n = nx * ny
F = []
for j in range(ny - 1):
    for i in range(nx - 1):
        a = j * nx + i
        F.append((a, a + 1, a + nx + 1, a + nx))
        F.append((n + a, n + a + nx, n + a + nx + 1, n + a + 1))
for i in range(nx - 1):
    F.append((i, n + i, n + i + 1, i + 1))
    a = (ny - 1) * nx + i
    F.append((a, a + 1, n + a + 1, n + a))
for j in range(ny - 1):
    a = j * nx
    F.append((a, a + nx, n + a + nx, n + a))
    a = j * nx + nx - 1
    F.append((a, n + a, n + a + nx, a + nx))
me = bpy.data.meshes.new("Relief")
me.from_pydata(V.tolist(), [], F)
me.update()
rel = bpy.data.objects.new("Relief", me)
sc.collection.objects.link(rel)
if not A["sans_simu"]:
    mr = rel.modifiers.new("Fluide", "FLUID")
    mr.fluid_type = "EFFECTOR"
    mr.effector_settings.effector_type = "COLLISION"
    mr.effector_settings.surface_distance = 0.5
mt = bpy.data.materials.new("Relief")
mt.use_nodes = True
mt.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.20, 0.23, 0.17, 1)
mt.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.95
me.materials.append(mt)

# --- émetteur
s = 0.8 * (X1 - X0) / int(A["res"])
tet = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], float) * s / 2
P, Vv = etat(0.0)
vv = (P[:, None, :] + tet[None, :, :]).reshape(-1, 3)
ff = [(4 * k + a, 4 * k + b, 4 * k + c) for k in range(K) for (a, b, c) in ((0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2))]
mem = bpy.data.meshes.new("Emetteur")
mem.from_pydata(vv.tolist(), [], ff)
mem.update()
emi = bpy.data.objects.new("Emetteur", mem)
sc.collection.objects.link(emi)
vg = emi.vertex_groups.new(name="poids")
vg.add(list(range(4 * K)), 0.0, "REPLACE")
if not A["sans_simu"]:
    mf = emi.modifiers.new("Fluide", "FLUID")
    mf.fluid_type = "FLOW"
    fs = mf.flow_settings
    fs.flow_type, fs.flow_behavior, fs.flow_source = "SMOKE", "INFLOW", "MESH"
    fs.density, fs.temperature, fs.surface_distance, fs.volume_density = 1.0, 0.0, 1.0, 1.0
    fs.use_initial_velocity = True
    fs.velocity_factor = float(A["elan"])
    fs.density_vertex_group = "poids"
emi.hide_render = bool(not A["sans_simu"])      # sans simulation (contrôle du cadrage): on voit les émetteurs
if A["sans_simu"]:
    dom.hide_render = True
VREF = 40.0


def maj(scene, *a):
    t = max(0.0, (scene.frame_current - 1) / fps)
    P, Vv = etat(min(t, len(FICH) - 1.01))
    P[:, 2] += 6.0                                    # un peu au-dessus de la matière
    w = np.clip((np.linalg.norm(Vv, axis=1) / VREF) ** 2, 0.0, 1.0)
    w[w < 0.04] = 0.0
    mem.vertices.foreach_set("co", (P[:, None, :] + tet[None, :, :]).reshape(-1).astype(np.float32))
    mem.update()
    ww = np.repeat(w, 4)
    for i_ in range(4 * K):
        mem.vertices[i_].groups[0].weight = float(ww[i_])


bpy.app.handlers.frame_change_pre.append(maj)

# --- rendu de contrôle: fumée (densité de la simulation), ciel couvert, caméra du film tournée vers l'événement
mv = bpy.data.materials.new("Fumee")
mv.use_nodes = True
nt = mv.node_tree
for nd in list(nt.nodes):
    nt.nodes.remove(nd)
o = nt.nodes.new("ShaderNodeOutputMaterial")
pv = nt.nodes.new("ShaderNodeVolumePrincipled")
pv.inputs["Color"].default_value = (0.66, 0.63, 0.59, 1)
at = nt.nodes.new("ShaderNodeAttribute")
at.attribute_name = "density"
mu = nt.nodes.new("ShaderNodeMath")
mu.operation = "MULTIPLY"
mu.inputs[1].default_value = float(A["densite"])
nt.links.new(at.outputs["Fac"], mu.inputs[0])
nt.links.new(mu.outputs[0], pv.inputs["Density"])
nt.links.new(pv.outputs[0], o.inputs["Volume"])
dom.data.materials.append(mv)
w = bpy.data.worlds.new("Ciel")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.78, 0.80, 0.84, 1)
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.location = (-643.73, 769.57, 1685.6)
cap, elev = math.radians(128.0), math.radians(12.0)          # vers l'événement, un peu au-dessus de l'horizon
dirv = np.array([math.sin(cap) * math.cos(elev), math.cos(cap) * math.cos(elev), math.sin(elev)])
from mathutils import Vector
cam.rotation_euler = Vector(dirv).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 16
cam.data.clip_end = 20000
r = sc.render
r.engine = "CYCLES"
r.resolution_x, r.resolution_y = int(A["largeur"]), int(A["largeur"] * 9 / 16)
r.image_settings.file_format = "PNG"
sc.cycles.samples = int(A["echant"])
sc.cycles.use_denoising = True
sc.cycles.volume_bounces = 1
try:
    pr = bpy.context.preferences.addons["cycles"].preferences
    for typ in ("OPTIX", "CUDA"):
        try:
            pr.compute_device_type = typ
            pr.get_devices()
            if any(d.type == typ for d in pr.devices):
                for d in pr.devices:
                    d.use = d.type == typ
                sc.cycles.device = "GPU"
                print(f"[fumee] rendu sur carte graphique ({typ})", flush=True)
                break
        except Exception:
            continue
except Exception as e:
    print("[fumee] rendu sur processeur:", e, flush=True)

fixes = {int(round(t * fps)) + 1: t for t in (20.0, 30.0, 40.0)}
pas_clip = max(1, int(round(0.5 * fps)))
t0 = time.time()
kclip = 0
for f in range(sc.frame_start, sc.frame_end + 1):
    sc.frame_set(f)
    t = (f - 1) / fps
    if f % fps == 0:
        print(f"[fumee] simulation: image {f}/{sc.frame_end} (t = {t:.1f} s), {time.time() - t0:.0f} s écoulées", flush=True)
    if A["sans_rendu"]:
        continue
    if f in fixes:
        r.filepath = os.path.join(OUT, f"fumee_t{int(fixes[f]):02d}.png")
        bpy.ops.render.render(write_still=True)
    if (f - 1) % pas_clip == 0 and t >= 8.0:
        kclip += 1
        r.filepath = os.path.join(OUT, "clip", f"clip_{kclip:04d}.png")
        bpy.ops.render.render(write_still=True)
print(f"[fumee] terminé: {time.time() - t0:.0f} s pour {sc.frame_end} images de simulation, sorties dans {OUT}", flush=True)
