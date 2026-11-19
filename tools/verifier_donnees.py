#!/usr/bin/env python3
"""Contrôle de cohérence entre deux PC (19 nov.): imprime l'empreinte du code et celle des données du rendu, et les écrit dans
render/empreinte_pc.json. Si les deux PC affichent les mêmes valeurs ET le même Blender, leurs images sont identiques.
   python tools/verifier_donnees.py            (empreinte complète des données: 1 à 3 minutes)
   python tools/verifier_donnees.py --rapide   (tailles seulement, quelques secondes)
Ne modifie rien d'autre que render/empreinte_pc.json. Ne lance aucun rendu."""
import hashlib, json, os, subprocess, sys, time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "src"))
os.chdir(RACINE)
import blatten as B                                    # noqa: E402
D = B._module("duo", os.path.join(B.SRC, "partage", "duo.py"))
DC = B._module("duo_commandes", os.path.join(B.SRC, "partage", "duo_commandes.py"))


def sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for bloc in iter(lambda: f.read(8 << 20), b""):
            h.update(bloc)
    return h.hexdigest()[:12]


def main():
    rapide = "--rapide" in sys.argv
    cfg = B.load_config()
    paths = B.Paths(cfg)
    rep = {"date": time.strftime("%Y-%m-%d %H:%M"), "machine": os.environ.get("COMPUTERNAME", "?")}
    rep["empreinte_code"] = D.empreinte_code(RACINE)
    try:
        rep["git"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=RACINE).stdout.strip()
        rep["git_modifie"] = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True,
                                            cwd=RACINE).stdout.strip() != ""
    except Exception:
        pass
    try:
        exe = B.find_blender(cfg, ask=False)
        rep["blender_exe"] = exe
        rep["blender_version"] = DC._version_blender(exe)
    except Exception as e:
        rep["blender_version"] = f"introuvable ({e})"
    rels = DC._donnees_paquet(paths)
    taille, manque, h = 0, [], hashlib.sha1()
    for rel in rels:
        p = os.path.join(paths.cache, rel)
        if not os.path.isfile(p):
            manque.append(rel)
            continue
        t = os.path.getsize(p)
        taille += t
        h.update(f"{rel}\0{t}\0".encode())
        if not rapide:
            h.update(sha(p).encode())
    rep["donnees_fichiers"] = len(rels)
    rep["donnees_taille_Go"] = round(taille / 1e9, 2)
    rep["donnees_manquantes"] = manque
    rep["empreinte_donnees" + ("_tailles" if rapide else "")] = h.hexdigest()[:16]
    rep["dossier_cache"] = paths.cache
    try:
        os.makedirs(os.path.join(RACINE, "render"), exist_ok=True)
        json.dump(rep, open(os.path.join(RACINE, "render", "empreinte_pc.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    except OSError:
        pass
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    return 1 if manque else 0


if __name__ == "__main__":
    sys.exit(main())
