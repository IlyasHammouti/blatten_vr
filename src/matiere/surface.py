"""
surface.py : SURFACE CONTINUE de la matière à partir des points MPM (recommandation de Johan Gaume, 20 octobre 2026).

Pourquoi : les points de la simulation MPM sont des TRACEURS du mouvement d'un milieu continu, pas des blocs. Les dessiner comme
des roches de 3 à 5 m (version A, matiere_roches) donne un lit de gros graviers, alors que les blocs du dépôt réel dépassaient
rarement 1 à 2 m. Ici on enveloppe les points d'une surface (l'équivalent Blender du noeud « Particle Fluid Surface » de
Houdini), puis on pose éventuellement de PETITS blocs (0,4 à 2 m) sur la peau.

Méthode (noeuds de géométrie de Blender 5.2, recalculés à chaque image) :
  1. chaque point reçoit un rayon `rs` (numpy) selon la densité locale EN 3D: `surface_rayon_facteur` x espacement médian dans la masse,
     plus petit dans les zones éparses (avant, bords), 0 pour un point isolé (moins de `surface_isoles` voisins): un grain projeté
     ne fait ni boule ni boudin; en mode mixte, il porte un bloc;
  2. Points to SDF Grid (grille de distance signée, maille `surface_voxel` m): union des sphères;
  3. SDF Grid Mean (`surface_lissage_largeur` voxels, `surface_lissage` passes): les sphères fondent en une masse;
  4. SDF Grid Offset (`surface_retrait` m): on resserre la peau pour compenser le gonflement des sphères;
  5. Grid to Mesh: maillage de la surface (`surface_adaptivite` > 0 le simplifie dans les zones planes);
  6. TEXTURE QUI SUIT LA MATIÈRE: chaque sommet prend la position de départ (`p0`) et la vitesse du point le plus proche, floutées
     sur la peau (`texture_flou` passes). Le motif roche/glace avance donc avec l'écoulement au lieu de glisser dessus;
  7. mode "mixte": les points proches de la peau (moins de `blocs_profondeur` m dessous) portent un petit bloc (taille
     `blocs_taille_min` à `blocs_taille_max` m): identité stable d'une image à l'autre, il voyage avec son traceur.
Ce n'est pas de la physique: c'est la surface visible de la masse simulée.
"""
import math

import bpy
import numpy as np

ETAT = dict(mesh=None, r=None, rs=1.0, log=print)


# ---------------------------------------------------------------- outils noeuds
def _entree(node, nom, kind=None):
    for s in node.inputs:
        if s.name == nom and s.enabled and (kind is None or s.type == kind):
            return s
    raise KeyError(f"{node.bl_idname}: pas d'entrée active '{nom}' ({kind})")


def _sortie(node, kind=None, nom=None):
    for s in node.outputs:
        if s.enabled and (kind is None or s.type == kind) and (nom is None or s.name == nom):
            return s
    raise KeyError(f"{node.bl_idname}: pas de sortie {nom or ''} {kind or ''}")


def _attr(N, nom, kind="FLOAT"):
    n = N.new("GeometryNodeInputNamedAttribute")
    n.data_type = kind
    n.inputs["Name"].default_value = nom
    return n


# ---------------------------------------------------------------- matériau de la peau
def materiau(helpers, r):
    """Roche sombre et claire en taches, plaques de glace sale, poussière claire sur la matière rapide, relief fin (bump)."""
    mat = bpy.data.materials.new("MatiereSurface")
    mat.use_nodes = True
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    bsdf = N["Principled BSDF"]

    if r["texture_suit_matiere"]:
        co = N.new("ShaderNodeAttribute")
        co.attribute_type = "GEOMETRY"
        co.attribute_name = "p0"
        vec = co.outputs["Vector"]
    else:
        geo = N.new("ShaderNodeNewGeometry")
        vec = geo.outputs["Position"]
    sp = N.new("ShaderNodeAttribute")
    sp.attribute_type = "GEOMETRY"
    sp.attribute_name = "speed"

    def bruit(echelle_m, detail=3.0, rugo=0.6):
        n = N.new("ShaderNodeTexNoise")
        n.noise_dimensions = "3D"
        n.inputs["Scale"].default_value = 1.0 / max(float(echelle_m), 1e-3)
        n.inputs["Detail"].default_value = detail
        n.inputs["Roughness"].default_value = rugo
        L.new(vec, n.inputs["Vector"])
        return n

    # 1. roche: taches sombres/claires
    t1 = bruit(r["taches_echelle"], 4.0, 0.65)
    rampe = N.new("ShaderNodeMapRange")
    rampe.clamp = True
    rampe.inputs["From Min"].default_value = 0.35
    rampe.inputs["From Max"].default_value = 0.65
    L.new(t1.outputs["Fac"], rampe.inputs["Value"])
    roche = N.new("ShaderNodeMix")
    roche.data_type = "RGBA"
    roche.inputs[6].default_value = (*r["surface_couleur_sombre"], 1)
    roche.inputs[7].default_value = (*r["surface_couleur_claire"], 1)
    L.new(rampe.outputs["Result"], roche.inputs[0])

    # 2. glace: plaques (seuil sur un bruit plus large), bord net
    t2 = bruit(r["glace_echelle"], 3.0, 0.55)
    seuil = N.new("ShaderNodeMapRange")
    seuil.clamp = True
    s0 = 1.0 - float(r["glace_part"])                       # part approximative de surface couverte de glace
    seuil.inputs["From Min"].default_value = s0 - 0.03
    seuil.inputs["From Max"].default_value = s0 + 0.03
    L.new(t2.outputs["Fac"], seuil.inputs["Value"])
    glace = N.new("ShaderNodeMix")
    glace.data_type = "RGBA"
    glace.inputs[7].default_value = (*r["couleur_glace"], 1)
    L.new(seuil.outputs["Result"], glace.inputs[0])
    L.new(roche.outputs[2], glace.inputs[6])

    # 3. poussière claire sur la matière rapide (même règle que les roches)
    dust = N.new("ShaderNodeMapRange")
    dust.clamp = True
    dust.inputs["From Min"].default_value = 3.0
    dust.inputs["From Max"].default_value = float(r["poussiere_vitesse"])
    dust.inputs["To Min"].default_value = 0.0
    dust.inputs["To Max"].default_value = float(r["surface_poussiere_max"])
    L.new(sp.outputs["Fac"], dust.inputs["Value"])
    mix_d = N.new("ShaderNodeMix")
    mix_d.data_type = "RGBA"
    mix_d.inputs[7].default_value = (*r["couleur_poussiere"], 1)
    L.new(dust.outputs["Result"], mix_d.inputs[0])
    L.new(glace.outputs[2], mix_d.inputs[6])
    L.new(mix_d.outputs[2], bsdf.inputs["Base Color"])

    # 4. rugosité: glace plus brillante
    rug = N.new("ShaderNodeMapRange")
    rug.inputs["To Min"].default_value = float(r["rugosite"])
    rug.inputs["To Max"].default_value = float(r["glace_rugosite"])
    L.new(seuil.outputs["Result"], rug.inputs["Value"])
    L.new(rug.outputs["Result"], bsdf.inputs["Roughness"])

    # 5. relief: blocs (grosse échelle) + grain
    b1 = bruit(r["relief_echelle"], 4.0, 0.7)
    b2 = bruit(r["relief_fin_echelle"], 2.0, 0.5)
    h = N.new("ShaderNodeMath")
    h.operation = "MULTIPLY_ADD"
    h.inputs[1].default_value = 0.75
    m2 = N.new("ShaderNodeMath")
    m2.operation = "MULTIPLY"
    m2.inputs[1].default_value = 0.25
    L.new(b2.outputs["Fac"], m2.inputs[0])
    L.new(b1.outputs["Fac"], h.inputs[0])
    L.new(m2.outputs[0], h.inputs[2])
    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = float(r["relief_force"])
    bump.inputs["Distance"].default_value = float(r["relief_distance"])
    L.new(h.outputs[0], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    helpers["apply_height_fog"](mat)
    return mat


# ---------------------------------------------------------------- arbre de géométrie
def arbre(r, mat, modeles=None, rayon_blocs=(0.2, 1.0), graine=7, n_variantes=4):
    """Points (attributs rs, p0, speed) -> peau maillée (+ petits blocs si modeles)."""
    ng = bpy.data.node_groups.new("MatiereSurface", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    nin, nout = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    m2p = N.new("GeometryNodeMeshToPoints")
    m2p.mode = "VERTICES"
    L.new(nin.outputs["Geometry"], m2p.inputs["Mesh"])
    pts = m2p.outputs["Points"]

    sdf = N.new("GeometryNodePointsToSDFGrid")
    sdf.inputs["Voxel Size"].default_value = float(r["surface_voxel"])
    L.new(pts, sdf.inputs["Points"])
    L.new(_attr(N, "rs").outputs["Attribute"], sdf.inputs["Radius"])
    g = sdf.outputs[0]
    if int(r["surface_lissage"]) > 0:
        mean = N.new("GeometryNodeSDFGridMean")
        mean.inputs["Width"].default_value = int(r["surface_lissage_largeur"])
        mean.inputs["Iterations"].default_value = int(r["surface_lissage"])
        L.new(g, mean.inputs["Grid"])
        g = mean.outputs[0]
    if abs(float(r["surface_retrait"])) > 1e-6:
        off = N.new("GeometryNodeSDFGridOffset")
        off.inputs["Distance"].default_value = -float(r["surface_retrait"])    # mesuré: Distance > 0 GONFLE la peau, d'où le signe
        L.new(g, off.inputs["Grid"])
        g = off.outputs[0]
    g2m = N.new("GeometryNodeGridToMesh")
    g2m.inputs["Threshold"].default_value = 0.0
    g2m.inputs["Adaptivity"].default_value = float(r["surface_adaptivite"])
    L.new(g, g2m.inputs["Grid"])
    peau = g2m.outputs["Mesh"]

    # texture qui suit la matière: position de départ et vitesse du point le plus proche, floutées sur la peau
    near = N.new("GeometryNodeSampleNearest")
    near.domain = "POINT"
    L.new(pts, near.inputs["Geometry"])
    for nom, kind, socket_type in (("p0", "FLOAT_VECTOR", "VECTOR"), ("speed", "FLOAT", "VALUE")):
        si = N.new("GeometryNodeSampleIndex")
        si.data_type = kind
        si.domain = "POINT"
        L.new(pts, si.inputs["Geometry"])
        L.new(_attr(N, nom, kind).outputs["Attribute"], _entree(si, "Value", socket_type))
        L.new(near.outputs["Index"], si.inputs["Index"])
        val = _sortie(si, socket_type)
        if int(r["texture_flou"]) > 0:
            bl = N.new("GeometryNodeBlurAttribute")
            bl.data_type = kind
            _entree(bl, "Iterations").default_value = int(r["texture_flou"])
            L.new(val, _entree(bl, "Value", socket_type))
            val = _sortie(bl, socket_type)
        st = N.new("GeometryNodeStoreNamedAttribute")
        st.data_type = kind
        st.domain = "POINT"
        st.inputs["Name"].default_value = nom
        L.new(peau, st.inputs["Geometry"])
        L.new(val, _entree(st, "Value", socket_type))
        peau = st.outputs["Geometry"]

    lisse = N.new("GeometryNodeSetShadeSmooth")
    _entree(lisse, "Shade Smooth").default_value = True
    L.new(peau, lisse.inputs["Mesh"])
    sm = N.new("GeometryNodeSetMaterial")
    sm.inputs["Material"].default_value = mat
    L.new(lisse.outputs["Mesh"], sm.inputs["Geometry"])
    sortie = sm.outputs["Geometry"]

    if modeles is not None:
        # petits blocs sur les traceurs proches de la peau (distance signée > -profondeur), plus les grains isolés (rs = 0)
        sg = N.new("GeometryNodeSampleGrid")
        sg.data_type = "FLOAT"
        L.new(g, sg.inputs["Grid"])
        pos = N.new("GeometryNodeInputPosition")
        L.new(pos.outputs[0], sg.inputs["Position"])
        cmp_ = N.new("FunctionNodeCompare")
        cmp_.data_type = "FLOAT"
        cmp_.operation = "GREATER_THAN"
        _entree(cmp_, "B", "VALUE").default_value = -float(r["blocs_profondeur"])
        L.new(_sortie(sg, "VALUE"), _entree(cmp_, "A", "VALUE"))
        tri = N.new("FunctionNodeRandomValue")       # densité de blocs: une part des traceurs seulement
        tri.data_type = "BOOLEAN"
        _entree(tri, "Probability").default_value = float(r["blocs_part"])
        _entree(tri, "Seed", "INT").default_value = int(graine) + 11
        et = N.new("FunctionNodeBooleanMath")
        et.operation = "AND"
        L.new(cmp_.outputs[0], et.inputs[0])
        L.new(_sortie(tri, "BOOLEAN"), et.inputs[1])
        iso = N.new("FunctionNodeCompare")                  # traceur isolé (rs = 0): toujours un bloc, la peau ne le montre pas
        iso.data_type = "FLOAT"
        iso.operation = "LESS_THAN"
        _entree(iso, "B", "VALUE").default_value = 0.01
        L.new(_attr(N, "rs").outputs["Attribute"], _entree(iso, "A", "VALUE"))
        ou = N.new("FunctionNodeBooleanMath")
        ou.operation = "OR"
        L.new(et.outputs[0], ou.inputs[0])
        L.new(iso.outputs[0], ou.inputs[1])
        et = ou

        ci = N.new("GeometryNodeCollectionInfo")
        ci.transform_space = "RELATIVE"
        ci.inputs["Collection"].default_value = modeles
        ci.inputs["Separate Children"].default_value = True
        ci.inputs["Reset Children"].default_value = True
        iop = N.new("GeometryNodeInstanceOnPoints")
        iop.inputs["Pick Instance"].default_value = True
        ridx = N.new("FunctionNodeRandomValue")
        ridx.data_type = "INT"
        _entree(ridx, "Min", "INT").default_value = 0
        _entree(ridx, "Max", "INT").default_value = int(n_variantes) - 1
        _entree(ridx, "Seed", "INT").default_value = int(graine)
        rrot = N.new("FunctionNodeRandomValue")
        rrot.data_type = "FLOAT_VECTOR"
        _entree(rrot, "Min", "VECTOR").default_value = (0.0, 0.0, 0.0)
        _entree(rrot, "Max", "VECTOR").default_value = (2 * math.pi,) * 3
        _entree(rrot, "Seed", "INT").default_value = int(graine) + 1
        rsc = N.new("FunctionNodeRandomValue")       # taille uniforme par bloc, puis proportions de la variante
        rsc.data_type = "FLOAT"
        _entree(rsc, "Min", "VALUE").default_value = float(rayon_blocs[0])
        _entree(rsc, "Max", "VALUE").default_value = float(rayon_blocs[1])
        _entree(rsc, "Seed", "INT").default_value = int(graine) + 2
        L.new(pts, iop.inputs["Points"])
        L.new(et.outputs[0], iop.inputs["Selection"])
        L.new(ci.outputs["Instances"], iop.inputs["Instance"])
        L.new(_sortie(ridx, "INT"), iop.inputs["Instance Index"])
        L.new(_sortie(rrot, "VECTOR"), iop.inputs["Rotation"])
        L.new(_sortie(rsc, "VALUE"), iop.inputs["Scale"])
        join = N.new("GeometryNodeJoinGeometry")
        L.new(iop.outputs["Instances"], join.inputs[0])
        L.new(sortie, join.inputs[0])
        sortie = join.outputs[0]

    L.new(sortie, nout.inputs["Geometry"])
    return ng


# ---------------------------------------------------------------- rayons par point (numpy, à chaque image)
def voisins3d(P, cellule):
    """Nombre de points dans les 3 x 3 x 3 cellules de `cellule` m autour de chaque point (0,3 s pour 234 000 points)."""
    q = np.floor((P - P.min(0)) / cellule).astype(np.int64) + 1
    m = q.max(0) + 2
    cle = (q[:, 0] * m[1] + q[:, 1]) * m[2] + q[:, 2]
    uk, cnt = np.unique(cle, return_counts=True)
    tot = np.zeros(len(P), np.int64)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                k2 = ((q[:, 0] + dx) * m[1] + (q[:, 1] + dy)) * m[2] + (q[:, 2] + dz)
                j = np.clip(np.searchsorted(uk, k2), 0, len(uk) - 1)
                tot += np.where(uk[j] == k2, cnt[j], 0)
    return tot


def rayons(P, rs, espacement, kmin, kref, rmin):
    """Rayon de la sphère autour de chaque traceur, selon la densité locale en 3D (cubes de 3 x 2 espacements de côté):
    0 si moins de kmin voisins (grain projeté: pas de peau, il porte un bloc en mode mixte), rs plein à partir de kref voisins,
    entre les deux rs x (part de kref)^(1/3), au moins rmin x rs. Mesuré à t = 43 s: médiane 101 voisins, 4 % des points sous 20.
    Sans cette règle, les traceurs épars de l'avant et des bords se soudent en boudins (rendu du 30 oct.)."""
    if len(P) == 0:
        return np.zeros(0, np.float32)
    c = voisins3d(P, 2.0 * espacement)
    f = np.clip(((c - kmin) / max(kref - kmin, 1)) ** (1.0 / 3.0), rmin, 1.0)
    out = (float(rs) * f).astype(np.float32)
    out[c < kmin] = 0.0
    return out
