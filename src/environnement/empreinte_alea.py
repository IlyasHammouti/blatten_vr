"""
empreinte_alea.py : où passe la matière (simulation de Johan), pour finir l'environnement sans rien oublier.

Lit les particules préparées (cache/meta.json + .npy, prep-particules) et écrit <cache>/env/alea_empreinte.npz, grille de 4 m en LV95:
  occ    vrai là où une particule est passée, à un instant quelconque
  tarr   instant (s de simulation, depuis le premier fichier) de la première arrivée de la matière; NaN si jamais
  zfin   altitude de la surface du dépôt (plus haute particule du dernier fichier), NaN hors dépôt
  zmax   altitude maximale atteinte par une particule dans la cellule, tous instants
  x0, y1, step   coin nord-ouest (LV95) et pas

Servent: 1. visible.py garde un couloir protégé autour de l'empreinte (la coupe du relief invisible ne la touche jamais),
         2. la scène masque bâtiments et arbres à l'arrivée de la matière (ils sont balayés),
         3. l'alea peut remodeler le fond de vallée d'après zfin.
Les particules sont lues avec le pas (stride) déjà préparé; une particule fait 4 m, la grille aussi: rien ne manque.

Utilisation (via blatten.py):  python blatten.py empreinte-alea [--dt 1.0]
"""
import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
ROOT = os.environ.get("BLATTEN_ROOT") or os.path.dirname(os.path.dirname(HERE))


def log(*a):
    print("[empreinte]", *a, flush=True)


def main():
    ap = argparse.ArgumentParser(prog="empreinte_alea")
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--swisstopo")   # ignoré
    ap.add_argument("--dt", type=float, default=1.0, help="durée simulée entre deux fichiers (s)")
    ap.add_argument("--pas", type=float, default=4.0, help="pas de la grille (m)")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    a = ap.parse_args(argv)
    env = os.path.join(a.data, "env")
    meta = json.load(open(os.path.join(env, "env_meta.json")))
    pm = os.path.join(a.data, "meta.json")
    if not os.path.exists(pm):
        sys.exit("Pas de particules préparées (meta.json): lancer prep-particules d'abord.")
    pmeta = json.load(open(pm))
    files = pmeta["files"]
    t0 = time.time()
    # emprise: première passe rapide (1 particule sur 20)
    lo = np.full(2, np.inf)
    hi = np.full(2, -np.inf)
    for f in files:
        d = np.load(os.path.join(a.data, f["file"]), mmap_mode="r")[::20]
        X, Y = np.asarray(d[:, 0]), -np.asarray(d[:, 2])
        lo = np.minimum(lo, [X.min(), Y.min()])
        hi = np.maximum(hi, [X.max(), Y.max()])
    pad = 40.0
    lo, hi = lo - pad, hi + pad
    s = a.pas
    W, H = int(np.ceil((hi[0] - lo[0]) / s)), int(np.ceil((hi[1] - lo[1]) / s))
    E0 = meta["scene_E0"] + lo[0]
    N1 = meta["scene_N0"] + meta["flip"] * hi[1]
    log(f"emprise des particules: X {lo[0]:.0f}..{hi[0]:.0f}  Y {lo[1]:.0f}..{hi[1]:.0f} (repère Blender), grille {W} x {H} de {s:g} m")
    occ = np.zeros((H, W), bool)
    tarr = np.full((H, W), np.nan, np.float32)
    zmax = np.full((H, W), -np.inf, np.float32)
    zfin = np.full((H, W), -np.inf, np.float32)
    s0 = files[0]["step"]
    for k, f in enumerate(files):
        d = np.asarray(np.load(os.path.join(a.data, f["file"]), mmap_mode="r"))
        X, Y, Z = d[:, 0], -d[:, 2], d[:, 1]
        j = np.clip(((hi[1] - Y) / s).astype(np.int64), 0, H - 1)
        i = np.clip(((X - lo[0]) / s).astype(np.int64), 0, W - 1)
        t = (f["step"] - s0) * a.dt
        new = ~occ[j, i]
        # première arrivée: on retient la plus précoce parmi les particules de ce fichier
        if new.any():
            tarr[j[new], i[new]] = t
        occ[j, i] = True
        np.maximum.at(zmax, (j, i), Z.astype(np.float32))
        if k == len(files) - 1:
            np.maximum.at(zfin, (j, i), Z.astype(np.float32))
        if k % 20 == 0 or k == len(files) - 1:
            log(f"  fichier {k + 1}/{len(files)} ({time.time() - t0:.0f} s)")
    # un échantillon de particules (stride) ne remplit pas toutes les cellules: on comble par dilatation, en propageant l'instant d'arrivée
    r = max(1, int(np.ceil(0.6 * np.sqrt(float(pmeta.get("stride", 1))))))
    log(f"comblement des cellules vides: {r} cellule(s) (stride {pmeta.get('stride', 1)})")
    occ2 = occ.copy()
    for _ in range(r):
        o = occ2.copy()
        o[1:] |= occ2[:-1]; o[:-1] |= occ2[1:]; o[:, 1:] |= occ2[:, :-1]; o[:, :-1] |= occ2[:, 1:]
        ajout = o & ~occ2
        p_ = np.pad(tarr, 1, constant_values=np.nan)
        vois = np.stack([p_[:-2, 1:-1], p_[2:, 1:-1], p_[1:-1, :-2], p_[1:-1, 2:]])
        with np.errstate(all="ignore"):
            tmin = np.nanmin(np.where(np.isfinite(vois), vois, np.inf), axis=0)
        tarr = np.where(ajout & np.isfinite(tmin), tmin, tarr).astype(np.float32)
        occ2 = o
    zmax[~np.isfinite(zmax)] = np.nan
    zfin[~np.isfinite(zfin)] = np.nan
    np.savez_compressed(os.path.join(env, "alea_empreinte.npz"), occ=occ2, tarr=tarr, zfin=zfin, zmax=zmax, x0=E0, y1=N1, step=s)
    meta["alea_empreinte"] = dict(file="alea_empreinte.npz", fichiers=len(files), dt=a.dt, surface_km2=float(occ2.sum() * s * s / 1e6),
                                  duree_s=float((files[-1]["step"] - s0) * a.dt), created=time.strftime("%Y-%m-%d %H:%M"))
    json.dump(meta, open(os.path.join(env, "env_meta.json"), "w"), indent=1)
    log(f"surface balayée: {occ2.sum() * s * s / 1e6:.2f} km2, durée {(files[-1]['step'] - s0) * a.dt:.0f} s, "
        f"altitude max des particules {np.nanmax(zmax):.0f} m ({time.time() - t0:.0f} s)")
    log(f"écrit alea_empreinte.npz dans {env}")


main()
