"""
blatten_blender.py : scène Blender du glissement de Blatten (28 mai 2025), vidéo VR 360 stéréo.

Entrées : le dossier produit par src/matiere/prep_particules.py (meta.json + .npy) et, facultatif,
les VDB de Johan Gaume (terrain, zone de départ).

Lancement (Blender 4.x ou 5.x, testé avec l'API de 5.2) :
  Test rapide, une image, basse résolution :
    blender -b -P blatten_blender.py -- --data cache --terrain Nesthorn_terrain_klein.vdb ^
            --release Nesthorn_release_klein.vdb --preset test --render-frame 1 --save
  Animation finale :
    blender -b -P blatten_blender.py -- --data cache --preset final --render-anim --frames 1 900
  Interface : ouvrir ce fichier dans l'éditeur de texte, ajuster CFG ci-dessous, Run Script.

Repères : la simulation est en Y vertical (Houdini), Blender est en Z vertical.
Conversion : (x, y, z) -> (x, -z, y). Tout est recentré sur meta["origin"] ; l'altitude
réelle est conservée (Z Blender = altitude en m).

Hypothèses à valider (marquées HYPOTHESE) : pas de temps entre fichiers, échelle de temps,
alignement des VDB sur les particules.
"""
import argparse
import datetime as _dt
import json
import math
import os
import sys

import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Euler, Vector

# ----------------------------------------------------------------------------------
# Réglages par défaut (surchargés par la ligne de commande après "--")
# ----------------------------------------------------------------------------------
CFG = dict(
    data_dir=None,          # dossier meta.json + npy (défaut: ./cache à côté du script)
    terrain=None,           # chemin du VDB terrain (facultatif)
    release=None,           # chemin du VDB zone de départ (facultatif)
    grid_name="surface",    # nom de la grille VDB (repli: première grille)
    terrain_voxel=None,     # m, voxel du maillage terrain. None = meilleur maillage déjà converti
    terrain_only=None,      # m: convertit seulement le terrain à ce voxel, puis quitte
    release_voxel=4.0,
    adaptivity=0.03,        # simplification du maillage VDB (0..1)
    dt_per_step=0.01,       # HYPOTHESE: secondes de simulation par unité de numéro de fichier
    time_scale=1.0,         # secondes vidéo par seconde simulée (4.0 = ralenti x4)
    max_extrap=4.0,         # s, extrapolation max par la vitesse (cas fichier unique / après le dernier)
    fps=30,
    radius=None,            # m, rayon des points (défaut: 0.6 x espacement estimé)
    color=None,             # "speed" (couleur = vitesse) ou "natural". Défaut: selon --look
    look="realiste",        # "realiste" (terrain végétation/roche/neige, brume) ou "didactique"
    haze=0.0,               # ancien effet de brume dans le matériau (1/m). Remplacé par la brume physique (fog); 0 = désactivé
    cam=None,               # (x, y, z) m, repère Blender recentré (Z = altitude). Défaut: auto
    target=None,            # point visé (x, y, z). Défaut: centroïde des particules rapides
    stereo=True,
    ipd=40.0,               # m, écart inter-oculaire. 0.065 = réaliste, trop faible à 1 km+
    preset="test",          # "test" ou "final"
    show_release=True,      # zone de départ visible dans la vue, jamais dans le rendu
    sun_elevation=35.0,     # degrés
    sun_rotation=200.0,     # degrés
    out=None,               # dossier de rendu (défaut: ../render)
    frames=None,            # (début, fin)
    render_frame=None,
    render_anim=False,
    save=False,
    exposure=None,          # exposition de la vue (EV). None: 0 en ciel couvert, -2.5 en ciel clair
    views=False,            # génère 8 aperçus pour choisir le point de vue
    vue=None,               # numéro d'aperçu (1..8) à utiliser comme caméra 360
    dist=2500.0,            # m, distance des aperçus au centre de l'écoulement
    height=1000.0,          # m, hauteur des aperçus au-dessus du centre
    no_env=False,           # True: ignore l'environnement swisstopo (cache/env) et affiche le terrain de Johan
    snow=1.0,               # 0..1, quantité de neige ajoutée par l'altitude (l'image aérienne date de l'été)
    snow_line=2300.0,       # m, début de la neige (28 mai: d'après la capture RTS, neige au-dessus de 2200-2400 m)
    ortho_gain=1.0,         # luminosité de l'image aérienne dans le rendu (l'image est déséclairée par la préparation)
    clouds=0.0,             # 0..1, couverture nuageuse procédurale (0 = ciel dégagé)
    time="2025-05-28T15:24:00+02:00",   # instant de l'événement (heure locale), sert au soleil
    sky="couvert",          # "couvert" (voile blanc, lumière diffuse, comme le 28 mai 2025) ou "clair" (soleil réel)
    sky_gain=0.7,           # luminosité de l'éclairage du ciel couvert
    fog_mode="shader",      # "shader" (rapide, dans les matériaux) ou "volume" (physique, très lent sans GPU)
    fog=0.6,                # multiplicateur de la brume (0 = aucune). 1.0: crêtes à 5 km environ 50 % fondues
    mist=0.0,               # 0..1, bancs de brume dans la vallée (visibles sur les vidéos de l'événement)
    detail=1.0,             # 0..1, détail procédural ajouté à l'image aérienne (sol, roche)
    cam_rot=None,           # (rx, ry, rz) degrés, lu dans camera.json (orientation de la vue 360)
    _env_ok=False,          # interne: environnement swisstopo chargé
    camera_confirmed=False, # garde-fou rendu final: position de caméra validée par le groupe
    accept_lowres=False,    # garde-fou rendu final: accepte le relief 2 m / l'image 2 m (déconseillé)
    bench=False,            # mode benchmark: rend des images test et estime le temps du rendu final (src/bench/bench.py)
    bench_scale=None,       # échelle de la résolution du benchmark (None: 1.0 avec GPU, 0.25 sans)
    bench_no_warm=False,    # benchmark: saute la série "données persistantes" (plus rapide)
    matiere="defaut",       # "defaut": particules en sphères (build_debris ci-dessous), ou nom d'un module de src/matiere/ (ex. rendu_matiere), voir docs/HANDOVER_ALEA.md
    cull=False,             # ne construit que le relief VISIBLE depuis la caméra (masques de "python blatten.py visible")
    no_hires=False,         # ignore le relief 0,5 m et les images locales (comparaison / test mémoire)
    env_dir=None,           # dossier contenant env/ (défaut: celui des particules). Sert au test-clip
    clip=False,             # test grandeur nature: quelques secondes de l'événement (src/bench/clip.py)
    clip_seconds=3.0, clip_every=1, clip_quality=48, clip_scale=0.5, clip_samples=(24, 48, 96, 192),
    clip_no_keys=False, clip_no_video=False, clip_fullscale=1.0,
    persistent=False,       # rendu: garde en mémoire ce qui ne change pas d'une image à l'autre (plus rapide, plus de mémoire)
)

PRESETS = {
    "test": dict(res=(1024, 512), samples=16),
    "final": dict(res=(3840, 1920), samples=96),   # mono; en stéréo haut/bas l'image fait 3840 x 3840
}


def log(*a):
    print("[blatten]", *a, flush=True)


# ----------------------------------------------------------------------------------
# Séquence de particules
# ----------------------------------------------------------------------------------
class Sequence:
    """Fichiers .npy triés par pas. Interpolation par les vitesses entre deux fichiers."""

    def __init__(self, data_dir):
        self.dir = data_dir
        self.meta = json.load(open(os.path.join(data_dir, "meta.json")))
        self.files = self.meta["files"]
        self.steps = np.array([f["step"] for f in self.files], np.float64)
        self.times = (self.steps - self.steps[0]) * CFG["dt_per_step"]
        self._cache = {}

    def arr(self, i):
        if i not in self._cache:
            if len(self._cache) > 3:
                self._cache.pop(next(iter(self._cache)))
            self._cache[i] = np.load(os.path.join(self.dir, self.files[i]["file"]), mmap_mode="r")
        return self._cache[i]

    @property
    def count(self):
        return self.files[0]["count"]

    def state(self, t):
        """Positions (N,3) et vitesses (N,3), repère simulation (Y haut), temps t en s sim."""
        n = len(self.files)
        if n == 1 or t >= self.times[-1]:
            a = self.arr(n - 1)
            tau = min(max(t - self.times[-1], 0.0), CFG["max_extrap"]) if n > 1 else min(max(t, 0.0), CFG["max_extrap"])
            return a[:, :3] + a[:, 3:6] * tau, np.asarray(a[:, 3:6])
        t = max(t, self.times[0])
        i = int(np.searchsorted(self.times, t, side="right") - 1)
        a0, a1 = self.arr(i), self.arr(i + 1)
        dt = self.times[i + 1] - self.times[i]
        tau = t - self.times[i]
        f = tau / dt
        if len(a0) != len(a1):  # ordre des particules non garanti: plus proche fichier
            a = a0 if f < 0.5 else a1
            return np.asarray(a[:, :3]), np.asarray(a[:, 3:6])
        p0 = a0[:, :3] + a0[:, 3:6] * tau
        p1 = a1[:, :3] - a1[:, 3:6] * (dt - tau)
        return (1 - f) * p0 + f * p1, (1 - f) * np.asarray(a0[:, 3:6]) + f * np.asarray(a1[:, 3:6])


def to_blender(a):
    """Y vertical (Houdini) -> Z vertical (Blender) : (x, y, z) -> (x, -z, y)."""
    out = np.empty(a.shape, np.float32)
    out[:, 0] = a[:, 0]
    out[:, 1] = -a[:, 2]
    out[:, 2] = a[:, 1]
    return out


STATE = dict(seq=None, mesh=None, last_t=None)


def apply_time(t):
    seq, mesh = STATE["seq"], STATE["mesh"]
    if seq is None or mesh is None or STATE["last_t"] == t:
        return
    P, V = seq.state(t)
    mesh.vertices.foreach_set("co", to_blender(P).ravel())
    mesh.attributes["speed"].data.foreach_set("value", np.linalg.norm(V, axis=1).astype(np.float32))
    mesh.update()
    STATE["last_t"] = t


def frame_to_time(scene, frame):
    fps = scene.render.fps / scene.render.fps_base
    return (frame - scene.frame_start) / fps / CFG["time_scale"]


MATIERE = dict(mod=None)   # module de matière externe (src/matiere/<nom>.py), None = matière par défaut ci-dessous


def load_matiere(root):
    """Charge src/matiere/<CFG["matiere"]>.py. Interface (voir docs/HANDOVER_ALEA.md):
         build(scene, seq, coll, cfg, log, helpers) -> objet principal de la matière (ou None)
         update(scene, t, seq)   appelée à chaque changement d'image, t = temps de simulation en s
    """
    import importlib.util
    name = CFG["matiere"]
    path = name if name.endswith(".py") else os.path.join(root, "src", "matiere", name + ".py")
    if not os.path.exists(path):
        raise SystemExit(f"Module de matière introuvable: {path}")
    spec = importlib.util.spec_from_file_location("matiere_externe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in ("build", "update"):
        if not hasattr(mod, fn):
            raise SystemExit(f"{path}: fonction {fn}() manquante (interface: docs/HANDOVER_ALEA.md)")
    log(f"matière: module externe {path}")
    return mod


@persistent
def on_frame(scene, *args):
    t = frame_to_time(scene, scene.frame_current)
    if MATIERE["mod"] is not None:
        MATIERE["mod"].update(scene, t, STATE["seq"])
    else:
        apply_time(t)


# ----------------------------------------------------------------------------------
# Construction de la scène
# ----------------------------------------------------------------------------------
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def new_collection(scene, name):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    return c


def build_debris(scene, seq, coll):
    n = seq.count
    mesh = bpy.data.meshes.new("debris")
    mesh.vertices.add(n)
    mesh.attributes.new("speed", "FLOAT", "POINT")
    obj = bpy.data.objects.new("Debris", mesh)
    coll.objects.link(obj)
    STATE["mesh"], STATE["seq"] = mesh, seq
    apply_time(frame_to_time(scene, scene.frame_start))

    st = seq.meta.get("stats", {})
    radius = CFG["radius"] or 0.6 * (st.get("nn_median") or 3.0)
    log(f"{n:,} particules, rayon {radius:.2f} m")
    if "stats" in seq.meta:
        b0, b1 = seq.meta["stats"]["bounds_min"], seq.meta["stats"]["bounds_max"]
        log(f"emprise particules (Blender, recentrée) X {b0[0]:.0f}..{b1[0]:.0f}  "
            f"Y {-b1[2]:.0f}..{-b0[2]:.0f}  Z {b0[1]:.0f}..{b1[1]:.0f}")

    # Geometry Nodes : sommets -> points (rendus comme sphères par Cycles) + matériau
    ng = bpy.data.node_groups.new("DebrisPoints", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nin, nout = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")
    m2p = ng.nodes.new("GeometryNodeMeshToPoints")
    m2p.mode = "VERTICES"
    setmat = ng.nodes.new("GeometryNodeSetMaterial")
    setmat.inputs["Material"].default_value = build_debris_material(seq.meta["vmax"])
    ng.links.new(nin.outputs["Geometry"], m2p.inputs["Mesh"])
    m2p.inputs["Radius"].default_value = radius
    ng.links.new(m2p.outputs["Points"], setmat.inputs["Geometry"])
    ng.links.new(setmat.outputs["Geometry"], nout.inputs["Geometry"])
    mod = obj.modifiers.new("Points", "NODES")
    mod.node_group = ng
    return obj


def build_debris_material(vmax):
    mat = bpy.data.materials.new("Debris")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.85
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    if CFG["color"] == "speed":
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_name, attr.attribute_type = "speed", "GEOMETRY"
        rng = nt.nodes.new("ShaderNodeMapRange")
        rng.inputs["From Min"].default_value = 0.0
        rng.inputs["From Max"].default_value = float(vmax)
        rng.clamp = True
        nt.links.new(attr.outputs["Fac"], rng.inputs["Value"])
        nt.links.new(rng.outputs["Result"], ramp.inputs["Fac"])
        stops = [(0.0, (0.22, 0.20, 0.18, 1)), (0.12, (0.80, 0.62, 0.18, 1)),
                 (0.5, (0.90, 0.25, 0.04, 1)), (1.0, (0.45, 0.02, 0.12, 1))]
    else:
        pi = nt.nodes.new("ShaderNodeParticleInfo")   # alea par point
        nt.links.new(pi.outputs["Random"], ramp.inputs["Fac"])
        stops = [(0.0, (0.14, 0.125, 0.11, 1)), (1.0, (0.30, 0.275, 0.25, 1))]
    cr = ramp.color_ramp
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[-1])
    cr.elements[0].position, cr.elements[0].color = stops[0]
    for pos, col in stops[1:]:
        e = cr.elements.new(pos)
        e.color = col
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    if CFG["color"] == "natural":
        apply_height_fog(mat)
    return mat


def find_cache(name, cache_dir):
    """Meilleur maillage déjà converti (plus petit voxel disponible), ou None."""
    import glob
    import re
    best = None
    for f in glob.glob(os.path.join(cache_dir, f"{name}_mesh_*m.blend")):
        m = re.search(r"_mesh_([\d.]+)m\.blend$", f)
        if m and (best is None or float(m.group(1)) < best[0]):
            best = (float(m.group(1)), f)
    return best


def vdb_to_mesh(path, name, voxel, offset, rot, coll, color, cache_dir, convert=True):
    """Importe un VDB (niveau set), le convertit en maillage figé et supprime le volume.
    Le maillage est mis en cache dans un .blend pour ne pas refaire la conversion.
    convert=False: ne lit que le cache (renvoie None s'il n'y en a pas). voxel=None: meilleur cache."""
    if voxel is None:
        found = find_cache(name, cache_dir)
        if found is None:
            log(f"{name}: pas encore converti (lancer: python blatten.py terrain). Ignoré.")
            return None
        voxel = found[0]
    cache = os.path.join(cache_dir, f"{name}_mesh_{voxel:g}m.blend")
    if not os.path.exists(cache) and not convert:
        return None
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9

    if os.path.exists(cache):
        with bpy.data.libraries.load(cache) as (src, dst):
            dst.meshes = list(src.meshes)[:1]
        mesh = dst.meshes[0]
        mesh.name = name
        log(f"{name}: maillage relu du cache {os.path.basename(cache)}")
    else:
        log(f"{name}: lecture du VDB (voxel visé {voxel:g} m), peut être long et gourmand en mémoire ...")
        before = set(bpy.data.objects)
        bpy.ops.object.volume_import(filepath=path, align="WORLD")
        vol = next(o for o in bpy.data.objects if o not in before)
        vol.rotation_euler = rot            # Y haut -> Z haut
        vol.location = offset               # recentrage sur l'origine
        vol.data.grids.load()
        grids = [g.name for g in vol.data.grids]
        grid = CFG["grid_name"] if CFG["grid_name"] in grids else grids[0]
        log(f"{name}: grilles {grids}, utilisée: {grid}")
        tmp_mesh = bpy.data.meshes.new(name + "_tmp")
        tmp = bpy.data.objects.new(name + "_tmp", tmp_mesh)
        coll.objects.link(tmp)
        mod = tmp.modifiers.new("V2M", "VOLUME_TO_MESH")
        mod.object, mod.grid_name = vol, grid
        mod.resolution_mode = "VOXEL_SIZE"
        mod.voxel_size = voxel
        mod.adaptivity = CFG["adaptivity"]
        mod.use_smooth_shade = True
        for thr in (0.0, 0.5):  # niveau set (0), puis grille de densité (0.5) en repli
            mod.threshold = thr
            bpy.context.view_layer.update()
            dg = bpy.context.evaluated_depsgraph_get()
            mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
            if len(mesh.polygons):
                break
            log(f"{name}: aucun polygone au seuil {thr}, nouvel essai")
            bpy.data.meshes.remove(mesh)
        else:
            mesh = bpy.data.meshes.new(name)
        mesh.name = name
        bpy.data.objects.remove(tmp)
        bpy.data.meshes.remove(tmp_mesh)
        bpy.data.objects.remove(vol)
        log(f"{name}: {len(mesh.polygons):,} faces")
        if len(mesh.vertices):
            co = np.empty(len(mesh.vertices) * 3, np.float32)
            mesh.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)
            log(f"{name}: emprise recentrée (m) min {co.min(0).round(0).tolist()} max {co.max(0).round(0).tolist()}")
        if len(mesh.polygons):
            bpy.data.libraries.write(cache, {mesh}, fake_user=True)
    obj = bpy.data.objects.new(name, mesh)
    mesh.materials.append(mat)
    coll.objects.link(obj)
    return obj


# ----------------------------------------------------------------------------------
# Environnement réaliste : relief swissALTI3D, image SWISSIMAGE, soleil réel
# (préparé par src/environnement/prep_env.py dans cache/env)
# ----------------------------------------------------------------------------------
ENV_RINGS = [(2.0, 1024.0), (8.0, 4096.0), (32.0, 8192.0), (128.0, 16384.0)]  # (pas, demi-côté) en m


def _block_mean(a, f):
    h, w = a.shape[0] // f * f, a.shape[1] // f * f
    return a[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3), dtype=np.float32)


def load_env(data_dir):
    d = os.path.join(data_dir, "env")
    p = os.path.join(d, "env_meta.json")
    if not os.path.exists(p):
        return None
    m = json.load(open(p))
    d8, d2 = m["dem8"], m["dem2"]
    a8 = np.load(os.path.join(d, d8["file"]))
    a2 = np.load(os.path.join(d, d2["file"]), mmap_mode="r")
    a32 = _block_mean(a8, 4)
    a128 = _block_mean(a32, 4)
    lv = {2.0: (a2, d2["x0"], d2["y1"], 2.0), 8.0: (a8, d8["x0"], d8["y1"], 8.0),
          32.0: (a32, d8["x0"], d8["y1"], 32.0), 128.0: (a128, d8["x0"], d8["y1"], 128.0)}
    if m.get("dem05") and not CFG["no_hires"]:   # relief 0,5 m autour de la caméra (prep-env --hires)
        d5 = m["dem05"]
        a5 = np.load(os.path.join(d, d5["file"]))
        lv[0.5] = (a5, d5["x0"], d5["y1"], 0.5)
        lv[1.0] = (_block_mean(a5, 2), d5["x0"], d5["y1"], 1.0)
    vis = None
    vd = os.path.join(d, "visible")
    if CFG["cull"]:
        if os.path.exists(os.path.join(vd, "visible_2m.npy")):
            v2 = np.load(os.path.join(vd, "visible_2m.npy"))
            v8 = np.load(os.path.join(vd, "visible_8m.npy"))

            def pool(v, f):
                h, w = v.shape[0] // f * f, v.shape[1] // f * f
                return v[:h, :w].reshape(h // f, f, w // f, f).any(axis=(1, 3))
            vis = {0.5: (v2, d2["x0"], d2["y1"], 2.0), 1.0: (v2, d2["x0"], d2["y1"], 2.0), 2.0: (v2, d2["x0"], d2["y1"], 2.0),
                   8.0: (v8, d8["x0"], d8["y1"], 8.0), 32.0: (pool(v8, 4), d8["x0"], d8["y1"], 32.0),
                   128.0: (pool(v8, 16), d8["x0"], d8["y1"], 128.0)}
            p05 = os.path.join(vd, "visible_05m.npy")
            if m.get("dem05") and not CFG["no_hires"] and os.path.exists(p05):   # masque fin pour les anneaux 0,5 et 1 m
                v5, d5 = np.load(p05), m["dem05"]
                vis[0.5] = (v5, d5["x0"], d5["y1"], 0.5)
                vis[1.0] = (pool(v5, 2), d5["x0"], d5["y1"], 1.0)
            log(f"coupe du relief non visible (--cull): {np.mean(v2) * 100:.1f} % de la grille 2 m conservée")
        else:
            log("--cull demandé mais pas de masque: lancer d'abord python blatten.py visible (relief complet utilisé)")
    return dict(meta=m, dir=d, levels=lv, vis=vis)


def _bilin(level, E, N):
    arr, x0, y1, step = level
    u = np.clip((E - x0) / step - 0.5, 0, arr.shape[1] - 1.001)
    v = np.clip((y1 - N) / step - 0.5, 0, arr.shape[0] - 1.001)
    i, j = np.floor(v).astype(np.int64), np.floor(u).astype(np.int64)
    fy, fx = (v - i).astype(np.float32), (u - j).astype(np.float32)
    return ((1 - fy) * ((1 - fx) * arr[i, j] + fx * arr[i, j + 1]) +
            fy * ((1 - fx) * arr[i + 1, j] + fx * arr[i + 1, j + 1]))


def _vis_at(level, E, N):
    """Vrai là où le masque de visibilité l'est (ou hors de la grille du masque: on garde)."""
    arr, x0, y1, s = level
    i = np.floor((E - x0) / s).astype(np.int64)
    j = np.floor((y1 - N) / s).astype(np.int64)
    ok = (i >= 0) & (i < arr.shape[1]) & (j >= 0) & (j < arr.shape[0])
    return ~ok | arr[np.clip(j, 0, arr.shape[0] - 1), np.clip(i, 0, arr.shape[1] - 1)]


def env_ring(env, Ec, Nc, step, H, hole, next_step):
    """Un anneau carré de relief (pas `step`, demi-côté H) centré en (Ec, Nc) LV95, percé d'un trou
    carré de demi-côté `hole`. Le bord extérieur est calé sur le segment du maillage plus grossier
    voisin (pas de fissure), avec raccord progressif vers l'intérieur."""
    m = env["meta"]
    lv = env["levels"]
    n = int(round(2 * H / step))
    u = -H + step * np.arange(n + 1, dtype=np.float64)
    E = Ec + np.broadcast_to(u[None, :], (n + 1, n + 1))
    N = Nc + np.broadcast_to(u[:, None], (n + 1, n + 1))
    z = _bilin(lv[step], E, N).astype(np.float64)
    if next_step:
        cl = lv[next_step]
        ta = np.floor(u / next_step) * next_step
        tb = ta + next_step
        f = (u - ta) / next_step

        def edge(fe=None, fn=None):
            if fe is not None:
                za, zb = _bilin(cl, Ec + fe, Nc + ta), _bilin(cl, Ec + fe, Nc + tb)
            else:
                za, zb = _bilin(cl, Ec + ta, Nc + fn), _bilin(cl, Ec + tb, Nc + fn)
            return (1 - f) * za + f * zb

        zl, zr, zbo, zt = edge(fe=-H), edge(fe=H), edge(fn=-H), edge(fn=H)
        dl, dr, db, dt = zl - z[:, 0], zr - z[:, n], zbo - z[0, :], zt - z[n, :]
        w = np.clip(1 - np.arange(n + 1) * step / (4.0 * next_step), 0, 1) ** 2
        Wl, Wr, Wb, Wt = w[None, :], w[::-1][None, :], w[:, None], w[::-1][:, None]
        num = Wl * dl[:, None] + Wr * dr[:, None] + Wb * db[None, :] + Wt * dt[None, :]
        z = z + num / np.maximum(1.0, Wl + Wr + Wb + Wt)
        z[:, 0], z[:, n], z[0, :], z[n, :] = zl, zr, zbo, zt
    flip = m["flip"]
    dz = m.get("dz", 0.0)
    dz = dz if abs(dz) < 30 else 0.0
    X = E - m["scene_E0"]
    Y = flip * (N - m["scene_N0"])
    r, c = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    if hole > 0:
        cu = -H + (np.arange(n) + 0.5) * step
        inside = (np.abs(cu)[None, :] < hole) & (np.abs(cu)[:, None] < hole)
        keep = ~inside
    else:
        keep = np.ones((n, n), bool)
    if env.get("vis") is not None and step in env["vis"]:
        cu = -H + (np.arange(n) + 0.5) * step
        keep = keep & _vis_at(env["vis"][step], Ec + cu[None, :], Nc + cu[:, None])
    v00 = (r * (n + 1) + c)[keep]
    quads = np.stack([v00, v00 + 1, v00 + n + 2, v00 + n + 1], axis=1)
    if flip < 0:
        quads = quads[:, ::-1]
    used = np.zeros((n + 1) * (n + 1), bool)
    used[quads.ravel()] = True
    remap = np.cumsum(used) - 1
    quads = remap[quads].astype(np.int32)
    co = np.stack([X.ravel(), Y.ravel(), (z + dz).ravel()], axis=1)[used].astype(np.float32)
    return co, quads


def quads_to_mesh(name, co, quads):
    me = bpy.data.meshes.new(name)
    nv, nf = len(co), len(quads)
    me.vertices.add(nv)
    me.vertices.foreach_set("co", co.ravel())
    me.loops.add(nf * 4)
    me.loops.foreach_set("vertex_index", quads.ravel())
    me.polygons.add(nf)
    me.polygons.foreach_set("loop_start", np.arange(0, nf * 4, 4, dtype=np.int32))
    try:
        me.polygons.foreach_set("loop_total", np.full(nf, 4, np.int32))
    except Exception:
        pass
    me.update(calc_edges=True)
    try:
        me.polygons.foreach_set("use_smooth", np.ones(nf, bool))
    except Exception:
        try:
            me.shade_smooth()
        except Exception:
            pass
    return me


HIRES_RINGS = [(0.5, 384.0), (1.0, 768.0)]   # (pas, demi-côté) ajoutés au centre quand le relief 0,5 m existe


def env_rings(env, Ec, Nc):
    rings = list(ENV_RINGS)
    if 0.5 in env["levels"]:
        arr, x0, y1, st = env["levels"][0.5]
        cx1, cy0 = x0 + arr.shape[1] * st, y1 - arr.shape[0] * st
        hi = []
        for stp, H in HIRES_RINGS:   # chaque anneau doit tenir dans l'emprise du relief 0,5 m
            if Ec - H >= x0 and Ec + H <= cx1 and Nc - H >= cy0 and Nc + H <= y1:
                hi.append((stp, H))
            else:
                log(f"  anneau {stp:g} m (demi-côté {H:g} m) hors de l'emprise du relief 0,5 m: ignoré")
        rings = hi + rings
    return rings


def build_env_terrain(env, center, coll, mat):
    m = env["meta"]
    flip = m["flip"]
    Ec = round((m["scene_E0"] + center[0]) / 128.0) * 128.0
    Nc = round((m["scene_N0"] + flip * center[1]) / 128.0) * 128.0
    rings = env_rings(env, Ec, Nc)
    log(f"relief swisstopo centré sur E {Ec:.0f} N {Nc:.0f} (anneaux {', '.join(f'{s:g} m' for s, _ in rings)})")
    prev = 0.0
    objs = []
    for k, (step, H) in enumerate(rings):
        nxt = rings[k + 1][0] if k + 1 < len(rings) else None
        co, quads = env_ring(env, Ec, Nc, step, H, prev, nxt)
        me = quads_to_mesh(f"Relief_{step:g}m", co, quads)
        me.materials.append(mat)
        ob = bpy.data.objects.new(f"Relief_{step:g}m", me)
        coll.objects.link(ob)
        ob.color = (0.5, 0.48, 0.44, 1)
        objs.append(ob)
        log(f"  anneau {step:g} m: {len(co):,} sommets, {len(quads):,} faces")
        prev = H
    return objs


def lv95_to_wgs84(E, N):
    y, x = (E - 2600000.0) / 1e6, (N - 1200000.0) / 1e6
    lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return lat * 100.0 / 36.0, lon * 100.0 / 36.0


def sun_position(lat, lon, when):
    """Élévation et azimut (depuis le nord, vers l'est) du soleil, formules astronomiques simplifiées."""
    u = when.astimezone(_dt.timezone.utc)
    d = (u - _dt.datetime(2000, 1, 1, 12, tzinfo=_dt.timezone.utc)).total_seconds() / 86400.0
    L = math.radians((280.460 + 0.9856474 * d) % 360)
    g = math.radians((357.528 + 0.9856003 * d) % 360)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 0.0000004 * d)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    H = math.radians(((18.697374558 + 24.06570982441908 * d) % 24) * 15 + lon) - ra
    la = math.radians(lat)
    el = math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(H))
    az = math.atan2(-math.cos(dec) * math.sin(H), math.sin(dec) * math.cos(la) - math.cos(dec) * math.sin(la) * math.cos(H))
    return math.degrees(el), math.degrees(az) % 360


def sun_vector(env, center):
    """Direction du soleil (vers le soleil) dans le repère Blender. Avec l'environnement: soleil réel."""
    if env:
        m = env["meta"]
        lat, lon = lv95_to_wgs84(m["scene_E0"] + center[0], m["scene_N0"] + m["flip"] * center[1])
        el, az = sun_position(lat, lon, _dt.datetime.fromisoformat(CFG["time"]))
        flip = m["flip"]
        log(f"soleil le {CFG['time']} à {lat:.3f} N {lon:.3f} E : élévation {el:.1f}°, azimut {az:.1f}° (depuis le nord)")
    else:
        el, az, flip = CFG["sun_elevation"], CFG["sun_rotation"], 1
    e, a = math.radians(el), math.radians(az)
    return Vector((math.sin(a) * math.cos(e), flip * math.cos(a) * math.cos(e), math.sin(e)))


def build_terrain_material(env=None):
    """Terrain réaliste sans texture externe : couleur selon l'altitude (forêt, alpage, roche),
    roche sur les pentes raides, neige sur les pentes douces en altitude, micro-relief par bruit.
    Les altitudes sont celles du modèle (Z Blender = altitude en m)."""
    mat = bpy.data.materials.new("TerrainReel")
    mat.use_nodes = True
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    bsdf = N["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.95

    geo = N.new("ShaderNodeNewGeometry")
    pos = N.new("ShaderNodeSeparateXYZ")
    nor = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Position"], pos.inputs["Vector"])
    L.new(geo.outputs["Normal"], nor.inputs["Vector"])

    def noise(scale, detail=4.0):
        n = N.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        L.new(geo.outputs["Position"], n.inputs["Vector"])
        return n.outputs["Fac"]

    def mrange(src, a, b, lo=0.0, hi=1.0):
        m = N.new("ShaderNodeMapRange")
        m.interpolation_type = "SMOOTHSTEP"
        m.clamp = True
        m.inputs["From Min"].default_value, m.inputs["From Max"].default_value = a, b
        m.inputs["To Min"].default_value, m.inputs["To Max"].default_value = lo, hi
        if isinstance(src, (int, float)):
            m.inputs["Value"].default_value = src
        else:
            L.new(src, m.inputs["Value"])
        return m.outputs["Result"]

    def math(op, a, b):
        m = N.new("ShaderNodeMath")
        m.operation = op
        for i, v in enumerate((a, b)):
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                L.new(v, m.inputs[i])
        return m.outputs["Value"]

    def mix(fac, a, b):
        m = N.new("ShaderNodeMix")
        m.data_type = "RGBA"
        L.new(fac, m.inputs[0]) if not isinstance(fac, (int, float)) else None
        for idx, v in ((6, a), (7, b)):
            if isinstance(v, tuple):
                m.inputs[idx].default_value = v
            else:
                L.new(v, m.inputs[idx])
        return m.outputs[2]

    big, mid, fine = noise(0.004), noise(0.02), noise(0.15, 6.0)
    # altitude "bruitée" pour que les limites de végétation et de neige ne soient pas des lignes droites
    alt = math("ADD", pos.outputs["Z"], math("MULTIPLY", math("SUBTRACT", big, 0.5), 450.0))
    # dégradé d'altitude : forêt -> alpage -> éboulis -> roche
    ramp = N.new("ShaderNodeValToRGB")
    L.new(mrange(alt, 1200.0, 3200.0), ramp.inputs["Fac"])
    cr = ramp.color_ramp
    stops = [(0.00, (0.030, 0.050, 0.020, 1)), (0.35, (0.045, 0.070, 0.028, 1)),
             (0.48, (0.110, 0.120, 0.060, 1)), (0.62, (0.180, 0.170, 0.140, 1)),
             (1.00, (0.230, 0.220, 0.210, 1))]
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[-1])
    cr.elements[0].position, cr.elements[0].color = stops[0]
    for pos_, col in stops[1:]:
        e = cr.elements.new(pos_)
        e.color = col
    base = ramp.outputs["Color"]
    # roche nue sur les pentes raides (normale peu verticale), striée par le bruit
    steep = mrange(math("ADD", nor.outputs["Z"], math("MULTIPLY", math("SUBTRACT", mid, 0.5), 0.35)), 0.50, 0.78, 1.0, 0.0)
    rock = mix(fine, (0.17, 0.165, 0.16, 1), (0.27, 0.26, 0.25, 1))
    col = mix(steep, base, rock)
    o = env["meta"].get("ortho") if env else None
    if o:  # image aérienne SWISSIMAGE projetée à la verticale, fondue vers le procédural hors emprise
        em = env["meta"]
        img = bpy.data.images.load(os.path.join(env["dir"], o["file"]))
        img.colorspace_settings.name = "sRGB"
        tex = N.new("ShaderNodeTexImage")
        tex.image, tex.interpolation, tex.extension = img, "Linear", "EXTEND"
        mp = N.new("ShaderNodeMapping")
        mp.vector_type = "POINT"
        Wm, Hm = o["shape"][1] * o["step"], o["shape"][0] * o["step"]
        nb = o["y1"] - Hm
        mp.inputs["Location"].default_value = ((em["scene_E0"] - o["x0"]) / Wm, (em["scene_N0"] - nb) / Hm, 0.0)
        mp.inputs["Scale"].default_value = (1.0 / Wm, em["flip"] / Hm, 1.0)
        L.new(geo.outputs["Position"], mp.inputs["Vector"])
        L.new(mp.outputs["Vector"], tex.inputs["Vector"])
        sepuv = N.new("ShaderNodeSeparateXYZ")
        L.new(mp.outputs["Vector"], sepuv.inputs["Vector"])
        uu, vv = sepuv.outputs["X"], sepuv.outputs["Y"]
        du = math("MINIMUM", uu, math("SUBTRACT", 1.0, uu))
        dv = math("MINIMUM", vv, math("SUBTRACT", 1.0, vv))
        inside = mrange(math("MINIMUM", du, dv), 0.0, 0.015)
        hs = N.new("ShaderNodeHueSaturation")
        hs.inputs["Saturation"].default_value = 0.8
        hs.inputs["Value"].default_value = CFG["ortho_gain"]
        L.new(tex.outputs["Color"], hs.inputs["Color"])
        col = mix(inside, col, hs.outputs["Color"])
        for pa in ([] if CFG["no_hires"] else em.get("ortho_patches", [])):   # images locales 50 cm, 10 cm (du plus grossier au plus fin)
            pimg = bpy.data.images.load(os.path.join(env["dir"], pa["file"]))
            pimg.colorspace_settings.name = "sRGB"
            pt = N.new("ShaderNodeTexImage")
            pt.image, pt.interpolation, pt.extension = pimg, "Linear", "EXTEND"
            pm = N.new("ShaderNodeMapping")
            pm.vector_type = "POINT"
            pW, pH = pa["shape"][1] * pa["step"], pa["shape"][0] * pa["step"]
            pnb = pa["y1"] - pH
            pm.inputs["Location"].default_value = ((em["scene_E0"] - pa["x0"]) / pW, (em["scene_N0"] - pnb) / pH, 0.0)
            pm.inputs["Scale"].default_value = (1.0 / pW, em["flip"] / pH, 1.0)
            L.new(geo.outputs["Position"], pm.inputs["Vector"])
            L.new(pm.outputs["Vector"], pt.inputs["Vector"])
            psep = N.new("ShaderNodeSeparateXYZ")
            L.new(pm.outputs["Vector"], psep.inputs["Vector"])
            pdu = math("MINIMUM", psep.outputs["X"], math("SUBTRACT", 1.0, psep.outputs["X"]))
            pdv = math("MINIMUM", psep.outputs["Y"], math("SUBTRACT", 1.0, psep.outputs["Y"]))
            pin = mrange(math("MINIMUM", pdu, pdv), 0.0, min(0.2, 30.0 / pW))   # fondu sur 30 m en bord d'image
            phs = N.new("ShaderNodeHueSaturation")
            phs.inputs["Saturation"].default_value = 0.8
            phs.inputs["Value"].default_value = CFG["ortho_gain"]
            L.new(pt.outputs["Color"], phs.inputs["Color"])
            col = mix(pin, col, phs.outputs["Color"])
    # neige : en altitude et sur pentes douces (l'image date de l'été, le 28 mai il y en avait plus haut)
    sl = CFG["snow_line"] if env else 2350.0
    snow_alt = mrange(alt, sl, sl + 400.0)
    snow_flat = mrange(math("ADD", nor.outputs["Z"], math("MULTIPLY", math("SUBTRACT", fine, 0.5), 0.25)), 0.50, 0.80)
    snow = math("MULTIPLY", snow_alt, snow_flat)
    if CFG["snow"] != 1.0:
        snow = math("MULTIPLY", snow, CFG["snow"])
    D = max(0.0, min(1.0, CFG["detail"]))
    n_fine = noise(0.9, 5.0)      # grain de ~1 m: herbe, cailloux
    n_mid = noise(0.12, 4.0)      # taches de ~8 m
    # strates de la roche: bruit étiré à l'horizontale (fréquence verticale forte)
    comb = N.new("ShaderNodeCombineXYZ")
    L.new(math("MULTIPLY", pos.outputs["X"], 0.04), comb.inputs["X"])
    L.new(math("MULTIPLY", pos.outputs["Y"], 0.04), comb.inputs["Y"])
    L.new(math("MULTIPLY", pos.outputs["Z"], 0.55), comb.inputs["Z"])
    strata = N.new("ShaderNodeTexNoise")
    strata.inputs["Scale"].default_value, strata.inputs["Detail"].default_value = 1.0, 3.0
    L.new(comb.outputs["Vector"], strata.inputs["Vector"])
    if D > 0:  # détail ajouté à l'image de 2 m, estompé avec la distance (invisible au-delà de quelques km)
        cam0 = N.new("ShaderNodeCameraData")
        near = mrange(cam0.outputs["View Distance"], 500.0, 3000.0, 1.0, 0.0)
        dv = math("ADD", 1.0, math("ADD", math("MULTIPLY", math("SUBTRACT", n_fine, 0.5), 0.5 * D), math("MULTIPLY", math("SUBTRACT", n_mid, 0.5), 0.4 * D)))
        dvec = N.new("ShaderNodeCombineColor")
        for ch in ("Red", "Green", "Blue"):
            L.new(dv, dvec.inputs[ch])
        mm = N.new("ShaderNodeMix")
        mm.data_type, mm.blend_type = "RGBA", "MULTIPLY"
        L.new(near, mm.inputs[0])
        L.new(col, mm.inputs[6])
        L.new(dvec.outputs["Color"], mm.inputs[7])
        col = mm.outputs[2]
    col = mix(snow, col, (0.80, 0.82, 0.86, 1))
    L.new(col, bsdf.inputs["Base Color"])
    # micro-relief
    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 1.0
    h = math("ADD", math("MULTIPLY", mid, 0.7), math("MULTIPLY", fine, 0.3))
    if D > 0:
        h = math("ADD", h, math("MULTIPLY", n_fine, 0.25 * D))
        h = math("ADD", h, math("MULTIPLY", math("MULTIPLY", strata.outputs["Fac"], steep), 0.6 * D))
    L.new(h, bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if CFG["haze"] > 0:  # perspective atmosphérique: on mélange vers la couleur du ciel avec la distance
        cam = N.new("ShaderNodeCameraData")
        decay = math("POWER", 2.718281828, math("MULTIPLY", cam.outputs["View Distance"], -CFG["haze"]))
        fog = math("SUBTRACT", 1.0, decay)
        em = N.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (0.62, 0.76, 0.95, 1)
        em.inputs["Strength"].default_value = 2.0
        mx = N.new("ShaderNodeMixShader")
        L.new(fog, mx.inputs[0])
        L.new(bsdf.outputs["BSDF"], mx.inputs[1])
        L.new(em.outputs["Emission"], mx.inputs[2])
        L.new(mx.outputs["Shader"], N["Material Output"].inputs["Surface"])
    apply_height_fog(mat)
    return mat


def add_clouds(nt, sky_col, sun_dir):
    """Couche de nuages procédurale (plan projeté), épargnant le disque solaire."""
    N, L = nt.nodes, nt.links
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Generated"], sep.inputs["Vector"])

    def mth(op, a, b=None):
        m = N.new("ShaderNodeMath")
        m.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                L.new(v, m.inputs[i])
        return m.outputs["Value"]

    def rng(src, a, b):
        r = N.new("ShaderNodeMapRange")
        r.interpolation_type, r.clamp = "SMOOTHSTEP", True
        r.inputs["From Min"].default_value, r.inputs["From Max"].default_value = a, b
        L.new(src, r.inputs["Value"])
        return r.outputs["Result"]

    zz = mth("ADD", mth("MAXIMUM", sep.outputs["Z"], 0.0), 0.18)
    comb = N.new("ShaderNodeCombineXYZ")
    L.new(mth("DIVIDE", sep.outputs["X"], zz), comb.inputs["X"])
    L.new(mth("DIVIDE", sep.outputs["Y"], zz), comb.inputs["Y"])
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value, nz.inputs["Detail"].default_value = 1.6, 6.0
    L.new(comb.outputs["Vector"], nz.inputs["Vector"])
    mid = 0.6 - 0.2 * min(max(CFG["clouds"], 0.0), 1.0)
    cov = rng(nz.outputs["Fac"], mid - 0.07, mid + 0.07)
    cov = mth("MULTIPLY", cov, rng(sep.outputs["Z"], 0.0, 0.2))        # fondu vers l'horizon
    dotp = N.new("ShaderNodeVectorMath")
    dotp.operation = "DOT_PRODUCT"
    dotp.inputs[1].default_value = tuple(sun_dir)
    L.new(tc.outputs["Generated"], dotp.inputs[0])
    away = mth("SUBTRACT", 1.0, rng(dotp.outputs["Value"], 0.985, 0.998))
    cov = mth("MULTIPLY", cov, away)
    mx = N.new("ShaderNodeMix")
    mx.data_type = "RGBA"
    L.new(cov, mx.inputs[0])
    L.new(sky_col, mx.inputs[6])
    mx.inputs[7].default_value = (5.0, 5.0, 5.1, 1.0)   # luminance du ciel (exposition de la vue: -2.5 EV)
    return mx.outputs[2]


class _Nodes:
    """Petits constructeurs de noeuds pour écrire les shaders sans répétition."""

    def __init__(self, nt):
        self.nt, self.N, self.L = nt, nt.nodes, nt.links

    def _set(self, node, idx, v):
        if isinstance(v, (int, float, tuple)):
            node.inputs[idx].default_value = v
        elif v is not None:
            self.L.new(v, node.inputs[idx])

    def math(self, op, a, b=None, clamp=False):
        m = self.N.new("ShaderNodeMath")
        m.operation = op
        m.use_clamp = clamp
        self._set(m, 0, a)
        if b is not None:
            self._set(m, 1, b)
        return m.outputs["Value"]

    def rng(self, src, a, b, lo=0.0, hi=1.0):
        r = self.N.new("ShaderNodeMapRange")
        r.interpolation_type, r.clamp = "SMOOTHSTEP", True
        r.inputs["From Min"].default_value, r.inputs["From Max"].default_value = a, b
        r.inputs["To Min"].default_value, r.inputs["To Max"].default_value = lo, hi
        self._set(r, 0, src)
        return r.outputs["Result"]

    def mix(self, fac, a, b):
        m = self.N.new("ShaderNodeMix")
        m.data_type = "RGBA"
        self._set(m, 0, fac)
        self._set(m, 6, a)
        self._set(m, 7, b)
        return m.outputs[2]

    def noise(self, vec, scale, detail=4.0, rough=0.5):
        n = self.N.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        n.inputs["Roughness"].default_value = rough
        self.L.new(vec, n.inputs["Vector"])
        return n.outputs["Fac"]


def build_overcast_sky(nt):
    """Ciel couvert: voile blanc peu opaque. Éclairage = répartition CIE d'un ciel couvert (zénith 3x l'horizon),
    modulée par de larges variations d'épaisseur. Pour la caméra: voile clair presque uniforme."""
    X = _Nodes(nt)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    z = X.math("MAXIMUM", sep.outputs["Z"], 0.0)
    # variations d'épaisseur du voile: bruit sur le plan projeté, très doux
    zz = X.math("ADD", z, 0.25)
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(X.math("DIVIDE", sep.outputs["X"], zz), comb.inputs["X"])
    nt.links.new(X.math("DIVIDE", sep.outputs["Y"], zz), comb.inputs["Y"])
    veil = X.noise(comb.outputs["Vector"], 1.1, 5.0, 0.55)
    thick = X.rng(veil, 0.3, 0.7)                                   # 0 = voile fin, 1 = épais
    cie = X.math("DIVIDE", X.math("ADD", 1.0, X.math("MULTIPLY", z, 2.0)), 3.0)
    light = X.math("MULTIPLY", X.math("MULTIPLY", cie, X.math("ADD", 1.15, X.math("MULTIPLY", thick, -0.35))), 2.2 * CFG["sky_gain"])
    # sol sous l'horizon: gris-vert sombre (rebond du terrain)
    under = X.rng(sep.outputs["Z"], -0.02, 0.02)
    light_rgb = nt.nodes.new("ShaderNodeCombineColor")
    for i, ch in enumerate(("Red", "Green", "Blue")):
        k = (1.0, 1.0, 1.03)[i]
        nt.links.new(X.math("MULTIPLY", X.math("MAXIMUM", X.math("MULTIPLY", light, under), X.math("MULTIPLY", 0.18, X.math("SUBTRACT", 1.0, under))), k), light_rgb.inputs[ch])
    # vue directe: blanc lumineux, un peu plus gris vers l'horizon et là où le voile est épais
    vis = X.math("MULTIPLY", X.math("ADD", 0.72, X.math("MULTIPLY", z, 0.20)), X.math("ADD", 1.0, X.math("MULTIPLY", thick, -0.10)))
    vis_rgb = nt.nodes.new("ShaderNodeCombineColor")
    for ch, k in (("Red", 0.97), ("Green", 0.985), ("Blue", 1.0)):
        nt.links.new(X.math("MULTIPLY", vis, k * 1.10), vis_rgb.inputs[ch])
    lp = nt.nodes.new("ShaderNodeLightPath")
    return X.mix(lp.outputs["Is Camera Ray"], light_rgb.outputs["Color"], vis_rgb.outputs["Color"])


FOG_COLOR = (0.84, 0.865, 0.90, 1.0)   # luminance du voile à l'horizon (même échelle que le ciel visible)


def apply_height_fog(mat):
    """Brume d'altitude calculée dans le matériau, à coût quasi nul: transmittance exacte (à 6 % près) d'un air dont la
    densité décroit avec l'altitude, sigma(z) = sigma0 exp(-(z-1500)/2500), sigma0 = 1,4e-4 /m x fog (crêtes à 5 km à demi-contraste).
    Le trajet caméra -> point est lu dans le shader (distance et direction d'arrivée). Sans effet si fog_mode = volume."""
    if CFG["fog_mode"] != "shader" or (CFG["fog"] <= 0 and CFG["mist"] <= 0):
        return
    nt = mat.node_tree
    out = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output)
    src = out.inputs["Surface"].links[0].from_socket
    X = _Nodes(nt)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    cam = nt.nodes.new("ShaderNodeCameraData")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
    sinc = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Incoming"], sinc.inputs["Vector"])
    d = cam.outputs["View Distance"]
    z1 = sep.outputs["Z"]
    z0 = X.math("ADD", z1, X.math("MULTIPLY", sinc.outputs["Z"], d))
    zm = X.math("MULTIPLY", X.math("ADD", z0, z1), 0.5)
    dz = X.math("SUBTRACT", z1, z0)
    corr = X.math("ADD", 1.0, X.math("DIVIDE", X.math("MULTIPLY", dz, dz), 1.5e8))     # 1 + (dz/2H)^2 / 6, H = 2500
    sig = X.math("MULTIPLY", X.math("EXPONENT", X.math("MULTIPLY", X.math("SUBTRACT", zm, 1500.0), -1.0 / 2500.0)), 1.4e-4 * CFG["fog"])
    if CFG["mist"] > 0:   # bancs de brume: bande d'altitude 1500..2300 m
        band = X.math("MULTIPLY", X.rng(zm, 1300.0, 1700.0), X.rng(zm, 2500.0, 2000.0))
        sig = X.math("ADD", sig, X.math("MULTIPLY", band, 6e-4 * CFG["mist"]))
    tau = X.math("MULTIPLY", X.math("MULTIPLY", sig, d), corr)
    fog = X.math("SUBTRACT", 1.0, X.math("EXPONENT", X.math("MULTIPLY", tau, -1.0)), clamp=True)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = FOG_COLOR
    em.inputs["Strength"].default_value = 1.0
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(fog, mx.inputs[0])
    nt.links.new(src, mx.inputs[1])
    nt.links.new(em.outputs["Emission"], mx.inputs[2])
    nt.links.new(mx.outputs["Shader"], out.inputs["Surface"])


def build_fog(nt):
    """Brume physique (volume du monde): densité décroissante avec l'altitude, éventuels bancs de brume dans la vallée.
    Remplace l'ancien mélange dans le matériau: elle agit aussi sur les particules et la poussière."""
    if CFG["fog_mode"] != "volume" or (CFG["fog"] <= 0 and CFG["mist"] <= 0):
        return
    X = _Nodes(nt)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
    # sigma(z) = sigma0 * exp(-(z - 1500) / 2500) ; sigma0 = 1.4e-4 /m (visibilité ~ 5 km à demi-contraste)
    expo = X.math("EXPONENT", X.math("MULTIPLY", X.math("SUBTRACT", sep.outputs["Z"], 1500.0), -1.0 / 2500.0))
    dens = X.math("MULTIPLY", expo, 1.4e-4 * CFG["fog"])
    if CFG["mist"] > 0:  # bancs de brume: bande d'altitude 1500..2300 m modulée par du bruit large
        band = X.math("MULTIPLY", X.rng(sep.outputs["Z"], 1300.0, 1700.0), X.rng(sep.outputs["Z"], 2500.0, 2000.0))
        pn = X.noise(geo.outputs["Position"], 0.0007, 5.0, 0.6)
        patch = X.rng(pn, 0.42, 0.62)
        dens = X.math("ADD", dens, X.math("MULTIPLY", X.math("MULTIPLY", band, patch), 1.2e-3 * CFG["mist"]))
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.93, 0.95, 0.98, 1.0)
    vol.inputs["Anisotropy"].default_value = 0.25
    nt.links.new(dens, vol.inputs["Density"])
    nt.links.new(vol.outputs["Volume"], nt.nodes["World Output"].inputs["Volume"])


def build_world(scene, sun_dir=None):
    w = bpy.data.worlds.new("Sky")
    scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    if CFG["sky"] == "couvert":
        nt.links.new(build_overcast_sky(nt), nt.nodes["Background"].inputs["Color"])
        if CFG["clouds"] > 0:
            log("--clouds ignoré en ciel couvert")
        build_fog(nt)
        return
    try:
        sky = nt.nodes.new("ShaderNodeTexSky")
        for kind in ("NISHITA", "MULTIPLE_SCATTERING", "SINGLE_SCATTERING"):  # Blender 4.x puis 5.x
            try:
                sky.sky_type = kind
                break
            except TypeError:
                continue
        sd = sun_dir if sun_dir is not None else sun_vector(None, None)
        # Blender: sun_rotation = azimut mesuré depuis +Y vers +X (vérifié), sun_elevation au-dessus de l'horizon
        sky.sun_elevation = math.asin(max(-1.0, min(1.0, sd.z)))
        sky.sun_rotation = math.atan2(sd.x, sd.y)
        if hasattr(sky, "sun_intensity"):
            sky.sun_intensity = 0.5
        if hasattr(sky, "altitude"):
            sky.altitude = 1500.0
        sky_col = sky.outputs["Color"]
        if CFG["clouds"] > 0:
            sky_col = add_clouds(nt, sky_col, sd)
        nt.links.new(sky_col, nt.nodes["Background"].inputs["Color"])
    except Exception as e:  # ciel simple en repli
        log("Nishita indisponible:", e)
        nt.nodes["Background"].inputs["Color"].default_value = (0.45, 0.6, 0.85, 1)
    build_fog(nt)


def check_final_prereqs(env):
    """Garde-fous du rendu final: refuse de lancer tant que la caméra n'est pas validée et que les données
    ne sont pas à la résolution voulue (relief 0,5 m, image 10 cm). Voir PREREQUIS_VERSION_FINALE.md."""
    if CFG["preset"] != "final" or not (CFG["render_anim"] or CFG["render_frame"] is not None):
        return
    bloquants, resolution = [], []
    if not CFG["camera_confirmed"]:
        bloquants.append("position de la caméra non confirmée par le groupe (option --camera-confirmed)")
    if not CFG["cam"]:
        bloquants.append("aucune position de caméra explicite (--cam X Y Z): la position automatique n'est qu'un test")
    if env:
        m = env["meta"]
        if (not m.get("dem05") or CFG["no_hires"]) and m["dem2"]["step"] > 0.5 + 1e-6:
            resolution.append(f"relief swissALTI3D à {m['dem2']['step']:g} m au lieu de 0,5 m autour de la caméra (python blatten.py prep-env --hires)")
        o = m.get("ortho")
        fin = min([p["step"] for p in m.get("ortho_patches", [])] + [o["step"] if o else 9.0])
        if CFG["no_hires"] or fin > 0.1 + 1e-6:
            resolution.append(f"image SWISSIMAGE à {fin:g} m au lieu de 10 cm autour de la caméra")
    else:
        resolution.append("environnement swisstopo absent (cache/env)")
    if resolution and CFG["accept_lowres"]:
        log("ATTENTION: rendu final avec données de moindre résolution (--accept-lowres): " + "; ".join(resolution))
        resolution = []
    pb = bloquants + resolution
    if pb:
        log("RENDU FINAL REFUSE. A faire avant:")
        for x in pb:
            log("  - " + x)
        log("Rappel: télécharger les dalles swissALTI3D 0,5 m et SWISSIMAGE 10 cm à la bonne date autour de la caméra "
            "(carré d'environ 2 km), puis refaire la préparation de l'environnement.")
        raise SystemExit(2)


def load_camera_file(here):
    """camera.json (racine du dépôt): position (et orientation) de la caméra choisie, lues par défaut.
    {"cam": [x, y, z], "rot_deg": [rx, ry, rz], "confirmed": true/false}. --cam sur la ligne de commande l'emporte."""
    path = os.path.join(here, "camera.json")
    if not os.path.exists(path) or CFG["cam"]:
        return
    try:
        c = json.load(open(path))
        CFG["cam"] = tuple(c["cam"])
        CFG["cam_rot"] = tuple(c["rot_deg"]) if c.get("rot_deg") else None
        if c.get("confirmed"):
            CFG["camera_confirmed"] = True
        log(f"caméra lue dans camera.json: {CFG['cam']} (confirmée: {bool(c.get('confirmed'))})")
    except Exception as e:
        log("camera.json illisible:", e)


def build_camera(scene, seq):
    st = seq.meta.get("stats", {})

    def blend_pt(p):
        return Vector((p[0], -p[2], p[1]))

    target = Vector(CFG["target"]) if CFG["target"] else (
        blend_pt(st["moving_centroid"]) if st.get("moving_centroid") else Vector((0, 0, 1800)))
    if CFG["cam"]:
        loc = Vector(CFG["cam"])
    else:  # AUTO: de côté par rapport au sens d'écoulement, 1,5 km, +250 m. A SURCHARGER.
        v = st.get("moving_mean_velocity") or [1, 0, 0]
        d = Vector((v[0], -v[2], 0.0))
        d = d.normalized() if d.length > 1e-6 else Vector((1, 0, 0))
        rest = blend_pt(st["rest_centroid"]) if st.get("rest_centroid") else target
        loc = rest + Vector((-d.y, d.x, 0.0)) * 1500.0 + Vector((0, 0, 250.0))
        log("caméra AUTO (à remplacer par --cam X Y Z):", tuple(round(c) for c in loc))
    cd = bpy.data.cameras.new("Cam360")
    cam = bpy.data.objects.new("Cam360", cd)
    scene.collection.objects.link(cam)
    cam.location = loc
    if CFG["cam_rot"]:
        cam.rotation_euler = tuple(math.radians(a) for a in CFG["cam_rot"])
    else:
        cam.rotation_euler = (target - loc).to_track_quat("-Z", "Y").to_euler()
    cd.clip_start, cd.clip_end = 1.0, 50000.0
    cd.type = "PANO"
    if hasattr(cd, "panorama_type"):
        cd.panorama_type = "EQUIRECTANGULAR"
    else:  # Blender < 4.0
        cd.cycles.panorama_type = "EQUIRECTANGULAR"
    r = scene.render
    if CFG["stereo"]:
        r.use_multiview = True
        r.views_format = "STEREO_3D"
        cd.stereo.convergence_mode = "PARALLEL"
        cd.stereo.interocular_distance = CFG["ipd"]
        cd.stereo.use_spherical_stereo = True
        r.image_settings.views_format = "STEREO_3D"
        r.image_settings.stereo_3d_format.display_mode = "TOPBOTTOM"
        r.image_settings.stereo_3d_format.use_squeezed_frame = False
    scene.camera = cam
    return cam


def view_points(seq):
    """8 points de vue autour du centre de l'écoulement. 1 = en amont (on regarde dans le sens
    de l'écoulement), 5 = en aval (l'écoulement vient vers la caméra), 3 et 7 = de côté."""
    st = seq.meta.get("stats", {})
    bp = lambda q: Vector((q[0], -q[2], q[1]))
    mc = bp(st["moving_centroid"]) if st.get("moving_centroid") else Vector((0, 0, 1800))
    rest = bp(st["rest_centroid"]) if st.get("rest_centroid") else mc
    target = Vector(CFG["target"]) if CFG["target"] else (mc + rest) / 2
    v = st.get("moving_mean_velocity") or [1, 0, 0]
    d = Vector((v[0], -v[2], 0.0))
    d = d.normalized() if d.length > 1e-6 else Vector((1, 0, 0))
    pts = {}
    for k in range(8):
        a = math.radians(45 * k)
        dd = Vector((d.x * math.cos(a) - d.y * math.sin(a), d.x * math.sin(a) + d.y * math.cos(a), 0.0))
        loc = target - dd * CFG["dist"] + Vector((0, 0, CFG["height"]))
        pts[str(k + 1)] = dict(cam=[round(c, 1) for c in loc], target=[round(c, 1) for c in target])
    return pts


def render_previews(scene, seq, out_dir):
    pts = view_points(seq)
    r = scene.render
    r.use_multiview = False
    r.resolution_x, r.resolution_y = 960, 540
    r.image_settings.file_format, r.image_settings.color_depth = "PNG", "8"
    scene.cycles.samples = 8
    cd = bpy.data.cameras.new("Apercu")
    cd.lens, cd.clip_start, cd.clip_end = 28.0, 1.0, 50000.0
    cam = bpy.data.objects.new("Apercu", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    for k, p in pts.items():
        if CFG["vue"] and str(CFG["vue"]) != k:   # --vue N: un seul aperçu
            continue
        loc = Vector(p["cam"])
        cam.location = loc
        cam.rotation_euler = (Vector(p["target"]) - loc).to_track_quat("-Z", "Y").to_euler()
        r.filepath = os.path.join(out_dir, f"vue_{k}")
        bpy.ops.render.render(write_still=True)
        log(f"aperçu {k}/8 : caméra {p['cam']}")


def prepare_viewports(center):
    """Vue 3D utilisable d'emblée : distance de clipping adaptée au km, cadrage sur l'écoulement,
    couleur par objet. Sans cela la scène (plusieurs km) est hors champ et la fenêtre semble vide."""
    q = Euler((math.radians(62), 0.0, math.radians(35))).to_quaternion()
    for scr in bpy.data.screens:
        for area in scr.areas:
            if area.type != "VIEW_3D":
                continue
            for sp in area.spaces:
                if sp.type != "VIEW_3D":
                    continue
                try:
                    sp.clip_start, sp.clip_end = 1.0, 100000.0
                    if CFG["_env_ok"]:   # environnement réel: aperçu avec matériaux (image aérienne, ciel, brume)
                        sp.shading.type = "MATERIAL"
                        sp.shading.use_scene_world = True
                    else:
                        sp.shading.type = "SOLID"
                        sp.shading.color_type = "OBJECT"
                    r3d = sp.region_3d
                    if r3d is not None:
                        r3d.view_perspective = "PERSP"
                        r3d.view_location = center
                        r3d.view_distance = 5000.0
                        r3d.view_rotation = q
                except Exception as e:
                    log("vue 3D:", e)


def setup_render(scene, out_dir):
    p = PRESETS[CFG["preset"]]
    r = scene.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y = p["res"]
    r.resolution_percentage = 100
    r.use_persistent_data = bool(CFG["persistent"])
    r.fps = CFG["fps"]
    r.image_settings.file_format = "PNG"
    r.image_settings.color_depth = "16" if CFG["preset"] == "final" else "8"
    r.filepath = os.path.join(out_dir, "frame_")
    try:  # AgX/Filmic délavent fortement ce ciel; Standard + exposition réduite
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.exposure = CFG["exposure"] if CFG["exposure"] is not None else (0.0 if CFG["sky"] == "couvert" else -2.5)
    except Exception:
        pass
    scene.cycles.samples = p["samples"]
    scene.cycles.use_denoising = True
    scene.cycles.device = "CPU"
    try:  # GPU si disponible
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                gpus = [d for d in prefs.devices if d.type != "CPU"]
                if gpus:
                    for d in prefs.devices:
                        d.use = d.type != "CPU"
                    scene.cycles.device = "GPU"
                    log("GPU:", kind, [d.name for d in gpus])
                    break
            except Exception:
                continue
    except Exception as e:
        log("Cycles prefs:", e)


# ----------------------------------------------------------------------------------
# Programme principal
# ----------------------------------------------------------------------------------
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="blatten_blender")
    ap.add_argument("--data", dest="data_dir"); ap.add_argument("--terrain"); ap.add_argument("--release")
    ap.add_argument("--terrain-voxel", type=float); ap.add_argument("--terrain-only", type=float); ap.add_argument("--release-voxel", type=float)
    ap.add_argument("--dt-per-step", type=float); ap.add_argument("--time-scale", type=float)
    ap.add_argument("--fps", type=int); ap.add_argument("--radius", type=float)
    ap.add_argument("--color", choices=["speed", "natural"]); ap.add_argument("--look", choices=["realiste", "didactique"]); ap.add_argument("--haze", type=float)
    ap.add_argument("--cam", type=float, nargs=3); ap.add_argument("--target", type=float, nargs=3)
    ap.add_argument("--mono", action="store_true"); ap.add_argument("--ipd", type=float)
    ap.add_argument("--preset", choices=list(PRESETS))
    ap.add_argument("--frames", type=int, nargs=2)
    ap.add_argument("--render-frame", type=int); ap.add_argument("--render-anim", action="store_true")
    ap.add_argument("--out"); ap.add_argument("--save", action="store_true")
    ap.add_argument("--views", action="store_true"); ap.add_argument("--vue", type=int)
    ap.add_argument("--dist", type=float); ap.add_argument("--exposure", type=float); ap.add_argument("--height", type=float)
    ap.add_argument("--no-env", action="store_true"); ap.add_argument("--snow", type=float); ap.add_argument("--snow-line", type=float)
    ap.add_argument("--ortho-gain", type=float); ap.add_argument("--clouds", type=float); ap.add_argument("--time")
    ap.add_argument("--sky", choices=["couvert", "clair"]); ap.add_argument("--sky-gain", type=float)
    ap.add_argument("--fog", type=float); ap.add_argument("--fog-mode", choices=["shader", "volume"]); ap.add_argument("--mist", type=float); ap.add_argument("--detail", type=float)
    ap.add_argument("--camera-confirmed", action="store_true"); ap.add_argument("--accept-lowres", action="store_true")
    ap.add_argument("--bench", action="store_true"); ap.add_argument("--bench-scale", type=float)
    ap.add_argument("--bench-no-warm", action="store_true"); ap.add_argument("--persistent", action="store_true")
    ap.add_argument("--matiere")
    ap.add_argument("--cull", action="store_true"); ap.add_argument("--no-hires", action="store_true")
    ap.add_argument("--env-dir"); ap.add_argument("--clip", action="store_true")
    ap.add_argument("--clip-seconds", type=float); ap.add_argument("--clip-every", type=int)
    ap.add_argument("--clip-quality", type=int); ap.add_argument("--clip-fullscale", type=float); ap.add_argument("--clip-scale", type=float)
    ap.add_argument("--clip-samples", type=int, nargs="+")
    ap.add_argument("--clip-no-keys", action="store_true"); ap.add_argument("--clip-no-video", action="store_true")
    a = ap.parse_args(argv)
    for k, v in vars(a).items():
        if k == "mono":
            if v:
                CFG["stereo"] = False
        elif k in ("no_env", "camera_confirmed", "accept_lowres", "bench", "bench_no_warm", "persistent", "clip", "clip_no_keys", "clip_no_video", "cull", "no_hires"):
            if v:
                CFG[k] = True
        elif v is not None and v is not False:
            CFG[k.replace("-", "_")] = v
    if a.render_anim:
        CFG["render_anim"] = True
    for k in ("terrain", "release", "data_dir", "out", "env_dir"):  # chemins absolus (le dossier courant varie)
        if CFG.get(k):
            CFG[k] = os.path.abspath(CFG[k])


def main():
    parse_args()
    # Racine du dépôt: variable BLATTEN_ROOT (posée par blatten.py), sinon deux dossiers au-dessus de src/scene.
    here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else bpy.path.abspath("//")
    root = os.environ.get("BLATTEN_ROOT") or os.path.dirname(os.path.dirname(here))
    data_dir = CFG["data_dir"] or os.path.join(root, "data", "cache")
    out_dir = CFG["out"] or os.path.join(root, "render")
    os.makedirs(out_dir, exist_ok=True)
    if CFG["bench"] or CFG["clip"]:
        sys.path.insert(0, os.path.join(os.path.dirname(here), "bench"))
        import bench
    if CFG["bench"]:
        bench.prepare(CFG)
    elif CFG["clip"]:
        import clip
        clip.prepare(CFG)

    load_camera_file(root)
    scene = reset_scene()
    seq = Sequence(data_dir)
    meta = seq.meta
    ox, oy, oz = meta["origin"]
    log(f"{len(seq.files)} fichier(s) de particules, origine {meta['origin']}")
    if len(seq.files) == 1:
        log("HYPOTHESE: un seul pas de temps, le mouvement est extrapolé par les vitesses (max "
            f"{CFG['max_extrap']} s). Ce n'est qu'un test de chaîne, pas la dynamique réelle.")

    scene.render.fps = CFG["fps"]
    f0, f1 = CFG["frames"] or (1, 250)
    scene.frame_start, scene.frame_end = f0, f1

    coll = new_collection(scene, "Blatten")
    CFG["color"] = CFG["color"] or ("natural" if CFG["look"] == "realiste" else "speed")
    if CFG["matiere"] and CFG["matiere"] != "defaut":
        MATIERE["mod"] = load_matiere(root)
        STATE["seq"] = seq
        helpers = dict(to_blender=to_blender, frame_to_time=frame_to_time, apply_height_fog=apply_height_fog,
                       new_collection=new_collection, build_default=lambda: build_debris(scene, seq, coll))
        deb = MATIERE["mod"].build(scene, seq, coll, CFG, log, helpers)
    else:
        deb = build_debris(scene, seq, coll)
    if deb is not None:
        deb.color = (0.95, 0.55, 0.15, 1)

    # VDB: repère simulation Y haut, recentrés comme les particules (origine en Houdini)
    rot = (math.pi / 2, 0.0, 0.0)
    offset = (-ox, oz, -oy)
    if CFG["terrain_only"]:  # conversion seule, dans un processus à part (peut manquer de mémoire)
        if os.path.exists(os.path.join(data_dir, f"Terrain_mesh_{CFG['terrain_only']:g}m.blend")):
            log("terrain déjà converti à ce voxel")
        else:
            vdb_to_mesh(CFG["terrain"], "Terrain", CFG["terrain_only"], offset, rot, coll,
                        (0.26, 0.23, 0.21, 1), data_dir)
        return
    env = None if CFG["no_env"] else load_env(CFG["env_dir"] or data_dir)
    if env:
        em = env["meta"]
        log(f"environnement swisstopo: scène à E {em['scene_E0']:.1f} N {em['scene_N0']:.1f} (LV95), "
            f"écart de calage médian {em.get('mad', em.get('rms', 0)):.2f} m")
    if CFG["terrain"] and not env:
        t = vdb_to_mesh(CFG["terrain"], "Terrain", CFG["terrain_voxel"], offset, rot, coll,
                        (0.16, 0.14, 0.12, 1), data_dir, convert=CFG["terrain_voxel"] is not None)
        if t:
            t.color = (0.55, 0.50, 0.45, 1)
            if CFG["look"] == "realiste":
                t.data.materials.clear()
                t.data.materials.append(build_terrain_material())
    if CFG["release"]:
        o = vdb_to_mesh(CFG["release"], "Release", CFG["release_voxel"], offset, rot, coll,
                        (0.8, 0.1, 0.1, 1), data_dir)
        o.color = (0.9, 0.1, 0.1, 1)
        o.hide_render = True
        o.hide_viewport = not CFG["show_release"]

    st = seq.meta.get("stats", {})
    if st.get("moving_centroid") and st.get("rest_centroid"):
        mc, rc = st["moving_centroid"], st["rest_centroid"]
        center = Vector(((mc[0] + rc[0]) / 2, -(mc[2] + rc[2]) / 2, (mc[1] + rc[1]) / 2))
    else:
        center = Vector((0, 0, 1800))
    build_world(scene, sun_vector(env, (center.x, center.y)))
    if CFG["vue"]:
        pt = view_points(seq)[str(CFG["vue"])]
        CFG["cam"] = CFG["cam"] or pt["cam"]
        CFG["target"] = CFG["target"] or pt["target"]
        log(f"vue {CFG['vue']}: caméra {CFG['cam']}")
    build_camera(scene, seq)
    check_final_prereqs(env)
    CFG["_env_ok"] = bool(env)
    if env:
        cp = center if (CFG["views"] or not bpy.app.background) else scene.camera.location   # interface: relief fin autour de l'écoulement
        build_env_terrain(env, (cp.x, cp.y), coll, build_terrain_material(env))
    setup_render(scene, out_dir)
    prepare_viewports(center)
    if not bpy.app.background:  # l'interface n'est pas encore prête au démarrage: on recadre un peu après
        bpy.app.timers.register(lambda: prepare_viewports(center), first_interval=1.5)
    if CFG["views"]:
        render_previews(scene, seq, out_dir)
        return

    if on_frame not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(on_frame)

    if CFG["bench"]:
        bench.run(scene, root, CFG, log, PRESETS,
                  extra=dict(particules=int(seq.count), fichiers_particules=len(seq.files), environnement_swisstopo=bool(env)),
                  data_dir=data_dir)
        return

    if CFG["clip"]:
        clip.run(scene, root, CFG, log, PRESETS,
                 extra=dict(particules=int(seq.count), stride=seq.meta.get("stride"),
                            fichiers_particules=[f["step"] for f in seq.files], environnement_swisstopo=bool(env)),
                 data_dir=data_dir, bench=bench)
        return

    if CFG["save"]:
        path = os.path.join(root, "blatten_scene.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        log("scène enregistrée:", path)

    if CFG["render_frame"] is not None:
        scene.frame_set(CFG["render_frame"])
        scene.render.filepath = os.path.join(out_dir, f"frame_{CFG['render_frame']:04d}")
        bpy.ops.render.render(write_still=True)
        log("image:", scene.render.filepath)
    elif CFG["render_anim"]:
        bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
