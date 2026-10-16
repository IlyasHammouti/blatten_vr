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
    time_scale=1.0,         # secondes vidéo par seconde simulée (4.0 = ralenti x4, 0.5 = accéléré x2)
    t0=0.0,                 # seconde de simulation montrée au début de l'événement
    intro=0.0,              # secondes de paysage avant l'événement (matière immobile à t0)
    frame_step=1,           # 2 = une image sur deux (brouillon)
    chrono=None,            # brouillon: [t_début, t_fin, images, ...] par tranches (remplace t0/time_scale/intro)
    render_time=None,       # image test à cet instant de simulation (s), quelle que soit l'image
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
    origine=None,           # image de référence du temps (défaut: première image). Sert aux rendus par paquets
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
    env_only=False,         # ENVIRONNEMENT SEUL: ni particules ni zone de rupture (décor d'avant l'événement)
    lite=False,             # version légère: environnement seul + relief visible seulement, enregistrée avec ses images dans render/blatten_env_lite.blend
    cull=False,             # ne construit que le relief VISIBLE depuis la caméra (masques de "python blatten.py visible")
    no_buildings=False,     # ne place pas les bâtiments 3D (python blatten.py prep-batiments les prépare)
    no_water=False,         # pas de rivière animée (python blatten.py prep-eau la prépare)
    no_trees=False,         # ne place pas les arbres (python blatten.py prep-vegetation les prépare)
    wind=True,              # léger balancement des arbres proches (--no-wind pour le couper)
    wind_dist=1200.0,       # distance (m) jusqu'à laquelle les arbres bougent (au-delà, imperceptible)
    tree_ortho=0.5,         # part de la couleur de l'image aérienne dans la couleur des arbres (0 = couleurs d'essence seules)
    tree_dist=4700.0,       # distance maximale des arbres modélisés (m); au-delà l'image aérienne suffit
    no_hires=False,         # ignore le relief 0,5 m et les images locales (comparaison / test mémoire)
    env_dir=None,           # dossier contenant env/ (défaut: celui des particules). Sert au test-clip
    clip=False,             # test grandeur nature: quelques secondes de l'événement (src/bench/clip.py)
    clip_seconds=3.0, clip_every=1, clip_quality=48, clip_scale=0.5, clip_samples=(24, 48, 96, 192),
    clip_no_keys=False, clip_no_video=False, clip_fullscale=1.0,
    persistent=False,       # rendu: garde en mémoire ce qui ne change pas d'une image à l'autre (plus rapide, plus de mémoire)
)

PRESETS = {
    "test": dict(res=(1024, 512), samples=16),
    "brouillon": dict(res=(1920, 960), samples=16),   # film complet à mi-résolution, pour juger l'ensemble en une nuit
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
        # Hermite cubique (positions et vitesses aux deux fichiers): exact pour une accélération constante.
        # Mesuré sur la série de Johan (test_interpolation.py, écart de 2 s): erreur médiane 0,02 m contre 0,21 m pour l'ancien fondu.
        p0, v0 = np.asarray(a0[:, :3], np.float32), np.asarray(a0[:, 3:6], np.float32)
        p1, v1 = np.asarray(a1[:, :3], np.float32), np.asarray(a1[:, 3:6], np.float32)
        f2, f3 = f * f, f * f * f
        P = (2 * f3 - 3 * f2 + 1) * p0 + ((f3 - 2 * f2 + f) * dt) * v0 + (-2 * f3 + 3 * f2) * p1 + ((f3 - f2) * dt) * v1
        V = ((6 * f2 - 6 * f) / dt) * (p0 - p1) + (3 * f2 - 4 * f + 1) * v0 + (3 * f2 - 2 * f) * v1
        return P, V


def to_blender(a):
    """Y vertical (Houdini) -> Z vertical (Blender) : (x, y, z) -> (x, -z, y)."""
    out = np.empty(a.shape, np.float32)
    out[:, 0] = a[:, 0]
    out[:, 1] = -a[:, 2]
    out[:, 2] = a[:, 1]
    return out


STATE = dict(seq=None, mesh=None, last_t=None)
ENSEV = []   # (instant d'arrivée de la matière en s de simulation, objet): bâtiments et arbres balayés, masqués ensuite


def maj_ensevelis(t):
    """Masque (rendu et vue) les bâtiments et arbres que la matière a atteints à l'instant t."""
    for ta, ob in ENSEV:
        h = bool(t >= ta)
        if ob.hide_render != h:
            ob.hide_render = h
            ob.hide_viewport = h


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
    if CFG["render_time"] is not None:
        return float(CFG["render_time"])
    if CFG["chrono"]:
        c = list(CFG["chrono"])
        k = frame - (CFG["origine"] if CFG["origine"] is not None else scene.frame_start)
        for a, b, n in zip(c[0::3], c[1::3], c[2::3]):
            n = int(n)
            if k < n:
                return a + (b - a) * k / max(n, 1)
            k -= n
        return c[-2]
    fps = scene.render.fps / scene.render.fps_base
    return CFG["t0"] + max(0.0, (frame - (CFG["origine"] if CFG["origine"] is not None else scene.frame_start)) / fps - CFG["intro"]) / CFG["time_scale"]


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
    maj_ensevelis(t)
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
        # une maille est gardée si UN point de sa surface (grille 3 x 3) est visible (mailles larges: le centre seul ne suffit pas)
        vv = np.zeros((n, n), bool)
        for oy in (-0.5, 0.0, 0.5):
            for ox in (-0.5, 0.0, 0.5):
                vv |= _vis_at(env["vis"][step], Ec + (cu + ox * step * 0.999)[None, :], Nc + (cu + oy * step * 0.999)[:, None])
        keep = keep & vv
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
    env["ring_info"] = (Ec, Nc, rings)
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
    tot = sum(len(o.data.polygons) for o in objs)
    log(f"TOTAL relief: {tot:,} faces" + (" (relief invisible coupé)" if CFG["cull"] else " (relief complet)"))
    return objs


def _arrivee(env, E, N, pas=3.0):
    """Instant (s de simulation) où la matière atteint chaque point (E, N), arrondi par `pas` (regroupement); inf si jamais.
    Lit alea_empreinte.npz (python blatten.py empreinte-alea). Rend toujours un tableau inf si absent."""
    out = np.full(len(E), np.inf)
    f = os.path.join(env["dir"], "alea_empreinte.npz")
    if not os.path.exists(f) or CFG.get("no_ensevelis"):
        return out
    z = np.load(f)
    tarr, x0, y1, s = z["tarr"], float(z["x0"]), float(z["y1"]), float(z["step"])
    i = np.floor((E - x0) / s).astype(np.int64)
    j = np.floor((y1 - N) / s).astype(np.int64)
    ok = (i >= 0) & (i < tarr.shape[1]) & (j >= 0) & (j < tarr.shape[0])
    v = np.where(ok, tarr[np.clip(j, 0, tarr.shape[0] - 1), np.clip(i, 0, tarr.shape[1] - 1)], np.nan)
    good = np.isfinite(v)
    out[good] = np.floor(np.maximum(v[good] - 0.5, 0.0) / pas) * pas
    return out


def _objet_triangles(nom, co, tri, mats, mat_index=None, attrs=None, lisse=False, scalaires=None):
    me = bpy.data.meshes.new(nom)
    nv, nf = len(co), len(tri)
    me.vertices.add(nv)
    me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    me.loops.add(nf * 3)
    me.loops.foreach_set("vertex_index", tri.astype(np.int32).ravel())
    me.polygons.add(nf)
    me.polygons.foreach_set("loop_start", np.arange(0, nf * 3, 3, dtype=np.int32))
    try:
        me.polygons.foreach_set("loop_total", np.full(nf, 3, np.int32))
    except Exception:
        pass
    try:
        me.polygons.foreach_set("use_smooth", np.full(nf, bool(lisse)))      # facettes plates par défaut (les fenêtres lisent la normale de la face); lisse pour la végétation
    except Exception:
        pass
    me.update(calc_edges=True)
    for mt in mats:
        me.materials.append(mt)
    if mat_index is not None:
        me.polygons.foreach_set("material_index", mat_index)
    for nm, rgb in (attrs or {}).items():     # couleurs par sommet (linéaires)
        ca = me.color_attributes.new(nm, "FLOAT_COLOR", "POINT")
        ca.data.foreach_set("color", np.concatenate([rgb, np.ones((len(rgb), 1), np.float32)], 1).astype(np.float32).ravel())
    for nm, v in (scalaires or {}).items():
        fa = me.attributes.new(nm, "FLOAT", "POINT")
        fa.data.foreach_set("value", np.asarray(v, np.float32).ravel())
    return bpy.data.objects.new(nom, me)


def _vent_modifier(ob):
    """Léger balancement des arbres: décalage horizontal par un bruit 4D (espace + temps), proportionnel à l'attribut "vent"
    (nul au pied, maximal en cime). Calculé à chaque image par les nœuds de géométrie, donc dans la vidéo."""
    ng = bpy.data.node_groups.get("Vent")
    if ng is None:
        ng = bpy.data.node_groups.new("Vent", "GeometryNodeTree")
        ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        N, L = ng.nodes, ng.links
        gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
        sp = N.new("GeometryNodeSetPosition")
        pos = N.new("GeometryNodeInputPosition")
        tm = N.new("GeometryNodeInputSceneTime")
        na = N.new("GeometryNodeInputNamedAttribute")
        na.data_type = "FLOAT"
        na.inputs["Name"].default_value = "vent"
        vs = N.new("ShaderNodeVectorMath")
        vs.operation = "SCALE"
        vs.inputs["Scale"].default_value = 0.035                 # longueur d'onde ~ 30 m: les voisins bougent ensemble
        L.new(pos.outputs["Position"], vs.inputs[0])
        wt = N.new("ShaderNodeMath")
        wt.operation = "MULTIPLY"
        wt.inputs[1].default_value = 0.45                        # vitesse de variation du vent
        L.new(tm.outputs["Seconds"], wt.inputs[0])
        nz = N.new("ShaderNodeTexNoise")
        nz.noise_dimensions = "4D"
        nz.inputs["Scale"].default_value = 1.0
        nz.inputs["Detail"].default_value = 1.0
        L.new(vs.outputs["Vector"], nz.inputs["Vector"])
        L.new(wt.outputs["Value"], nz.inputs["W"])
        c = N.new("ShaderNodeVectorMath")
        c.operation = "SUBTRACT"
        c.inputs[1].default_value = (0.5, 0.5, 0.5)
        L.new(nz.outputs["Color"], c.inputs[0])
        z = N.new("ShaderNodeVectorMath")
        z.operation = "MULTIPLY"
        z.inputs[1].default_value = (2.0, 2.0, 0.3)
        L.new(c.outputs["Vector"], z.inputs[0])
        k = N.new("ShaderNodeVectorMath")
        k.operation = "SCALE"
        L.new(z.outputs["Vector"], k.inputs[0])
        L.new(na.outputs["Attribute"], k.inputs["Scale"])
        L.new(gi.outputs[0], sp.inputs["Geometry"])
        L.new(k.outputs["Vector"], sp.inputs["Offset"])
        L.new(sp.outputs["Geometry"], go.inputs[0])
    md = ob.modifiers.new("Vent", "NODES")
    md.node_group = ng


def _echantillon_ortho(env, E, N):
    """Couleur (sRGB 0..1) de l'image aérienne aux points (E, N): images locales 10 cm, 50 cm, puis l'image 2 m. NaN si hors de toutes."""
    m = env["meta"]
    out = np.full((len(E), 3), np.nan, np.float32)
    srcs = sorted(m.get("ortho_patches", []), key=lambda o: o["step"]) + ([m["ortho"]] if m.get("ortho") else [])
    for o in srcs:
        f = os.path.join(env["dir"], o["file"])
        if not os.path.exists(f):
            continue
        j = np.floor((E - o["x0"]) / o["step"]).astype(np.int64)
        i = np.floor((o["y1"] - N) / o["step"]).astype(np.int64)
        Hh_, Ww_ = o["shape"]
        ok = np.isnan(out[:, 0]) & (j >= 0) & (j < Ww_) & (i >= 0) & (i < Hh_)
        if not ok.any():
            continue
        img = bpy.data.images.load(f)
        try:
            w, h = img.size
            arr = np.empty(w * h * 4, np.float32)
            img.pixels.foreach_get(arr)
            arr = arr.reshape(h, w, 4)
            out[ok] = arr[h - 1 - i[ok], j[ok], :3]
        finally:
            bpy.data.images.remove(img)
    return out


def _noeuds_outils(nt):
    """Petits constructeurs de noeuds (maths, choix par classe) pour les matériaux procéduraux."""
    N_, L = nt.nodes, nt.links

    def mth(op, a=None, b_=None, clamp=False):
        n = N_.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        for idx, v in ((0, a), (1, b_)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[idx].default_value = v
            else:
                L.new(v, n.inputs[idx])
        return n.outputs[0]

    def choix(cls, valeurs):
        """valeurs[i] quand cls == i (cls: sortie de noeud, valeurs: nombres)."""
        tot = None
        for i, v in enumerate(valeurs):
            near = mth("LESS_THAN", mth("ABSOLUTE", mth("SUBTRACT", cls, float(i))), 0.5)
            t = mth("MULTIPLY", near, float(v))
            tot = t if tot is None else mth("ADD", tot, t)
        return tot
    return N_, L, mth, choix


def _brique(N_, L, vec, largeur, hauteur, mortier, c1, c2, cm, decal=0.5, echelle=1.0):
    """Noeud Brick (motif de dalles, planches, rondins...) piloté par des sorties de noeuds ou des nombres. Rend la sortie Couleur."""
    br = N_.new("ShaderNodeTexBrick")
    br.offset = decal
    br.offset_frequency = 2
    br.squash = 1.0
    br.inputs["Color1"].default_value = c1
    br.inputs["Color2"].default_value = c2
    br.inputs["Mortar"].default_value = cm
    br.inputs["Scale"].default_value = echelle
    br.inputs["Mortar Smooth"].default_value = 0.1
    L.new(vec, br.inputs["Vector"])
    for nom, v in (("Brick Width", largeur), ("Row Height", hauteur), ("Mortar Size", mortier)):
        if isinstance(v, (int, float)):
            br.inputs[nom].default_value = v
        else:
            L.new(v, br.inputs[nom])
    return br.outputs["Color"]


def _materiau_mur():
    """Façade procédurale. Attributs par sommet: 'mur' = couleur de base du bâtiment, 'cls' (R) = type: 0 rondins de mélèze (chalet),
    1 planches verticales (grange), 2 crépi, 3 pierre; (B) = 1 si fenêtres. Fenêtres sombres en grille (étage ~2,9 m, travée ~3,2 m)."""
    mt = bpy.data.materials.new("Mur")
    mt.use_nodes = True
    nt = mt.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.85
    N_, L, mth, choix = _noeuds_outils(nt)
    geo = N_.new("ShaderNodeNewGeometry")
    sp_ = N_.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sp_.inputs[0])
    sn_ = N_.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Normal"], sn_.inputs[0])
    at_c = N_.new("ShaderNodeAttribute"); at_c.attribute_name, at_c.attribute_type = "cls", "GEOMETRY"
    cs = N_.new("ShaderNodeSeparateColor"); L.new(at_c.outputs["Color"], cs.inputs[0])
    wall = cs.outputs["Red"]
    # coordonnée le long de la façade: Position . (-ny, nx, 0)
    u = mth("ADD", mth("MULTIPLY", sp_.outputs[0], mth("MULTIPLY", sn_.outputs[1], -1.0)), mth("MULTIPLY", sp_.outputs[1], sn_.outputs[0]))
    z = sp_.outputs[2]
    vec = N_.new("ShaderNodeCombineXYZ")
    L.new(u, vec.inputs["X"]); L.new(z, vec.inputs["Y"])
    # motif: rondins 7 m x 0,19 m, planches 0,24 x 6 m, crépi (uni), pierre 0,5 x 0,3 m
    gris = (1, 1, 1, 1)
    pat = _brique(N_, L, vec.outputs["Vector"],
                  choix(wall, [7.0, 0.24, 6.0, 0.55]), choix(wall, [0.19, 6.0, 6.0, 0.30]), choix(wall, [0.012, 0.010, 0.0, 0.035]),
                  gris, (0.72, 0.72, 0.72, 1), (0.25, 0.25, 0.25, 1))
    base = N_.new("ShaderNodeAttribute"); base.attribute_name, base.attribute_type = "mur", "GEOMETRY"
    mm = N_.new("ShaderNodeMix"); mm.data_type, mm.blend_type = "RGBA", "MULTIPLY"
    mm.inputs[0].default_value = 1.0
    L.new(base.outputs["Color"], mm.inputs[6]); L.new(pat, mm.inputs[7])
    # grain du crépi
    nz = N_.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 6.0; nz.inputs["Detail"].default_value = 5.0
    L.new(geo.outputs["Position"], nz.inputs["Vector"])
    gm = N_.new("ShaderNodeMix"); gm.data_type, gm.blend_type = "RGBA", "MULTIPLY"
    gm.inputs[0].default_value = 0.35
    L.new(mm.outputs[2], gm.inputs[6]); L.new(nz.outputs["Color"], gm.inputs[7])
    # fenêtres
    fu = mth("FRACT", mth("DIVIDE", u, 3.2))
    fz = mth("FRACT", mth("DIVIDE", z, 2.9))
    win = mth("MULTIPLY", mth("MULTIPLY", mth("GREATER_THAN", fu, 0.30), mth("LESS_THAN", fu, 0.62)),
              mth("MULTIPLY", mth("GREATER_THAN", fz, 0.40), mth("LESS_THAN", fz, 0.78)))
    win = mth("MULTIPLY", win, mth("LESS_THAN", mth("ABSOLUTE", sn_.outputs[2]), 0.4))
    win = mth("MULTIPLY", win, cs.outputs["Blue"])
    fm = N_.new("ShaderNodeMix"); fm.data_type = "RGBA"
    L.new(win, fm.inputs[0]); L.new(gm.outputs[2], fm.inputs[6])
    fm.inputs[7].default_value = (0.012, 0.016, 0.022, 1.0)
    L.new(fm.outputs[2], b.inputs["Base Color"])
    return mt


def _materiau_toit():
    """Toit: 'toit' = couleur de base, 'cls' (G) = type: 0 dalles de pierre/ardoise, 1 bardeaux de mélèze, 2 tuiles, 3 tôle à joints debout.
    Le motif suit la pente: lignes parallèles au faîtage, coordonnée le long de la pente corrigée par la pente."""
    mt = bpy.data.materials.new("Toit")
    mt.use_nodes = True
    nt = mt.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.8
    N_, L, mth, choix = _noeuds_outils(nt)
    geo = N_.new("ShaderNodeNewGeometry")
    sp_ = N_.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sp_.inputs[0])
    sn_ = N_.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Normal"], sn_.inputs[0])
    at_c = N_.new("ShaderNodeAttribute"); at_c.attribute_name, at_c.attribute_type = "cls", "GEOMETRY"
    cs = N_.new("ShaderNodeSeparateColor"); L.new(at_c.outputs["Color"], cs.inputs[0])
    roof = cs.outputs["Green"]
    nh = mth("MAXIMUM", mth("SQRT", mth("ADD", mth("MULTIPLY", sn_.outputs[0], sn_.outputs[0]), mth("MULTIPLY", sn_.outputs[1], sn_.outputs[1]))), 0.05)
    nx_, ny_ = mth("DIVIDE", sn_.outputs[0], nh), mth("DIVIDE", sn_.outputs[1], nh)
    run = mth("ADD", mth("MULTIPLY", sp_.outputs[0], nx_), mth("MULTIPLY", sp_.outputs[1], ny_))
    v = mth("DIVIDE", run, mth("MAXIMUM", sn_.outputs[2], 0.35))                       # le long de la pente
    u = mth("ADD", mth("MULTIPLY", sp_.outputs[0], mth("MULTIPLY", ny_, -1.0)), mth("MULTIPLY", sp_.outputs[1], nx_))   # le long du faîtage
    vec = N_.new("ShaderNodeCombineXYZ")
    L.new(u, vec.inputs["X"]); L.new(v, vec.inputs["Y"])
    # motif: dalles 0,55 x 0,32 m, bardeaux 0,16 x 0,45 m, tuiles 0,25 x 0,40 m, tôle 0,6 m x 40 m (joints parallèles à la pente)
    pat = _brique(N_, L, vec.outputs["Vector"],
                  choix(roof, [0.55, 0.16, 0.25, 0.60]), choix(roof, [0.32, 0.45, 0.40, 40.0]), choix(roof, [0.025, 0.012, 0.018, 0.012]),
                  (1, 1, 1, 1), (0.66, 0.66, 0.66, 1), (0.22, 0.22, 0.22, 1))
    base = N_.new("ShaderNodeAttribute"); base.attribute_name, base.attribute_type = "toit", "GEOMETRY"
    mm = N_.new("ShaderNodeMix"); mm.data_type, mm.blend_type = "RGBA", "MULTIPLY"
    mm.inputs[0].default_value = 1.0
    L.new(base.outputs["Color"], mm.inputs[6]); L.new(pat, mm.inputs[7])
    L.new(mm.outputs[2], b.inputs["Base Color"])
    return mt


def build_buildings(env, coll):
    """Bâtiments swissBUILDINGS3D (avant l'événement) préparés par prep-batiments. Avec --cull, seuls ceux de la zone visible.
    Ceux que la matière atteindra (empreinte de l'aléa) sont regroupés par instant d'arrivée et masqués à ce moment."""
    m = env["meta"]
    bm = m.get("batiments")
    path = os.path.join(env["dir"], bm["file"]) if bm else None
    if not bm or not os.path.exists(path):
        log("bâtiments 3D: non préparés (python blatten.py prep-batiments), scène sans bâtiments")
        return None
    z = np.load(path)
    V, T, nt, ctr = z["v"].astype(np.float64), z["t"], z["ntri"], z["centre"].astype(np.float64)
    Ec_, Nc_ = m["scene_E0"] + ctr[:, 0], m["scene_N0"] + m["flip"] * ctr[:, 1]
    keep = np.ones(len(nt), bool)
    if env.get("vis") and 2.0 in env["vis"]:
        keep = _vis_at(env["vis"][2.0], Ec_, Nc_)
    if not keep.any():
        log("bâtiments 3D: aucun dans la zone visible")
        return None
    ta = _arrivee(env, Ec_, Nc_)
    ts = np.concatenate([[0], np.cumsum(nt)])
    mats = [_materiau_mur(), _materiau_toit()]
    nf_tot, objs, nsw = 0, [], 0
    for g in np.unique(ta[keep]):
        kg = keep & (ta == g)
        sel = np.concatenate([np.arange(ts[k], ts[k + 1]) for k in np.nonzero(kg)[0]])
        tri = T[sel]
        used, inv = np.unique(tri.ravel(), return_inverse=True)
        co, tri = V[used], inv.reshape(-1, 3).astype(np.int32)
        n = np.cross(co[tri[:, 1]] - co[tri[:, 0]], co[tri[:, 2]] - co[tri[:, 0]])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        toit = (np.abs(n[:, 2]) > 0.35).astype(np.int32)     # faces peu verticales = toit
        # couleurs par bâtiment: toit d'après l'image aérienne (médiane des sommets de toit), façade tirée dans une palette locale
        bid = np.repeat(np.nonzero(kg)[0], nt[kg])                     # bâtiment de chaque triangle (dans l'ordre de `sel`)
        vb = np.zeros(len(co), np.int64)
        vb[tri.ravel()] = np.repeat(bid, 3)
        ub, ib = np.unique(vb, return_inverse=True)
        ub_b = ub
        rng_b0 = np.random.default_rng(5)
        Ev, Nv = m["scene_E0"] + co[:, 0], m["scene_N0"] + m["flip"] * co[:, 1]
        smp = _echantillon_ortho(env, Ev, Nv)
        roofv = np.zeros(len(co), bool)
        roofv[tri[toit == 1].ravel()] = True
        rc = np.full((len(ub), 3), 0.30, np.float32)
        for q in range(len(ub)):
            sel_v = (ib == q) & roofv & np.isfinite(smp[:, 0])
            if sel_v.any():
                rc[q] = np.median(smp[sel_v], axis=0)
        rc = np.clip(rc, 0.04, 0.85) ** 2.2                                   # sRGB -> linéaire
        # type de toit d'après la couleur vue d'en haut (la classe suffit, pas besoin de recaler l'image): 0 dalles, 1 bardeaux, 2 tuiles, 3 tôle
        lum = np.sum(rc ** (1 / 2.2) * np.array([0.3, 0.59, 0.11], np.float32), axis=1) if len(rc) else np.zeros(0)
        rcs = rc ** (1 / 2.2)
        rouge = (rcs[:, 0] > 1.25 * rcs[:, 1]) & (rcs[:, 0] > 1.3 * rcs[:, 2]) & (lum > 0.22)
        chaud = (rcs[:, 0] > 1.08 * rcs[:, 2]) & (lum < 0.40)
        cr = np.where(rouge, 2, np.where(lum > 0.52, 3, np.where(chaud, 1, 0))).astype(np.int64)
        palt = np.array([[0.050, 0.050, 0.055], [0.075, 0.048, 0.030], [0.30, 0.095, 0.060], [0.24, 0.25, 0.27]], np.float32)
        tc = palt[cr] * rng_b0.uniform(0.8, 1.2, (len(ub), 1)).astype(np.float32)
        # façade selon le type de bâtiment (calque swisstopo): 0 rondins, 1 planches, 2 crépi, 3 pierre
        cal = z["calque"][ub_b] if len(ub_b) else np.zeros(0, int)
        cw = np.zeros(len(ub), np.int64)
        u01 = rng_b0.random(len(ub))
        cw[:] = np.where(u01 < 0.50, 0, np.where(u01 < 0.65, 1, np.where(u01 < 0.90, 2, 3)))
        cw[cal == 1] = 1                                           # bâtiment ouvert (grange, stadel): planches
        cw[np.isin(cal, [2, 4, 7, 6])] = 2                         # chapelle, sacré, tour, serre: crépi
        cw[cal == 5] = 3                                           # grand mur: pierre
        fen = np.where(np.isin(cal, [1, 5, 6]), 0.0, 1.0)         # pas de fenêtres sur granges, murs, serres
        palw = np.array([[0.045, 0.028, 0.018], [0.080, 0.050, 0.030], [0.52, 0.48, 0.42], [0.20, 0.19, 0.18]], np.float32)
        mc = palw[cw] * rng_b0.uniform(0.85, 1.15, (len(ub), 1)).astype(np.float32)
        cl = np.stack([cw.astype(np.float32), cr.astype(np.float32), fen.astype(np.float32)], 1)
        ob = _objet_triangles("Batiments" if not np.isfinite(g) else f"Batiments_t{g:g}", co, tri, mats, toit,
                              attrs={"toit": tc[ib], "mur": mc[ib], "cls": cl[ib]})
        coll.objects.link(ob)
        if np.isfinite(g):
            ENSEV.append((float(g), ob))
            nsw += int(kg.sum())
        nf_tot += len(tri)
        objs.append(ob)
    log(f"bâtiments 3D: {int(keep.sum())} sur {len(nt)} (zone visible), {nf_tot:,} triangles"
        + (f", dont {nsw} sur le passage de la matière (masqués à son arrivée)" if nsw else ""))
    return objs[0]


# couleurs (linéaires) par essence: 0 épicéa, 1 mélèze, 2 pin cembro, 3 feuillus; tronc
COULEURS_ARBRES = np.array([[0.020, 0.038, 0.020], [0.070, 0.105, 0.028], [0.030, 0.052, 0.024], [0.085, 0.135, 0.034], [0.050, 0.092, 0.030]], np.float32)
COULEUR_TRONC = np.array([0.050, 0.034, 0.024], np.float32)


def _bipyramide(zb, zt, rb, n, jit, rng, zlow=0.3, ph=0.0):
    """Étage de feuillage fermé (anneau de rayon rb à zb, pointe haute à zt, pointe basse): rend (sommets, triangles)."""
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False) + ph
    r = rb * (1 + jit * (rng.random(n) - 0.5) * 2)
    ring = np.stack([r * np.cos(ang), r * np.sin(ang), zb + (rng.random(n) - 0.5) * jit * 0.06], 1)
    top = np.array([[0.0, 0.0, zt]])
    bot = np.array([[0.0, 0.0, zb - (zt - zb) * zlow]])
    V = np.concatenate([ring, top, bot])
    T = []
    for i in range(n):
        j = (i + 1) % n
        T += [(i, j, n), (j, i, n + 1)]
    return V, np.array(T, np.int32)


def _ellipsoide(z0, z1, n, rings, jit, rng, rmax, fmax):
    """Couronne arrondie (type sphère aplatie) de z0 à z1; le rayon maximal est atteint à la fraction fmax de la hauteur."""
    V = [np.array([[0.0, 0.0, z0]])]
    ph = rng.random() * 6.28
    lobe = 1 + 0.22 * np.sin(np.linspace(0, 2 * np.pi, n, endpoint=False) * rng.integers(2, 4) + rng.random() * 6.28)   # lobes de la couronne
    for k in range(rings):
        f = (k + 1) / (rings + 1)
        prof = np.sin(np.pi * f ** (np.log(0.5) / np.log(fmax))) ** 0.75
        ang = np.linspace(0, 2 * np.pi, n, endpoint=False) + ph + 0.35 * k             # décalage régulier: pas de torsion
        r = rmax * prof * lobe * (1 + jit * 0.35 * (rng.random(n) - 0.5) * 2)
        zz = z0 + (z1 - z0) * f + (rng.random(n) - 0.5) * jit * 0.02
        V.append(np.stack([r * np.cos(ang), r * np.sin(ang), zz], 1))
    V.append(np.array([[0.0, 0.0, z1]]))
    V = np.concatenate(V)
    T = []
    for i in range(n):
        j = (i + 1) % n
        T.append((0, 1 + j, 1 + i))
        for k in range(rings - 1):
            a0, a1 = 1 + k * n, 1 + (k + 1) * n
            T += [(a0 + i, a0 + j, a1 + i), (a0 + j, a1 + j, a1 + i)]
        top = 1 + rings * n
        T.append((1 + (rings - 1) * n + i, 1 + (rings - 1) * n + j, top))
    return V, np.array(T, np.int32)


def _fusion(parts):
    V, T, off = [], [], 0
    for v, t in parts:
        V.append(v)
        T.append(t + off)
        off += len(v)
    return np.concatenate(V), np.concatenate(T)


def _proto_arbre(espece, lod, rng):
    """Un arbre simplifié, rayon de couronne 1, hauteur 1, pied en z = 0. Rend (sommets, triangles, indice de tronc).
    lod 0: détaillé (< 120 m), 1: moyen (< 500 m), 2: lointain (< 1500 m), 3: très lointain (cônes simples)."""
    parts = []
    if espece in (0, 1):                      # conifères à étages (épicéa serré, mélèze plus lâche)
        T_ = {0: (16, 8, 2, 1), 1: (12, 6, 2, 1)}[espece][lod]
        n = (12, 8, 5, 4)[lod]
        zlow = 0.15 if espece == 0 else 0.22
        z0 = 0.16 if espece == 0 else 0.20
        expo = 0.95 if espece == 0 else 0.80
        for k in range(T_):
            zb = z0 + (1 - z0) * k / T_
            zt = z0 + (1 - z0) * min(1.0, (k + 1.6) / T_)
            rb = ((1 - zb) ** expo) * (1.0 if espece == 0 else 0.92)
            parts.append(_bipyramide(zb, zt, rb, n, (0.26, 0.16, 0.10, 0.05)[lod], rng, zlow, rng.random() * 6.28))
    elif espece == 4:                         # arbuste (aulne vert): dôme bas, sans tronc
        V, T = _ellipsoide(0.0, 1.0, (8, 6, 5, 4)[lod], (4, 3, 2, 1)[lod], 0.30, rng, 1.0, 0.40)
        return V, T, len(V)
    else:                                     # pin cembro (couronne ovoïde, plus haute) et feuillus (couronne arrondie)
        zc0, zc1 = (0.22, 1.0) if espece == 2 else (0.30, 1.0)
        rings = (6, 4, 2, 1)[lod]
        n = (10, 8, 5, 5)[lod]
        parts.append(_ellipsoide(zc0, zc1, n, rings, (0.30, 0.20, 0.14, 0.08)[lod], rng, 0.82 if espece == 2 else 1.0,
                                 0.55 if espece == 2 else 0.45))
    V, T = _fusion(parts)
    ntr = len(V)
    if lod < 2:                               # tronc: prisme à 4 pans
        a = np.linspace(0, 2 * np.pi, 4, endpoint=False)
        r0 = 0.07
        tv = np.concatenate([np.stack([r0 * np.cos(a), r0 * np.sin(a), np.zeros(4)], 1),
                             np.stack([r0 * 0.6 * np.cos(a), r0 * 0.6 * np.sin(a), np.full(4, 0.30)], 1)])
        tt = []
        for i in range(4):
            j = (i + 1) % 4
            tt += [(i, j, 4 + i), (j, 4 + j, 4 + i)]
        V = np.concatenate([V, tv])
        T = np.concatenate([T, np.array(tt, np.int32) + ntr])
    return V, T, ntr


def build_trees(env, coll, cam):
    """Arbres issus de prep-vegetation: essence (épicéa, mélèze, pin cembro, feuillus), hauteur, couronne, et posés sur
    le relief EXACTEMENT comme le maillage de la scène (même anneau, même résolution). Détail selon la distance.
    Avec --cull, seuls ceux de la zone visible. Maillage fusionné (pas d'instances: robuste, mémoire modeste)."""
    m = env["meta"]
    vm = m.get("vegetation")
    path = os.path.join(env["dir"], vm["file"]) if vm else None
    if not vm or not os.path.exists(path):
        log("arbres: non préparés (python blatten.py prep-vegetation), scène sans arbres")
        return None
    z = np.load(path)
    X, Y, Zf, Hh, R = (z[k].astype(np.float64) for k in ("x", "y", "z", "h", "r"))
    sp = z["sp"].astype(np.int64) if "sp" in z.files else np.zeros(len(X), np.int64)
    pente = z["pente"].astype(np.float64) if "pente" in z.files else np.zeros(len(X))
    d = np.hypot(X - cam.x, Y - cam.y)
    keep = d <= CFG["tree_dist"]
    E = m["scene_E0"] + X
    N = m["scene_N0"] + m["flip"] * Y
    if env.get("vis") and 2.0 in env["vis"]:
        keep &= _vis_at(env["vis"][2.0], E, N)
    # limite supérieure de la forêt: pas d'arbres dans la neige ni au-dessus (dégradé sur 200 m sous la ligne de neige)
    sl = CFG["snow_line"] - 50.0
    if CFG["snow"] > 0:
        pa = np.clip((sl - Zf) / 200.0, 0.0, 1.0)
        keep &= np.random.default_rng(3).random(len(X)) < pa
    n0 = len(X)
    if not keep.any():
        log("arbres: aucun dans la zone visible")
        return None
    X, Y, Zf, Hh, R, sp, pente, d, E, N = (a[keep] for a in (X, Y, Zf, Hh, R, sp, pente, d, E, N))
    # altitude du sol = celle du maillage de la scène à cet endroit
    Z = Zf.copy()
    ri = env.get("ring_info")
    if ri:
        Ec, Nc, rings = ri
        cheb = np.maximum(np.abs(E - Ec), np.abs(N - Nc))
        dz = m.get("dz", 0.0)
        dz = dz if abs(dz) < 30 else 0.0
        done = np.zeros(len(X), bool)
        for step, H in rings:
            sel = (cheb <= H) & ~done
            if sel.any():
                Z[sel] = _bilin(env["levels"][step], E[sel], N[sel]) + dz
                done |= sel
    rng = np.random.default_rng(7)
    nv_var = 5
    yaw = rng.uniform(0, 2 * np.pi, len(X))
    var = rng.integers(0, nv_var, len(X))
    R = R * rng.uniform(0.9, 1.1, len(X))      # hauteurs: celles du relevé laser, sans variation
    Z = Z + np.maximum(0.0, R * pente * 0.9 - 0.12 * Hh) - 0.10     # sur forte pente, la couronne amont ne rentre pas dans le sol
    lod = np.where(d < 120.0, 0, np.where(d < 500.0, 1, np.where(d < 1500.0, 2, 3)))
    tone = rng.uniform(0.85, 1.15, len(X))
    # couleur de la cime lue dans l'image aérienne (ombres et teintes locales comprises): les arbres s'accordent ainsi au reste
    oc = _echantillon_ortho(env, E, N)
    ok_oc = np.isfinite(oc[:, 0])
    oc = np.where(ok_oc[:, None], oc, 0.0).astype(np.float64)
    oc = np.where(oc <= 0.04045, oc / 12.92, ((oc + 0.055) / 1.055) ** 2.4)                 # sRGB -> linéaire
    w_oc = np.where(ok_oc, CFG["tree_ortho"], 0.0)
    near = d < CFG["wind_dist"]
    protos = {(e, l, v): _proto_arbre(e, l, np.random.default_rng(1000 * e + 100 * l + v)) for e in range(5) for l in range(4) for v in range(nv_var)}
    mt = bpy.data.materials.new("Arbre")
    mt.use_nodes = True
    nt_ = mt.node_tree
    b = nt_.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.92
    at = nt_.nodes.new("ShaderNodeAttribute")
    at.attribute_name, at.attribute_type = "col", "GEOMETRY"
    # grain d'aiguilles (bruit fin) et plaques de teinte (bruit large), en coordonnées du monde, + relief: casse l'aspect lisse des volumes
    Nn, Ln = nt_.nodes, nt_.links
    po = Nn.new("ShaderNodeNewGeometry")
    def _bruit(sc, det):
        t = Nn.new("ShaderNodeTexNoise")
        t.inputs["Scale"].default_value, t.inputs["Detail"].default_value = sc, det
        Ln.new(po.outputs["Position"], t.inputs["Vector"])
        return t.outputs["Fac"]
    def _plage(src, lo, hi):
        r = Nn.new("ShaderNodeMapRange")
        r.inputs["From Min"].default_value, r.inputs["From Max"].default_value = 0.25, 0.75
        r.inputs["To Min"].default_value, r.inputs["To Max"].default_value = lo, hi
        Ln.new(src, r.inputs["Value"])
        return r.outputs["Result"]
    grain = _bruit(2.2, 7.0)
    plaque = _bruit(0.12, 3.0)
    mx1 = Nn.new("ShaderNodeMix")
    mx1.data_type, mx1.blend_type = "RGBA", "MULTIPLY"
    mx1.inputs[0].default_value = 1.0
    Ln.new(at.outputs["Color"], mx1.inputs[6])
    g3 = Nn.new("ShaderNodeCombineColor")
    for ch in ("Red", "Green", "Blue"):
        Ln.new(_plage(grain, 0.55, 1.35), g3.inputs[ch])
    Ln.new(g3.outputs["Color"], mx1.inputs[7])
    mx2 = Nn.new("ShaderNodeMix")
    mx2.data_type, mx2.blend_type = "RGBA", "MULTIPLY"
    mx2.inputs[0].default_value = 1.0
    Ln.new(mx1.outputs[2], mx2.inputs[6])
    p3 = Nn.new("ShaderNodeCombineColor")
    Ln.new(_plage(plaque, 0.85, 1.12), p3.inputs["Red"])
    Ln.new(_plage(plaque, 0.88, 1.10), p3.inputs["Green"])
    Ln.new(_plage(plaque, 0.80, 1.05), p3.inputs["Blue"])
    Ln.new(p3.outputs["Color"], mx2.inputs[7])
    Ln.new(mx2.outputs[2], b.inputs["Base Color"])
    bp = Nn.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value, bp.inputs["Distance"].default_value = 0.8, 0.3
    Ln.new(_bruit(5.0, 5.0), bp.inputs["Height"])
    Ln.new(bp.outputs["Normal"], b.inputs["Normal"])
    ta = _arrivee(env, E, N)
    ob0, nf, nsw = None, 0, 0
    groupes = [(g, zn) for g in np.unique(ta) for zn in ((0, 1) if CFG["wind"] else (0,))]
    for g, zn in groupes:
        gsel = (ta == g) & (near == bool(zn))
        if not gsel.any():
            continue
        co_all, tri_all, col_all, vent_all = [], [], [], []
        off = 0
        for (e, l, v), (PV, PT, ntr) in protos.items():
            sel = (sp == e) & (lod == l) & (var == v) & gsel
            if not sel.any():
                continue
            nt = int(sel.sum())
            c, sn = np.cos(yaw[sel])[:, None], np.sin(yaw[sel])[:, None]
            px = PV[None, :, 0] * R[sel][:, None]
            py = PV[None, :, 1] * R[sel][:, None]
            pz = PV[None, :, 2] * Hh[sel][:, None]
            co = np.stack([X[sel][:, None] + px * c - py * sn, Y[sel][:, None] + px * sn + py * c, Z[sel][:, None] + pz], -1)
            k = len(PV)
            tri = (PT[None, :, :] + (np.arange(nt) * k + off)[:, None, None]).reshape(-1, 3)
            gg = np.clip(PV[:, 2], 0, 1)
            shade = (0.55 + 0.45 * gg)[None, :, None]                     # bas de la couronne plus sombre
            esp = np.broadcast_to(COULEURS_ARBRES[e][None, None, :], (nt, k, 3)) * shade * tone[sel][:, None, None]
            cim = oc[sel][:, None, :] * (0.55 + 0.45 * gg)[None, :, None] * tone[sel][:, None, None]
            wc = w_oc[sel][:, None, None]
            base = ((1.0 - wc) * esp + wc * cim).copy()
            base[:, ntr:, :] = COULEUR_TRONC[None, None, :]
            vent = (0.03 * Hh[sel][:, None]) * (gg ** 2)[None, :]                     # amplitude du balancement (m) en cime
            vent[:, ntr:] = 0.0
            vent_all.append(vent.reshape(-1))
            co_all.append(co.reshape(-1, 3))
            tri_all.append(tri)
            col_all.append(base.reshape(-1, 3))
            off += nt * k
        co = np.concatenate(co_all).astype(np.float32)
        tri = np.concatenate(tri_all).astype(np.int32)
        col = np.concatenate(col_all).astype(np.float32)
        ob = _objet_triangles(("Arbres" if not np.isfinite(g) else f"Arbres_t{g:g}") + ("_v" if zn else ""), co, tri, [mt], lisse=True,
                              scalaires={"vent": np.concatenate(vent_all)} if zn else None)
        if zn:
            _vent_modifier(ob)
        ca = ob.data.color_attributes.new("col", "BYTE_COLOR", "POINT")      # 4 octets par sommet au lieu de 16 (mémoire GPU)
        ca.data.foreach_set("color", np.concatenate([col, np.ones((len(co), 1), np.float32)], 1).ravel())
        coll.objects.link(ob)
        if np.isfinite(g):
            ENSEV.append((float(g), ob))
            nsw += int(gsel.sum())
        elif ob0 is None or not zn:
            ob0 = ob
        ob0 = ob0 or ob
        nf += len(tri)
    nl = [int((lod == i).sum()) for i in range(4)]
    log(f"arbres: {len(X):,} sur {n0:,} (visibles, à moins de {CFG['tree_dist']:.0f} m), {nf:,} triangles "
        f"(détaillés {nl[0]:,}, moyens {nl[1]:,}, lointains {nl[2]:,}, très lointains {nl[3]:,})"
        + (f", dont {nsw:,} sur le passage de la matière (masqués à son arrivée)" if nsw else ""))
    if nf > 15_000_000:
        log(f"!! {nf:,} triangles d'arbres: risque de dépasser les 6 Go de la carte graphique. Réduire avec --tree-dist 3500 ou relancer prep-vegetation --rayon 3500.")
    return ob0


def _z_sol(env, E, N):
    """Altitude du sol = celle du maillage de la scène (même anneau, même résolution) aux points (E, N)."""
    m = env["meta"]
    Z = np.zeros(len(E))
    ri = env.get("ring_info")
    dz = m.get("dz", 0.0)
    dz = dz if abs(dz) < 30 else 0.0
    done = np.zeros(len(E), bool)
    if ri:
        Ec, Nc, rings = ri
        cheb = np.maximum(np.abs(E - Ec), np.abs(N - Nc))
        for step, H in rings:
            sel = (cheb <= H) & ~done
            if sel.any():
                Z[sel] = _bilin(env["levels"][step], E[sel], N[sel]) + dz
                done |= sel
    if not done.all():
        lv = env["levels"][min(env["levels"])] if env.get("levels") else None
        if lv is not None:
            Z[~done] = _bilin(lv, E[~done], N[~done]) + dz
    return Z


def _materiau_eau():
    """Eau de rivière animée: rides étirées dans le sens du courant qui défilent (vitesse ~2 m/s), reflets du ciel (rugosité faible),
    teinte laiteuse de torrent glaciaire, écume sur les bords. Le temps vient de l'image courante (pilote), donc la rivière vit dans la vidéo."""
    mt = bpy.data.materials.new("Eau")
    mt.use_nodes = True
    nt = mt.node_tree
    N_, L, mth, _ch = _noeuds_outils(nt)
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.10
    b.inputs["IOR"].default_value = 1.33
    uvn = N_.new("ShaderNodeUVMap"); uvn.uv_map = "UVMap"
    sep = N_.new("ShaderNodeSeparateXYZ"); L.new(uvn.outputs["UV"], sep.inputs[0])
    U, V = sep.outputs[0], sep.outputs[1]
    tn = N_.new("ShaderNodeValue"); tn.label = "temps (s)"
    try:
        fc = tn.outputs[0].driver_add("default_value")
        fc.driver.type = "SCRIPTED"
        fps = max(float(bpy.context.scene.render.fps), 1.0)
        fc.driver.expression = f"(frame - 1) / {fps:g}"
    except Exception as e:
        log(f"eau: pilote de temps impossible ({e}), rivière figée")
    T = tn.outputs[0]

    def bruit(vec_xyz, scale, detail):
        c = N_.new("ShaderNodeCombineXYZ")
        for nm, v in zip(("X", "Y", "Z"), vec_xyz):
            if isinstance(v, (int, float)):
                c.inputs[nm].default_value = v
            else:
                L.new(v, c.inputs[nm])
        n = N_.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        n.inputs["Roughness"].default_value = 0.55
        L.new(c.outputs[0], n.inputs["Vector"])
        return n.outputs["Fac"]
    n1 = bruit((mth("MULTIPLY", V, 1.1), mth("MULTIPLY", mth("SUBTRACT", U, mth("MULTIPLY", T, 1.8)), 0.35), mth("MULTIPLY", T, 0.45)), 1.0, 5.0)
    n2 = bruit((mth("MULTIPLY", V, 3.6), mth("MULTIPLY", mth("SUBTRACT", U, mth("MULTIPLY", T, 2.4)), 1.2), mth("MULTIPLY", T, 0.9)), 1.0, 3.0)
    h = mth("ADD", mth("MULTIPLY", n1, 0.7), mth("MULTIPLY", n2, 0.3))
    bump = N_.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.55
    bump.inputs["Distance"].default_value = 0.12
    L.new(h, bump.inputs["Height"])
    L.new(bump.outputs["Normal"], b.inputs["Normal"])
    # couleur: eau trouble verdâtre, plus claire dans les crêtes; écume sur les bords et dans les turbulences
    r = N_.new("ShaderNodeMapRange"); r.clamp = True
    r.inputs["From Min"].default_value, r.inputs["From Max"].default_value = 0.3, 0.75
    L.new(n1, r.inputs["Value"])
    cm = N_.new("ShaderNodeMix"); cm.data_type = "RGBA"
    L.new(r.outputs["Result"], cm.inputs[0])
    cm.inputs[6].default_value = (0.020, 0.040, 0.042, 1.0)
    cm.inputs[7].default_value = (0.085, 0.120, 0.115, 1.0)
    at = N_.new("ShaderNodeAttribute"); at.attribute_name, at.attribute_type = "larg", "GEOMETRY"
    asep = N_.new("ShaderNodeSeparateColor"); L.new(at.outputs["Color"], asep.inputs[0])
    bord = mth("DIVIDE", mth("ABSOLUTE", V), mth("MAXIMUM", asep.outputs["Red"], 0.1))
    ecume = mth("MULTIPLY", mth("GREATER_THAN", bord, 0.88), mth("GREATER_THAN", n2, 0.58))
    ecume = mth("MAXIMUM", ecume, mth("MULTIPLY", mth("GREATER_THAN", n1, 0.84), 0.5))
    fm = N_.new("ShaderNodeMix"); fm.data_type = "RGBA"
    L.new(ecume, fm.inputs[0]); L.new(cm.outputs[2], fm.inputs[6])
    fm.inputs[7].default_value = (0.42, 0.45, 0.47, 1.0)
    L.new(fm.outputs[2], b.inputs["Base Color"])
    if CFG["haze"] > 0:
        cam = N_.new("ShaderNodeCameraData")
        decay = mth("POWER", 2.718281828, mth("MULTIPLY", cam.outputs["View Distance"], -CFG["haze"]))
        fog = mth("SUBTRACT", 1.0, decay)
        em = N_.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (0.62, 0.76, 0.95, 1)
        em.inputs["Strength"].default_value = 2.0
        mx = N_.new("ShaderNodeMixShader")
        L.new(fog, mx.inputs[0])
        L.new(b.outputs["BSDF"], mx.inputs[1])
        L.new(em.outputs["Emission"], mx.inputs[2])
        L.new(mx.outputs["Shader"], N_["Material Output"].inputs["Surface"])
    apply_height_fog(mt)
    return mt


def build_water(env, coll, cam):
    """Rubans d'eau le long des cours d'eau OpenStreetMap (prep-eau), posés sur le relief réel de la scène, animés par le matériau.
    Le ruban est placé au plus bas de la section (rives comprises) puis lissé le long du cours: les berges plus hautes le cachent
    naturellement. Avec --cull, seuls les tronçons visibles. Les tronçons atteints par la matière sont masqués à son arrivée."""
    m = env["meta"]
    if m.get("eau_masque"):
        log("eau: lue dans l'image aérienne (masque), sans ruban")
        return None
    em = m.get("eau")
    path = os.path.join(env["dir"], em["file"]) if em else None
    if not em or not os.path.exists(path):
        log("eau: non préparée (python blatten.py prep-eau), scène sans rivière")
        return None
    z = np.load(path)
    P, deb, larg = z["pts"].astype(np.float64), z["debut"], z["larg"]
    fin = np.append(deb[1:], len(P))
    mat = _materiau_eau()
    V_all, T_all, UV_all, LG_all, TA_all = [], [], [], [], []
    off = 0
    nseg = 0
    for k in range(len(deb)):
        q = P[deb[k]:fin[k]]
        d = np.hypot(*np.diff(q, axis=0).T)
        s = np.concatenate([[0.0], np.cumsum(d)])
        if s[-1] < 6.0:
            continue
        ns = int(s[-1] // 5.0) + 2
        ss = np.linspace(0, s[-1], ns)
        E = np.interp(ss, s, q[:, 0]); N = np.interp(ss, s, q[:, 1])
        tx, ty = np.gradient(E), np.gradient(N)
        nrm = np.maximum(np.hypot(tx, ty), 1e-6)
        nx, ny = -ty / nrm, tx / nrm
        w2 = 0.5 * float(larg[k])
        zl = _z_sol(env, E + nx * w2, N + ny * w2)
        zc = _z_sol(env, E, N)
        zr = _z_sol(env, E - nx * w2, N - ny * w2)
        zz = np.minimum(np.minimum(zl, zr), zc)
        zz = np.convolve(np.pad(zz, 3, mode="edge"), np.ones(7) / 7.0, mode="valid") + 0.10
        # le niveau de l'eau ne remonte jamais vers l'aval
        zz = np.minimum.accumulate(zz)
        X = E - m["scene_E0"]; Y = m["flip"] * (N - m["scene_N0"])
        ok = np.hypot(X - cam.x, Y - cam.y) <= CFG["tree_dist"]
        if env.get("vis") and 2.0 in env["vis"]:
            ok &= _vis_at(env["vis"][2.0], E, N)
        nxs, nys = nx, m["flip"] * ny
        L_ = np.stack([X + nxs * w2, Y + nys * w2, zz], 1)
        R_ = np.stack([X - nxs * w2, Y - nys * w2, zz], 1)
        seg = np.nonzero(ok[:-1] & ok[1:])[0]
        if not len(seg):
            continue
        verts = np.empty((ns * 2, 3)); verts[0::2], verts[1::2] = L_, R_
        uvv = np.empty((ns * 2, 2)); uvv[0::2, 0] = ss; uvv[1::2, 0] = ss; uvv[0::2, 1] = w2; uvv[1::2, 1] = -w2
        lg = np.zeros((ns * 2, 3)); lg[:, 0] = w2
        tri = np.concatenate([np.stack([2 * seg, 2 * seg + 1, 2 * seg + 2], 1), np.stack([2 * seg + 1, 2 * seg + 3, 2 * seg + 2], 1)])
        Em = E[seg]; Nm = N[seg]
        ta = np.tile(_arrivee(env, Em, Nm), 2)
        V_all.append(verts); T_all.append(tri + off); UV_all.append(uvv); LG_all.append(lg); TA_all.append(ta)
        off += ns * 2
        nseg += len(seg)
    if not V_all:
        log("eau: aucun tronçon dans la zone visible")
        return None
    Vv = np.concatenate(V_all); Tt = np.concatenate(T_all); UVv = np.concatenate(UV_all); LGv = np.concatenate(LG_all); TA = np.concatenate(TA_all)
    ob = None
    for g in np.unique(TA):
        sel = TA == g
        o = _objet_triangles("Eau" if not np.isfinite(g) else f"Eau_t{g:g}", Vv, Tt[sel], [mat], None, attrs={"larg": LGv.astype(np.float32)})
        uvl = o.data.uv_layers.new(name="UVMap")
        uvl.data.foreach_set("uv", UVv[Tt[sel].ravel()].astype(np.float32).ravel())
        # sommets inutilisés: sans effet (ils ne sont dans aucune face)
        coll.objects.link(o)
        if np.isfinite(g):
            ENSEV.append((float(g), o))
        ob = ob or o
    log(f"eau: {nseg:,} tronçons de 5 m, {len(Tt):,} triangles, matériau animé (courant ~2 m/s)")
    return ob


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
    # sous la canopée, l'image aérienne montre la cime des arbres (déjà modélisés en volume): on la remplace par un sol de forêt sombre
    cmk = env["meta"].get("canopee_masque") if env else None
    if cmk and env["meta"].get("vegetation") and not CFG["no_trees"] and os.path.exists(os.path.join(env["dir"], cmk["file"])):
        em_ = env["meta"]
        cimg = bpy.data.images.load(os.path.join(env["dir"], cmk["file"]))
        cimg.colorspace_settings.name = "Non-Color"
        ct = N.new("ShaderNodeTexImage")
        ct.image, ct.interpolation, ct.extension = cimg, "Linear", "CLIP"
        cmp_ = N.new("ShaderNodeMapping")
        cmp_.vector_type = "POINT"
        cW, cH = cmk["shape"][1] * cmk["step"], cmk["shape"][0] * cmk["step"]
        cnb = cmk["y1"] - cH
        cmp_.inputs["Location"].default_value = ((em_["scene_E0"] - cmk["x0"]) / cW, (em_["scene_N0"] - cnb) / cH, 0.0)
        cmp_.inputs["Scale"].default_value = (1.0 / cW, em_["flip"] / cH, 1.0)
        L.new(geo.outputs["Position"], cmp_.inputs["Vector"])
        L.new(cmp_.outputs["Vector"], ct.inputs["Vector"])
        csep = N.new("ShaderNodeSeparateColor")
        L.new(ct.outputs["Color"], csep.inputs["Color"])
        under = mrange(csep.outputs["Red"], 0.25, 0.75, 0.0, 0.35)
        sol = N.new("ShaderNodeMix")
        sol.data_type, sol.blend_type = "RGBA", "MULTIPLY"
        sol.inputs[0].default_value = 1.0
        L.new(col, sol.inputs[6])
        sol.inputs[7].default_value = (0.62, 0.64, 0.58, 1)      # assombrit sans changer la teinte
        col = mix(under, col, sol.outputs[2])
    # eau: masque tiré de l'image aérienne (prep-eau). Sol sombre, très brillant (reflets du ciel), ondulations qui bougent doucement.
    wq = None
    emk = env["meta"].get("eau_masque") if env else None
    if emk and not CFG["no_water"]:
        em_ = env["meta"]

        def _tex_masque(info):
            im_ = bpy.data.images.load(os.path.join(env["dir"], info["file"]))
            im_.colorspace_settings.name = "Non-Color"
            tx = N.new("ShaderNodeTexImage")
            tx.image, tx.interpolation, tx.extension = im_, "Linear", "CLIP"
            mp_ = N.new("ShaderNodeMapping")
            mp_.vector_type = "POINT"
            cW, cH = info["shape"][1] * info["step"], info["shape"][0] * info["step"]
            cnb = info["y1"] - cH
            mp_.inputs["Location"].default_value = ((em_["scene_E0"] - info["x0"]) / cW, (em_["scene_N0"] - cnb) / cH, 0.0)
            mp_.inputs["Scale"].default_value = (1.0 / cW, em_["flip"] / cH, 1.0)
            L.new(geo.outputs["Position"], mp_.inputs["Vector"])
            L.new(mp_.outputs["Vector"], tx.inputs["Vector"])
            sp_ = N.new("ShaderNodeSeparateColor")
            L.new(tx.outputs["Color"], sp_.inputs["Color"])
            return sp_.outputs["Red"], mp_.outputs["Vector"]

        wq = None
        if emk.get("grossier"):
            wq, _v = _tex_masque(emk["grossier"])
        if emk.get("fin"):
            wf, vf = _tex_masque(emk["fin"])
            sx = N.new("ShaderNodeSeparateXYZ")
            L.new(vf, sx.inputs["Vector"])
            dedans = math("MULTIPLY", math("MULTIPLY", math("GREATER_THAN", sx.outputs["X"], 0.0), math("LESS_THAN", sx.outputs["X"], 1.0)),
                          math("MULTIPLY", math("GREATER_THAN", sx.outputs["Y"], 0.0), math("LESS_THAN", sx.outputs["Y"], 1.0)))
            wq = wf if wq is None else mix(dedans, wq, wf)
        # temps (s), pour l'animation
        tn_ = N.new("ShaderNodeValue")
        tn_.label = "temps (s)"
        try:
            fc_ = tn_.outputs[0].driver_add("default_value")
            fc_.driver.type = "SCRIPTED"
            fc_.driver.expression = f"(frame - 1) / {max(float(bpy.context.scene.render.fps), 1.0):g}"
        except Exception as e:
            log(f"eau: pilote de temps impossible ({e}), eau figée")
        T_eau = tn_.outputs[0]
    # pentes raides: l'image projetée à la verticale s'étire en stries; on y ajoute des strates (multiplicatives) qui gardent les couleurs de l'image
    w_steep = mrange(nor.outputs["Z"], 0.62, 0.38, 0.0, 0.6)
    st_f = math("ADD", 0.75, math("MULTIPLY", strata.outputs["Fac"], 0.5))
    st_c = N.new("ShaderNodeCombineColor")
    for ch in ("Red", "Green", "Blue"):
        L.new(st_f, st_c.inputs[ch])
    st_m = N.new("ShaderNodeMix")
    st_m.data_type, st_m.blend_type = "RGBA", "MULTIPLY"
    st_m.inputs[0].default_value = 1.0
    L.new(col, st_m.inputs[6])
    L.new(st_c.outputs["Color"], st_m.inputs[7])
    col = mix(w_steep, col, st_m.outputs[2])
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
    if wq is not None:
        col = mix(wq, col, mix(0.55, col, (0.030, 0.060, 0.070, 1)))      # eau turbide: moitié de l'image, moitié teinte sombre bleu-vert
        snow = math("MULTIPLY", snow, math("SUBTRACT", 1.0, wq))          # pas de neige sur l'eau
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
    if wq is not None:
        def _onde(echelle, vit, amp):
            sc_ = N.new("ShaderNodeVectorMath")
            sc_.operation = "SCALE"
            sc_.inputs["Scale"].default_value = echelle
            L.new(geo.outputs["Position"], sc_.inputs[0])
            nz_ = N.new("ShaderNodeTexNoise")
            nz_.noise_dimensions = "4D"
            nz_.inputs["Detail"].default_value = 2.0
            L.new(sc_.outputs["Vector"], nz_.inputs["Vector"])
            w_ = math("MULTIPLY", T_eau, vit)
            L.new(w_, nz_.inputs["W"])
            return math("MULTIPLY", math("SUBTRACT", nz_.outputs["Fac"], 0.5), amp)
        ond = math("ADD", _onde(1.1, 0.9, 0.22), _onde(3.5, 1.7, 0.08))
        h = math("ADD", h, math("MULTIPLY", ond, wq))
        L.new(math("SUBTRACT", 0.95, math("MULTIPLY", wq, 0.89)), bsdf.inputs["Roughness"])
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
    ap.add_argument("--dt-per-step", type=float); ap.add_argument("--time-scale", type=float); ap.add_argument("--t0", type=float); ap.add_argument("--intro", type=float); ap.add_argument("--frame-step", type=int); ap.add_argument("--chrono", type=float, nargs="+"); ap.add_argument("--render-time", type=float)
    ap.add_argument("--fps", type=int); ap.add_argument("--radius", type=float)
    ap.add_argument("--color", choices=["speed", "natural"]); ap.add_argument("--look", choices=["realiste", "didactique"]); ap.add_argument("--haze", type=float)
    ap.add_argument("--cam", type=float, nargs=3); ap.add_argument("--target", type=float, nargs=3)
    ap.add_argument("--mono", action="store_true"); ap.add_argument("--ipd", type=float)
    ap.add_argument("--preset", choices=list(PRESETS))
    ap.add_argument("--frames", type=int, nargs=2); ap.add_argument("--origine", type=int)
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
    ap.add_argument("--no-buildings", action="store_true"); ap.add_argument("--no-trees", action="store_true"); ap.add_argument("--no-water", action="store_true"); ap.add_argument("--no-wind", action="store_true"); ap.add_argument("--tree-ortho", type=float); ap.add_argument("--tree-dist", type=float); ap.add_argument("--env-only", action="store_true"); ap.add_argument("--lite", action="store_true")
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
        elif k == "no_wind":
            if v:
                CFG["wind"] = False
        elif k in ("no_env", "camera_confirmed", "accept_lowres", "bench", "bench_no_warm", "persistent", "clip", "clip_no_keys", "clip_no_video", "cull", "no_hires", "env_only", "lite", "no_buildings", "no_trees", "no_water"):
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

    if CFG["lite"]:
        CFG["env_only"] = CFG["cull"] = True
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
    if CFG["env_only"]:
        deb = None
        log("ENVIRONNEMENT SEUL: aucune particule, aucune zone de rupture")
    elif CFG["matiere"] and CFG["matiere"] != "defaut":
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
    if CFG["terrain"] and not env and not CFG["env_only"]:
        t = vdb_to_mesh(CFG["terrain"], "Terrain", CFG["terrain_voxel"], offset, rot, coll,
                        (0.16, 0.14, 0.12, 1), data_dir, convert=CFG["terrain_voxel"] is not None)
        if t:
            t.color = (0.55, 0.50, 0.45, 1)
            if CFG["look"] == "realiste":
                t.data.materials.clear()
                t.data.materials.append(build_terrain_material())
    if CFG["release"] and not CFG["env_only"]:
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
        if not CFG["no_buildings"]:
            build_buildings(env, coll)
        if not CFG["no_trees"]:
            build_trees(env, coll, scene.camera.location)
        if not CFG["no_water"]:
            build_water(env, coll, scene.camera.location)
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

    if CFG["lite"]:
        path = os.path.join(out_dir, "blatten_env_lite.blend")
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
        log(f"version lite enregistrée: {path} ({os.path.getsize(path) / 1e6:.0f} Mo, images incluses)")
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
        scene.frame_step = max(1, int(CFG["frame_step"]))
        scene.render.use_overwrite = False      # reprise: les images déjà rendues sont gardées (relancer la même commande après une coupure)
        scene.render.use_placeholder = True     # plusieurs Blender peuvent se partager la plage sans refaire les mêmes images
        log(f"animation: images {scene.frame_start} à {scene.frame_end}, pas {scene.frame_step}, sortie {scene.render.filepath}")
        bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
