#!/usr/bin/env python3
"""
analyse_temps.py : chronologie de l'événement à partir des .npy de la simulation (aide au choix de la fenêtre de temps).

Pour chaque fichier (1 fichier = 1 s de simulation, hypothèse) : vitesse moyenne, part de particules qui bougent,
distance parcourue depuis le fichier 0 (horizontal), et quelques instants clés (début, 50 % parcouru, arrêt).
Aucune dépendance autre que numpy (matplotlib facultatif : trace un graphique PNG si présent).

Usage (depuis la racine du dépôt) :
    python src/matiere/analyse_temps.py                 # lit cache_dir dans config.local.json
    python src/matiere/analyse_temps.py D:/.../cache    # ou un dossier explicite
Sorties : render/alea/chronologie.csv, render/alea/chronologie.png, et un résumé affiché.
"""
import json
import os
import sys

import numpy as np


def cache_dir():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for name in ("config.local.json", "config.json"):
        if os.path.exists(name):
            d = json.load(open(name, encoding="utf-8")).get("cache_dir")
            if d:
                return d
    sys.exit("Donne le dossier du cache (celui qui contient meta.json) en argument.")


def main():
    d = cache_dir()
    meta = json.load(open(os.path.join(d, "meta.json")))
    files = meta["files"]
    out = os.path.join("render", "alea")
    os.makedirs(out, exist_ok=True)

    a0 = np.load(os.path.join(d, files[0]["file"]), mmap_mode="r")
    p0 = np.asarray(a0[:, :3], np.float64)
    rows = []
    for i, f in enumerate(files):
        a = np.load(os.path.join(d, f["file"]), mmap_mode="r")
        if len(a) != len(p0):
            print(f"  ! fichier {i}: {len(a)} particules (attendu {len(p0)}), ignoré")
            continue
        v = np.linalg.norm(np.asarray(a[:, 3:6]), axis=1)
        disp = np.asarray(a[:, :3], np.float64) - p0
        dh = np.hypot(disp[:, 0], disp[:, 2])          # Y vertical : horizontal = (x, z)
        mov = v > 1.0
        rows.append(dict(
            i=i, step=f["step"], v_mean=v.mean(), v_p95=np.percentile(v, 95), v_max=v.max(),
            frac_mov=mov.mean(), frac_fast=(v > 20).mean(),
            d_med=np.median(dh), d_p95=np.percentile(dh, 95),
            z_mean=float(np.asarray(a[:, 1]).mean()),
        ))
        if i % 20 == 0:
            print(f"  fichier {i}/{len(files)}")

    cols = list(rows[0])
    with open(os.path.join(out, "chronologie.csv"), "w", encoding="utf-8") as fh:
        fh.write(";".join(cols) + "\n")
        for r in rows:
            fh.write(";".join(f"{r[c]:.4g}" for c in cols) + "\n")

    dp = np.array([r["d_p95"] for r in rows])
    fm = np.array([r["frac_mov"] for r in rows])
    vm = np.array([r["v_mean"] for r in rows])
    dmax = dp.max()

    def first(cond):
        k = np.flatnonzero(cond)
        return int(k[0]) if len(k) else None

    t_start = first(dp > 5)
    t_50 = first(dp > 0.5 * dmax)
    t_90 = first(dp > 0.9 * dmax)
    last_mov = np.flatnonzero(fm > 0.05)
    t_stop = int(last_mov[-1]) + 1 if len(last_mov) else None
    t_vpeak = int(np.argmax(vm))

    print("\n=== Chronologie (1 fichier = 1 s, à confirmer avec Johan) ===")
    print(f"  Début du mouvement (95 % des particules > 5 m parcourus) : t = {t_start} s")
    print(f"  Pic de vitesse moyenne                                  : t = {t_vpeak} s ({vm[t_vpeak]:.1f} m/s)")
    print(f"  50 % de la distance finale (p95, {dmax:.0f} m)            : t = {t_50} s")
    print(f"  90 % de la distance finale                              : t = {t_90} s")
    print(f"  Moins de 5 % des particules > 1 m/s                     : t = {t_stop} s")
    if t_start is not None and t_90 is not None:
        print(f"  Phase active (début -> 90 %)                            : {t_90 - t_start} s  (fenêtre vidéo visée : ~40 s)")
        print(f"  Facteur d'accélération pour tenir en 40 s               : x{(t_90 - t_start) / 40:.1f}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        t = np.arange(len(rows))
        fig, ax = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
        ax[0].plot(t, vm, label="vitesse moyenne"); ax[0].plot(t, [r["v_p95"] for r in rows], label="p95")
        ax[0].set_ylabel("m/s"); ax[0].legend()
        ax[1].plot(t, fm); ax[1].set_ylabel("part > 1 m/s")
        ax[2].plot(t, dp); ax[2].set_ylabel("distance p95 (m)"); ax[2].set_xlabel("fichier (≈ s)")
        for a_ in ax:
            for x in (t_start, t_50, t_90, t_stop):
                if x is not None:
                    a_.axvline(x, color="gray", lw=0.6, ls="--")
            a_.axvspan(t_start or 0, (t_start or 0) + 40, color="orange", alpha=0.12)
        fig.tight_layout(); fig.savefig(os.path.join(out, "chronologie.png"), dpi=120)
        print(f"\nGraphique : {os.path.join(out, 'chronologie.png')} (zone orange = 40 s à 1x depuis le début)")
    except ImportError:
        print("\n(matplotlib absent : pas de graphique, le CSV suffit)")
    print(f"CSV : {os.path.join(out, 'chronologie.csv')}")


if __name__ == "__main__":
    main()
