#!/usr/bin/env python3
"""Veilleur de nuit (boucle fixe, à ne pas modifier pendant qu'elle tourne): toutes les 30 s, met le dépôt à jour depuis GitHub puis
lance UN pas (tools/veilleur_pas.py, relu à chaque fois: toute la logique est là et peut être corrigée à distance par un simple push).
Le pas exécute la prochaine commande blatten.py de nuit/file.txt. Empêche la mise en veille du PC. Code de retour 99 du pas: arrêt."""
import os, subprocess, sys, time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    os.chdir(RACINE)
    os.makedirs(os.path.join(RACINE, "render", "nuit"), exist_ok=True)
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    except Exception:
        pass
    print("Veilleur de nuit: ne pas fermer cette fenêtre. Journal: render\\nuit\\journal.txt", flush=True)
    while True:
        try:
            subprocess.call(["git", "fetch", "-q", "origin"])
            subprocess.call(["git", "reset", "-q", "--hard", "origin/main"])
            rc = subprocess.call([sys.executable, os.path.join(RACINE, "tools", "veilleur_pas.py")])
        except Exception as e:
            print("veilleur:", e, flush=True)
            rc = 0
        if rc == 99:
            return 0
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
