"""
test_duo.py : vérifie le protocole du rendu à deux PC (src/partage/duo.py) sans Blender ni réseau.

    python tools/test_duo.py

1. listes compactes d'images, plan du film (intro une image sur deux), copies
2. simulation en temps virtuel du vrai film (1710 images à calculer, coût par image croissant avec la poussière, 3 min de
   construction de scène par paquet): RTX 2060 (Ilyas) et RTX 3060 (1,6 fois plus rapide). On vérifie: aucune image faite
   deux fois, toutes faites, fins proches; puis la même chose quand le PC du frère s'arrête en route ou démarre en retard.
"""
import importlib.util
import os
import random
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("duo", os.path.join(ICI, "..", "src", "partage", "duo.py"))
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


def test_plages():
    rnd = random.Random(1)
    for _ in range(300):
        n = rnd.randint(0, 80)
        xs = sorted(set(rnd.sample(range(1, 400), n)) | set(range(10, 10 + rnd.randint(0, 30))) | set(range(101, 160, 2)))
        assert D.deplages(D.plages(xs)) == xs, xs
    assert D.plages([1, 3, 5, 7, 9, 10, 11, 12, 30]) == "1-9:2,10-12,30"
    assert D.deplages("") == [] and D.plages([]) == ""


def test_plan():
    pl = D.plan(1830, 240, 2, 1)
    assert len(pl) == 120 + 1590 and pl[0] == (1, 2) and pl[119] == (239, 2) and pl[120] == (241, 1)
    cp = D.copies(pl, 1830)
    assert len(cp) == 120 and cp[0] == (1, 2) and cp[-1] == (239, 240)
    assert {f for f, _ in pl} | {d for _, d in cp} == set(range(1, 1831))


def cout(f):
    """Minutes par image sur la RTX 2060, construction de scène non comprise (ordre de grandeur des mesures de nov.)."""
    if f <= 240:
        return 3.5
    e = (f - 241) / 1590
    return 4.5 + 5.0 * min(1.0, e / 0.8)


def simuler(vitesse_frere=1.6, mort_frere=None, retard_frere=0.0, K=10, bruit=0.08, graine=0):
    rnd = random.Random(graine)
    pl = D.plan(1830, 240, 2, 1)
    ordre, pas = [f for f, _ in pl], dict(pl)
    ag = {"ilyas": dict(v=1.0, sens=1, fait=set(), cours=set(), tc=None, vit=None, maj=0.0, libre=0.0, fin=None, etat="rend"),
          "frere": dict(v=vitesse_frere, sens=-1, fait=set(), cours=set(), tc=None, vit=None, maj=-1e9, libre=retard_frere * 3600,
                        fin=None, etat="rend")}
    rendus = {}
    t = 0.0
    evts = []
    while True:
        prets = [(a["libre"], r) for r, a in ag.items() if a["fin"] is None and a["libre"] <= t + 1e-9]
        if not prets:
            futurs = [a["libre"] for a in ag.values() if a["fin"] is None]
            if not futurs:
                break
            t = min(futurs)
            continue
        _, r = min(prets)
        a = ag[r]
        o = ag["frere" if r == "ilyas" else "ilyas"]
        if mort_frere is not None and r == "frere" and t >= mort_frere * 3600:
            a["fin"] = t            # arrêté pendant ce paquet: ses images en cours sont perdues, son annonce reste
            continue
        # fin du paquet en cours: les images deviennent faites
        if a["cours"]:
            a["fait"] |= a["cours"]
            a["cours"] = set()
            a["tc"] = None
        a["maj"] = t
        autre = None
        if o["maj"] > -1e8:
            maj_o = o["maj"] if not (r == "ilyas" and mort_frere is not None and t >= mort_frere * 3600) else min(o["maj"], mort_frere * 3600)
            autre = dict(fait=set(o["fait"]), cours=set(o["cours"]), tc=o["tc"], vit=o["vit"], maj=maj_o, etat=o["etat"], role=None)
        vivant = D.est_vivant(autre, t)
        vm = a["vit"]
        va = (autre or {}).get("vit")
        ratio = vitesse_frere if r == "ilyas" else 1 / vitesse_frere
        if vm is None and va:
            vm = va / ratio
        if va is None and vm:
            va = vm * ratio
        images, raison = D.choisir(ordre, pas, a["fait"], autre, a["sens"], K, vm, va, t, vivant)
        if images:
            dur = 3.0 + sum(cout(f) for f in images) / a["v"] * (1 + rnd.uniform(-bruit, bruit))
            a["cours"], a["tc"], a["libre"] = set(images), t, t + dur * 60
            v = len(images) / (dur / 60)
            a["vit"] = v if a["vit"] is None else 0.3 * a["vit"] + 0.7 * v
            for f in images:
                rendus[f] = rendus.get(f, 0) + 1
            evts.append((t, r, images[0], images[-1]))
        elif raison == "attendre":
            a["libre"] = t + 180
            a["etat"] = "attente"
        else:
            a["fin"] = t
            a["etat"] = "fini"
    doubles = sum(c - 1 for c in rendus.values() if c > 1)
    manque = [f for f in ordre if f not in rendus]
    fins = {r: a["fin"] / 3600 for r, a in ag.items()}
    travail_h = (sum(cout(f) for f in ordre)) / 60
    return dict(doubles=doubles, manque=len(manque), fins=fins, seul_h=travail_h, evts=evts,
                ideal_h=(travail_h + 3 * len(ordre) / K / 60) / (1 + vitesse_frere) + retard_frere * vitesse_frere / (1 + vitesse_frere))


def test_simulation():
    for vf in (1.0, 1.6, 2.5):
        for g in range(3):
            r = simuler(vitesse_frere=vf, graine=g)
            fin = max(r["fins"].values())
            ecart = abs(r["fins"]["ilyas"] - r["fins"]["frere"])
            assert r["manque"] == 0 and r["doubles"] == 0, r
            assert ecart < 0.5, (vf, r["fins"])           # les deux PC finissent à moins de 30 min d'écart
            assert fin < r["ideal_h"] * 1.06 + 0.3, (fin, r["ideal_h"])   # idéal approché (constructions de scène comptées à part)
        print(f"  frère x{vf}: fin {fin:.1f} h (Ilyas seul: {r['seul_h']:.0f} h de calcul + constructions), écart entre PC "
              f"{60 * ecart:.0f} min, idéal {r['ideal_h']:.1f} h")
    r = simuler(mort_frere=20)
    assert r["manque"] == 0, r
    print(f"  frère arrêté à 20 h: tout est fait, Ilyas finit à {r['fins']['ilyas']:.1f} h (reprise après 2 h de silence), "
          f"{r['doubles']} image(s) refaite(s)")
    r = simuler(retard_frere=24)
    assert r["manque"] == 0 and r["doubles"] == 0, r
    print(f"  frère démarré 24 h après: fin {max(r['fins'].values()):.1f} h, écart {60 * abs(r['fins']['ilyas'] - r['fins']['frere']):.0f} min")


def test_conflit():
    autre = dict(cours={10, 11, 12}, fait=set(), role="frere", t_cours_serveur=100.0, maj=100.0)
    assert D.retirer_conflit([8, 9, 10, 11], autre, +1, 105.0, "ilyas") == [8, 9]     # il était là avant
    assert D.retirer_conflit([8, 9, 10, 11], autre, +1, 95.0, "ilyas") == [8, 9, 10, 11]
    assert D.retirer_conflit([8, 9, 10, 11], autre, +1, 100.0, "ilyas") == [8, 9, 10, 11]   # égalité: Ilyas garde
    autre = dict(cours={10, 11}, fait=set(), role="ilyas", t_cours_serveur=100.0, maj=100.0)
    assert D.retirer_conflit([10, 11, 12, 13], autre, -1, 100.0, "frere") == [12, 13]


if __name__ == "__main__":
    test_plages()
    test_plan()
    test_conflit()
    print("plages, plan, conflits: OK")
    test_simulation()
    print("simulation: OK")
