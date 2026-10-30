#!/usr/bin/env python3
"""
test_interpolation.py : l'interpolation entre deux fichiers de la simulation est-elle assez bonne pour 30 images/s ?

Principe : on cache un fichier au milieu (i), on le PRÉDIT à partir de ses voisins (i-1 et i+1, donc un écart de 2 s: pire cas
par rapport au vrai usage, 1 s) et on compare à la vérité. Erreur en mètres, par particule. Une particule fait 4 m: une erreur
médiane sous 1 m et un p95 sous 4 m ne se voient pas dans la vidéo. Trois méthodes :
    actuelle   : celle de Sequence.state (src/scene/blatten_blender.py): fondu entre l'extrapolation avant et arrière
    hermite    : interpolation cubique d'Hermite (positions + vitesses aux deux bouts)
    lineaire   : fondu des positions seules (référence, sans les vitesses)

Estime aussi le PAS DE TEMPS réel entre deux fichiers (1,0 s ou 1,04 s ?) : déplacement entre deux fichiers contre vitesse moyenne
(règle des trapèzes). Utile pour la question à Johan sans le déranger. N'utilise que numpy.

Usage (depuis la racine du dépôt) :
    python src/matiere/test_interpolation.py                  # cache_dir de config.local.json
    python src/matiere/test_interpolation.py D:/.../cache --sub 20 --pas 3
Sorties : render/alea/interpolation.csv et un résumé affiché.
"""
import argparse
import json
import os
import sys

import numpy as np


def cache_dir(arg):
    if arg:
        return arg
    for name in ("config.local.json", "config.json"):
        if os.path.exists(name):
            d = json.load(open(name, encoding="utf-8")).get("cache_dir")
            if d:
                return d
    sys.exit("Donne le dossier du cache (celui qui contient meta.json) en argument.")


def charge(d, files, i, idx):
    a = np.load(os.path.join(d, files[i]["file"]), mmap_mode="r")
    a = np.asarray(a[idx] if idx is not None else a, np.float64)
    return a[:, :3], a[:, 3:6]


def predit(p0, v0, p1, v1, dt, tau):
    f = tau / dt
    # actuelle (identique à Sequence.state)
    q0 = p0 + v0 * tau
    q1 = p1 - v1 * (dt - tau)
    actuelle = (1 - f) * q0 + f * q1
    # Hermite cubique
    h00, h10 = 2 * f ** 3 - 3 * f ** 2 + 1, f ** 3 - 2 * f ** 2 + f
    h01, h11 = -2 * f ** 3 + 3 * f ** 2, f ** 3 - f ** 2
    hermite = h00 * p0 + h10 * dt * v0 + h01 * p1 + h11 * dt * v1
    lineaire = (1 - f) * p0 + f * p1
    return dict(actuelle=actuelle, hermite=hermite, lineaire=lineaire)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cache", nargs="?", help="dossier du cache (meta.json + .npy)")
    ap.add_argument("--dt", type=float, default=1.0, help="durée simulée entre deux fichiers supposée (défaut 1,0 s)")
    ap.add_argument("--sub", type=int, default=20, help="une particule sur N (défaut 20, assez pour des statistiques)")
    ap.add_argument("--pas", type=int, default=3, help="un instant sur K (défaut 3)")
    a = ap.parse_args()

    d = cache_dir(a.cache)
    meta = json.load(open(os.path.join(d, "meta.json")))
    files = meta["files"]
    n = files[0]["count"]
    idx = np.arange(0, n, a.sub)
    out = os.path.join("render", "alea")
    os.makedirs(out, exist_ok=True)

    rows, dts = [], []
    for i in range(1, len(files) - 1, a.pas):
        pa, va = charge(d, files, i - 1, idx)
        pm, vm = charge(d, files, i, idx)
        pb, vb = charge(d, files, i + 1, idx)
        vit = np.linalg.norm(vm, axis=1)
        mov = vit > 1.0
        if mov.mean() < 0.02:
            continue
        # pas de temps: déplacement vs vitesse moyenne (trapèzes), sur les particules en mouvement
        w = (0.5 * (va + vm))[mov]
        dd = (pm - pa)[mov]
        den = (w * w).sum()
        if den > 0:
            dts.append(float((dd * w).sum() / den))
        pred = predit(pa, va, pb, vb, 2 * a.dt, a.dt)
        row = dict(i=i, frac_mov=float(mov.mean()), v_mean=float(vit.mean()))
        for k, p in pred.items():
            e = np.linalg.norm(p - pm, axis=1)[mov]
            row[f"{k}_med"], row[f"{k}_p95"], row[f"{k}_max"] = np.median(e), np.percentile(e, 95), e.max()
            row[f"{k}_gt2m"] = float((e > 2.0).mean())
        rows.append(row)
        if len(rows) % 10 == 0:
            print(f"  fichier {i}/{len(files)}")
    if not rows:
        sys.exit("Aucun instant avec assez de matière en mouvement.")

    cols = list(rows[0])
    with open(os.path.join(out, "interpolation.csv"), "w", encoding="utf-8") as fh:
        fh.write(";".join(cols) + "\n")
        for r in rows:
            fh.write(";".join(f"{r[c]:.4g}" for c in cols) + "\n")

    def agg(k, c):
        return np.median([r[f"{k}_{c}"] for r in rows]), np.max([r[f"{k}_{c}"] for r in rows])

    print(f"\n=== Interpolation (écart de 2 s, milieu prédit; {len(rows)} instants, 1 particule sur {a.sub}) ===")
    print("  méthode      erreur médiane (médiane / pire instant)   p95 (médiane / pire)   part > 2 m (pire)")
    for k in ("actuelle", "hermite", "lineaire"):
        m1, m2 = agg(k, "med")
        p1_, p2_ = agg(k, "p95")
        g = np.max([r[f"{k}_gt2m"] for r in rows])
        print(f"  {k:<10}   {m1:6.2f} m / {m2:6.2f} m                     {p1_:6.2f} / {p2_:6.2f} m      {100 * g:5.1f} %")
    pire = max(rows, key=lambda r: r["actuelle_p95"])
    print(f"  Pire instant (méthode actuelle): fichier {pire['i']}, p95 = {pire['actuelle_p95']:.2f} m, vitesse moyenne {pire['v_mean']:.1f} m/s")
    if dts:
        print(f"\n=== Pas de temps entre deux fichiers (déplacement / vitesse moyenne) ===")
        print(f"  médiane {np.median(dts):.3f} s, entre {np.percentile(dts, 10):.3f} et {np.percentile(dts, 90):.3f} s (10e-90e centile)")
        print("  (valeur supposée par la scène: dt_per_step = 1,0; l'hypothèse du contrat était ~1,04 s)")
    print("\nLecture: l'erreur à 1 s d'écart (usage réel) est bien plus faible que celle-ci (écart de 2 s).")
    print(f"CSV : {os.path.join(out, 'interpolation.csv')}")


if __name__ == "__main__":
    main()
