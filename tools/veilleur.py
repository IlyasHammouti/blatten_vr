#!/usr/bin/env python3
"""Veilleur de nuit: exécute l'une après l'autre les commandes blatten.py listées dans nuit/file.txt (fichier du dépôt git).
Chaque ligne: <identifiant> <arguments de blatten.py>. Une ligne déjà faite (identifiant dans render/nuit/faits.txt) n'est pas refaite.
Entre deux commandes: git fetch + reset (la file et le code se mettent à jour depuis GitHub), attente tant qu'un Blender tourne.
Journal: render/nuit/journal.txt; sortie de chaque commande: render/nuit/<identifiant>.log. Ligne "stop" dans la file: arrêt.
N'exécute que blatten.py. Empêche la mise en veille du PC tant qu'il tourne."""
import os, shlex, subprocess, sys, time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = os.path.join(RACINE, "nuit", "file.txt")
DOS = os.path.join(RACINE, "render", "nuit")
FAITS = os.path.join(DOS, "faits.txt")
JOURNAL = os.path.join(DOS, "journal.txt")


def note(msg):
    ligne = f"[{time.strftime('%d/%m %H:%M:%S')}] {msg}"
    print(ligne, flush=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(ligne + "\n")


def blender_tourne():
    try:
        s = subprocess.run(["tasklist", "/FI", "IMAGENAME eq blender.exe", "/NH"], capture_output=True, text=True, errors="replace").stdout
        return "blender.exe" in s.lower()
    except Exception:
        return False


def faits():
    try:
        return {l.split()[0] for l in open(FAITS, encoding="utf-8") if l.strip()}
    except OSError:
        return set()


def file_attente():
    try:
        lignes = [l.strip() for l in open(FILE, encoding="utf-8")]
    except OSError:
        return []
    return [l for l in lignes if l and not l.startswith("#")]


def main():
    os.makedirs(DOS, exist_ok=True)
    os.chdir(RACINE)
    try:                                   # pas de mise en veille tant que le veilleur tourne (demande propre au processus)
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    except Exception:
        pass
    note("veilleur démarré")
    calme = 0
    dernier_etat = ""
    while True:
        if blender_tourne():
            calme = 0
            if dernier_etat != "attente":
                note("un Blender tourne déjà: j'attends qu'il finisse")
                dernier_etat = "attente"
            time.sleep(60)
            continue
        calme += 1
        if calme < 2:                      # deux contrôles de suite sans Blender (trou entre deux paquets d'un rendu en cours)
            time.sleep(45)
            continue
        subprocess.call(["git", "fetch", "-q", "origin"])
        subprocess.call(["git", "reset", "-q", "--hard", "origin/main"])
        deja = faits()
        prochaine = None
        for l in file_attente():
            ident = l.split()[0]
            if ident == "stop":
                if "stop" not in deja:
                    note("ligne stop: fin du veilleur")
                    return 0
                continue
            if ident not in deja:
                prochaine = l
                break
        if not prochaine:
            if dernier_etat != "vide":
                note("file vide: j'attends de nouvelles commandes")
                dernier_etat = "vide"
            time.sleep(60)
            continue
        ident, args = prochaine.split()[0], shlex.split(prochaine, posix=True)[1:]
        note(f"début {ident}: blatten.py {' '.join(args)}")
        dernier_etat = "travail"
        t0 = time.time()
        with open(os.path.join(DOS, ident + ".log"), "w", encoding="utf-8", errors="replace") as log:
            try:
                rc = subprocess.call([sys.executable, "blatten.py"] + args, stdout=log, stderr=subprocess.STDOUT)
            except Exception as e:
                rc = f"exception {e}"
        with open(FAITS, "a", encoding="utf-8") as f:
            f.write(f"{ident} rc={rc} {time.strftime('%d/%m %H:%M')} {round((time.time() - t0) / 60)}min\n")
        note(f"fin {ident}: code {rc}, {round((time.time() - t0) / 60)} min")
        calme = 0


if __name__ == "__main__":
    sys.exit(main())
