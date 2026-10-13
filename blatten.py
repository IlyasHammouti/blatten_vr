#!/usr/bin/env python3
"""
blatten.py : point d'entrée unique du projet Blatten VR 360.

    python blatten.py status          état des données et des réglages
    python blatten.py setup           trouve Blender, installe les bibliothèques, crée les dossiers
    python blatten.py download        télécharge les dalles swisstopo (listes dans data_sources/)
    python blatten.py prep-env        relief + image aérienne, calage sur la simulation
    python blatten.py prep-env --hires   relief 0,5 m + images 50 cm / 10 cm autour de la caméra (après download)
    python blatten.py visible [--eye 1.7]   zone du relief visible depuis la caméra (fichiers à part, rien n'est écrasé)
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
import math
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
    "visible": os.path.join(SRC, "environnement", "visible.py"),
    "prep_bat": os.path.join(SRC, "environnement", "prep_batiments.py"),
    "prep_veg": os.path.join(SRC, "environnement", "prep_vegetation.py"),
    "comparer": os.path.join(SRC, "environnement", "comparer.py"),
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
            # année (ou année-mois pour les bâtiments: _2024-05_) puis clé de dalle (2628-1140 ou 1268-14)
            m = re.search(r"_(\d{4})(?:-(\d{2}))?_(\d{4}-\d{2,4})_", name)
            if not m:
                continue
            y, k = int(m.group(1)), m.group(3)
            order = y * 100 + int(m.group(2) or 0)
            if y > max_year:
                continue
            if k not in sets[ds] or order > sets[ds][k][1]:
                sets[ds][k] = (u, order)
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


def _head_size(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return None


def _print_sizes(todo):
    """Taille totale à télécharger (requêtes HEAD, rien n'est téléchargé)."""
    with cf.ThreadPoolExecutor(8) as ex:
        sizes = list(ex.map(_head_size, [u for u, _f in todo]))
    ok = [x for x in sizes if x]
    if ok:
        note = "" if len(ok) == len(sizes) else f" (taille connue pour {len(ok)} dalles sur {len(sizes)})"
        print(f"    taille à télécharger: {sum(ok) / 1e9:.2f} Go{note}")


def _lv95_to_wgs84(E, N):
    y, x = (E - 2600000.0) / 1e6, (N - 1200000.0) / 1e6
    lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return lat * 100.0 / 36.0, lon * 100.0 / 36.0


STAC = "https://data.geo.admin.ch/api/stac/v0.9/collections/{coll}/items"


def _stac_tuiles(coll, bbox, max_year, cle_res):
    """Interroge le catalogue swisstopo (STAC) et rend {feuille: (url, année)}: la dalle la plus récente <= max_year."""
    import json as _json
    url = STAC.format(coll=coll) + "?bbox=" + ",".join(f"{v:.5f}" for v in bbox) + "&limit=100"
    best = {}
    while url:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = _json.load(r)
        for it in data.get("features", []):
            m = re.search(r"_(\d{4})_(\d{4}-\d{4})", it.get("id", ""))
            if not m:
                continue
            y, k = int(m.group(1)), m.group(2)
            if y > max_year:
                continue
            for nom, a in (it.get("assets") or {}).items():
                if cle_res in nom and nom.endswith(".tif") and (k not in best or y > best[k][1]):
                    best[k] = (a["href"], y)
        url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "next"), None)
    return best


def _download_canopee(cfg, paths, max_year, dry, workers):
    """Modèle de surface swissSURFACE3D raster 0,5 m (hauteur de la végétation et des bâtiments) autour de la caméra."""
    mp = os.path.join(paths.cache, "env", "env_meta.json")
    if not os.path.exists(mp):
        sys.exit("Préparer d'abord relief + image aérienne (menus 6 et 7): l'emprise de la haute résolution en dépend.")
    d5 = _load_json(mp).get("dem05")
    if not d5:
        sys.exit("Pas de relief 0,5 m: faire d'abord la préparation de la haute résolution (menu 7).")
    x0, y1 = d5["x0"], d5["y1"]
    x1, y0 = x0 + d5["shape"][1] * d5["step"], y1 - d5["shape"][0] * d5["step"]
    la0, lo0 = _lv95_to_wgs84(x0 - 200, y0 - 200)
    la1, lo1 = _lv95_to_wgs84(x1 + 200, y1 + 200)
    dest = os.path.join(paths.swisstopo, "swisssurface3d_raster_05m")
    os.makedirs(dest, exist_ok=True)
    print("\nInterrogation du catalogue swisstopo ...")
    try:
        tuiles = _stac_tuiles("ch.swisstopo.swisssurface3d-raster", (lo0, la0, lo1, la1), max_year, "_0.5_")
    except Exception as e:
        sys.exit(f"Catalogue swisstopo injoignable: {e}\nVérifier la connexion Internet et relancer.")
    if not tuiles:
        sys.exit("Aucune dalle trouvée dans le catalogue pour cette zone.")
    todo = [(u, os.path.join(dest, os.path.basename(u))) for u, _y in sorted(tuiles.values())]
    todo = [(u, f) for u, f in todo if not os.path.exists(f)]
    ans = sorted({y for _u, y in tuiles.values()})
    print(f"=== modèle de surface 0,5 m: {len(tuiles)} dalles (années {ans}), {len(tuiles) - len(todo)} déjà présentes, {len(todo)} à télécharger ===")
    if dry:
        if todo:
            _print_sizes(todo)
        return
    done = fail = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_fetch, u, f): (u, f) for u, f in todo}
        for i, fu in enumerate(cf.as_completed(futs), 1):
            ok, err = fu.result()
            done += ok
            fail += not ok
            print(f"[{i}/{len(todo)}] {'OK    ' if ok else 'ECHEC '}{os.path.basename(futs[fu][1])}{'' if ok else ' : ' + err}", flush=True)
    print(f"Bilan: {done} téléchargées, {fail} échecs. Relancer en cas d'échec (reprise automatique).")


def cmd_download(cfg, paths, extra, max_year=None, dry=False, workers=4, jeux=None):
    max_year = max_year or int(cfg.get("swisstopo_max_year", 2024))
    if extra:   # appelé depuis le menu: options passées en liste
        if "--dry-run" in extra:
            dry = True
        if "--jeux" in extra:
            jeux = [x for x in extra[extra.index("--jeux") + 1:] if not x.startswith("--")]
    if jeux and "canopee" in jeux:
        return _download_canopee(cfg, paths, max_year, dry, workers)
    sets, guess = _parse_csvs(paths.csv, max_year)
    if not sets:
        sys.exit(f"Aucun fichier swiss*.csv dans {paths.csv}")
    for ds in sorted(sets):
        if jeux and not any(j in ds for j in jeux):
            continue
        dest = os.path.join(paths.swisstopo, ds)
        os.makedirs(dest, exist_ok=True)
        items = sorted(sets[ds].values())
        todo = [(u, os.path.join(dest, os.path.basename(u))) for u, _y in items]
        # une dalle déjà présente sous une autre année (ex. 2019 au lieu de 2024) n'est pas retéléchargée
        have = {re.sub(r"_(19|20)\d\d(-\d\d)?_", "_", n) for n in os.listdir(dest)}
        todo = [(u, f) for u, f in todo if not os.path.exists(f) and re.sub(r"_(19|20)\d\d(-\d\d)?_", "_", os.path.basename(f)) not in have]
        print(f"\n=== {ds} : {len(items)} dalles, {len(items) - len(todo)} déjà présentes, {len(todo)} à télécharger (année max {max_year}) ===")
        if dry:
            if 0 < len(todo) <= 60:
                _print_sizes(todo)
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


def cmd_prep_batiments(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["prep_bat"], ["--swisstopo", paths.swisstopo, "--data", paths.cache] + extra)


def cmd_prep_vegetation(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["prep_veg"], ["--swisstopo", paths.swisstopo, "--data", paths.cache] + extra)


def cmd_visible(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["visible"], ["--data", paths.cache] + extra)


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


def cmd_valider_env(cfg, paths, extra):
    """Rend la même image test deux fois (environnement seul, mono), avec puis sans coupe du relief invisible, et les compare."""
    d1, d2 = os.path.join(ROOT, "render", "val_cull"), os.path.join(ROOT, "render", "val_sans_cull")
    base = scene_args(cfg, paths) + ["--preset", "test", "--render-frame", "1", "--mono", "--env-only"]
    print("\n--- 1/3 image AVEC coupe du relief invisible ---")
    if run_blender(cfg, SCRIPTS["scene"], base + ["--cull", "--out", d1] + extra):
        return 1
    print("\n--- 2/3 image SANS coupe (relief complet) ---")
    if run_blender(cfg, SCRIPTS["scene"], base + ["--out", d2] + extra):
        return 1
    print("\n--- 3/3 comparaison ---")
    return run_blender(cfg, SCRIPTS["comparer"], [os.path.join(d1, "frame_0001.png"), os.path.join(d2, "frame_0001.png"),
                                                  os.path.join(ROOT, "render", "val_difference.png")])


def cmd_lite(cfg, paths, extra):
    """Version légère de l'environnement: seul le relief visible depuis la caméra, sans particules, images incluses."""
    rc = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--lite", "--preset", "test"] + extra)
    print("Fichier:", os.path.join(ROOT, "render", "blatten_env_lite.blend"))
    return rc


def cmd_env_complet(cfg, paths, extra):
    """UN SEUL CLIC: canopée, arbres, image test de l'environnement seul, puis ouverture dans la visionneuse 360.
    Une étape qui échoue n'arrête pas les suivantes (le bilan final dit ce qui a marché)."""
    etapes = [
        ("Télécharger la canopée", lambda: cmd_download(cfg, paths, ["--jeux", "canopee"])),
        ("Préparer les arbres", lambda: cmd_prep_vegetation(cfg, paths, [])),
        ("Image test de l'environnement seul", lambda: cmd_test360(cfg, paths, ["--mono", "--env-only", "--cull", "--out", "render/env_seul"])),
    ]
    bilan = []
    for i, (nom, f) in enumerate(etapes, 1):
        print(f"\n==================== {i}/{len(etapes)} : {nom} ====================", flush=True)
        try:
            rc = f()
            ok = not rc
        except SystemExit as e:
            print(f"!! {e}")
            ok = False
        except Exception:
            traceback.print_exc()
            ok = False
        bilan.append((nom, ok))
    print("\n==================== BILAN ====================")
    for nom, ok in bilan:
        print(("  OK      " if ok else "  ECHEC   ") + nom)
    if not all(ok for _n, ok in bilan):
        print("\nCopie-moi les lignes marquées '!!' ou l'erreur au-dessus de l'étape en échec.")
    try:
        print("\nOuverture de l'image dans la visionneuse 360 ...")
        cmd_voir360(cfg, paths, ["render/env_seul/frame_0001.png"])
    except Exception:
        pass
    return 0


def cmd_open(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--save"] + extra, background=False)


def cmd_voir360(cfg, paths, extra):
    """Ouvre un rendu dans la visionneuse 360 (tools/voir360.html) servie en local: qualité d'origine, rien n'est envoyé sur Internet."""
    import http.server
    import socketserver
    import threading
    import webbrowser
    exts = (".png", ".jpg", ".jpeg")
    found = []
    for dp, _dn, fns in os.walk(os.path.join(ROOT, "render")):
        for fn in fns:
            if fn.lower().endswith(exts):
                fp = os.path.join(dp, fn)
                found.append((os.path.getmtime(fp), os.path.relpath(fp, ROOT).replace(os.sep, "/")))
    found.sort(reverse=True)
    if not found:
        print("Aucune image dans le dossier render. Lance d'abord un test (image test 360).")
        return 1
    want = [a for a in extra if not a.startswith("-")]
    img = want[0].replace("\\", "/") if want else found[0][1]

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=ROOT, **k)

        def do_GET(self):
            if self.path.startswith("/__liste"):
                body = json.dumps([f for _t, f in found[:60]]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                super().do_GET()

        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), H) as srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{port}/tools/voir360.html?img={img}"
        print(f"Visionneuse 360: {img}\n(adresse locale {url})")
        webbrowser.open(url)
        input("\nLaisse cette fenêtre ouverte tant que tu regardes l'image. Entrée pour fermer la visionneuse ... ")
    return 0


def cmd_bench(cfg, paths, extra):
    return run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--bench"] + extra)


def cmd_meta360(cfg, paths, extra):
    """Ajoute les métadonnées 360 à un MP4 équirectangulaire (YouTube, VLC)."""
    files = [a for a in extra if not a.startswith("-")]
    if not files:
        sys.exit("Indiquez le fichier, par exemple :\n  python blatten.py meta360 render/test_clip/clip_apercu.mp4")
    import importlib.util
    spec = importlib.util.spec_from_file_location("inject_360", os.path.join(SRC, "scene", "inject_360.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for f in files:
        out = f[:-4] + "_360.mp4" if f.lower().endswith(".mp4") else f + "_360.mp4"
        mod.inject(f, out)
        print("écrit :", out)


def cmd_bench_compare(cfg, paths, extra):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bench", os.path.join(SRC, "bench", "bench.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.compare(os.path.join(ROOT, "bench_results"))


def cmd_render(cfg, paths, extra):
    a = scene_args(cfg, paths) + ["--preset", "final", "--render-anim"] + extra
    return run_blender(cfg, SCRIPTS["scene"], a)


def _ply_step(path):
    m = re.findall(r"(\d+)", os.path.splitext(os.path.basename(path))[0])
    return int(m[-1]) if m else 0


def _find_ply_dir(paths, wanted):
    """Dossier de Johan contenant les PLY numérotés (le plus fourni). `wanted`: numéros nécessaires."""
    best = None
    roots = [paths.johan] + [d for d in glob.glob(os.path.join(paths.johan, "*")) if os.path.isdir(d)]
    for d in roots:
        files = glob.glob(os.path.join(d, "*.ply"))
        if len(files) > 20 and (best is None or len(files) > best[0]):
            best = (len(files), d)
    return best[1] if best else None


def cmd_test_clip(cfg, paths, extra):
    """Test grandeur nature: quelques secondes de l'événement, dans l'environnement, avec les vrais fichiers de Johan."""
    ap = argparse.ArgumentParser(prog="test-clip", allow_abbrev=False)
    ap.add_argument("--start", type=int, default=50, help="numéro du premier fichier PLY (1 fichier = 1 s simulée)")
    ap.add_argument("--seconds", type=float, default=3.0, help="durée du clip en secondes")
    ap.add_argument("--stride", type=int, default=5, help="1 particule sur N (5 = environ 234 000 particules)")
    ap.add_argument("--ply", help="dossier des PLY de Johan (défaut: détecté dans johan_dir)")
    ap.add_argument("--every", type=int, default=1, help="rendre une image sur N du clip (3 = essai rapide)")
    ap.add_argument("--quality", type=int, default=48, help="échantillons du clip (demi-résolution)")
    ap.add_argument("--samples", type=int, nargs="+", default=[24, 48, 96, 192], help="échantillons des images pleine résolution")
    ap.add_argument("--no-keys", action="store_true", help="saute les images pleine résolution")
    ap.add_argument("--no-video", action="store_true", help="saute le clip")
    ap.add_argument("--reconvert", action="store_true", help="refait la conversion des PLY")
    a, rest = ap.parse_known_args(extra)

    if not os.path.exists(os.path.join(paths.cache, "env", "env_meta.json")):
        sys.exit(f"Environnement absent : {os.path.join(paths.cache, 'env', 'env_meta.json')}\n"
                 "Décompressez cache_ilyas.zip dans cache_dir, ou lancez prep-env (voir TUTO.md).")
    need = list(range(a.start, a.start + int(math.ceil(a.seconds)) + 1))
    ply_dir = a.ply or _find_ply_dir(paths, need)
    if not ply_dir or not os.path.isdir(ply_dir):
        sys.exit(f"Dossier des PLY de Johan introuvable (cherché dans {paths.johan}).\n"
                 "Indiquez-le avec --ply \"D:/.../dossier_des_ply\".")
    by_step = {_ply_step(f): f for f in glob.glob(os.path.join(ply_dir, "*.ply"))}
    missing = [n for n in need if n not in by_step]
    if missing:
        sys.exit(f"Fichiers PLY manquants dans {ply_dir} : numéros {missing}")
    print(f"PLY : {ply_dir} (fichiers {need[0]} à {need[-1]})")

    clip_dir = os.path.join(paths.cache, "clip", f"f{need[0]}-{need[-1]}_k{a.stride}")
    meta_p = os.path.join(clip_dir, "meta.json")
    if a.reconvert or not os.path.exists(meta_p):
        origin = [1117.4016956592827, 0.0, -1121.1231332002285]    # repère de la simulation (voir docs/CONTRAT_MATIERE.md)
        old = _load_json(os.path.join(paths.cache, "meta.json"))
        if old.get("origin"):
            origin = old["origin"]
        print(f"\n--- conversion de {len(need)} fichiers (1 particule sur {a.stride}) vers {clip_dir} ---")
        rc = run_blender(cfg, SCRIPTS["prep_part"],
                         [by_step[n] for n in need] + ["--out", clip_dir, "--stride", a.stride, "--reset",
                                                       "--origin"] + [repr(float(x)) for x in origin])
        if rc != 0 or not os.path.exists(meta_p):
            sys.exit("La conversion des PLY a échoué (voir le message plus haut).")
    else:
        print(f"Conversion déjà faite : {clip_dir}  (--reconvert pour la refaire)")

    args = scene_args(cfg, paths, with_vdb=False)
    args[args.index("--data") + 1] = clip_dir
    args += ["--env-dir", paths.cache, "--dt-per-step", "1.0", "--clip", "--clip-seconds", a.seconds,
             "--clip-every", a.every, "--clip-quality", a.quality, "--clip-samples"] + a.samples
    if a.no_keys:
        args.append("--clip-no-keys")
    if a.no_video:
        args.append("--clip-no-video")
    print("\n--- rendu (plusieurs heures en pleine qualité, interruption possible: relancer la même commande reprend le clip) ---")
    return run_blender(cfg, SCRIPTS["scene"], args + rest)


# (commande, texte du menu, options fixes). Les options fixes évitent à l'utilisateur de taper des paramètres.
MENU = [
    ("status", "Etat des données et des réglages", []),
    ("setup", "Installation (Blender, bibliothèques, dossiers), une seule fois", []),
    ("download", "Télécharger les dalles swisstopo de base (relief et image 2 m)", ["--jeux", "2m"]),
    ("download", "Télécharger la HAUTE RESOLUTION autour de la caméra (relief 0,5 m, image 10 cm, bâtiments 3D)", ["--jeux", "05m", "10cm", "buildings3d"]),
    ("terrain", "Convertir le terrain de Johan en maillage (une fois)", []),
    ("prep-env", "Préparer relief + image aérienne (calage)", []),
    ("prep-env", "Préparer la HAUTE RESOLUTION (après son téléchargement)", ["--hires"]),
    ("visible", "Calculer la zone du relief visible depuis la caméra (et régler la caméra à hauteur d'yeux)", []),
    ("views", "8 aperçus pour choisir le point de vue", []),
    ("test360", "Image test 360 basse résolution", []),
    ("voir360", "Voir le dernier rendu en 360 (qualité d'origine, dans le navigateur)", []),
    ("test360", "DIAGNOSTIC: image test 360 en une seule image (mono), AVEC haute résolution", ["--mono", "--out", "render/diag_hd"]),
    ("test360", "DIAGNOSTIC: image test 360 en une seule image (mono), SANS haute résolution", ["--mono", "--no-hires", "--out", "render/diag_sans_hd"]),
    ("open", "Ouvrir la scène dans Blender", []),
    ("bench", "Benchmark de rendu de cette machine", []),
    ("bench-compare", "Comparer les benchmarks enregistrés", []),
    ("valider-env", "VALIDER l'environnement seul: même image avec et sans coupe du relief invisible, comparées", []),
    ("lite", "Créer la VERSION LITE de l'environnement (relief visible seulement, sans aléa, un seul fichier .blend)", []),
    ("prep-batiments", "Préparer les BATIMENTS 3D (après leur téléchargement)", []),
    ("test360", "Image test de l'ENVIRONNEMENT SEUL (sans aléa, avec bâtiments), mono", ["--mono", "--env-only", "--cull", "--out", "render/env_seul"]),
    ("download", "Télécharger la CANOPEE (hauteur de la végétation, pour les arbres)", ["--jeux", "canopee"]),
    ("prep-vegetation", "Préparer les ARBRES (après le téléchargement de la canopée)", []),
    ("env-complet", "UN SEUL CLIC: canopée + arbres + image test de l'environnement seul, puis visionneuse", []),
    ("test-clip", "Test grandeur nature: 3 s de l'événement dans l'environnement (plusieurs heures)", []),
]


def cmd_menu(cfg, paths, extra):
    while True:
        print("\n==== Blatten VR 360 ====")
        for i, (c, d, _x) in enumerate(MENU, 1):
            print(f" {i} = {d}")
        print(" 0 = Quitter")
        ch = input("Votre choix : ").strip()
        if ch in ("", "0"):
            return 0
        if not ch.isdigit() or not 1 <= int(ch) <= len(MENU):
            continue
        name, _d, ex = MENU[int(ch) - 1]
        ex = list(ex)
        if name in ("test360", "open") and not ex:
            v = input("Numéro de vue 1 à 8 (Entrée = automatique) : ").strip()
            if v:
                ex = ["--vue", v]
        if name == "visible":
            h = input("Hauteur des yeux au-dessus du sol, en m (Entrée = 1,7 ; 0 = ne pas toucher à la caméra) : ").strip().replace(",", ".")
            if h != "0":
                ex = ["--eye", h or "1.7", "--ecrire-camera"]
        if name == "download":   # on compte d'abord, puis on demande confirmation
            print("\nComptage des dalles à télécharger ...")
            COMMANDS[name](cfg, paths, ex + ["--dry-run"])
            if input("\nLancer le téléchargement maintenant ? (o/n) : ").strip().lower() not in ("o", "oui", "y"):
                continue
        COMMANDS[name](cfg, paths, ex)
        input("\nEntrée pour revenir au menu ...")


COMMANDS = {
    "status": cmd_status, "setup": cmd_setup, "download": cmd_download, "prep-env": cmd_prep_env, "prep-batiments": cmd_prep_batiments, "prep-vegetation": cmd_prep_vegetation, "env-complet": cmd_env_complet, "visible": cmd_visible,
    "prep-particules": cmd_prep_particules, "terrain": cmd_terrain, "views": cmd_views, "test360": cmd_test360,
    "valider-env": cmd_valider_env, "lite": cmd_lite, "open": cmd_open, "voir360": cmd_voir360, "bench": cmd_bench, "test-clip": cmd_test_clip, "meta360": cmd_meta360, "bench-compare": cmd_bench_compare, "render": cmd_render, "menu": cmd_menu,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument("commande", nargs="?", default="menu", choices=sorted(COMMANDS),
                    help="sans commande (double-clic), le menu s'ouvre")
    ap.add_argument("--jeux", nargs="+", help="download: ne traiter que ces jeux (ex. 05m 10cm buildings3d)")
    ap.add_argument("--max-year", type=int, help="download: année maximale des dalles (défaut: config)")
    ap.add_argument("--dry-run", action="store_true", help="download: compte sans télécharger")
    a, extra = ap.parse_known_args()
    cfg = load_config()
    paths = Paths(cfg)
    if a.commande == "download":
        return cmd_download(cfg, paths, extra, max_year=a.max_year, dry=a.dry_run, jeux=a.jeux)
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
