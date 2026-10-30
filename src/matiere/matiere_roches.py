"""
matiere_roches.py : matière ALEA, version A (roches instanciées), chargée par la scène avec  --matiere matiere_roches

Idée : à 0,5 km, une particule de 4 m couvre 4 à 5 pixels. Une sphère lisse y ressemble à une perle. On remplace chaque
point par une ROCHE irrégulière (quelques variantes de polyèdres déformés, 80 faces), avec rotation et proportions
aléatoires par particule, un relief procédural (bump) qui tourne avec la roche, et une couleur qui dépend de l'individu
et de la vitesse (la matière rapide se couvre de poussière claire). Coût de reconstruction par image: identique à la
matière par défaut (un point par particule, on ne touche qu'aux positions et à la vitesse).

Interface (voir docs/archive/HANDOVER_ALEA.md, ne pas changer sans prévenir ENV):
    build(scene, seq, coll, cfg, log, helpers) -> objet Blender principal
    update(scene, t, seq)

Réglages: valeurs par défaut dans REGLAGES, remplaçables par un fichier src/matiere/reglages_matiere.json (facultatif,
mêmes clés), pour essayer sans modifier le code. Pas de dépendance autre que bpy et numpy.
"""
import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # le module est chargé par chemin: retrouver ses voisins
import interpolation  # noqa: E402
import surface  # noqa: E402     (peau continue à partir des points, voir surface.py)
import poussiere  # noqa: E402   (panache de poussière, voir poussiere.py)
import depot  # noqa: E402       (peau continue sous les roches, voir depot.py)

REGLAGES = dict(
    n_variantes=4,           # nombre de formes de roche
    subdiv=2,                # bmesh: 1 = 20 faces par roche, 2 = 80, 3 = 320 (plus lisse, plus lourd)
    rayon_facteur=1.0,       # multiplie le rayon de base (cfg["radius"] ou 0.6 x espacement des particules)
    echelle_min=(0.70, 0.70, 0.55),   # proportions aléatoires par axe (avant le rayon de base)
    echelle_max=(1.30, 1.30, 1.05),
    deformation=0.30,        # irrégularité des roches (0 = sphère)
    aplatissement=0.35,      # jusqu'à quel point certaines variantes sont aplaties
    bump_force=0.9,
    bump_echelle=3.5,        # grosses facettes (par rayon de roche)
    bump_fin_echelle=14.0,   # grain fin
    couleur_sombre=(0.085, 0.075, 0.068),   # roche, tirage aléatoire entre sombre et clair
    couleur_claire=(0.30, 0.275, 0.25),
    couleur_poussiere=(0.46, 0.44, 0.41),   # dépôt clair sur la matière rapide
    poussiere_vitesse=45.0,  # vitesse (m/s) à laquelle la matière est couverte à poussiere_max
    poussiere_max=0.45,
    rugosite=0.9,
    interpolation="hermite",   # "hermite" (src/matiere/interpolation.py) ou "scene" (Sequence.state, pour comparer)
    graine=7,
    # ---- RENDU de la matière (recommandation de Johan, 20 oct.: les points MPM sont des traceurs, blocs réels de 1 à 2 m)
    rendu="roches",          # "roches": une roche de 3 à 5 m par point (version A) | "surface": peau continue (src/matiere/surface.py)
                             # | "mixte": peau continue + petits blocs portés par les traceurs proches de la peau
    surface_voxel=2.0,       # m, maille de la grille de distance. Mesuré à t = 43 s: 1,5 m -> 1,9 M faces, 2 m -> 0,95 M (0,68 M avec adaptivité 0,3)
    surface_rayon_facteur=1.5,    # rayon des sphères autour des points, en espacements médians (nn_median, ~3,6 m). 1,25: peau trouée
    surface_isoles=4,        # un point avec moins de N voisins (colonnes de 2 rayons) ne gonfle pas la peau (grains projetés)
    surface_lissage=3,       # passes de lissage de la distance (0 = boules visibles)
    surface_lissage_largeur=2,    # largeur du lissage en voxels
    surface_retrait=1.0,     # m, resserre la peau après le lissage (compense le gonflement des sphères). Mesuré: sans retrait, sommets à
                             # 4,3 m (médiane) du traceur le plus proche; 2 m de retrait -> 3,4 m
    surface_adaptivite=0.2,  # 0..1: simplifie le maillage dans les zones planes (moins de mémoire graphique, un peu de détail perdu)
    texture_suit_matiere=True,    # la texture avance avec la matière (position de départ des traceurs), sinon fixe dans l'espace
    texture_flou=2,          # passes de flou de cette position sur la peau (adoucit les coutures entre traceurs)
    surface_couleur_sombre=(0.055, 0.050, 0.046),   # débris humides, sombres (vidéos de l'événement)
    surface_couleur_claire=(0.17, 0.155, 0.14),
    surface_poussiere_max=0.25,   # dépôt clair sur la peau rapide (les roches: poussiere_max)
    taches_echelle=9.0,      # m, taille des taches sombres/claires de la roche
    glace_part=0.22,         # part de la surface en plaques de glace (le dépôt contenait environ un tiers de glace)
    glace_echelle=14.0,      # m, taille des plaques de glace
    couleur_glace=(0.50, 0.53, 0.55),   # glace sale, grisée par les débris
    glace_rugosite=0.45,
    relief_echelle=2.2,      # m, bosses de la peau (blocs noyés)
    relief_fin_echelle=0.5,  # m, grain fin
    relief_force=0.8,
    relief_distance=0.6,     # m, amplitude apparente du relief (bump)
    depot_avec_surface=False,     # garde la peau du dépôt (depot.py) en plus de la surface (inutile en principe)
    blocs_taille_min=0.4,    # m, plus petits blocs (diamètre) en mode "mixte"
    blocs_taille_max=2.0,    # m, plus gros blocs (Johan: rarement plus de 1 à 2 m dans le dépôt)
    blocs_profondeur=1.5,    # m: seuls les traceurs à moins de cette profondeur sous la peau portent un bloc (les autres sont cachés)
    blocs_part=0.6,          # part de ces traceurs qui portent un bloc
)

STATE = dict(mesh=None, last_t=None, seq=None, to_blender=None, interp="hermite")


def _reglages(cfg=None):
    """REGLAGES, puis l'ancien fichier src/matiere/reglages_matiere.json s'il existe, puis la section "matiere" des jeux de
    réglages (reglages/<nom>.json, --reglages / --set, voir src/reglages.py)."""
    r = dict(REGLAGES)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reglages_matiere.json")
    if os.path.exists(p):
        try:
            r.update(json.load(open(p, encoding="utf-8")))
        except Exception as e:  # un réglage cassé ne doit pas empêcher le rendu
            print("[matiere_roches] reglages_matiere.json ignoré:", e)
    regl = (cfg or {}).get("_regl") or {}
    inconnues = [k for k in regl.get("matiere", {}) if k not in REGLAGES and not k.endswith("_reglages")]
    if inconnues:
        raise SystemExit(f"Réglages matière inconnus: {inconnues} (voir REGLAGES dans src/matiere/matiere_roches.py)")
    for k, v in regl.get("matiere", {}).items():
        r[k] = tuple(v) if isinstance(v, list) and isinstance(REGLAGES.get(k), tuple) else v
    if r["rendu"] not in ("roches", "surface", "mixte"):
        raise SystemExit(f"matiere.rendu = {r['rendu']!r}: attendu \"roches\", \"surface\" ou \"mixte\"")
    r["depot_reglages"] = dict(r.get("depot_reglages") or {}, **regl.get("depot", {}))
    r["poussiere_reglages"] = dict(r.get("poussiere_reglages") or {}, **regl.get("poussiere", {}))
    return r


# ---------------------------------------------------------------- formes de roche
def _variante(nom, r, i):
    """Polyèdre irrégulier de rayon ~1: icosphère déformée par un bruit par sommet, plus ou moins aplatie."""
    rng = np.random.default_rng(r["graine"] * 1000 + i)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=int(r["subdiv"]), radius=1.0)
    ap = 1.0 - r["aplatissement"] * (i % 3) / 2.0           # 1, 0.82, 0.65 de hauteur selon la variante
    axes = np.array([1.0, rng.uniform(0.8, 1.0), ap])
    for v in bm.verts:
        d = 1.0 + r["deformation"] * rng.uniform(-1.0, 1.0)
        v.co.x *= d * axes[0]
        v.co.y *= d * axes[1]
        v.co.z *= d * axes[2]
    bm.normal_update()
    me = bpy.data.meshes.new(nom)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False                                   # facettes: lisible à quelques pixels
    return me


# ---------------------------------------------------------------- matériau
def _material(helpers, cfg, r):
    mat = bpy.data.materials.new("MatiereRoches")
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = r["rugosite"]

    # aléatoire par instance (stable d'une image à l'autre)
    oi = nodes.new("ShaderNodeObjectInfo")
    # vitesse portée par chaque point -> instance (attribut "speed")
    sp = nodes.new("ShaderNodeAttribute")
    sp.attribute_type = "INSTANCER"
    sp.attribute_name = "speed"

    # 1. couleur de roche : tirage aléatoire entre sombre et clair
    mix_roche = nodes.new("ShaderNodeMix")
    mix_roche.data_type = "RGBA"
    mix_roche.inputs[6].default_value = (*r["couleur_sombre"], 1)
    mix_roche.inputs[7].default_value = (*r["couleur_claire"], 1)
    links.new(oi.outputs["Random"], mix_roche.inputs[0])

    # 2. poussière selon la vitesse
    dust = nodes.new("ShaderNodeMapRange")
    dust.inputs["From Min"].default_value = 3.0
    dust.inputs["From Max"].default_value = float(r["poussiere_vitesse"])
    dust.inputs["To Min"].default_value = 0.0
    dust.inputs["To Max"].default_value = float(r["poussiere_max"])
    dust.clamp = True
    links.new(sp.outputs["Fac"], dust.inputs["Value"])
    mix_dust = nodes.new("ShaderNodeMix")
    mix_dust.data_type = "RGBA"
    mix_dust.inputs[7].default_value = (*r["couleur_poussiere"], 1)
    links.new(dust.outputs["Result"], mix_dust.inputs[0])
    links.new(mix_roche.outputs[2], mix_dust.inputs[6])
    links.new(mix_dust.outputs[2], bsdf.inputs["Base Color"])

    # 3. relief: deux bruits en coordonnées OBJET (la roche emporte son relief), décalés par instance
    tc = nodes.new("ShaderNodeTexCoord")
    off = nodes.new("ShaderNodeCombineXYZ")
    for k, f in enumerate((37.0, 91.0, 13.0)):
        m = nodes.new("ShaderNodeMath")
        m.operation = "MULTIPLY"
        m.inputs[1].default_value = f
        links.new(oi.outputs["Random"], m.inputs[0])
        links.new(m.outputs[0], off.inputs[k])
    add = nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    links.new(tc.outputs["Object"], add.inputs[0])
    links.new(off.outputs["Vector"], add.inputs[1])

    n1 = nodes.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = float(r["bump_echelle"])
    n1.inputs["Detail"].default_value = 3.0
    n1.inputs["Roughness"].default_value = 0.6
    n2 = nodes.new("ShaderNodeTexNoise")
    n2.inputs["Scale"].default_value = float(r["bump_fin_echelle"])
    n2.inputs["Detail"].default_value = 2.0
    links.new(add.outputs["Vector"], n1.inputs["Vector"])
    links.new(add.outputs["Vector"], n2.inputs["Vector"])
    hmix = nodes.new("ShaderNodeMath")
    hmix.operation = "MULTIPLY_ADD"        # n1 * 0.7 + n2 * 0.3 via deux étapes
    hmix.inputs[1].default_value = 0.7
    links.new(n1.outputs["Fac"], hmix.inputs[0])
    n2s = nodes.new("ShaderNodeMath")
    n2s.operation = "MULTIPLY"
    n2s.inputs[1].default_value = 0.3
    links.new(n2.outputs["Fac"], n2s.inputs[0])
    links.new(n2s.outputs[0], hmix.inputs[2])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = float(r["bump_force"])
    bump.inputs["Distance"].default_value = 0.35
    links.new(hmix.outputs[0], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    helpers["apply_height_fog"](mat)       # brume avec la hauteur, comme le reste de la scène
    return mat


# ---------------------------------------------------------------- arbre de géométrie
def _socket(node, name, kind=None):
    """Entrée active d'un noeud par nom (les noeuds à plusieurs types ont des noms en double)."""
    for s in node.inputs:
        if s.name == name and s.enabled and (kind is None or s.type == kind):
            return s
    raise KeyError(f"{node.bl_idname}: pas d'entrée active '{name}' ({kind})")


def _arbre(modeles, r, rayon):
    ng = bpy.data.node_groups.new("MatiereRoches", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N = ng.nodes
    nin, nout = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    m2p = N.new("GeometryNodeMeshToPoints")
    m2p.mode = "VERTICES"

    ci = N.new("GeometryNodeCollectionInfo")
    ci.transform_space = "RELATIVE"
    ci.inputs["Collection"].default_value = modeles
    ci.inputs["Separate Children"].default_value = True
    ci.inputs["Reset Children"].default_value = True

    iop = N.new("GeometryNodeInstanceOnPoints")
    iop.inputs["Pick Instance"].default_value = True

    # variante tirée au hasard par particule (graine fixe, identifiant = indice de point: stable d'une image à l'autre)
    ridx = N.new("FunctionNodeRandomValue")
    ridx.data_type = "INT"
    _socket(ridx, "Min", "INT").default_value = 0
    _socket(ridx, "Max", "INT").default_value = int(r["n_variantes"]) - 1
    _socket(ridx, "Seed", "INT").default_value = int(r["graine"])

    rrot = N.new("FunctionNodeRandomValue")
    rrot.data_type = "FLOAT_VECTOR"
    _socket(rrot, "Min", "VECTOR").default_value = (0.0, 0.0, 0.0)
    _socket(rrot, "Max", "VECTOR").default_value = (2 * math.pi,) * 3
    _socket(rrot, "Seed", "INT").default_value = int(r["graine"]) + 1

    rsc = N.new("FunctionNodeRandomValue")
    rsc.data_type = "FLOAT_VECTOR"
    _socket(rsc, "Min", "VECTOR").default_value = tuple(float(x) * rayon for x in r["echelle_min"])
    _socket(rsc, "Max", "VECTOR").default_value = tuple(float(x) * rayon for x in r["echelle_max"])
    _socket(rsc, "Seed", "INT").default_value = int(r["graine"]) + 2

    L = ng.links
    L.new(nin.outputs["Geometry"], m2p.inputs["Mesh"])
    L.new(m2p.outputs["Points"], iop.inputs["Points"])
    L.new(ci.outputs["Instances"], iop.inputs["Instance"])
    L.new(ridx.outputs[_index_sortie(ridx, "INT")], iop.inputs["Instance Index"])
    L.new(rrot.outputs[_index_sortie(rrot, "VECTOR")], iop.inputs["Rotation"])
    L.new(rsc.outputs[_index_sortie(rsc, "VECTOR")], iop.inputs["Scale"])
    L.new(iop.outputs["Instances"], nout.inputs["Geometry"])
    return ng


def _index_sortie(node, kind):
    for i, s in enumerate(node.outputs):
        if s.enabled and s.type == kind:
            return i
    raise KeyError(f"{node.bl_idname}: pas de sortie {kind}")


# ---------------------------------------------------------------- interface scène
def build(scene, seq, coll, cfg, log, helpers):
    r = _reglages(cfg)
    n = seq.count
    st = seq.meta.get("stats", {})
    espacement = st.get("nn_median") or 3.0
    rayon = (cfg.get("radius") or 0.6 * espacement) * float(r["rayon_facteur"])
    mode = r["rendu"]

    mat = _material(helpers, cfg, r)
    modeles = bpy.data.collections.new("MatiereRoches_modeles")     # non liée à la scène: sert seulement de réserve
    for i in range(int(r["n_variantes"])):
        me = _variante(f"roche_{i}", r, i)
        me.materials.append(mat)
        modeles.objects.link(bpy.data.objects.new(f"roche_{i}", me))

    mesh = bpy.data.meshes.new("matiere")
    mesh.vertices.add(n)
    mesh.attributes.new("speed", "FLOAT", "POINT")
    obj = bpy.data.objects.new("Matiere", mesh)
    coll.objects.link(obj)
    rs = 0.0
    if mode == "roches":
        obj.modifiers.new("Roches", "NODES").node_group = _arbre(modeles, r, rayon)
    else:
        rs = float(r["surface_rayon_facteur"]) * espacement
        mesh.attributes.new("rs", "FLOAT", "POINT")
        mesh.attributes.new("p0", "FLOAT_VECTOR", "POINT")
        p0 = helpers["to_blender"](np.asarray(seq.arr(0)[:, :3], np.float32))     # position de départ: la texture suit la matière
        mesh.attributes["p0"].data.foreach_set("vector", p0.ravel())
        mat_s = surface.materiau(helpers, r)
        blocs = modeles if mode == "mixte" else None
        rb = (0.5 * float(r["blocs_taille_min"]), 0.5 * float(r["blocs_taille_max"]))    # variantes de rayon ~1: échelle = rayon
        obj.modifiers.new("Surface", "NODES").node_group = surface.arbre(r, mat_s, blocs, rb, int(r["graine"]), int(r["n_variantes"]))
        log(f"matière ({mode}): peau continue, grille {r['surface_voxel']:g} m, sphères de {rs:.2f} m autour des traceurs"
            + (f", blocs de {r['blocs_taille_min']:g} à {r['blocs_taille_max']:g} m" if blocs else ""))

    STATE.update(mesh=mesh, last_t=None, seq=seq, to_blender=helpers["to_blender"], interp=r["interpolation"], poussiere=False, depot=False,
                 mode=mode, rs=rs, r=r)
    if not cfg.get("no_depot") and (mode == "roches" or r["depot_avec_surface"]):
        try:
            STATE["depot"] = depot.construire(coll, mat, rayon, log, r.get("depot_reglages"))
        except Exception as e:  # même règle que la poussière: un ajout qui échoue ne bloque pas le rendu
            log(f"!! dépôt NON construit ({e!r}): roches seules")
    try:
        STATE["poussiere"] = poussiere.construire(scene, coll, seq, helpers["to_blender"], cfg, log, r.get("poussiere_reglages"))
    except Exception as e:      # le panache est un ajout: s'il échoue, la matière seule est rendue (et on le dit clairement)
        log(f"!! poussière NON construite ({e!r}): rendu sans panache")
    update(scene, helpers["frame_to_time"](scene, scene.frame_start), seq)
    if mode == "roches":
            log(f"matière (roches): {n:,} particules, {int(r['n_variantes'])} variantes de {len(bpy.data.meshes['roche_0'].polygons)} faces, rayon de base {rayon:.2f} m")
    return obj


def update(scene, t, seq):
    mesh = STATE["mesh"]
    if mesh is None or STATE["last_t"] == t:
        return
    P, V = interpolation.etat(seq, t) if STATE["interp"] == "hermite" else seq.state(t)
    Pb = STATE["to_blender"](P)
    mesh.vertices.foreach_set("co", Pb.ravel())
    vit = np.linalg.norm(V, axis=1).astype(np.float32)
    mesh.attributes["speed"].data.foreach_set("value", vit)
    if STATE.get("mode", "roches") != "roches":
        r = STATE["r"]
        rs = surface.rayons(Pb, STATE["rs"], 2.0 * STATE["rs"], int(r["surface_isoles"]))
        mesh.attributes["rs"].data.foreach_set("value", rs)
    mesh.update()
    if STATE.get("depot"):
        try:
            depot.maj(Pb, vit)
        except Exception as e:
            log_ = print
            log_(f"[depot] ERREUR ({e!r}), peau coupée")
            STATE["depot"] = False
    if STATE.get("poussiere"):
        poussiere.maj(t)
    STATE["last_t"] = t
