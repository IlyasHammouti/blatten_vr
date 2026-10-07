"""
installer_bibliotheques.py : installe tifffile et imagecodecs (lecture des GeoTIFF swisstopo)
dans le dossier .pylibs/ de la racine du dépôt (ignoré par git). À lancer une seule fois, via Blender :
  blender -b -P installer_bibliotheques.py
Nécessite Internet (téléchargement depuis PyPI). N'installe rien ailleurs sur l'ordinateur.
"""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
root = os.environ.get("BLATTEN_ROOT") or os.path.dirname(os.path.dirname(here))
target = os.path.join(root, ".pylibs")
os.makedirs(target, exist_ok=True)
py = sys.executable
try:
    import bpy
    py = getattr(bpy.app, "binary_path_python", "") or sys.executable
except Exception:
    pass
print("[install] Python utilisé:", py)
print("[install] Python version:", sys.version.split()[0])
try:
    subprocess.run([py, "-m", "ensurepip"], check=False)
except Exception as e:
    print("[install] ensurepip ignoré:", e)
cmd = [py, "-m", "pip", "install", "--no-deps", "--upgrade", "--target", target, "tifffile", "imagecodecs"]
print("[install]", " ".join(cmd))
r = subprocess.run(cmd)
if r.returncode != 0:
    print("[install] ECHEC de l'installation (code %d). Copie le message ci-dessus." % r.returncode)
    sys.exit(r.returncode)
sys.path.insert(0, target)
try:
    import tifffile
    import imagecodecs
    print("[install] OK: tifffile", tifffile.__version__, "imagecodecs", imagecodecs.__version__)
except Exception as e:
    print("[install] Installé mais l'import échoue:", e)
    sys.exit(1)
