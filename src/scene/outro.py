"""
outro.py : image de fin du film, rendue dans Blender. Écran noir, texte blanc posé sur l'horizon, dans la direction
de l'événement (cap ~128 degrés), comme si le spectateur regardait encore la vallée.

Texte: reglages/outro.json (lignes; les [balises] sont à remplacer par Ilyas). Une seule image fixe: le montage la tient
la durée de l'outro avec un fondu d'entrée et de sortie.
    blender -b --python outro.py -- --format 360|bande --out dossier
Le format 360 donne une image équirectangulaire 3840x1920 (face = cap 200, comme le film); bande: 2560x1280,
130 x 65 degrés centrés sur le cap 170 (même cadrage que le brouillon HD plat).
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

DEFAUT = dict(
    lignes=[["[TEXTE DE FIN: message principal]", 1.4], "",
            "Simulation: Johan Gaume (ETH Zurich / WSL-SLF)",
            "[Réalisation: noms]", "",
            ["Sounds: klankbeeld (CC BY 4.0), craigsmith (CC0), via freesound.org", 0.7]],
    cap=128.0,               # degrés: direction de l'événement (360)
    cap_bande=150.0,         # dans la bande (105-235 degrés), un peu décalé pour que le texte tienne entier
    elevation=2.0,           # degrés: centre du bloc de texte, un peu au-dessus de l'horizon
    hauteur_ligne=1.5,       # degrés: hauteur des capitales d'une ligne de taille 1
    interligne=1.6,
)


def log(*a):
    print("[outro]", *a, flush=True)


def _dir(cap, el):
    c, h = math.radians(cap), math.radians(el)
    return Vector((math.sin(c) * math.cos(h), math.cos(c) * math.cos(h), math.sin(h)))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    fmt = argv[argv.index("--format") + 1] if "--format" in argv else "360"
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "render", "outro")
    R = dict(DEFAUT)
    f = os.path.join(ROOT, "reglages", "outro.json")
    if os.path.exists(f):
        R.update({k: v for k, v in json.load(open(f, encoding="utf-8")).items() if not k.startswith("_")})
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    coll = sc.collection
    w = bpy.data.worlds.new("Noir")
    sc.world = w
    w.color = (0, 0, 0)
    try:
        w.use_nodes = True
        w.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
    except Exception:
        pass
    mat = bpy.data.materials.new("Texte")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1, 1, 1, 1)
    em.inputs["Strength"].default_value = 1.0
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], o.inputs["Surface"])
    dist = 100.0
    lignes = [x[0] if isinstance(x, list) else x for x in R["lignes"]]
    tailles = [float(x[1]) if isinstance(x, list) else 1.0 for x in R["lignes"]]
    cap = R["cap_bande"] if fmt == "bande" else R["cap"]
    pas = [t * R["hauteur_ligne"] * R["interligne"] for t in tailles]
    total = sum(pas)
    el = R["elevation"] + total / 2
    for i, (txt, t) in enumerate(zip(lignes, tailles)):
        el -= pas[i] / 2
        if txt.strip():
            cu = bpy.data.curves.new(f"L{i}", "FONT")
            cu.body = txt
            cu.align_x, cu.align_y = "CENTER", "CENTER"
            ob = bpy.data.objects.new(f"L{i}", cu)
            coll.objects.link(ob)
            cu.materials.append(mat)
            bpy.context.view_layer.update()
            k = 2 * dist * math.tan(math.radians(t * R["hauteur_ligne"] / 2)) / 0.75     # 0,75: hauteur d'une capitale pour size 1
            ob.scale = (k, k, k)
            pos = _dir(cap, el) * dist
            ob.location = pos
            ob.rotation_euler = (-pos).to_track_quat("Z", "Y").to_euler()
        el -= pas[i] / 2
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    coll.objects.link(cam)
    sc.camera = cam
    cd = cam.data
    cd.type = "PANO"
    cd.clip_start, cd.clip_end = 0.1, 1000
    try:
        cd.panorama_type = "EQUIRECTANGULAR"
    except Exception:
        cd.cycles.panorama_type = "EQUIRECTANGULAR"
    if fmt == "bande":
        cam.rotation_euler = (math.pi / 2, 0, -math.radians(170.0))
        cd.longitude_min, cd.longitude_max = -math.radians(65), math.radians(65)
        cd.latitude_min, cd.latitude_max = math.radians(-30), math.radians(35)
        res = (2560, 1280)
    else:
        cam.rotation_euler = (math.pi / 2, 0, -math.radians(200.0))
        res = (3840, 1920)
    r = sc.render
    r.engine = "CYCLES"
    sc.cycles.samples = 16
    sc.cycles.use_denoising = False
    r.resolution_x, r.resolution_y = res
    r.resolution_percentage = 100
    sc.view_settings.view_transform = "Standard"
    os.makedirs(out, exist_ok=True)
    r.image_settings.file_format = "PNG"
    r.filepath = os.path.join(out, f"outro_{fmt}.png")
    bpy.ops.render.render(write_still=True)
    log("écrit", r.filepath)


main()
