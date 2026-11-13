#!/usr/bin/env python3
"""Un pas du veilleur de nuit: si aucun Blender ne tourne, exécute la prochaine commande de nuit/file.txt qui n'a pas encore été faite.
Chaque ligne de la file: <identifiant> <arguments de blatten.py>. Faits: render/nuit/faits.txt. Journal: render/nuit/journal.txt.
Sortie de chaque commande: render/nuit/<identifiant>.log. Ligne "stop": le veilleur s'arrête (code 99). N'exécute que blatten.py."""
import os, shlex, subprocess, sys, time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = os.path.join(RACINE, "nuit", "file.txt")
DOS = os.path.join(RACINE, "render", "nuit")
FAITS = os.path.join(DOS, "faits.txt")
JOURNAL = os.path.join(DOS, "journal.txt")
ETAT = os.path.join(DOS, "etat.txt")


def note(msg):
    ligne = f"[{time.strftime('%d/%m %H:%M:%S')}] {msg}"
    print(ligne, flush=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(ligne + "\n")


def etat(msg):
    with open(ETAT, "w", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%d/%m %H:%M:%S')}] {msg}\n")


def blender_tourne():
    try:
        s = subprocess.run(["tasklist", "/FI", "IMAGENAME eq blender.exe", "/NH"], capture_output=True, text=True, errors="replace").stdout
        return "blender.exe" in s.lower()
    except Exception:
        return False


def main():
    os.makedirs(DOS, exist_ok=True)
    os.chdir(RACINE)
    if not os.path.exists(JOURNAL):
        note("veilleur démarré")
    if blender_tourne():
        etat("un Blender tourne: attente")
        time.sleep(30)
        return 0
    time.sleep(45)                         # deuxième contrôle: trou possible entre deux paquets d'un rendu en cours
    if blender_tourne():
        return 0
    try:
        deja = {l.split()[0] for l in open(FAITS, encoding="utf-8") if l.strip()}
    except OSError:
        deja = set()
    try:
        lignes = [l.strip() for l in open(FILE, encoding="utf-8")]
    except OSError:
        lignes = []
    prochaine = None
    for l in lignes:
        if not l or l.startswith("#"):
            continue
        ident = l.split()[0]
        if ident in deja:
            continue
        if ident == "stop":
            note("ligne stop: fin du veilleur")
            with open(FAITS, "a", encoding="utf-8") as f:
                f.write("stop\n")
            return 99
        prochaine = l
        break
    if not prochaine:
        etat("file vide: attente de nouvelles commandes")
        return 0
    ident, args = prochaine.split()[0], shlex.split(prochaine, posix=True)[1:]
    note(f"début {ident}: blatten.py {' '.join(args)}")
    etat(f"en cours: {ident}")
    t0 = time.time()
    with open(os.path.join(DOS, ident + ".log"), "w", encoding="utf-8", errors="replace") as log:
        try:
            rc = subprocess.call([sys.executable, "blatten.py"] + args, stdout=log, stderr=subprocess.STDOUT)
        except Exception as e:
            rc = f"exception {e}"
    mn = round((time.time() - t0) / 60)
    with open(FAITS, "a", encoding="utf-8") as f:
        f.write(f"{ident} rc={rc} {time.strftime('%d/%m %H:%M')} {mn}min\n")
    note(f"fin {ident}: code {rc}, {mn} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
