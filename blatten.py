#!/usr/bin/env python3
"""
blatten.py : point d'entrée unique du projet Blatten VR 360.

    python blatten.py status          état des données et des réglages
    python blatten.py setup           trouve Blender, installe les bibliothèques, crée les dossiers
    python blatten.py download        télécharge les dalles swisstopo (listes dans data_sources/)
    python blatten.py prep-env        relief + image aérienne, calage sur la simulation
    python blatten.py prep-particules DOSSIER_PLY [--stride N ...]   PLY de Johan -> .npy
    python blatten.py terrain         convertit le terrain de Johan en maillage (une fois)
    python blatten.py views           8 aperçus pour choisir un point de vue
    python blatten.py test360 --vue N image test 360 basse résolution
    python blatten.py open [--vue N]  ouvre la scène dans Blender pour se promener
    python blatten.py bench           benchmark: temps de rendu de cette machine
    python blatten.py bench-compare   compare les benchmarks enregistrés (machines, clé de comparabilité)
    python blatten.py render --frames 1 1200   rendu final (garde-fous: voir docs/)
    python blatten.py menu            menu interactif

Python 3.8+ suffit (aucune bibliothèque externe). Les réglages sont dans config.json, et ceux
de VOTRE machine (chemin de Blender, dossier des données) dans config.local.json (ignoré par git).
Les arguments inconnus sont transmis tels quels au script Blender (src/scene/blatten_blender.py).
"""
import argparse
import concurrent.futures as cf
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
SCRIPTS = {
    "scene": os.path.join(SRC, "scene", "blatten_blender.py"),
    "prep_env": os.path.join(SRC, "environnement", "prep_env.py"),
    "install": os.path.join(SRC, "environnement", "installer_bibliotheques.py"),
    "prep_part": os.path.join(SRC, "matiere", "prep_particules.py"),
}


# ----------------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------------
def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config():
    cfg = _load_json(os.path.join(ROOT, "config.json"))
    local = _load_json(os.path.join(ROOT, "config.local.json"))
    for k, v in local.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def _path(p, base=ROOT):
    p = os.path.expanduser(os.path.expandvars(str(p)))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


class Paths:
    def __init__(self, cfg):
        self.data = _path(cfg.get("data_root") or "data")
        self.cache = _path(cfg["cache_dir"]) if cfg.get("cache_dir") else os.path.join(self.data, "cache")
        self.swisstopo = _path(cfg["swisstopo_dir"]) if cfg.get("swisstopo_dir") else os.path.join(self.data, "swisstopo")
        self.johan = _path(cfg["johan_dir"]) if cfg.get("johan_dir") else os.path.join(self.data, "Data_Johan")
        self.terrain_vdb = os.path.join(self.johan, cfg.get("terrain_vdb", "Nesthorn_terrain_klein.vdb"))
        self.release_vdb = os.path.join(self.johan, cfg.get("release_vdb", "Nesthorn_release_klein.vdb"))
        self.csv = os.path.join(ROOT, "data_sources", "swisstopo")


def save_local(key, value):
    path = os.path.join(ROOT, "config.local.json")
    d = _load_json(path)
    d[key] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


# ----------------------------------------------------------------------------------
# Blender
# ----------------------------------------------------------------------------------
def _blender_candidates():
    c = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), "C:\\Program Files", "F:\\Program Files (x86)"):
            if base:
                c += sorted(glob.glob(os.path.join(base, "Blender Foundation", "Blender *", "blender.exe")), reverse=True)
                c.append(os.path.join(base, "Blender", "blender.exe"))
        c += sorted(glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Blender Foundation", "Blender *", "blender.exe")), reverse=True)
    elif sys.platform == "darwin":
        c.append("/Applications/Blender.app/Contents/MacOS/Blender")
    else:
        c += ["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender"]
    return c


def find_blender(cfg, ask=True):
    for cand in (cfg.get("blender"), os.environ.get("BLENDER"), shutil.which("blender")):
        if cand and os.path.exists(_path(cand)):
            return _path(cand)
    for cand in _blender_candidates():
        if os.path.exists(cand):
            return cand
    if ask and sys.stdin.isatty():
        p = input("Blender introuvable. Collez le chemin complet de blender.exe : ").strip().strip('"')
        if p and os.path.exists(p):
            save_local("blender", p)
            print(f"Chemin enregistré dans config.local.json : {p}")
            return p
    sys.exit("Blender introuvable. Installez Blender 5.2 LTS ou indiquez son chemin dans config.local.json "
             '(clé "blender"), voir config.local.example.json.')


def run_blender(cfg, script, args, background=True, extra_env=None):
    exe = find_blender(cfg)
    cmd = [exe] + (["-b"] if background else []) + ["--python", script, "--"] + [str(a) for a in args]
    env = dict(os.environ, BLATTEN_ROOT=ROOT)
    env.update(extra_env or {})
    print("$", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    rc = subprocess.call(cmd, env=env)
    if rc != 0:
        print(f"\n!! Blender s'est terminé avec une erreur (code {rc}). Le message se trouve juste au-dessus.", flush=True)
    return rc


def scene_args(cfg, paths, with_vdb=True):
    """Arguments communs du script de scène, tirés de config.json (clé "scene") et des chemins."""
    a = ["--data", paths.cache]
    if with_vdb:
        if os.path.exists(paths.terrain_vdb):
            a += ["--terrain", paths.terrain_vdb]
        if os.path.exists(paths.release_vdb):
            a += ["--release", paths.release_vdb]
    for k, v in (cfg.get("scene") or {}).items():
        if v is None or v is False:
            continue
        flag = "--" + k.replace("_", "-")
        if v is True:
            a.append(flag)
        elif isinstance(v, (list, tuple)):
            a += [flag] + [str(x) for x in v]
        else:
            a += [flag, str(v)]
    return a


# ----------------------------------------------------------------------------------
# Commandes
# ----------------------------------------------------------------------------------
def cmd_status(cfg, paths, extra):
    def ok(b):
        return "OK " if b else "-- "
    exe = None
    try:
        exe = find_blender(cfg, ask=False)
    except SystemExit:
        pass
    print(f"Racine du dépôt : {ROOT}")
    print(f"{ok(exe)}Blender : {exe or 'introuvable (python blatten.py setup)'}")
    print(f"{ok(os.path.isdir(paths.data))}Données : {paths.data}")
    print(f"{ok(os.path.isdir(os.path.join(ROOT, '.pylibs')))}Bibliothèques swisstopo (.pylibs) installées")
    for ds in ("swissalti3d_2m", "swissimage_2m"):
        n = len(glob.glob(os.path.join(paths.swisstopo, ds, "*.tif")))
        print(f"{ok(n)}swisstopo/{ds} : {n} dalles")
    print(f"{ok(os.path.exists(paths.terrain_vdb))}VDB terrain de Johan : {paths.terrain_vdb}")
    print(f"{ok(os.path.exists(paths.release_vdb))}VDB zone de départ : {paths.release_vdb}")
    meta = os.path.join(paths.cache, "meta.json")
    n = 0
    if os.path.exists(meta):
        n = len(_load_json(meta).get("files", []))
    print(f"{ok(n)}Particules converties (cache/meta.json) : {n} fichier(s)")
    ply = glob.glob(os.path.join(paths.johan, "**", "*.ply"), recursive=True)
    print(f"   PLY de Johan présents : {len(ply)}")
    tm = sorted(os.path.basename(p) for p in glob.glob(os.path.join(paths.cache, "Terrain_mesh_*m.blend")))
    print(f"{ok(tm)}Maillages du terrain : {', '.join(tm) or 'aucun (python blatten.py terrain)'}")
    env = os.path.join(paths.cache, "env", "env_meta.json")
    print(f"{ok(os.path.exists(env))}Environnement swisstopo préparé (cache/env)")
    cam = _load_json(os.path.join(ROOT, "camera.json"))
    print(f"{ok(cam.get('confirmed'))}Caméra : {cam.get('cam')} (confirmée : {bool(cam.get('confirmed'))})")
    b = glob.glob(os.path.join(ROOT, "bench_results", "bench_*.json"))
    print(f"   Benchmarks enregistrés : {len(b)}")


def cmd_setup(cfg, paths, extra):
    exe = find_blender(cfg)
    print("Blender :", exe)
    for d in (paths.data, paths.cache, paths.swisstopo):
        os.makedirs(d, exist_ok=True)
    print("Dossiers de données prêts :", paths.data)
    print("Installation de tifffile et imagecodecs (Internet requis) ...")
    rc = run_blender(cfg, SCRIPTS["install"], [])
    if rc == 0:
        print("\nSetup terminé. Étape suivante : python blatten.py download")
    return rc


def _parse_csvs(csv_dir, max_year):
    sets, guess = {}, {}
    for c in sorted(glob.glob(os.path.join(csv_dir, "swiss*.csv"))):
        ds = re.sub(r"_R[A-Za-z]$", "", os.path.splitext(os.path.basename(c))[0])
        sets.setdefault(ds, {})
        guess.setdefault(ds, {})
        for line in open(c, encoding="utf-8-sig"):
            u = line.strip().strip('"').strip()
            if not u.startswith("http"):
                continue
            name = os.path.basename(u)
            if "YYYY" in name:
                m = re.search(r"_(\d{4}-\d{4})_", name)
                if m:
                    guess[ds][m.group(1)] = u
                continue
            m = re.search(r"_(\d{4})_(\d{4}-\d{4})_", name)
            if not m:
                continue
            y, k = int(m.group(1)), m.group(2)
            if y > max_year:
                continue
            if k not in sets[ds] or y > sets[ds][k][1]:
                sets[ds][k] = (u, y)
    return sets, guess


def _fetch(url, dest, tries=3):
    last = ""
    for _ in range(tries):
        try:
            tmp = dest + ".part"
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            os.replace(tmp, dest)
            return True, ""
        except Exception as e:
            last = str(e)
            if os.path.exists(dest + ".part"):
                os.remove(dest + ".part")
            time.sleep(2)
    return False, last


def cmd_download(cfg, paths, extra, max_year=None, dry=False, workers=4):
    max_year = max_year or int(cfg.get("swisstopo_max_year", 2024))
    sets, guess = _parse_csvs(paths.csv, max_year)
    if not sets:
        sys.exit(f"Aucun fichier swiss*.csv dans {paths.csv}")
    for ds in sorted(sets):
        dest = os.path.join(paths.swisstopo, ds)
        os.makedirs(dest, exist_ok=True)
        items = sorted(sets[ds].values())
        todo = [(u, os.path.join(dest, os.path.basename(u))) for u, _y in items]
        todo = [(u, f) for u, f in todo if not os.path.exists(f)]
        print(f"\n=== {ds} : {len(items)} dalles, {len(items) - len(todo)} déjà présentes, {len(todo)} à télécharger (année max {max_year}) ===")
        if dry:
            continue
        done = fail = 0
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(_fetch, u, f): (u, f) for u, f in todo}
            for i, fu in enumerate(cf.as_completed(futs), 1):
                ok, err = fu.result()
                name = os.path.basename(futs[fu][1])
                done += ok
                fail += not ok
                print(f"[{i}/{len(todo)}] {'OK    ' if ok else 'ECHEC '}{name}{'' if ok else ' : ' + err}", flush=True)
        # dalles listées sans année: essais 2024 à 2019
        gk = [k for k in sorted(guess.get(ds, {})) if k not in sets[ds] and not glob.glob(os.path.join(dest, f"*_{k}_*"))]
        if gk:
            print(f"--- {len(gk)} dalles à année inconnue (essais {max_year} à {max_year - 5}) ---")
        if gk and not dry:
            for k in gk:
                got = False
                for y in range(max_year, max_year - 6, -1):
                    u = guess[ds][k].replace("YYYY", str(y))
                    f = os.path.join(dest, os.path.basename(u))
                    ok, _ = _fetch(u, f, tries=1)
                    if ok:
                        print("OK    ", os.path.basename(f), flush=True)
                        got = True
                        break
                if not got:
                    print("introuvable :", k)
        print(f"Bilan {ds} : {done} téléchargées, {fail} échecs. Relancer la commande en cas d'échec (reprise automatique).")


def cmd_prep_env(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["prep_env"], ["--swisstopo", paths.swisstopo, "--data", paths.cache] + extra)


def cmd_prep_particules(cfg, paths, extra):
    args = list(extra)
    if not any(not a.startswith("-") for a in args):
        sys.exit("Indiquez le dossier des PLY, par exemple :\n  python blatten.py prep-particules "
                 f'"{os.path.join(paths.johan, "<dossier_des_ply>")}" --stride 10')
    if "--out" not in args:
        args += ["--out", paths.cache]
    return run_blender(cfg, SCRIPTS["prep_part"], args)


def cmd_terrain(cfg, paths, extra):
    if not os.path.exists(paths.terrain_vdb):
        sys.exit(f"VDB terrain introuvable : {paths.terrain_vdb}")
    print("Conversion du terrain en maillage, du plus léger au plus fin : 24, 16, 12, 8 m.")
    print("Si Blender se ferme sur une étape, c'est un manque de mémoire : on passe à la suivante.")
    for v in (24, 16, 12, 8):
        print(f"\n--- terrain à {v} m ---")
        run_blender(cfg, SCRIPTS["scene"], ["--data", paths.cache, "--terrain", paths.terrain_vdb, "--terrain-only", v])
    print("\nMaillages obtenus :", ", ".join(sorted(os.path.basename(p) for p in glob.glob(os.path.join(paths.cache, "Terrain_mesh_*m.blend")))))


def cmd_views(cfg, paths, extra):
    rc = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--views"] + extra)
    print("Aperçus dans :", os.path.join(ROOT, "render"))
    return rc


def cmd_test360(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "test", "--render-frame", "1"] + extra)


def cmd_open(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--save"] + extra, background=False)


def cmd_bench(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--bench"] + extra)


def cmd_bench_compare(cfg, paths, extra):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bench", os.path.join(SRC, "bench", "bench.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.compare(os.path.join(ROOT, "bench_results"))


def cmd_render(cfg, paths, extra):
    a = scene_args(cfg, paths) + ["--preset", "final", "--render-anim"] + extra
    return run_blender(cfg, SCRIPTS["scene"], a)


MENU = [
    ("status", "Etat des données et des réglages"),
    ("setup", "Installation (Blender, bibliothèques, dossiers), une seule fois"),
    ("download", "Télécharger les dalles swisstopo"),
    ("terrain", "Convertir le terrain de Johan en maillage (une fois)"),
    ("prep-env", "Préparer relief + image aérienne (calage)"),
    ("views", "8 aperçus pour choisir le point de vue"),
    ("test360", "Image test 360 basse résolution"),
    ("open", "Ouvrir la scène dans Blender"),
    ("bench", "Benchmark de rendu de cette machine"),
    ("bench-compare", "Comparer les benchmarks enregistrés"),
]


def cmd_menu(cfg, paths, extra):
    while True:
        print("\n==== Blatten VR 360 ====")
        for i, (c, d) in enumerate(MENU, 1):
            print(f" {i} = {d}")
        print(" 0 = Quitter")
        ch = input("Votre choix : ").strip()
        if ch in ("", "0"):
            return 0
        if not ch.isdigit() or not 1 <= int(ch) <= len(MENU):
            continue
        name = MENU[int(ch) - 1][0]
        ex = []
        if name in ("test360", "open"):
            v = input("Numéro de vue 1 à 8 (Entrée = automatique) : ").strip()
            if v:
                ex = ["--vue", v]
        COMMANDS[name](cfg, paths, ex)
        input("\nEntrée pour revenir au menu ...")


COMMANDS = {
    "status": cmd_status, "setup": cmd_setup, "download": cmd_download, "prep-env": cmd_prep_env,
    "prep-particules": cmd_prep_particules, "terrain": cmd_terrain, "views": cmd_views, "test360": cmd_test360,
    "open": cmd_open, "bench": cmd_bench, "bench-compare": cmd_bench_compare, "render": cmd_render, "menu": cmd_menu,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument("commande", nargs="?", default="menu", choices=sorted(COMMANDS),
                    help="sans commande (double-clic), le menu s'ouvre")
    ap.add_argument("--max-year", type=int, help="download: année maximale des dalles (défaut: config)")
    ap.add_argument("--dry-run", action="store_true", help="download: compte sans télécharger")
    a, extra = ap.parse_known_args()
    cfg = load_config()
    paths = Paths(cfg)
    if a.commande == "download":
        return cmd_download(cfg, paths, extra, max_year=a.max_year, dry=a.dry_run)
    return COMMANDS[a.commande](cfg, paths, extra) or 0


def _pause():
    try:
        input("\nAppuyez sur Entrée pour fermer cette fenêtre ...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    # Fenêtre qui se ferme toute seule (double-clic): on attend Entrée à la fin, même en cas d'erreur,
    # pour pouvoir lire le message. Sans argument (double-clic), l'attente est automatique.
    # Forcer l'attente dans un terminal: ajouter --pause, ou BLATTEN_PAUSE=1.
    pause = len(sys.argv) == 1 or "--pause" in sys.argv or os.environ.get("BLATTEN_PAUSE") == "1"
    if "--pause" in sys.argv:
        sys.argv.remove("--pause")
    code = 0
    try:
        code = main() or 0
    except SystemExit as e:
        if isinstance(e.code, str):
            print("\nERREUR :", e.code)
            code = 1
        else:
            code = e.code or 0
    except KeyboardInterrupt:
        print("\nInterrompu.")
        code = 130
    except Exception:
        print("\nERREUR inattendue (copiez tout ce qui suit pour la signaler) :\n")
        traceback.print_exc()
        code = 1
    if pause:
        _pause()
    sys.exit(code)
