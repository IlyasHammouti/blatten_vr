"""
arbres_ez.py : arbres procéduraux détaillés (écorce et feuillage photographiques), pour les arbres proches de la caméra.

Portage en Python (numpy, sans Blender) de l'algorithme d'EZ-Tree de Daniel Greenheck (licence MIT,
https://github.com/dgreenheck/ez-tree, copie de la licence dans assets/arbres/LICENSE_ez-tree.txt): tronc et branches en
cylindres effilés, perturbés (« gnarliness »), tordus et attirés par une force (gravité, lumière); feuillage en cartes
croisées texturées (rameau d'épicéa, feuilles de frêne ou de chêne) avec transparence. Même générateur aléatoire que
l'original: une graine donne le même arbre que sur https://www.eztree.dev.

    geo = generer(charger_preset("pine_large"), graine=3)      # dict branches / feuilles (V, N, UV, T), Z vers le haut
Les arbres sont normalisés: pied en (0, 0, 0), hauteur 1, rayon de couronne 1 (à étirer par la hauteur et le rayon relevés).
Textures et réglages de base: assets/arbres/ (écorces Poly Haven et texturecan, CC0; feuilles et réglages d'EZ-Tree, MIT).
"""
import json
import math
import os

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ICI, "..", "..", "assets", "arbres")


# ------------------------------------------------------------------ aléa identique à EZ-Tree (rng.js)
def _i32(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x & 0x80000000 else x


class RNG:
    def __init__(self, graine):
        self.w = _i32(123456789 + int(graine))
        self.z = _i32(987654321 - int(graine))

    def random(self, mx=1.0, mn=0.0):
        self.z = _i32(36969 * (self.z & 65535) + (self.z >> 16))
        self.w = _i32(18000 * (self.w & 65535) + (self.w >> 16))
        r = (_i32(self.z << 16) + (self.w & 65535)) & 0xFFFFFFFF
        return (mx - mn) * (r / 4294967296.0) + mn


# ------------------------------------------------------------------ quaternions (w, x, y, z)
def q_axe(axe, ang):
    s = math.sin(ang / 2.0)
    return np.array([math.cos(ang / 2.0), axe[0] * s, axe[1] * s, axe[2] * s])


def q_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def q_rot(q, v):
    """Tourne le(s) vecteur(s) v (..., 3) par le quaternion q."""
    w, u = q[0], q[1:]
    v = np.asarray(v, np.float64)
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def q_slerp(a, b, t):
    """Interpolation sphérique de a vers b (t peut sortir de [0, 1], comme three.js)."""
    c = float(np.dot(a, b))
    if c < 0:
        b, c = -b, -c
    if c > 0.9995:
        r = a + t * (b - a)
        return r / np.linalg.norm(r)
    th = math.acos(min(1.0, c))
    s = math.sin(th)
    return (math.sin((1 - t) * th) / s) * a + (math.sin(t * th) / s) * b


def q_vers(q, cible, pas):
    """Quaternion.rotateTowards de three.js: tourne q vers cible d'un angle pas (radians, négatif: s'en éloigne)."""
    c = min(1.0, abs(float(np.dot(q, cible))))
    ang = 2.0 * math.acos(c)
    if ang == 0.0:
        return q
    return q_slerp(q, cible, min(1.0, pas / ang))


def q_entre(u, v):
    """Rotation qui amène le vecteur unitaire u sur v."""
    u, v = np.asarray(u, float), np.asarray(v, float)
    r = float(np.dot(u, v)) + 1.0
    if r < 1e-6:
        ax = np.array([1.0, 0, 0]) if abs(u[0]) < 0.9 else np.array([0, 0, 1.0])
        ax = np.cross(u, ax)
        q = np.array([0.0, *ax])
    else:
        q = np.array([r, *np.cross(u, v)])
    return q / np.linalg.norm(q)


X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


# ------------------------------------------------------------------ réglages
def charger_preset(nom):
    with open(os.path.join(ASSETS, "presets", nom + ".json"), encoding="utf-8") as f:
        return json.load(f)


def _niv(d, k):
    return d[str(k)] if str(k) in d else d[k]


def generer(o, graine=None):
    """Arbre complet d'après les réglages o (format EZ-Tree). Rend dict(branches=..., feuilles=...), chaque partie
    dict(V (n,3), N (n,3), UV (n,2), T (m,3)), Z vers le haut, normalisé (hauteur 1, rayon de couronne 1)."""
    rng = RNG(o["seed"] if graine is None else graine)
    b, fe = o["branch"], o["leaves"]
    persistant = o["type"] == "evergreen"
    niveaux = int(b["levels"])
    force_q = q_entre(Y, (b["force"]["direction"]["x"], b["force"]["direction"]["y"], b["force"]["direction"]["z"]))
    force = float(b["force"]["strength"])
    BV, BN, BUV, BT = [], [], [], []
    FV, FN, FUV, FT = [], [], [], []
    nb = [0]
    nf = [0]
    file = [(np.zeros(3), np.array([1.0, 0, 0, 0]), float(_niv(b["length"], 0)), float(_niv(b["radius"], 0)), 0,
             int(_niv(b["sections"], 0)), int(_niv(b["segments"], 0)))]

    long_max = float(_niv(b["length"], niveaux)) if niveaux > 0 else 1.0
    reduire = bool(o.get("_rameaux_selon_branche"))      # ajout: rameaux plus petits sur les branches courtes (cime pointue)
    long_courante = [long_max]

    def feuille(origine, q):
        taille = fe["size"] * (1 + rng.random(fe["sizeVariance"], -fe["sizeVariance"]))
        if reduire:
            taille *= min(1.0, max(0.3, long_courante[0] / max(long_max, 1e-9))) ** 0.7
        W = L = taille

        def carte(rot):
            coins = np.array([[-W / 2, L, 0], [-W / 2, 0, 0], [W / 2, 0, 0], [W / 2, L, 0]], float)
            qq = q_mul(q, q_axe(Y, rot))
            FV.append(q_rot(qq, coins) + origine)
            n = q_rot(q, np.array([0.0, 0.0, 1.0]))
            FN.append(np.repeat(n[None, :], 4, 0))
            FUV.append(np.array([[0, 1], [0, 0], [1, 0], [1, 1]], float))
            i = nf[0]
            FT.append(np.array([[i, i + 1, i + 2], [i, i + 2, i + 3]]))
            nf[0] += 4

        carte(0.0)
        if fe.get("billboard") == "double":
            carte(math.pi / 2)

    def le_long(sections, debut):
        """Origine, orientation et rayon à la fraction debut (0..1) d'une branche (comme EZ-Tree, y compris son slerp)."""
        n = len(sections)
        k = int(math.floor(debut * (n - 1)))
        A = sections[k]
        Bs = sections[k + 1] if k < n - 1 else A
        alpha = (debut - k / (n - 1)) / (1.0 / (n - 1))
        org = A[0] + (Bs[0] - A[0]) * alpha
        ray = (1 - alpha) * A[2] + alpha * Bs[2]
        q = q_slerp(Bs[1], A[1], alpha)
        return org, q, ray

    while file:
        org, q, longueur, rayon, niv, nsec, nseg = file.pop(0)
        org = org.copy()
        long_courante[0] = longueur
        off = nb[0]
        lsec = longueur / nsec
        sections = []
        ang = 2.0 * np.pi * np.arange(nseg) / nseg
        cercle = np.stack([np.cos(ang), np.zeros(nseg), np.sin(ang)], 1)
        for i in range(nsec + 1):
            r = rayon
            if i == nsec and niv == niveaux:
                r = 0.001
            elif not persistant:
                r *= 1 - _niv(b["taper"], niv) * (i / nsec)
            else:
                r *= 1 - i / nsec
            nrm = q_rot(q, cercle)
            v = nrm * r + org
            BV.append(np.vstack([v, v[:1]]))
            BN.append(np.vstack([nrm, nrm[:1]]))
            u = np.r_[np.arange(nseg) / nseg, 1.0]
            BUV.append(np.stack([u, np.full(nseg + 1, float(i % 2))], 1))
            sections.append((org.copy(), q.copy(), r))
            org = org + q_rot(q, np.array([0.0, lsec, 0.0]))
            g = max(1.0, 1.0 / math.sqrt(max(r, 1e-9))) * _niv(b["gnarliness"], niv)
            dx = rng.random(g, -g)
            dz = rng.random(g, -g)
            q = q_mul(q_mul(q_axe(X, dx), q), q_axe(Z, dz))          # Euler x (axe global) et z (axe local) perturbés
            q = q_mul(q, q_axe(Y, _niv(b["twist"], niv)))
            q = q_vers(q, force_q, force / max(r, 1e-9))
            q = q / np.linalg.norm(q)
        nb[0] += (nsec + 1) * (nseg + 1)
        N1 = nseg + 1
        ii, jj = np.meshgrid(np.arange(nsec), np.arange(nseg), indexing="ij")
        v1 = off + ii * N1 + jj
        v2 = v1 + 1
        v3, v4 = v1 + N1, v2 + N1
        BT.append(np.stack([np.stack([v1, v3, v2], -1), np.stack([v2, v3, v4], -1)], 2).reshape(-1, 3))
        if not persistant:          # branche terminale qui prolonge la branche (feuillus)
            dern = sections[-1]
            if niv < niveaux:
                file.append((dern[0], dern[1], float(_niv(b["length"], niv + 1)), dern[2], niv + 1, nsec, nseg))
            else:
                feuille(dern[0], dern[1])
        if niv == niveaux:          # feuillage le long des dernières branches
            dec = rng.random()
            for i in range(int(fe["count"])):
                debut = rng.random(1.0, fe["start"])
                o_, q_, _ = le_long(sections, debut)
                rad = 2.0 * math.pi * (dec + i / fe["count"])
                qf = q_mul(q_, q_mul(q_axe(Y, rad), q_axe(X, math.radians(fe["angle"]))))
                feuille(o_, qf)
        elif niv < niveaux:         # branches filles
            n_enf = int(_niv(b["children"], niv))
            dec = rng.random()
            for i in range(n_enf):
                debut = rng.random(1.0, _niv(b["start"], niv + 1))
                o_, q_, r_ = le_long(sections, debut)
                r_ *= _niv(b["radius"], niv + 1)
                rad = 2.0 * math.pi * (dec + i / n_enf)
                qc = q_mul(q_, q_mul(q_axe(Y, rad), q_axe(X, math.radians(_niv(b["angle"], niv + 1)))))
                lg = _niv(b["length"], niv + 1) * ((1.0 - debut) if persistant else 1.0)
                file.append((o_, qc, float(lg), float(r_), niv + 1, int(_niv(b["sections"], niv + 1)),
                             int(_niv(b["segments"], niv + 1))))

    def fin(V, N, UV, T):
        if not V:
            return dict(V=np.zeros((0, 3)), N=np.zeros((0, 3)), UV=np.zeros((0, 2)), T=np.zeros((0, 3), np.int64))
        return dict(V=np.vstack(V), N=np.vstack(N), UV=np.vstack(UV), T=np.vstack(T).astype(np.int64))

    br, fl = fin(BV, BN, BUV, BT), fin(FV, FN, FUV, FT)
    # repère de la scène: Y vers le haut (three.js) -> Z vers le haut (Blender), puis normalisation
    for d in (br, fl):
        for k in ("V", "N"):
            d[k] = np.stack([d[k][:, 0], -d[k][:, 2], d[k][:, 1]], 1)
    tout = np.vstack([br["V"], fl["V"]])
    h = max(float(tout[:, 2].max()), 1e-6)
    rc = float(np.percentile(np.hypot(fl["V"][:, 0], fl["V"][:, 1]), 98)) if len(fl["V"]) else 1.0
    rc = max(rc, 1e-6)
    for d in (br, fl):
        d["V"] = d["V"] / np.array([rc, rc, h])
    return dict(branches=br, feuilles=fl, hauteur=h, rayon=rc, ecorce=o["bark"]["type"], feuillage=fe["type"],
                alpha_seuil=float(fe.get("alphaTest", 0.5)))


def resume(geo):
    return (f"{len(geo['branches']['T'])} triangles de branches, {len(geo['feuilles']['T'])} de feuillage "
            f"(hauteur d'origine {geo['hauteur']:.1f}, couronne {geo['rayon']:.1f})")


if __name__ == "__main__":
    import time
    for nom in ("pine_large", "pine_medium", "ash_medium", "bush_1"):
        t0 = time.time()
        g = generer(charger_preset(nom))
        print(f"{nom:12s} {resume(g)}  {time.time() - t0:.2f} s")
