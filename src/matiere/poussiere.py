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
)

STATE = dict(classes=[], S=None, R=None, nmax=0, noeud_t=None, erreur=False)


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
    Tf, Tm = float(R["frein"]), float(R["montee_duree"])
    pos = P + V * (Tf * (1.0 - np.exp(-tau / Tf)))[..., None]
    pos[..., 2] += float(R["montee"]) * Tm * (1.0 - np.exp(-tau / Tm))
    pos[..., 0] += float(R["vent"][0]) * tau
    pos[..., 1] += float(R["vent"][1]) * tau
    r = np.minimum(float(R["rayon0"]) + float(R["croissance"]) * tau ** 0.8, float(R["rayon_max"]))
    d = W * (float(R["rayon0"]) / r) ** float(R["dilution"]) * np.exp(-tau / float(R["depot"]))
    u = np.clip(tau / max(float(R["apparition"]), 1e-3), 0.0, 1.0)
    d = d * (u * u * (3.0 - 2.0 * u))
    garde = (W * 1.0 > 0.02)
    pos, r, d = pos[garde], np.broadcast_to(r, W.shape)[garde], d[garde]
    return pos.astype(np.float32), r.astype(np.float32), d.astype(np.float32)


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
    mr.inputs["From Min"].default_value = 0.30
    mr.inputs["From Max"].default_value = 0.68
    mr.inputs["To Min"].default_value = 0.15
    mr.inputs["To Max"].default_value = 1.7
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
    diff.inputs["Anisotropy"].default_value = 0.25
    L.new(dens2.outputs[0], diff.inputs["Density"])
    absn = N.new("ShaderNodeVolumeAbsorption")
    absn.inputs["Color"].default_value = (0.45, 0.42, 0.38, 1.0)
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
    R.update(reglages or {})
    if not R["poussiere"] or cfg.get("no_poussiere"):
        log("poussière: désactivée")
        return False
    S = sources(seq, to_blender, R, log)
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


def maj(t):
    """Place les bouffées à l'instant t (secondes simulées). Sans effet si le panache n'a pas été construit."""
    if not STATE["classes"] or STATE["erreur"]:
        return
    try:
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
