"""Bilan du banc d'essai du PC du frere (Lancer_bench_frere.bat).
Lit render/bench_frere/ordre.txt (une ligne par essai: etiquette) et les dossiers render/tests/final/* crees depuis,
puis ecrit le tableau des temps par image et l'estimation du film entier a 30 et 25 images par seconde.
    python tools/bench_frere.py"""
import json, os, sys, glob
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, "render", "bench_frere")
ordre = [l.strip() for l in open(os.path.join(B, "ordre.txt"), encoding="utf-8") if l.strip()]
t_debut = os.path.getmtime(os.path.join(B, "debut.txt"))
dossiers = sorted(d for d in glob.glob(os.path.join(ROOT, "render", "tests", "final", "*"))
                  if os.path.exists(os.path.join(d, "bilan.json")) and os.path.getmtime(os.path.join(d, "bilan.json")) >= t_debut - 5)
cfg = json.load(open(os.path.join(ROOT, "reglages", "film.json"), encoding="utf-8")).get("scene", {})
intro = float(cfg.get("intro", 8.0)); duree_evt = 53.0

def film(ts, ms, fps):
    n_evt = int(round(duree_evt * fps)); n_intro = int(round(intro * fps))
    ms = [max(0.5, m - 1.0) for m in ms]
    evt = np.interp(np.arange(n_evt) / fps, ts, ms).sum()
    return (evt + (n_intro // 2) * np.interp(0.0, ts, ms)) / 60

lignes = []
for tag, d in zip(ordre, dossiers):
    bil = [b for b in json.load(open(os.path.join(d, "bilan.json"), encoding="utf-8")) if b.get("variante") == "A_film" and b.get("ok")]
    bil.sort(key=lambda b: b["t"])
    if not bil:
        lignes.append(f"{tag:<22} ECHEC ou vide ({os.path.basename(d)})"); continue
    ts = [b["t"] for b in bil]; ms = [b["minutes"] for b in bil]
    txt = "  ".join(f"t={t:g}s {m:.1f} min (carte {b.get('carte_mo_max')}/{b.get('carte_mo_total')} Mo, RAM libre {b.get('ram_libre_min_go')} Go)"
                    for t, m, b in zip(ts, ms, bil))
    if len(ts) >= 2:
        txt += f"\n{'':<22} film complet: {film(ts, ms, 30):.0f} h a 30 i/s, {film(ts, ms, 25):.0f} h a 25 i/s (seul, sans le temps de la fin du film non mesure)"
    lignes.append(f"{tag:<22} {txt}")
out = os.path.join(B, "bilan_bench.txt")
open(out, "w", encoding="utf-8").write("\n".join(lignes) + "\n")
print("\n".join(lignes)); print("\nEcrit:", out)
