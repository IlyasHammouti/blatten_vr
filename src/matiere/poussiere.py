"""
poussiere.py : panache de poussière de l'avalanche, ajouté à la matière (chargé par matiere_roches.py).

CE QUE C'EST (et ce que ce n'est pas)
  La simulation de Johan est un écoulement granulaire: elle ne contient ni poussière ni air. Les avalanches de roche
  produisent pourtant un nuage de fines (fragmentation, abrasion sur le lit, glace pulvérisée) qui voyage avec l'écoulement,
  s'étale, monte et se dépose lentement; c'est le même phénomène physique que l'aérosol d'une avalanche de neige poudreuse.
  Ici le nuage est un MODÈLE VISUEL cohérent avec cette physique, piloté par les particules de Johan, pas un résultat de
  simulation: son extension et sa densité sont des réglages (REGLAGES ci-dessous), à comparer avec les vidéos de l'événement.

MODÈLE (sans état: l'image au temps t se calcule seule, donc reprise et paquets d'images restent exacts)
  1. Sources: toutes les `pas` secondes simulées, on retient `sources` particules, tirées avec une probabilité proportionnelle
     au carré de leur vitesse (la fragmentation croît avec l'énergie cinétique). Calculé une fois, gardé dans le dossier cache.
  2. Chaque source émet une bouffée à l'instant t_j. A l'âge tau = t - t_j:
       position  = p_j + v_j * T (1 - exp(-tau/T))     la bouffée garde l'élan de la matière puis est freinée par l'air (T = frein)
                 + (0, 0, montée * Tm (1 - exp(-tau/Tm)))   elle monte (mélange turbulent, air entraîné)
                 + vent * tau
       rayon     = r0 + k tau^0,8, plafonné           l'entraînement d'air gonfle le nuage
       densité   = poids * (r0 / rayon)^dilution * exp(-tau/dépôt)    dilution par l'expansion, dépôt des grains
  3. Les bouffées deviennent des volumes (noeud Points to Volume, grille de `voxel` m; sa densité est une valeur unique, donc
     une classe de densité par objet, les classes s'additionnant) rendus par Cycles avec un matériau de
     diffusion (poussière claire, légèrement absorbante) dont la densité est creusée par du bruit 3D qui dérive (aspect de
     bouffées turbulentes plutôt que de sphères).
"""
import hashlib
import json
import os

import bpy
import numpy as np

REGLAGES = dict(
    poussiere=True,
    sources=900,             # bouffées émises à chaque instant d'émission
    pas=2,                   # secondes simulées entre deux émissions
    vitesse_ref=40.0,        # m/s: vitesse à laquelle une source est à pleine densité
    rayon0=18.0,             # m, rayon d'une bouffée à sa naissance
    croissance=3.2,          # m par s^0,8
    rayon_max=150.0,         # m
    duree=240.0,             # s: au-delà, la bouffée est supprimée
    frein=15.0,              # s: durée de freinage de l'élan (plus grand = le nuage précède davantage)
    montee=3.0,              # m/s de montée initiale
    montee_duree=50.0,       # s: la montée se stabilise (altitude gagnée max = montee * montee_duree)
    depot=140.0,             # s: décroissance de la densité par dépôt
    dilution=1.2,            # exposant de la dilution avec le rayon
    apparition=3.0,          # s: fondu d'apparition d'une bouffée
    voxel=22.0,              # m: finesse de la grille de densité
    densite=0.05,            # 1/m: coefficient d'extinction du coeur dense (réglage principal de l'opacité)
    niveaux=(1.0, 0.45, 0.2, 0.09),   # classes de densité: un volume par classe, leurs densités s'additionnent là où elles se recouvrent
    albedo=(0.66, 0.63, 0.59),
    absorption=0.18,         # part d'absorption (assombrit le coeur du nuage)
    bruit_grand=55.0,        # m: taille des grosses bouffées du bruit
    bruit_petit=14.0,        # m: taille des détails
    vent=(0.0, 0.0),         # m/s (x est, y nord, repère de la scène)
    graine=11,
    # ---- V2 (30 oct., retours de Johan: « champignons » d'échelle peu réaliste, nuage qui masque vite l'écoulement; choix
    #      d'Ilyas: garder de la transparence pour voir la matière). Valeurs par défaut = comportement V1; la V2 est dans
    #      reglages/poussiere_v2.json. Les sources (cache .npz) ne changent pas: on en garde seulement une part.
    fraction=1.0,            # part des sources utilisées (0..1): moins de bouffées, chacune plus grande = nuage d'un seul tenant
    transparence_jeune=1.0,  # densité d'une bouffée à sa naissance, relative (0..1): < 1 = on voit la matière à travers le nuage naissant
    age_opaque=1.0,          # s: âge auquel la bouffée atteint toute sa densité (après le fondu d'apparition)
    bruit_seuil_bas=0.30,    # bruit (0..1) en dessous duquel le nuage est creusé au maximum
    bruit_seuil_haut=0.68,   # bruit au-dessus duquel il est le plus dense
    bruit_creux=0.15,        # densité relative dans les creux du bruit (0 = trous francs, nuage déchiqueté)
    bruit_pleins=1.7,        # densité relative dans les pleins
    anisotropie=0.25,        # diffusion vers l'avant de la lumière (0 = isotrope, 0,6 = nuage très lumineux à contre-jour)
    couleur_absorption=(0.45, 0.42, 0.38),
    # ---- V3 « trois étapes » (CDC du 31 oct., observations d'Ilyas sur les vidéos): modele="trois_etapes".
    #  1. fusées: jets partis de la masse rapide en pente, trajectoire surtout horizontale, montée puis retombée (convexe);
    #  2. champignons: au pied du versant (impact dans la vallée), bouffées qui gonflent et montent vite, avec un pied;
    #  3. nuage: avec l'âge toutes les bouffées grossissent, deviennent floues (autre matériau, bruit plus doux) et se fondent.
    #  Densité continue (décomposition sur des niveaux 1, 1/2, 1/4, 1/8): plus de sauts de densité d'une image à l'autre,
    #  cause probable des morceaux de nuage coupés net du brouillon du 31 oct.
    modele="v2",
    fusee_part=0.35,         # part des sources hautes (sur le versant) qui lancent une fusée
    fusee_vitesse=1.15,      # vitesse horizontale de la fusée / vitesse de la matière
    fusee_frein=6.0,         # s
    fusee_hauteur=60.0,      # m: hauteur maximale de l'arc
    fusee_pic=5.0,           # s: âge au sommet de l'arc
    fusee_rayon0=9.0,
    fusee_croissance=2.2,
    fusee_dens=1.0,
    champ_altitude=250.0,    # m au-dessus du fond de vallée (2e centile des sources): en dessous, la source est un impact
    champ_part=0.7,
    champ_montee=180.0,      # m gagnés par le chapeau
    champ_montee_duree=12.0, # s
    champ_frein=3.0,         # s: le champignon reste près de l'impact
    champ_rayon0=20.0,
    champ_croissance=7.0,
    champ_pied=0.45,         # rayon du pied / rayon du chapeau
    champ_dens=1.0,
    nuage_debut=10.0,        # s d'âge: début du passage au nuage (floutage, grossissement)
    nuage_fin=25.0,          # s d'âge: bouffée entièrement « nuage »
    nuage_croissance=6.0,    # m par s^0,8 ajoutés après nuage_debut
    nuage_montee=1.5,        # m/s de montée lente du nuage
    voxel_jeune=8.0,         # m: grille fine pour les fusées et champignons (détail)
    vieux_bruit_grand=260.0,
    vieux_bruit_petit=70.0,
    vieux_creux=0.35,
    vieux_pleins=1.3,
    niveaux_v3=(1.0, 0.5, 0.25, 0.125),
)

STATE = dict(classes=[], S=None, R=None, nmax=0, noeud_t=None, erreur=False, v3=False, typ=None, noeuds_t=[])


# ---------------------------------------------------------------- sources
def _cle(seq, R):
    p = {k: R[k] for k in ("sources", "pas", "vitesse_ref", "graine")}
    p["n"] = len(seq.times)
    return hashlib.md5(json.dumps(p, sort_keys=True).encode()).hexdigest()[:10]


def sources(seq, to_blender, R, log):
    """Tableaux P, V (J,K,3) repère scène, W (J,K) poids 0-1, T (J,) instants. Gardés dans le cache des particules."""
    chemin = os.path.join(seq.dir, f"poussiere_sources_{_cle(seq, R)}.npz")
    if os.path.exists(chemin):
        try:
            z = np.load(chemin)
            log(f"poussière: sources relues ({z['T'].size} instants x {z['W'].shape[1]})")
            return dict(P=z["P"], V=z["V"], W=z["W"], T=z["T"])
        except Exception:
            pass
    K, pas, vref = int(R["sources"]), int(R["pas"]), float(R["vitesse_ref"])
    rng = np.random.default_rng(int(R["graine"]))
    P, V, W, T = [], [], [], []
    g = None
    for i in range(0, len(seq.times), max(1, pas)):
        a = np.asarray(seq.arr(i), np.float32)
        if g is None or len(g) != len(a):
            g = rng.gumbel(size=len(a)).astype(np.float32)
        v = np.linalg.norm(a[:, 3:6], axis=1)
        cle = 2.0 * np.log(v / vref + 1e-3) + g            # tirage sans remise, probabilité proportionnelle à v^2 (Gumbel-top-k)
        k = min(K, len(a))
        sel = np.argpartition(-cle, k - 1)[:k]
        if k < K:                                            # rare: moins de particules que de sources
            sel = np.resize(sel, K)
        P.append(to_blender(a[sel, :3]))
        V.append(to_blender(a[sel, 3:6]))
        W.append(np.minimum(1.0, (v[sel] / vref) ** 2).astype(np.float32))
        T.append(float(seq.times[i]))
    S = dict(P=np.array(P, np.float32), V=np.array(V, np.float32), W=np.array(W, np.float32), T=np.array(T, np.float64))
    try:
        np.savez(chemin, **S)
    except Exception as e:
        log("poussière: cache des sources non écrit:", e)
    log(f"poussière: sources calculées ({S['T'].size} instants x {K})")
    return S


# ---------------------------------------------------------------- bouffées à l'instant t
def bouffees(S, R, t):
    """Positions (n,3), rayons (n,), densités (n,) des bouffées vivantes à l'instant t."""
    tau = t - S["T"]                                         # (J,)
    vivant = (tau >= 0.0) & (tau < R["duree"])
    if not vivant.any():
        return np.zeros((0, 3), np.float32), np.zeros(0, np.float32), np.zeros(0, np.float32)
    tau = tau[vivant][:, None]                               # (j,1)
    P, V, W = S["P"][vivant], S["V"][vivant], S["W"][vivant]
    fr = float(R.get("fraction", 1.0))
    if fr < 1.0:                                             # même sous-ensemble de sources à chaque image (graine fixe)
        garde_k = np.random.default_rng(int(R["graine"]) + 5).random(P.shape[1]) < max(fr, 1e-3)
        P, V, W = P[:, garde_k], V[:, garde_k], W[:, garde_k]
    Tf, Tm = float(R["frein"]), float(R["montee_duree"])
    pos = P + V * (Tf * (1.0 - np.exp(-tau / Tf)))[..., None]
    pos[..., 2] += float(R["montee"]) * Tm * (1.0 - np.exp(-tau / Tm))
    pos[..., 0] += float(R["vent"][0]) * tau
    pos[..., 1] += float(R["vent"][1]) * tau
    r = np.minimum(float(R["rayon0"]) + float(R["croissance"]) * tau ** 0.8, float(R["rayon_max"]))
    d = W * (float(R["rayon0"]) / r) ** float(R["dilution"]) * np.exp(-tau / float(R["depot"]))
    u = np.clip(tau / max(float(R["apparition"]), 1e-3), 0.0, 1.0)
    d = d * (u * u * (3.0 - 2.0 * u))
    tj = float(R.get("transparence_jeune", 1.0))
    if tj < 1.0:                                             # bouffée naissante plus claire: la matière reste visible dessous
        a = np.clip(tau / max(float(R.get("age_opaque", 1.0)), 1e-3), 0.0, 1.0)
        d = d * (tj + (1.0 - tj) * (a * a * (3.0 - 2.0 * a)))
    garde = (W * 1.0 > 0.02)
    pos, r, d = pos[garde], np.broadcast_to(r, W.shape)[garde], d[garde]
    return pos.astype(np.float32), r.astype(np.float32), d.astype(np.float32)



def _lisse(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def types_sources(S, R):
    """0 trainée, 1 fusée, 2 champignon, pour chaque source (J,K). Déterministe (graine)."""
    rng = np.random.default_rng(int(R["graine"]) + 7)
    u = rng.random(S["W"].shape)
    z = S["P"][..., 2]
    ok = S["W"] > 0.05
    zf = float(np.percentile(z[ok], 2)) if ok.any() else float(z.min())
    bas = z < zf + float(R["champ_altitude"])
    typ = np.zeros(S["W"].shape, np.int8)
    typ[~bas & (u < float(R["fusee_part"]))] = 1
    typ[bas & (u < float(R["champ_part"]))] = 2
    return typ, zf


def bouffees_v3(S, R, t, typ):
    """Positions (n,3), rayons, densités, part « nuage » (0..1) des bouffées vivantes à l'instant t (modèle en 3 étapes)."""
    vide = (np.zeros((0, 3), np.float32), np.zeros(0, np.float32), np.zeros(0, np.float32), np.zeros(0, np.float32))
    tau = t - S["T"]
    vivant = (tau >= 0.0) & (tau < R["duree"])
    if not vivant.any():
        return vide
    tau = tau[vivant][:, None]
    P, V, W, ty = S["P"][vivant], S["V"][vivant], S["W"][vivant], typ[vivant]
    fr = float(R.get("fraction", 1.0))
    if fr < 1.0:
        garde_k = np.random.default_rng(int(R["graine"]) + 5).random(P.shape[1]) < max(fr, 1e-3)
        P, V, W, ty = P[:, garde_k], V[:, garde_k], W[:, garde_k], ty[:, garde_k]
    tau = np.broadcast_to(tau, W.shape)
    e = lambda T_: (T_ * (1.0 - np.exp(-tau / T_)))[..., None]
    Vh = V.copy()
    Vh[..., 2] = 0.0
    nd = float(R["nuage_debut"])
    tn = np.maximum(tau - nd, 0.0)
    w = _lisse((tau - nd) / max(float(R["nuage_fin"]) - nd, 1e-3))
    mont_nuage = float(R["nuage_montee"]) * 30.0 * (1.0 - np.exp(-tn / 30.0))
    # 0 trainée (comme la V2)
    Tf, Tm = float(R["frein"]), float(R["montee_duree"])
    p0 = P + V * e(Tf)
    p0[..., 2] += float(R["montee"]) * Tm * (1.0 - np.exp(-tau / Tm))
    r0 = float(R["rayon0"]) + float(R["croissance"]) * tau ** 0.8
    # 1 fusée
    p1 = P + Vh * float(R["fusee_vitesse"]) * e(float(R["fusee_frein"]))
    a = tau / float(R["fusee_pic"])
    p1[..., 2] += float(R["fusee_hauteur"]) * a * np.exp(1.0 - a) + mont_nuage
    r1 = float(R["fusee_rayon0"]) + float(R["fusee_croissance"]) * tau ** 0.8
    # 2 champignon (chapeau)
    p2 = P + Vh * e(float(R["champ_frein"]))
    monte = float(R["champ_montee"]) * (1.0 - np.exp(-tau / float(R["champ_montee_duree"])))
    p2[..., 2] += monte + mont_nuage
    r2 = float(R["champ_rayon0"]) + float(R["champ_croissance"]) * tau ** 0.8
    t1, t2 = (ty == 1), (ty == 2)
    pos = np.where(t1[..., None], p1, np.where(t2[..., None], p2, p0))
    rr0 = np.where(t1, float(R["fusee_rayon0"]), np.where(t2, float(R["champ_rayon0"]), float(R["rayon0"])))
    r = np.where(t1, r1, np.where(t2, r2, r0)) + float(R["nuage_croissance"]) * tn ** 0.8
    r = np.minimum(r, float(R["rayon_max"]))
    poids = W * np.where(t1, float(R["fusee_dens"]), np.where(t2, float(R["champ_dens"]), 1.0))
    d = poids * (rr0 / r) ** float(R["dilution"]) * np.exp(-tau / float(R["depot"]))
    d = d * _lisse(tau / max(float(R["apparition"]), 1e-3))
    tj = float(R.get("transparence_jeune", 1.0))
    if tj < 1.0:     # trainées naissantes claires (on voit la matière); fusées et champignons denses dès le début
        jeune = tj + (1.0 - tj) * _lisse(tau / max(float(R.get("age_opaque", 1.0)), 1e-3))
        d = d * np.where(ty == 0, jeune, 1.0)
    garde = W > 0.02
    # pied des champignons: plus bas, plus fin, s'efface en devenant nuage
    pied = t2 & garde & (w < 0.999)
    pp = P + Vh * e(float(R["champ_frein"]))
    pp[..., 2] += 0.35 * monte
    out_p = [pos[garde], pp[pied]]
    out_r = [r[garde], (float(R["champ_pied"]) * r)[pied]]
    out_d = [d[garde], (0.8 * d * (1.0 - w))[pied]]
    out_w = [w[garde], w[pied]]
    return tuple(np.concatenate(x).astype(np.float32) for x in (out_p, out_r, out_d, out_w))


def decomposer(d, niveaux):
    """Décompose chaque densité en une somme de niveaux (binaire, glouton, arrondi au plus proche sur le dernier).
    Rend un tableau booléen (n, len(niveaux)): la bouffée est-elle dans la classe k."""
    rem = d.astype(np.float64).copy()
    out = np.zeros((len(d), len(niveaux)), bool)
    for k, lv in enumerate(niveaux):
        dern = k == len(niveaux) - 1
        pris = rem >= (0.5 * lv if dern else lv)
        out[:, k] = pris
        rem = np.where(pris, rem - lv, rem)
    return out

# ---------------------------------------------------------------- objet Blender
def _materiau(R):
    mat = bpy.data.materials.new("Poussiere")
    mat.use_nodes = True
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    for n in list(N):
        N.remove(n)
    sortie = N.new("ShaderNodeOutputMaterial")

    info = N.new("ShaderNodeVolumeInfo")                    # densité "density" de la grille
    geo = N.new("ShaderNodeNewGeometry")
    tmp = N.new("ShaderNodeValue")
    tmp.name = tmp.label = "temps"
    tmp.outputs[0].default_value = 0.0

    # le bruit dérive avec le vent (et monte un peu), pour que le nuage bouillonne au lieu de glisser comme un bloc
    vx, vy = float(R["vent"][0]), float(R["vent"][1])
    dec = N.new("ShaderNodeCombineXYZ")
    for k, f in enumerate((vx + 1.5, vy + 0.5, 1.2)):
        m = N.new("ShaderNodeMath")
        m.operation = "MULTIPLY"
        m.inputs[1].default_value = f
        L.new(tmp.outputs[0], m.inputs[0])
        L.new(m.outputs[0], dec.inputs[k])
    pos = N.new("ShaderNodeVectorMath")
    pos.operation = "SUBTRACT"
    L.new(geo.outputs["Position"], pos.inputs[0])
    L.new(dec.outputs["Vector"], pos.inputs[1])

    n1 = N.new("ShaderNodeTexNoise")
    n1.noise_dimensions = "3D"
    n1.inputs["Scale"].default_value = 1.0 / float(R["bruit_grand"])
    n1.inputs["Detail"].default_value = 4.0
    n1.inputs["Roughness"].default_value = 0.6
    n2 = N.new("ShaderNodeTexNoise")
    n2.noise_dimensions = "3D"
    n2.inputs["Scale"].default_value = 1.0 / float(R["bruit_petit"])
    n2.inputs["Detail"].default_value = 2.0
    L.new(pos.outputs[0], n1.inputs["Vector"])
    L.new(pos.outputs[0], n2.inputs["Vector"])
    mel = N.new("ShaderNodeMix")
    mel.data_type = "FLOAT"
    mel.inputs[0].default_value = 0.3
    L.new(n1.outputs["Fac"], mel.inputs[2])
    L.new(n2.outputs["Fac"], mel.inputs[3])
    mr = N.new("ShaderNodeMapRange")                        # bruit 0.3-0.7 -> facteur 0.15-1.7: creux et bouffées
    mr.clamp = True
    mr.inputs["From Min"].default_value = float(R["bruit_seuil_bas"])
    mr.inputs["From Max"].default_value = float(R["bruit_seuil_haut"])
    mr.inputs["To Min"].default_value = float(R["bruit_creux"])
    mr.inputs["To Max"].default_value = float(R["bruit_pleins"])
    L.new(mel.outputs[0], mr.inputs["Value"])

    dens = N.new("ShaderNodeMath")
    dens.operation = "MULTIPLY"
    L.new(info.outputs["Density"], dens.inputs[0])
    L.new(mr.outputs["Result"], dens.inputs[1])
    dens2 = N.new("ShaderNodeMath")
    dens2.operation = "MULTIPLY"
    dens2.inputs[1].default_value = float(R["densite"])
    L.new(dens.outputs[0], dens2.inputs[0])

    diff = N.new("ShaderNodeVolumeScatter")
    diff.inputs["Color"].default_value = (*R["albedo"], 1.0)
    diff.inputs["Anisotropy"].default_value = float(R["anisotropie"])
    L.new(dens2.outputs[0], diff.inputs["Density"])
    absn = N.new("ShaderNodeVolumeAbsorption")
    absn.inputs["Color"].default_value = (*R["couleur_absorption"], 1.0)
    dabs = N.new("ShaderNodeMath")
    dabs.operation = "MULTIPLY"
    dabs.inputs[1].default_value = float(R["absorption"])
    L.new(dens2.outputs[0], dabs.inputs[0])
    L.new(dabs.outputs[0], absn.inputs["Density"])
    ajout = N.new("ShaderNodeAddShader")
    L.new(diff.outputs[0], ajout.inputs[0])
    L.new(absn.outputs[0], ajout.inputs[1])
    L.new(ajout.outputs[0], sortie.inputs["Volume"])
    return mat, tmp


def _arbre(mat, R, niveau, nom):
    ng = bpy.data.node_groups.new(nom, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    nin, nout = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    m2p = N.new("GeometryNodeMeshToPoints")
    m2p.mode = "VERTICES"
    p2v = N.new("GeometryNodePointsToVolume")
    p2v.inputs["Resolution Mode"].default_value = "Size"
    p2v.inputs["Voxel Size"].default_value = float(R["voxel"])
    p2v.inputs["Density"].default_value = float(niveau)     # valeur unique (ce n'est pas un champ): d'où une classe par objet
    nr = N.new("GeometryNodeInputNamedAttribute")
    nr.data_type = "FLOAT"
    nr.inputs["Name"].default_value = "pr"
    sm = N.new("GeometryNodeSetMaterial")
    sm.inputs["Material"].default_value = mat
    L.new(nin.outputs["Geometry"], m2p.inputs["Mesh"])
    L.new(m2p.outputs["Points"], p2v.inputs["Points"])
    L.new(nr.outputs["Attribute"], p2v.inputs["Radius"])
    L.new(p2v.outputs["Volume"], sm.inputs["Geometry"])
    L.new(sm.outputs["Geometry"], nout.inputs["Geometry"])
    return ng


def construire(scene, coll, seq, to_blender, cfg, log, reglages=None):
    """Crée les objets Poussiere_*. Renvoie True si le panache est actif."""
    R = dict(REGLAGES)
    inconnues = [k for k in (reglages or {}) if k not in REGLAGES]
    if inconnues:
        raise SystemExit(f"Réglages poussière inconnus: {inconnues} (voir REGLAGES dans src/matiere/poussiere.py)")
    for k, v in (reglages or {}).items():
        R[k] = tuple(v) if isinstance(v, list) and isinstance(REGLAGES.get(k), tuple) else v
    if not R["poussiere"] or cfg.get("no_poussiere"):
        log("poussière: désactivée")
        return False
    S = sources(seq, to_blender, R, log)
    if R["modele"] == "trois_etapes":
        return _construire_v3(scene, coll, S, R, log)
    nmax = int(S["P"].shape[0] * S["P"].shape[1])
    mat, tmp = _materiau(R)
    classes = []
    for k, niv in enumerate(R["niveaux"]):
        mesh = bpy.data.meshes.new(f"poussiere_{k}")
        mesh.vertices.add(nmax)
        mesh.attributes.new("pr", "FLOAT", "POINT")
        obj = bpy.data.objects.new(f"Poussiere_{k}", mesh)
        coll.objects.link(obj)
        obj.modifiers.new("Poussiere", "NODES").node_group = _arbre(mat, R, niv, f"Poussiere_{k}")
        classes.append((float(niv), mesh))
    try:  # volumes: un seul rebond de diffusion suffit sous ciel couvert, pas fin raisonnable
        c = scene.cycles
        c.volume_bounces = 1
        c.volume_step_rate = 1.5
        c.volume_max_steps = 1024
    except Exception as e:
        log("poussière: réglages de volume Cycles:", e)
    STATE.update(classes=classes, S=S, R=R, nmax=nmax, noeud_t=tmp, erreur=False)
    log(f"poussière: {nmax:,} bouffées possibles en {len(classes)} classes de densité, grille {R['voxel']:g} m, extinction {R['densite']:g}/m")
    return True


def _reglages_cycles(scene, log):
    try:  # volumes: un seul rebond de diffusion suffit sous ciel couvert, pas fin raisonnable
        c = scene.cycles
        c.volume_bounces = 1
        c.volume_step_rate = 1.5
        c.volume_max_steps = 1024
    except Exception as e:
        log("poussière: réglages de volume Cycles:", e)


def _construire_v3(scene, coll, S, R, log):
    typ, zf = types_sources(S, R)
    kf = int(np.ceil(S["P"].shape[1] * min(1.0, float(R.get("fraction", 1.0))))) + 8
    nmax = int(S["P"].shape[0] * kf * 2)
    Rv = dict(R)
    Rv.update(bruit_grand=R["vieux_bruit_grand"], bruit_petit=R["vieux_bruit_petit"], bruit_creux=R["vieux_creux"],
              bruit_pleins=R["vieux_pleins"])
    mj, tj = _materiau(R)
    mv, tv = _materiau(Rv)
    classes = []
    for g, (mat, Rg, vox) in enumerate(((mj, R, float(R["voxel_jeune"])), (mv, Rv, float(R["voxel"])))):
        Rg = dict(Rg)
        Rg["voxel"] = vox
        for k, niv in enumerate(R["niveaux_v3"]):
            nom = f"Poussiere_{'jeune' if g == 0 else 'nuage'}_{k}"
            mesh = bpy.data.meshes.new(nom)
            mesh.vertices.add(nmax)
            mesh.attributes.new("pr", "FLOAT", "POINT")
            obj = bpy.data.objects.new(nom, mesh)
            coll.objects.link(obj)
            obj.modifiers.new("Poussiere", "NODES").node_group = _arbre(mat, Rg, niv, nom)
            classes.append((g, k, float(niv), mesh))
    _reglages_cycles(scene, log)
    STATE.update(classes=classes, S=S, R=R, nmax=nmax, noeud_t=tj, noeuds_t=[tj, tv], erreur=False, v3=True, typ=typ)
    n = np.bincount(typ.ravel(), minlength=3)
    log(f"poussière 3 étapes: fond de vallée {zf:.0f} m, sources {n[0]:,} trainées, {n[1]:,} fusées, {n[2]:,} champignons; "
        f"{len(classes)} volumes (grilles {R['voxel_jeune']:g} et {R['voxel']:g} m)")
    return True


def _maj_v3(t):
    R, nmax = STATE["R"], STATE["nmax"]
    pos, r, d, w = bouffees_v3(STATE["S"], R, t, STATE["typ"])
    niv = np.array(R["niveaux_v3"], np.float64)
    parts = (decomposer(d * (1.0 - w), niv), decomposer(d * w, niv))
    repos = pos[0] if len(pos) else np.zeros(3, np.float32)
    for g, k, _, mesh in STATE["classes"]:
        sel = parts[g][:, k] if len(d) else np.zeros(0, bool)
        n = int(min(sel.sum(), nmax))
        co = np.tile(repos, (nmax, 1)).astype(np.float32)
        pr = np.full(nmax, 0.01, np.float32)
        if n:
            co[:n], pr[:n] = pos[sel][:n], r[sel][:n]
        mesh.vertices.foreach_set("co", co.ravel())
        mesh.attributes["pr"].data.foreach_set("value", pr)
        mesh.update()
    for nd in STATE["noeuds_t"]:
        nd.outputs[0].default_value = float(t)


def maj(t):
    """Place les bouffées à l'instant t (secondes simulées). Sans effet si le panache n'a pas été construit."""
    if not STATE["classes"] or STATE["erreur"]:
        return
    try:
        if STATE["v3"]:
            _maj_v3(t)
            return
        R, nmax = STATE["R"], STATE["nmax"]
        pos, r, d = bouffees(STATE["S"], R, t)
        niv = np.array([c[0] for c in STATE["classes"]], np.float32)
        if len(d):
            cl = np.argmin(np.abs(np.log(np.maximum(d, 1e-6))[:, None] - np.log(niv)[None, :]), axis=1)
            vivant = d > 0.6 * niv.min()
        else:
            cl = np.zeros(0, np.int64)
            vivant = np.zeros(0, bool)
        repos = pos[vivant][0] if vivant.any() else np.zeros(3, np.float32)   # les inutilisées restent DANS la zone (sinon l'emprise du volume s'étend)
        for k, (_, mesh) in enumerate(STATE["classes"]):
            sel = vivant & (cl == k)
            n = int(min(sel.sum(), nmax))
            co = np.tile(repos, (nmax, 1)).astype(np.float32)
            pr = np.full(nmax, 0.01, np.float32)
            if n:
                co[:n], pr[:n] = pos[sel][:n], r[sel][:n]
            mesh.vertices.foreach_set("co", co.ravel())
            mesh.attributes["pr"].data.foreach_set("value", pr)
            mesh.update()
        STATE["noeud_t"].outputs[0].default_value = float(t)
    except Exception as e:     # le panache ne doit jamais faire échouer un rendu de plusieurs heures
        STATE["erreur"] = True
        print("[poussiere] ERREUR, panache coupé pour la suite:", repr(e), flush=True)
