"""
depot.py : PEAU CONTINUE sous les roches (dépôt et coulée), recalculée à chaque image. Appelée par matiere_roches.py.

Pourquoi : à 1 grain sur 5, les particules sont espacées d'environ 6,8 m et les roches font ~4 m: entre elles on voit le
terrain d'avant l'événement (pré, forêt), et la masse se lit comme un lit de graviers posé sur l'herbe. Sous la couche de
roches, on tend donc une surface continue, de la couleur de la matière, à la hauteur des particules du dessus moins un
demi-rayon: les roches dépassent, les trous sont bouchés. Sur le dépôt c'est le sol enseveli; dans la coulée, la masse.

Méthode (numpy, quelques dizaines de ms par image):
  1. grille de `maille` m (repère de la scène); dans chaque case, altitude de la particule la plus haute et nombre de particules;
  2. on ne garde que les cases assez peuplées autour d'elles (`densite_min` particules dans le carré 3 x 3): les grains isolés
     ou projetés ne tendent pas de peau;
  3. on bouche les trous d'une case entourés de cases pleines, puis on lisse (moyenne 3 x 3);
  4. maillage: une face par case gardée; les sommets du bord sont abaissés de `bord` m pour que la peau rentre dans le sol
     au lieu de flotter.
Ce n'est pas de la physique: c'est la surface visible de la masse simulée, dessinée sans trous.
"""
import numpy as np

REGLAGES = dict(
    depot=True,          # False: pas de peau (matière en roches seules, comme avant)
    maille=5.0,          # m, côté d'une case
    densite_min=4,       # particules minimum dans le carré 3 x 3 autour d'une case pour y tendre la peau
    enfoncement=0.5,     # sous la particule la plus haute, en rayons de roche
    bord=3.0,            # m, abaissement des sommets du bord
    lissage=1,           # passes de moyenne 3 x 3
)

ETAT = dict(mesh=None, r=None, rayon=2.0, log=print)


def _somme3(a):
    """Somme sur le carré 3 x 3 (bords: zéro)."""
    p = np.pad(a, 1)
    return sum(p[1 + dy:p.shape[0] - 1 + dy, 1 + dx:p.shape[1] - 1 + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1))


def surface(P, r, rayon):
    """P (N,3) repère scène (Z haut). Rend (x0, y0, maille, H, garde): H (ny, nx) altitude de la peau, garde (ny, nx) bool."""
    g = float(r["maille"])
    if len(P) == 0:
        return None
    x0, y0 = np.floor(P[:, 0].min() / g) * g - g, np.floor(P[:, 1].min() / g) * g - g
    ix = ((P[:, 0] - x0) / g).astype(np.int64)
    iy = ((P[:, 1] - y0) / g).astype(np.int64)
    nx, ny = int(ix.max()) + 2, int(iy.max()) + 2
    lin = iy * nx + ix
    cnt = np.bincount(lin, minlength=nx * ny).reshape(ny, nx)
    top = np.full(nx * ny, -np.inf, np.float64)
    np.maximum.at(top, lin, P[:, 2].astype(np.float64))
    top = top.reshape(ny, nx)
    plein = cnt > 0
    dense = _somme3(cnt) >= int(r["densite_min"])
    garde = plein & dense
    H = np.where(garde, top, 0.0)
    # trous isolés: case vide dont au moins 5 voisines sont gardées
    nvois = _somme3(garde.astype(np.int64))
    trou = ~garde & (nvois >= 5)
    if trou.any():
        s = _somme3(H * garde)
        H = np.where(trou, s / np.maximum(nvois, 1), H)
        garde = garde | trou
    for _ in range(int(r["lissage"])):
        w = _somme3(garde.astype(np.float64))
        H = np.where(garde, _somme3(H * garde) / np.maximum(w, 1.0), 0.0)
    H = H - float(r["enfoncement"]) * rayon
    return x0, y0, g, H, garde


def maillage(x0, y0, g, H, garde, bord):
    """Sommets aux coins des cases gardées (altitude = moyenne des cases voisines), faces = cases gardées."""
    ny, nx = H.shape
    gv = np.zeros((ny + 1, nx + 1), np.float64)      # nombre de cases gardées autour de chaque coin
    hv = np.zeros((ny + 1, nx + 1), np.float64)
    gf = garde.astype(np.float64)
    for dy in (0, 1):
        for dx in (0, 1):
            gv[dy:dy + ny, dx:dx + nx] += gf
            hv[dy:dy + ny, dx:dx + nx] += H * gf
    hv = hv / np.maximum(gv, 1.0)
    hv = hv - bord * (gv < 4)                          # bord: le coin touche une case vide
    jj, ii = np.nonzero(garde)
    if len(jj) == 0:
        return np.zeros((0, 3), np.float32), np.zeros((0, 4), np.int32)
    c00 = jj * (nx + 1) + ii
    quads = np.stack([c00, c00 + 1, c00 + nx + 2, c00 + nx + 1], axis=1)
    used = np.zeros((ny + 1) * (nx + 1), bool)
    used[quads.ravel()] = True
    remap = np.cumsum(used) - 1
    vy, vx = np.divmod(np.nonzero(used)[0], nx + 1)
    co = np.stack([x0 + vx * g, y0 + vy * g, hv.ravel()[used]], axis=1).astype(np.float32)
    return co, remap[quads].astype(np.int32)


def construire(coll, mat, rayon, log, reglages=None):
    import bpy
    r = dict(REGLAGES)
    r.update(reglages or {})
    if not r["depot"]:
        return False
    me = bpy.data.meshes.new("depot")
    me.materials.append(mat)
    ob = bpy.data.objects.new("Depot", me)
    coll.objects.link(ob)
    ETAT.update(mesh=me, r=r, rayon=rayon, log=log)
    log(f"dépôt: peau continue sous les roches (cases de {r['maille']:g} m, au moins {r['densite_min']} particules autour)")
    return True


def maj(Pb):
    """Pb: positions (N,3) dans le repère de la scène. Reconstruit la peau."""
    me = ETAT["mesh"]
    if me is None:
        return
    s = surface(Pb, ETAT["r"], ETAT["rayon"])
    me.clear_geometry()
    if s is None:
        return
    co, quads = maillage(*s, bord=float(ETAT["r"]["bord"]))
    nv, nf = len(co), len(quads)
    if nf == 0:
        me.update()
        return
    me.vertices.add(nv)
    me.vertices.foreach_set("co", co.ravel())
    me.loops.add(nf * 4)
    me.loops.foreach_set("vertex_index", quads.ravel())
    me.polygons.add(nf)
    me.polygons.foreach_set("loop_start", np.arange(0, nf * 4, 4, dtype=np.int32))
    me.update(calc_edges=True)
    me.polygons.foreach_set("use_smooth", np.ones(nf, bool))
    me.update()
