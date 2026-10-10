"""
rendu_matiere.py : GABARIT du module de matière (côté "aléa"), chargé par la scène avec  --matiere rendu_matiere

La scène (src/scene/blatten_blender.py, côté "environnement") ne connaît de la matière que ces deux fonctions.
Tout ce qui est propre à l'aléa (représentation, matériaux, poussière, interpolation, dépôt) vit ICI et dans les
autres fichiers de src/matiere/, ce qui évite de modifier la scène et de se marcher dessus.

Interface (ne pas changer sans prévenir l'autre conversation, voir docs/HANDOVER_ALEA.md) :

    build(scene, seq, coll, cfg, log, helpers) -> objet Blender principal de la matière, ou None
        scene    scène Blender (résolution, fps, image de début/fin déjà réglés)
        seq      Sequence de particules: seq.count (nombre de particules), seq.meta (meta.json: origine, stats, vmax),
                 seq.state(t) -> (positions N x 3, vitesses N x 3) en repère SIMULATION (Y vertical), temps t en s,
                 interpolées entre deux fichiers (voir Sequence.state dans la scène; à remplacer si besoin)
        coll     collection Blender "Blatten" où ranger les objets créés
        cfg      dictionnaire des réglages de la scène (CFG): cfg["radius"], cfg["color"], cfg["fog"], cfg["look"], ...
        log      fonction d'affichage ("[blatten] ...")
        helpers  dict: to_blender (repère simulation -> Blender), frame_to_time (scène, image -> s), apply_height_fog (mat),
                 new_collection, build_default (construit la matière par défaut, pour comparer)

    update(scene, t, seq)
        Appelée à CHAQUE changement d'image (rendu, aperçu, bench). t = temps de simulation en secondes.
        Doit être idempotente (même t -> même état) et rapide: le coût de reconstruction compte dans le temps de rendu.

Ce gabarit reproduit la matière par défaut (une sphère par particule, couleur aléatoire sombre) pour servir de point de départ.
Test:  python blatten.py test360 --matiere rendu_matiere
"""
import bpy
import numpy as np

STATE = dict(mesh=None, last_t=None, seq=None, to_blender=None)


def build(scene, seq, coll, cfg, log, helpers):
    n = seq.count
    mesh = bpy.data.meshes.new("matiere")
    mesh.vertices.add(n)
    mesh.attributes.new("speed", "FLOAT", "POINT")
    obj = bpy.data.objects.new("Matiere", mesh)
    coll.objects.link(obj)
    STATE.update(mesh=mesh, last_t=None, seq=seq, to_blender=helpers["to_blender"])
    update(scene, helpers["frame_to_time"](scene, scene.frame_start), seq)

    st = seq.meta.get("stats", {})
    radius = cfg["radius"] or 0.6 * (st.get("nn_median") or 3.0)
    log(f"matière (gabarit): {n:,} particules, rayon {radius:.2f} m")

    # points -> sphères rendues par Cycles (Geometry Nodes), un matériau
    ng = bpy.data.node_groups.new("MatierePoints", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nin, nout = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")
    m2p = ng.nodes.new("GeometryNodeMeshToPoints")
    m2p.mode = "VERTICES"
    m2p.inputs["Radius"].default_value = radius
    setmat = ng.nodes.new("GeometryNodeSetMaterial")
    setmat.inputs["Material"].default_value = _material(helpers, cfg)
    ng.links.new(nin.outputs["Geometry"], m2p.inputs["Mesh"])
    ng.links.new(m2p.outputs["Points"], setmat.inputs["Geometry"])
    ng.links.new(setmat.outputs["Geometry"], nout.inputs["Geometry"])
    obj.modifiers.new("Points", "NODES").node_group = ng
    return obj


def _material(helpers, cfg):
    mat = bpy.data.materials.new("Matiere")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.85
    pi = nt.nodes.new("ShaderNodeParticleInfo")          # valeur aléatoire par point
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.0, (0.14, 0.125, 0.11, 1)
    cr.elements[1].position, cr.elements[1].color = 1.0, (0.30, 0.275, 0.25, 1)
    nt.links.new(pi.outputs["Random"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    helpers["apply_height_fog"](mat)                      # brume avec la hauteur, comme le reste de la scène
    return mat


def update(scene, t, seq):
    mesh = STATE["mesh"]
    if mesh is None or STATE["last_t"] == t:
        return
    P, V = seq.state(t)
    mesh.vertices.foreach_set("co", STATE["to_blender"](P).ravel())
    mesh.attributes["speed"].data.foreach_set("value", np.linalg.norm(V, axis=1).astype(np.float32))
    mesh.update()
    STATE["last_t"] = t
