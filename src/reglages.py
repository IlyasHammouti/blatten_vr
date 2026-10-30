"""
reglages.py : jeux de réglages nommés (dossier reglages/ à la racine du dépôt), pour essayer plusieurs rendus sans toucher au code.

Un jeu est un fichier JSON  reglages/<nom>.json  découpé en sections, une par partie de la scène :
    {
      "_doc": "à quoi sert ce jeu (affiché dans le journal)",
      "herite": ["autre_jeu"],          facultatif: jeux appliqués avant celui-ci (dans l'ordre)
      "scene":     { ... },             clés de CFG de src/scene/blatten_blender.py (ex. "fog": 0.5, "tree_dist": 3000)
      "matiere":   { ... },             REGLAGES de src/matiere/matiere_roches.py (rendu "roches" ou "surface", couleurs, blocs...)
      "depot":     { ... },             REGLAGES de src/matiere/depot.py
      "poussiere": { ... }              REGLAGES de src/matiere/poussiere.py
    }
Les valeurs absentes gardent la valeur par défaut écrite dans le module (en tête de chaque fichier, avec leur explication).

Ligne de commande (blatten.py transmet tout au script de scène):
    --reglages surface poussiere_v2          plusieurs jeux, appliqués dans l'ordre (le dernier gagne)
    --set poussiere.densite=0.02             une valeur précise, appliquée après les jeux (répétable)
    --set matiere.rendu="surface"            (valeur JSON; texte sans guillemets accepté)

Aucune dépendance (Python 3.8+): utilisé à la fois par blatten.py et, dans Blender, par la scène.
"""
import json
import os

SECTIONS = ("scene", "matiere", "depot", "poussiere")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(ROOT, "reglages")


def chemin(nom, dossier=None):
    """Nom de jeu (sans .json) ou chemin d'un fichier."""
    if nom.endswith(".json") or os.sep in nom or "/" in nom:
        return os.path.abspath(nom)
    return os.path.join(dossier or DOSSIER, nom + ".json")


def lister(dossier=None):
    """{nom: _doc} des jeux disponibles."""
    d = dossier or DOSSIER
    out = {}
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json") and not f.startswith("_"):
                try:
                    out[f[:-5]] = json.load(open(os.path.join(d, f), encoding="utf-8")).get("_doc", "")
                except Exception as e:
                    out[f[:-5]] = f"(illisible: {e})"
    return out


def _fusion(dst, src):
    for sec, vals in src.items():
        if sec.startswith("_") or sec == "herite":
            continue
        if sec not in SECTIONS:
            raise ValueError(f"section inconnue '{sec}' (sections possibles: {', '.join(SECTIONS)})")
        if not isinstance(vals, dict):
            raise ValueError(f"la section '{sec}' doit être un objet JSON {{...}}")
        dst.setdefault(sec, {}).update(vals)


def charger(noms, dossier=None, _vus=None):
    """Fusionne les jeux dans l'ordre (avec leurs 'herite'). Rend ({section: {clé: valeur}}, [noms appliqués])."""
    out, appliques = {}, []
    vus = _vus if _vus is not None else set()
    for nom in noms or []:
        p = chemin(nom, dossier)
        if not os.path.exists(p):
            dispo = ", ".join(lister(dossier)) or "aucun"
            raise FileNotFoundError(f"jeu de réglages introuvable: {p} (disponibles: {dispo})")
        if p in vus:
            continue
        vus.add(p)
        d = json.load(open(p, encoding="utf-8"))
        h = d.get("herite") or []
        if isinstance(h, str):
            h = [h]
        if h:
            sous, sous_noms = charger(h, os.path.dirname(p), vus)
            for sec, vals in sous.items():
                out.setdefault(sec, {}).update(vals)
            appliques += sous_noms
        _fusion(out, d)
        appliques.append(os.path.splitext(os.path.basename(p))[0])
    return out, appliques


def _valeur(txt):
    try:
        return json.loads(txt)
    except ValueError:
        low = txt.strip().lower()
        if low in ("vrai", "oui"):
            return True
        if low in ("faux", "non"):
            return False
        return txt


def appliquer_set(regl, affectations):
    """affectations: ["poussiere.densite=0.02", ...]. Modifie regl en place et le rend."""
    for a in affectations or []:
        if "=" not in a or "." not in a.split("=", 1)[0]:
            raise ValueError(f"--set attend section.cle=valeur (exemple: poussiere.densite=0.02), reçu: {a}")
        cle, v = a.split("=", 1)
        sec, k = cle.split(".", 1)
        if sec not in SECTIONS:
            raise ValueError(f"--set {a}: section inconnue '{sec}' (sections: {', '.join(SECTIONS)})")
        regl.setdefault(sec, {})[k.strip()] = _valeur(v)
    return regl


def resume(regl):
    """Une ligne lisible par section, pour le journal."""
    lignes = []
    for sec in SECTIONS:
        if regl.get(sec):
            lignes.append(f"{sec}: " + ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in regl[sec].items()))
    return lignes


def avec_defauts(defauts, regl, section, inconnues=None):
    """Copie de defauts mise à jour par regl[section]; les clés absentes des défauts sont signalées (faute de frappe probable)."""
    r = dict(defauts)
    for k, v in (regl or {}).get(section, {}).items():
        if k not in defauts and inconnues is not None:
            inconnues.append(f"{section}.{k}")
        if isinstance(r.get(k), (list, tuple)) and isinstance(v, list):
            v = type(r[k])(v) if isinstance(r[k], tuple) else v
        r[k] = v
    return r
