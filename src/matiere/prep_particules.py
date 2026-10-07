#!/usr/bin/env python3
"""
prep_particules.py : PLY (simulation MPM de Johan Gaume) -> .npy allégés pour Blender.

Pourquoi : Blender importe mal 7,85 M de points en double précision, et les 600 Go
bruts sont inutilisables. Ce script lit les PLY en memmap (RAM quasi nulle), garde
1 particule sur N, recentre en float64 puis stocke en float32 (7 colonnes :
x y z vx vy vz mu_b, repère de la simulation, Y vertical comme Houdini).

Usage :
    python prep_particules.py Data_Johan --out cache --stride 10
    python prep_particules.py Data_Johan/all_particles_1500.ply --out cache --stride 10
    # nouveaux fichiers plus tard : relancer la même commande, l'origine est conservée
    # et la liste meta.json est complétée.

Dépendances : numpy (scipy facultatif, sert à estimer l'espacement des particules).
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np

PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}
COLS = ["x", "y", "z", "vx", "vy", "vz", "mu_b"]


def read_header(path):
    """Retourne (dtype numpy, nb de sommets, offset des données)."""
    fmt, n, props, cur = None, None, [], None
    with open(path, "rb") as f:
        while True:
            line = f.readline()
            if not line:
                raise ValueError(f"{path}: en-tête PLY incomplet")
            s = line.decode("ascii", "replace").strip()
            if s.startswith("format"):
                fmt = s.split()[1]
            elif s.startswith("element"):
                cur = s.split()[1]
                if cur == "vertex":
                    n = int(s.split()[2])
            elif s.startswith("property") and cur == "vertex":
                parts = s.split()
                if parts[1] == "list":
                    raise ValueError("propriété list non gérée sur les sommets")
                props.append((parts[2], parts[1]))
            elif s == "end_header":
                off = f.tell()
                break
    if fmt not in ("binary_little_endian", "binary_big_endian"):
        raise ValueError(f"{path}: format {fmt} non géré (binaire attendu)")
    end = "<" if fmt == "binary_little_endian" else ">"
    dt = np.dtype([(name, end + PLY_TYPES[t]) for name, t in props])
    return dt, n, off


def open_ply(path):
    dt, n, off = read_header(path)
    size = os.path.getsize(path)
    avail = (size - off) // dt.itemsize
    if avail < n:  # fichier tronqué (téléchargement interrompu)
        print(f"  ! {os.path.basename(path)} tronqué: {avail}/{n} sommets lus", file=sys.stderr)
        n = avail
    return np.memmap(path, dtype=dt, mode="r", offset=off, shape=(n,))


def strided(a, stride, offset=0, chunk=2_000_000):
    """Générateur de blocs (float64) des colonnes COLS, 1 ligne sur `stride`."""
    sel = a[offset::stride]
    names = a.dtype.names
    for i in range(0, len(sel), chunk):
        blk = sel[i:i + chunk]
        out = np.zeros((len(blk), 7), np.float64)
        for j, c in enumerate(COLS):
            if c in names:
                out[:, j] = blk[c]
        yield out


def step_of(path):
    m = re.findall(r"(\d+)", os.path.splitext(os.path.basename(path))[0])
    return int(m[-1]) if m else 0


def collect(inputs):
    files = []
    for p in inputs:
        if os.path.isdir(p):
            files += glob.glob(os.path.join(p, "*.ply"))
        elif any(ch in p for ch in "*?["):
            files += glob.glob(p)
        else:
            files.append(p)
    return sorted(set(files), key=step_of)


def nn_spacing(P, k=40000, seed=0):
    """Espacement typique des particules (m) dans le jeu allégé: plus proche voisin (scipy) ou densité par cellules."""
    try:
        from scipy.spatial import cKDTree
    except Exception:
        # repli numpy : densité par cellules de 20 m, quartile le plus dense
        L = 20.0
        cell = np.floor(P / L).astype(np.int64)
        _, cnt = np.unique(cell, axis=0, return_counts=True)
        dense = cnt[cnt >= np.percentile(cnt, 75)]
        return float((L ** 3 / np.median(dense)) ** (1 / 3))
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(P), size=min(k, len(P)), replace=False)
    d, _ = cKDTree(P).query(P[idx], k=2)
    return float(np.median(d[:, 1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="dossier(s), fichier(s) ou glob PLY")
    ap.add_argument("--out", default="cache", help="dossier de sortie (npy + meta.json)")
    ap.add_argument("--stride", type=int, default=10, help="1 particule sur N (défaut 10)")
    ap.add_argument("--every", type=int, default=1, help="ne garder qu'un fichier sur K")
    ap.add_argument("--origin", type=float, nargs=3, metavar=("X", "Y", "Z"),
                    help="origine de recentrage (repère simulation). Défaut: milieu de X et Z, Y=0")
    ap.add_argument("--reset", action="store_true", help="ignorer un meta.json existant")
    # sous Blender (-b -P ... -- args), les arguments utiles suivent "--"
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)

    files = collect(a.inputs)[::a.every]
    if not files:
        sys.exit("Aucun PLY trouvé.")
    os.makedirs(a.out, exist_ok=True)
    meta_path = os.path.join(a.out, "meta.json")
    meta = {}
    if os.path.exists(meta_path) and not a.reset:
        meta = json.load(open(meta_path))
        if meta.get("stride") != a.stride:
            sys.exit(f"meta.json existant avec stride={meta.get('stride')}; utilise --reset ou le même --stride.")

    origin = meta.get("origin") or a.origin
    entries = {e["file"]: e for e in meta.get("files", [])}
    speeds_all = []

    for path in files:
        out_name = os.path.splitext(os.path.basename(path))[0] + ".npy"
        out_path = os.path.join(a.out, out_name)
        print(f"{os.path.basename(path)} ...", flush=True)
        arr = open_ply(path)
        if origin is None:  # calculé sur le premier fichier, ~1/100 des points
            s = np.concatenate(list(strided(arr, max(a.stride * 10, 100))))
            lo, hi = np.percentile(s[:, [0, 2]], [1, 99], axis=0)
            origin = [float((lo[0] + hi[0]) / 2), 0.0, float((lo[1] + hi[1]) / 2)]
            print(f"  origine auto (repère simulation): {origin}")
        o = np.array(origin + [0, 0, 0, 0], np.float64)
        blocks = [(b - o).astype(np.float32) for b in strided(arr, a.stride)]
        data = np.concatenate(blocks) if blocks else np.zeros((0, 7), np.float32)
        np.save(out_path, data)
        sp = np.linalg.norm(data[:, 3:6], axis=1)
        speeds_all.append(sp[:: max(1, len(sp) // 200000)])
        entries[out_name] = {"file": out_name, "step": step_of(path), "count": int(len(data))}
        print(f"  -> {out_name}: {len(data):,} particules ({data.nbytes / 1e6:.0f} Mo)")

        if "stats" not in meta:  # statistiques de calage, sur le premier fichier traité
            moving = sp > 1.0
            slow = ~moving
            st = {
                "bounds_min": data[:, :3].min(0).tolist(),
                "bounds_max": data[:, :3].max(0).tolist(),
                "speed_pct": {str(p): float(np.percentile(sp, p)) for p in (50, 90, 99, 99.5)},
                "moving_centroid": data[moving, :3].mean(0).tolist() if moving.any() else None,
                "moving_mean_velocity": data[moving, 3:6].mean(0).tolist() if moving.any() else None,
                "rest_centroid": np.median(data[slow, :3], axis=0).tolist() if slow.any() else None,
                "nn_median": nn_spacing(data[:, :3]),
                "mu_b_constant": bool(np.ptp(data[:, 6]) == 0),
            }
            meta["stats"] = st

    vmax = float(np.percentile(np.concatenate(speeds_all), 99.5)) if speeds_all else 1.0
    meta.update({
        "origin": origin,
        "stride": a.stride,
        "up_axis": "Y",
        "columns": COLS,
        "vmax": max(vmax, meta.get("vmax", 0.0)),
        "files": sorted(entries.values(), key=lambda e: e["step"]),
    })
    json.dump(meta, open(meta_path, "w"), indent=2)
    print(f"meta.json écrit ({len(meta['files'])} fichier(s)), vmax={meta['vmax']:.1f} m/s")


if __name__ == "__main__":
    main()
