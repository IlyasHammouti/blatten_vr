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
    "empreinte": os.path.join(SRC, "environnement", "empreinte_alea.py"),
    "prep_eau": os.path.join(SRC, "environnement", "prep_eau.py"),
    "montage": os.path.join(SRC, "scene", "montage.py"),
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


LOG_COURANT = {}


def _ram_libre_go():
    """Mémoire vive libre (Go) sous Windows, None ailleurs."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tot", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong),
                        ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av2", ctypes.c_ulonglong),
                        ("ex", ctypes.c_ulonglong)]
        m = MS()
        m.l = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.av / 2 ** 30
    except Exception:
        return None


def _lancer_journal(cmd, env, kw, surveiller):
    """Lance Blender en copiant tout ce qu'il écrit dans render/logs/*.log (la fenêtre peut se fermer, le journal reste).
    surveiller=True: ajoute toutes les 10 s la mémoire graphique (nvidia-smi) et la RAM libre, pour voir ce qui sature."""
    import threading
    dossier = os.path.join(ROOT, "render", "logs")
    os.makedirs(dossier, exist_ok=True)
    if "chemin" not in LOG_COURANT:
        LOG_COURANT["chemin"] = os.path.join(dossier, time.strftime("rendu_%Y%m%d_%H%M%S.log"))
    f = open(LOG_COURANT["chemin"], "a", encoding="utf-8", errors="replace")
    verrou = threading.Lock()

    def ecrire(txt, console=True):
        with verrou:
            f.write(txt if txt.endswith("\n") else txt + "\n")
            f.flush()
        if console:
            try:
                print(txt.rstrip("\n"), flush=True)
            except Exception:
                pass
    ecrire(f"[{time.strftime('%H:%M:%S')}] $ " + " ".join(cmd), console=False)
    arret = threading.Event()

    def sonde():
        while not arret.wait(10):
            ligne = f"[{time.strftime('%H:%M:%S')}] [sonde]"
            try:
                o = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.used,memory.total", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=8).stdout.strip().replace("\n", " | ")
                ligne += f" GPU(index, Mo utilisés, Mo total): {o}"
            except Exception:
                ligne += " GPU: nvidia-smi indisponible"
            r = _ram_libre_go()
            if r is not None:
                ligne += f"  RAM libre: {r:.1f} Go"
            try:
                t = subprocess.run(["tasklist", "/FI", "IMAGENAME eq blender.exe", "/FO", "CSV", "/NH"],
                                   capture_output=True, text=True, timeout=8).stdout
                ko = [int(re.sub(r"\D", "", l.split('","')[-1])) for l in t.splitlines() if "blender" in l.lower()]
                if ko:
                    ligne += f"  Blender: {sum(ko) / 1048576:.1f} Go"
            except Exception:
                pass
            ecrire(ligne, console=False)
    if surveiller:
        threading.Thread(target=sonde, daemon=True).start()
    try:
        pr = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", bufsize=1, **kw)
        for ligne in pr.stdout:
            ecrire(ligne.rstrip("\n"))
        rc = pr.wait()
    finally:
        arret.set()
        f.close()
    return rc


def _gros_consommateurs(n=8):
    """Les programmes qui occupent le plus de mémoire vive (Windows), regroupés par nom."""
    if os.name != "nt":
        return []
    cmd = ("Get-Process | Group-Object ProcessName | ForEach-Object { '{0}|{1:N1}' -f $_.Name, "
           "(($_.Group | Measure-Object WorkingSet64 -Sum).Sum / 1GB) } ")
    try:
        o = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=30).stdout
        L = [(a, float(b.replace(",", "."))) for a, b in (l.strip().split("|") for l in o.splitlines() if "|" in l)]
        return sorted(L, key=lambda x: -x[1])[:n]
    except Exception:
        return []


def _attendre_ram(min_go=7.0, attente_max=900):
    """Avant chaque paquet: Blender monte à environ 9 à 10 Go. Mesuré le 19 oct (images finales): avec 8 Go libres au départ, le rendu passe (minimum 0,6 Go libres).
    Le seuil de 11 Go n'était jamais atteint (attente de 15 min pour rien avant chaque image): réglé à 7 Go.
    Sinon on attend (jusqu'à 15 min) que de la place se libère, en disant qui occupe la mémoire."""
    debut = time.time()
    prevenu = False
    while True:
        r = _ram_libre_go()
        if r is None or r >= min_go:
            if prevenu:
                print(f"RAM libre: {r:.1f} Go, on repart.", flush=True)
            return
        if not prevenu:
            print(f"\n!! Seulement {r:.1f} Go de RAM libre (il en faut au moins {min_go:.0f} pour Blender). Programmes les plus gourmands:", flush=True)
            for nom, go in _gros_consommateurs():
                print(f"     {go:5.1f} Go  {nom}", flush=True)
            print("   Fermez ce qui n'est pas utile (Steam, navigateur, OneDrive...). Attente jusqu'à 15 min, puis le rendu repart quand même.", flush=True)
            prevenu = True
        if time.time() - debut > attente_max:
            print(f"   Toujours {r:.1f} Go libres: on tente quand même.", flush=True)
            return
        time.sleep(30)


def run_blender(cfg, script, args, background=True, extra_env=None, fond=False):
    """fond=True (rendus longs): priorité basse et 2 coeurs laissés libres, pour pouvoir travailler à côté."""
    exe = find_blender(cfg)
    fil = ["-t", str(max(2, (os.cpu_count() or 4) - 2))] if fond else []
    cmd = [exe] + (["-b"] if background else []) + fil + ["--python", script, "--"] + [str(a) for a in args]
    env = dict(os.environ, BLATTEN_ROOT=ROOT)
    env.update(extra_env or {})
    print("$", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    kw = {}
    if fond and os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000)
    rc = _lancer_journal(cmd, env, kw, fond)
    if rc != 0:
        print(f"\n!! Blender s'est terminé avec une erreur (code {rc}). Le message se trouve juste au-dessus"
              f" et dans le journal {LOG_COURANT.get('chemin', '')}.", flush=True)
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
            ass = it.get("assets") or {}
            trouve = False
            for nom, a in ass.items():
                if cle_res in nom and nom.endswith(".tif") and (k not in best or y > best[k][1]):
                    best[k] = (a["href"], y)
                    trouve = True
            if not trouve and cle_res != "_0.5_":
                # la résolution demandée n'est pas listée: même dalle, nom déduit de la version 0,5 m (même dossier swisstopo)
                for nom, a in ass.items():
                    if "_0.5_" in nom and nom.endswith(".tif") and (k not in best or y > best[k][1]):
                        best[k] = (a["href"].replace("_0.5_", cle_res), y)
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
    # arbres lointains: modèle de surface à 2 m dans un rayon autour de la caméra (au-delà de l'emprise 0,5 m)
    ray = float(cfg.get("tree_far_radius", 4600.0))
    try:
        cam = _load_json(os.path.join(ROOT, "camera.json"))["cam"]
        m_ = _load_json(mp)
        Ec, Nc = m_["scene_E0"] + cam[0], m_["scene_N0"] + m_["flip"] * cam[1]
        la0, lo0 = _lv95_to_wgs84(Ec - ray, Nc - ray)
        la1, lo1 = _lv95_to_wgs84(Ec + ray, Nc + ray)
        # swisstopo ne publie plus le modèle de surface qu'à 0,5 m (les dalles 2 m renvoient 404): on prend le 0,5 m, réduit à 2 m à la lecture
        t2 = _stac_tuiles("ch.swisstopo.swisssurface3d-raster", (lo0, la0, lo1, la1), max_year, "_0.5_")
        todo2 = [(u, os.path.join(dest, os.path.basename(u))) for u, _y in sorted(t2.values())]
        todo2 = [(u, f) for u, f in todo2 if not os.path.exists(f) and (u, f) not in todo]
        print(f"=== modèle de surface pour les arbres lointains (rayon {ray:.0f} m): {len(t2)} dalles 0,5 m en tout, {len(todo2)} à télécharger en plus (plusieurs Go) ===")
        if not t2:
            print("!! le catalogue ne renvoie aucune dalle: les arbres lointains manqueront (relancer; sinon prévenir).")
        todo += todo2
    except Exception as e:
        print(f"!! dalles 2 m non récupérées ({e}); les arbres resteront limités à l'emprise 0,5 m.")
    # taux de mélange des forêts (OFEV, 10 m, part de feuillus): donne l'essence des arbres. Fichier national, une seule fois.
    mel_url = ("https://data.geo.admin.ch/ch.bafu.landesforstinventar-waldmischungsgrad/landesforstinventar-waldmischungsgrad/"
               "landesforstinventar-waldmischungsgrad_2056.tif")
    mel_dir = os.path.join(paths.swisstopo, "waldmischungsgrad")
    mel_f = os.path.join(mel_dir, os.path.basename(mel_url))
    os.makedirs(mel_dir, exist_ok=True)
    mel_todo = [] if os.path.exists(mel_f) else [(mel_url, mel_f)]
    print(f"=== taux de mélange des forêts (OFEV, essences): {'déjà présent' if not mel_todo else 'à télécharger (fichier national)'} ===")
    if dry:
        if todo or mel_todo:
            _print_sizes(todo + mel_todo)
        return
    done = fail = 0
    todo = todo + mel_todo
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


def cmd_prep_eau(cfg, paths, extra):
    """Eau lue dans l'image aérienne (couloir OpenStreetMap seulement pour dire où chercher)."""
    return run_blender(cfg, SCRIPTS["prep_eau"], ["--data", paths.cache] + extra)


def cmd_empreinte_alea(cfg, paths, extra):
    """Où passe la matière (particules de Johan): sert au couloir protégé de la coupe, au masquage des bâtiments et arbres balayés, au dépôt."""
    if not os.path.exists(os.path.join(paths.cache, "meta.json")):
        print("Pas de particules préparées (prep-particules): empreinte de l'aléa ignorée. Sans elle, la coupe du relief invisible ne protège pas le couloir de l'avalanche.")
        return 0
    return run_blender(cfg, SCRIPTS["empreinte"], ["--data", paths.cache] + extra)


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
    if run_blender(cfg, SCRIPTS["scene"], base + ["--no-cull", "--out", d2] + extra):
        return 1
    print("\n--- 3/3 comparaison ---")
    return run_blender(cfg, SCRIPTS["comparer"], [os.path.join(d1, "frame_0001.png"), os.path.join(d2, "frame_0001.png"),
                                                  os.path.join(ROOT, "render", "val_difference.png")])


def cmd_lite(cfg, paths, extra):
    """Version légère de l'environnement: seul le relief visible depuis la caméra, sans particules, images incluses."""
    rc = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--lite", "--preset", "test"] + extra)
    f = os.path.join(ROOT, "render", "blatten_env_lite.blend")
    print("Fichier:", f)
    if not rc and os.path.isfile(f):
        print("Ouverture dans Blender (vue caméra: pavé num 0 ; aperçu matériau: icône sphère en haut à droite de la vue 3D) ...")
        try:
            subprocess.Popen([find_blender(cfg), f])
        except Exception as e:
            print("Ouverture impossible:", e)
    return rc


def cmd_env_complet(cfg, paths, extra):
    """UN SEUL CLIC: canopée, arbres, image test de l'environnement seul, puis ouverture dans la visionneuse 360.
    Une étape qui échoue n'arrête pas les suivantes (le bilan final dit ce qui a marché)."""
    etapes = [
        ("Télécharger la canopée", lambda: cmd_download(cfg, paths, ["--jeux", "canopee"])),
        ("Préparer les arbres", lambda: cmd_prep_vegetation(cfg, paths, [])),
        ("Préparer l'eau (image aérienne)", lambda: cmd_prep_eau(cfg, paths, [])),
        ("Empreinte de l'aléa (si les particules sont préparées)", lambda: cmd_empreinte_alea(cfg, paths, [])),
        ("Zone visible avec couloir protégé de l'aléa", lambda: cmd_visible(cfg, paths, [])),
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


def _film(cfg):
    """Réglages du film (config.json, clé "film"): plage d'images, fps."""
    f = cfg.get("film") or {}
    return int(f.get("images", 1350)), int((cfg.get("scene") or {}).get("fps", 30))


# Brouillon de TOUTE la simulation (0 à 202 s): 6 images par seconde simulée pendant la phase active (0-70 s),
# 1 par seconde ensuite (la matière ralentit). Vidéo à 12 images/s: phase active en accéléré x2, fin en accéléré x12.
CHRONO_BROUILLON = [0.0, 70.0, 420, 70.0, 202.0, 132]
FPS_BROUILLON = 12


def _ext(preset, extra=()):
    """Extension des images écrites: le preset final écrit en JPEG qualité 95 (environ 1 Mo par image au lieu de 30 Mo en PNG 16 bits),
    sauf avec --format png16. Les autres presets restent en PNG."""
    ex = list(extra)
    png16 = "--format" in ex and ex[ex.index("--format") + 1:ex.index("--format") + 2] == ["png16"]
    return ".jpg" if preset == "final" and not png16 else ".png"


def _nettoyer(out, ext=".png"):
    os.makedirs(out, exist_ok=True)
    for f in glob.glob(os.path.join(out, "frame_*" + ext)):
        if os.path.getsize(f) == 0:      # image commencée puis interrompue: à refaire
            os.remove(f)
    return len(glob.glob(os.path.join(out, "frame_*" + ext)))


def _options_nuit(extra, paquet):
    """Options d'un rendu par soirées, retirées de la liste transmise à Blender:
      --jusqu-a HH:MM   s'arrête proprement avant cette heure (le prochain paquet n'est lancé que s'il a le temps de finir); relancer la même commande le lendemain reprend à la première image manquante
      --paquet N        N images par Blender (plus petit = mémoire remise à zéro plus souvent)
      --pause S         S secondes de repos entre deux paquets (refroidissement de la carte graphique)"""
    extra = list(extra)
    fin = pause = None
    for flag in ("--jusqu-a", "--paquet", "--pause"):
        if flag in extra:
            i = extra.index(flag)
            if i + 1 >= len(extra):
                sys.exit(f"{flag} demande une valeur (exemple: {flag} " + {"--jusqu-a": "07:00", "--paquet": "10", "--pause": "60"}[flag] + ")")
            v = extra[i + 1]
            del extra[i:i + 2]
            if flag == "--paquet":
                paquet = max(1, int(v))
            elif flag == "--pause":
                pause = max(0.0, float(v))
            else:
                m = re.match(r"^(\d{1,2})[:h](\d{2})$", v)
                if not m:
                    sys.exit("--jusqu-a attend une heure du type 07:00")
                now = time.time()
                lt = time.localtime(now)
                cible = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(m.group(1)), int(m.group(2)), 0, 0, 0, -1))
                fin = cible if cible > now else cible + 86400
    return extra, paquet, pause, fin


def _rendre_film(cfg, paths, preset, out_rel, n, fps_video, extra, paquet=40, ram_min=7.0):
    extra, paquet, pause, heure_fin = _options_nuit(extra, paquet)
    out = os.path.join(ROOT, out_rel)
    # Les images du rendu FINAL (plusieurs Go) peuvent aller sur un autre disque: clé "render_dir" de config.local.json
    # (exemple "D:/Blatten_render"). Les aperçus et les journaux restent dans render/ du dépôt.
    rd = (cfg.get("render_dir") or "").strip()
    if rd and preset == "final":
        out = os.path.join(rd, "final")
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            sys.exit(f"Dossier de rendu impossible ({rd}): {e}")
        print(f"Images finales écrites dans {out} (render_dir)", flush=True)
    ext = _ext(preset, extra)
    deja = _nettoyer(out, ext)
    print(f"Film {preset}: {n} images, {deja} déjà rendues dans {out_rel}; reprise automatique en cas de coupure (relancer la même commande).")
    a = scene_args(cfg, paths) + ["--preset", preset, "--mono", "--render-anim", "--frames", "1", str(n), "--out", out] + extra
    # Par paquets: un Blender neuf tous les PAQUET images repart avec une mémoire (graphique et vive) propre, ce qui évite
    # l'accumulation dans un processus long. En cas d'arrêt, on réessaie; on abandonne après 2 paquets de suite sans image.
    # --origine 1 garde le calcul du temps de simulation identique quel que soit le paquet.
    PAQUET = paquet
    echecs = 0
    rc = 0
    duree_paquet = 0.0
    if heure_fin:
        print(f"Rendu de nuit: arrêt propre avant {time.strftime('%d/%m %H:%M', time.localtime(heure_fin))}; relancer la même commande pour reprendre.", flush=True)
    while True:
        manquantes = [i for i in range(1, n + 1) if not os.path.exists(os.path.join(out, f"frame_{i:04d}{ext}"))]
        if not manquantes:
            rc = 0
            break
        d0 = manquantes[0]
        d1 = min(d0 + PAQUET - 1, n)
        if heure_fin and duree_paquet and time.time() + 1.15 * duree_paquet > heure_fin:
            print(f"\nHeure limite atteinte: le prochain paquet (~{duree_paquet / 60:.0f} min) ne finirait pas à temps. "
                  f"{len(manquantes)} images restantes; relancer la même commande pour reprendre à l'image {d0}.", flush=True)
            return 0
        print(f"\n>>> paquet d'images {d0} à {d1} sur {n} ({len(manquantes)} restantes)", flush=True)
        i = a.index("--frames")
        b_args = a[:i] + ["--frames", str(d0), str(d1), "--origine", "1"] + a[i + 3:]
        avant = len(manquantes)
        _attendre_ram(ram_min)
        t_paquet = time.time()
        rc = run_blender(cfg, SCRIPTS["scene"], b_args, fond=True)
        duree_paquet = max(duree_paquet * 0.5, time.time() - t_paquet) if duree_paquet else time.time() - t_paquet
        _nettoyer(out, ext)
        apres = len([i for i in range(1, n + 1) if not os.path.exists(os.path.join(out, f"frame_{i:04d}{ext}"))])
        if apres >= avant:
            echecs += 1
            print(f"\n!! Aucune nouvelle image dans ce paquet (échec {echecs}/2).", flush=True)
            if echecs >= 2:
                print(f"Arrêt. Journal complet: {LOG_COURANT.get('chemin', '')}")
                rc = rc or 1
                break
        else:
            echecs = 0
        time.sleep(pause if pause is not None else 5)
    if rc == 0:
        rc = run_blender(cfg, SCRIPTS["montage"], ["--dir", out, "--fps", str(fps_video), "--out", os.path.join(out, f"{preset}.mp4")])
    return rc


def cmd_render(cfg, paths, extra):
    """Rendu final: 3840x1920 mono, fenêtre du film (config.json), reprise automatique."""
    n, fps = _film(cfg)
    return _rendre_film(cfg, paths, "final", os.path.join("render", "final"), n, fps, ["--camera-confirmed"] + extra)


def cmd_brouillon(cfg, paths, extra):
    """Brouillon de toute la simulation (1920x960, 16 échantillons), vidéo 360 au bout."""
    n = int(sum(CHRONO_BROUILLON[2::3]))
    return _rendre_film(cfg, paths, "brouillon", os.path.join("render", "brouillon"), n, FPS_BROUILLON,
                        ["--chrono"] + [str(x) for x in CHRONO_BROUILLON] + extra)


def cmd_images_test(cfg, paths, extra, temps=(30.0, 43.0)):
    """Images fixes de l'avalanche à des instants de simulation (défaut t = 30 s et 43 s), qualité brouillon."""
    rc = 0
    for t in temps:
        out = os.path.join(ROOT, "render", "tests", f"t{t:g}s")
        os.makedirs(out, exist_ok=True)
        if os.path.exists(os.path.join(out, "frame_0001.png")) and "--refaire" not in extra:
            print(f"image test t = {t:g} s déjà faite (render/tests/t{t:g}s), ignorée (--refaire pour la refaire)")
            continue
        print(f"\n>>> image test à t = {t:g} s -> render/tests/t{t:g}s")
        rc = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "brouillon", "--mono", "--render-frame", "1",
                         "--render-time", str(t), "--out", out] + [x for x in extra if x != "--refaire"], fond=True) or rc
    return rc


def cmd_apercu_alea(cfg, paths, extra):
    """TOUTE la simulation (t = 0 à 201 s, une image par seconde simulée) à très basse résolution (1280x640), avec tout
    l'environnement (relief, bâtiments, arbres, rivière, poussière) mais SANS image aérienne drapée sur le relief (couleurs
    procédurales) ni relief 0,5 m: sert à voir l'emprise de l'aléa, sa position par rapport à la caméra et à trancher la durée du film.
    Le temps de simulation est inscrit en bas de chaque image. Vidéo 360 à 10 images/s (10 s simulées par seconde)."""
    return _rendre_film(cfg, paths, "apercu", os.path.join("render", "apercu_alea"), 202, 10,
                        ["--chrono", "0.0", "202.0", "202", "--stamp", "--no-hires", "--no-ortho"] + extra, paquet=70, ram_min=6.0)


def cmd_images_finales(cfg, paths, extra, temps=(30.0, 43.0, 52.0)):
    """Trois images fixes à la résolution FINALE (3840x1920, 96 échantillons): environnement complet + aléa, à t = 30, 43 et 52 s.
    Sert à juger le réalisme (environnement et matière) et à mesurer le temps d'une image finale."""
    rc = 0
    for t in temps:
        out = os.path.join(ROOT, "render", "finales", f"t{t:g}s")
        os.makedirs(out, exist_ok=True)
        ext = _ext("final", extra)
        if os.path.exists(os.path.join(out, "frame_0001" + ext)) and "--refaire" not in extra:
            print(f"image finale t = {t:g} s déjà faite (render/finales/t{t:g}s), ignorée (--refaire pour la refaire)")
            continue
        # si l'image plante (mémoire), on réessaie en allégeant, et on le DIT: une image allégée ne juge plus tout le réalisme
        paliers = [([], "scène complète"),
                   (["--tree-dist", "2500"], "arbres limités à 2,5 km"),
                   (["--tree-dist", "2500", "--no-hires"], "arbres limités à 2,5 km, sans relief 0,5 m ni images locales")]
        for k, (moins, quoi) in enumerate(paliers):
            print(f"\n>>> image finale à t = {t:g} s ({quoi}) -> render/finales/t{t:g}s", flush=True)
            _attendre_ram(7.0)
            r1 = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "final", "--mono", "--camera-confirmed",
                             "--render-frame", "1", "--render-time", str(t), "--out", out] + moins
                             + [x for x in extra if x != "--refaire"], fond=True)
            f = os.path.join(out, "frame_0001" + ext)
            if os.path.exists(f) and os.path.getsize(f) > 0:
                if k:
                    with open(os.path.join(out, "ALLEGEE.txt"), "w", encoding="utf-8") as fh:
                        fh.write(f"Image allégée: {quoi} (la scène complète a planté).\n")
                    print(f"!! image t = {t:g} s obtenue ALLÉGÉE ({quoi}): la scène complète ne tient pas en mémoire.")
                break
            print(f"!! échec ({quoi}); essai suivant plus léger" if k + 1 < len(paliers) else "!! échec même allégée")
            rc = r1 or 1
        else:
            continue
    return rc


def cmd_apercu_complet(cfg, paths, extra):
    """Tout d'un coup, sans surveillance: images test t = 30 s et 43 s, puis brouillon de toute la simulation et sa vidéo 360."""
    rc = cmd_images_test(cfg, paths, extra)
    print("\nImages test terminées (render/tests). Lancement du brouillon complet ...")
    return cmd_brouillon(cfg, paths, extra) or rc


def cmd_cap(cfg, paths, extra):
    """Tourne la vue de départ de la vidéo de N degrés (positif = vers la droite). La visionneuse 360 donne N."""
    v = [x for x in extra if re.match(r"^[+-]?\d+(\.\d+)?$", x)]
    if not v:
        sys.exit("Indiquez l'angle, par exemple : python blatten.py cap 35   (positif = vers la droite)")
    f = os.path.join(ROOT, "camera.json")
    c = _load_json(f)
    rz = float(c["rot_deg"][2]) - float(v[0])
    rz = (rz + 180.0) % 360.0 - 180.0
    c["rot_deg"][2] = round(rz, 1)
    json.dump(c, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"Vue de départ tournée de {float(v[0]):g} degrés: rotation Z = {rz:.1f} (la zone visible ne change pas).")
    return 0


def cmd_montage(cfg, paths, extra):
    """Refait seulement la vidéo à partir des images déjà rendues (dossier en argument, défaut render/brouillon)."""
    d = next((x for x in extra if not x.startswith("-")), os.path.join("render", "brouillon"))
    d = d if os.path.isabs(d) else os.path.join(ROOT, d)
    n, fps = _film(cfg)
    fv = FPS_BROUILLON if os.path.basename(d.rstrip("/\\")) == "brouillon" else fps
    return run_blender(cfg, SCRIPTS["montage"], ["--dir", d, "--fps", str(fv), "--out", os.path.join(d, os.path.basename(d.rstrip("/\\")) + ".mp4")])


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
# ----------------------------------------------------------------------------------
# Menus (façon lanceur): un écran d'accueil, des rubriques, et dans chacune des actions avec une pastille d'état
#   OK = déjà fait   .. = pas encore fait   (rien) = action qui se relance à volonté
# ----------------------------------------------------------------------------------
def _etat(paths):
    """Ce qui est déjà prêt, d'après les fichiers (lecture seule, rapide)."""
    e = {}
    em = _load_json(os.path.join(paths.cache, "env", "env_meta.json"))
    e["base_dl"] = bool(glob.glob(os.path.join(paths.swisstopo, "swissalti3d_2m", "*.tif")))
    e["env"] = bool(em)
    e["hd_dl"] = bool(glob.glob(os.path.join(paths.swisstopo, "swissalti3d_05m", "*.tif*")) or glob.glob(os.path.join(paths.swisstopo, "*05m*", "*.tif*")))
    e["hd"] = bool(em.get("dem05"))
    e["visible"] = os.path.exists(os.path.join(paths.cache, "env", "visible", "visible_meta.json"))
    e["bat"] = bool(em.get("batiments"))
    e["canopee_dl"] = bool(glob.glob(os.path.join(paths.swisstopo, "swisssurface3d_raster_05m", "*.tif*")))
    e["veg"] = bool(em.get("vegetation"))
    e["eau"] = bool(em.get("eau"))
    e["emp"] = bool(em.get("alea_empreinte"))
    pm = _load_json(os.path.join(paths.cache, "meta.json"))
    e["nplies"] = len(pm.get("files", []))
    e["part"] = e["nplies"] > 0
    e["terrain"] = bool(glob.glob(os.path.join(paths.cache, "Terrain_mesh_*m.blend")))
    e["lite"] = os.path.exists(os.path.join(ROOT, "render", "blatten_env_lite.blend"))
    e["cam"] = bool(_load_json(os.path.join(ROOT, "camera.json")).get("confirmed"))
    return e


# (étiquette, commande, arguments, explication, clé d'état ou None, invite spéciale ou None)
RUBRIQUES = [
    ("Préparer l'environnement", "données, relief, bâtiments, arbres, rivière: dans l'ordre", [
        ("Télécharger relief et image de base (2 m)", "download", ["--jeux", "2m"], "une fois", "base_dl", "dl"),
        ("Préparer relief + image aérienne (calage)", "prep-env", [], "après le téléchargement", "env", None),
        ("Télécharger la haute résolution autour de la caméra", "download", ["--jeux", "05m", "10cm", "buildings3d"], "relief 0,5 m, image 10 cm, bâtiments 3D", "hd_dl", "dl"),
        ("Préparer la haute résolution", "prep-env", ["--hires"], "après son téléchargement", "hd", None),
        ("Calculer la zone visible depuis la caméra", "visible", [], "à refaire si la caméra bouge ou après l'empreinte de l'aléa", "visible", "visible"),
        ("Préparer les bâtiments 3D", "prep-batiments", [], "après le téléchargement HD", "bat", None),
        ("Télécharger la canopée (hauteur de végétation, forêts)", "download", ["--jeux", "canopee"], "arbres: emprise 0,5 m et jusqu'à 4,6 km, OFEV pour les essences", "canopee_dl", "dl"),
        ("Préparer les arbres et arbustes", "prep-vegetation", [], "après la canopée", "veg", None),
        ("Préparer l'eau (lue dans l'image aérienne)", "prep-eau", [], "Internet la 1re fois (couloir OSM); regarder ensuite eau_apercu_2m.png dans cache\\env", "eau", None),
        ("TOUT ENCHAINER en un clic (canopée, arbres, rivière, empreinte, zone visible, image test)", "env-complet", [], "recommandé: reprend ce qui manque, une étape en échec n'arrête pas les autres", None, None),
    ]),
    ("Voir et vérifier", "images test, version lite, Blender", [
        ("Image test de l'ENVIRONNEMENT SEUL (bâtiments, arbres, rivière)", "test360", ["--mono", "--env-only", "--cull", "--out", "render/env_seul"], "le contrôle habituel; à regarder avec « Voir en 360 »", None, None),
        ("Voir le dernier rendu en 360 (navigateur, qualité d'origine)", "voir360", [], "", None, None),
        ("VERSION LITE: créer et ouvrir dans Blender", "lite", [], "un seul fichier, relief visible seulement; vue caméra: pavé num 0", "lite", None),
        ("Ouvrir la scène complète dans Blender", "open", [], "lourd", None, None),
        ("8 aperçus pour choisir le point de vue", "views", [], "", None, None),
        ("Image test 360 basse résolution", "test360", [], "", None, None),
        ("Valider la coupe du relief invisible (avec / sans, comparées)", "valider-env", [], "doit conclure IDENTIQUES (bruit près)", None, None),
        ("Diagnostic: image mono AVEC haute résolution", "test360", ["--mono", "--out", "render/diag_hd"], "", None, None),
        ("Diagnostic: image mono SANS haute résolution", "test360", ["--mono", "--no-hires", "--out", "render/diag_sans_hd"], "", None, None),
    ]),
    ("Aléa (matière)", "particules de Johan, empreinte, test grandeur nature", [
        ("Convertir les particules de Johan (PLY vers .npy)", "prep-particules", [], "demande le dossier des PLY", "part", "ply"),
        ("Convertir le terrain de Johan en maillage", "terrain", [], "une fois", "terrain", None),
        ("Empreinte de l'aléa (où passe la matière)", "empreinte-alea", [], "protège le couloir de la coupe, masque bâtiments, arbres et rivière balayés; refaire la zone visible ensuite", "emp", None),
        ("Test grandeur nature: 3 s de l'événement dans l'environnement", "test-clip", [], "plusieurs heures", None, None),
    ]),
    ("Rendu et performances", "aperçu complet, rendu final, benchmark, métadonnées YouTube", [
        ("APERÇU DE L'ALÉA: toute la simulation, environnement complet sans orthophoto, très basse résolution (emprise, caméra, durée du film)", "apercu-alea", [], "~30-60 min; reprise automatique si coupure", None, None),
        ("IMAGES FINALES: 3 images 3840x1920 (t=30, 43, 52 s), environnement + matière + panache de poussière (réalisme)", "images-finales", [], "~30-60 min; donne aussi le temps d'une image finale", None, None),
        ("(ancien) Aperçu complet: images test puis brouillon 1920x960 de toute la simulation", "apercu-complet", [], "~5-8 h", None, None),
        ("Brouillon de toute la simulation seulement (1920x960, vidéo 360 au bout)", "brouillon", [], "~7-8 h; reprise automatique si coupure", None, None),
        ("Images test seulement (t=30 s et t=43 s, render/tests)", "images-test", [], "~5 min", None, None),
        ("Changer la vue de départ (angle donné par la visionneuse 360)", "cap", [], "", None, "cap"),
        ("RENDU FINAL (animation complète)", "render", [], "très long: demande confirmation; reprise automatique si coupure", None, "final"),
        ("Refaire seulement la vidéo à partir des images", "montage", [], "dossier render/brouillon par défaut", None, None),
        ("Benchmark de rendu de cette machine", "bench", [], "", None, None),
        ("Comparer les benchmarks enregistrés", "bench-compare", [], "", None, None),
        ("Ajouter les métadonnées 360 à un MP4 (YouTube)", "meta360", [], "demande le fichier", None, "mp4"),
    ]),
    ("Installation et état", "à faire une fois, ou en cas de doute", [
        ("Etat des données et des réglages", "status", [], "", None, None),
        ("Installation (Blender, bibliothèques, dossiers)", "setup", [], "une seule fois", None, None),
    ]),
]


def _pastille(e, cle):
    if cle is None:
        return "    "
    return " OK " if e.get(cle) else " .. "


def _invite(code, name, ex, cfg, paths):
    """Questions éventuelles avant de lancer une action. Rend la liste d'arguments, ou None pour annuler."""
    ex = list(ex)
    if code == "visible":
        h = input("Hauteur des yeux au-dessus du sol, en m (Entrée = 1,7 ; 0 = ne pas toucher à la caméra) : ").strip().replace(",", ".")
        if h != "0":
            ex = ["--eye", h or "1.7", "--ecrire-camera"]
    elif code == "dl":     # on compte d'abord, puis on demande confirmation
        print("\nComptage des dalles à télécharger ...")
        COMMANDS[name](cfg, paths, ex + ["--dry-run"])
        if input("\nLancer le téléchargement maintenant ? (o/n) : ").strip().lower() not in ("o", "oui", "y"):
            return None
    elif code == "ply":
        d = input(f"Dossier des PLY (Entrée = {paths.johan}) : ").strip().strip('"') or paths.johan
        st = input("Une particule sur N (Entrée = 10) : ").strip() or "10"
        ex = [d, "--stride", st]
    elif code == "final":
        print("\nLe rendu final dure des dizaines d'heures. Les garde-fous sont dans docs/.")
        fr = input("Images à rendre, par exemple 1 1200 (Entrée = les réglages de config.json) : ").strip()
        if input("Lancer le rendu final ? (o/n) : ").strip().lower() not in ("o", "oui", "y"):
            return None
        ex = ["--frames"] + fr.split() if fr else []
    elif code == "cap":
        n = input("Angle affiché par la visionneuse 360 (ex. 35 ou -20) : ").strip()
        if not n:
            return None
        ex = [n]
    elif code == "mp4":
        f = input("Fichier MP4 (glisser-déposer dans la fenêtre) : ").strip().strip('"')
        if not f:
            return None
        ex = [f]
    return ex


def _lancer(cfg, paths, label, name, ex, code):
    ex = _invite(code, name, ex, cfg, paths)
    if ex is None:
        return
    print(f"\n>>> {label}\n")
    try:
        COMMANDS[name](cfg, paths, ex)
    except SystemExit as e:
        if e.code not in (None, 0):
            print(f"\n!! {e.code}")
    except Exception:
        traceback.print_exc()
    input("\nEntrée pour revenir au menu ...")


def _ecran_rubrique(cfg, paths, titre, sous, items):
    while True:
        e = _etat(paths)
        print(f"\n==== {titre} ====\n     {sous}\n")
        for i, (lab, _c, _x, hint, cle, _k) in enumerate(items, 1):
            print(f" {i:>2} [{_pastille(e, cle)}] {lab}" + (f"\n          {hint}" if hint else ""))
        print("\n  0 = Retour")
        ch = input("Votre choix : ").strip()
        if ch in ("", "0"):
            return
        if not ch.isdigit() or not 1 <= int(ch) <= len(items):
            continue
        lab, name, ex, _h, _c, code = items[int(ch) - 1]
        _lancer(cfg, paths, lab, name, ex, code)


def _resume(e):
    def f(ok):
        return "OK" if ok else ".."
    return (f"Caméra {f(e['cam'])} | Relief HD {f(e['hd'])} | Zone visible {f(e['visible'])} | Bâtiments {f(e['bat'])} | Arbres {f(e['veg'])} | "
            f"Rivière {f(e['eau'])} | Particules {e['nplies']} fichier(s) | Empreinte aléa {f(e['emp'])}")


def cmd_menu(cfg, paths, extra):
    while True:
        e = _etat(paths)
        print("\n========================================")
        print("           BLATTEN VR 360")
        print("========================================")
        print(" " + _resume(e))
        print("\n  1 = TOUT PREPARER EN UN CLIC (environnement: reprend ce qui manque)")
        print("  2 = Aperçu rapide: image test de l'environnement seul, puis visionneuse 360")
        print("  3 = Version lite dans Blender (pour se promener et vérifier bâtiments, arbres, rivière)")
        print()
        for i, (t, s_, _it) in enumerate(RUBRIQUES, 4):
            print(f"  {i} = {t:<26} {s_}")
        print("  0 = Quitter")
        ch = input("\nVotre choix : ").strip()
        if ch in ("", "0"):
            return 0
        if not ch.isdigit():
            continue
        n = int(ch)
        if n == 1:
            _lancer(cfg, paths, "Tout préparer", "env-complet", [], None)
        elif n == 2:
            _lancer(cfg, paths, "Image test de l'environnement seul", "test360", ["--mono", "--env-only", "--cull", "--out", "render/env_seul"], None)
            if os.path.exists(os.path.join(ROOT, "render", "env_seul", "frame_0001.png")):
                try:
                    cmd_voir360(cfg, paths, ["render/env_seul/frame_0001.png"])
                except Exception:
                    pass
        elif n == 3:
            _lancer(cfg, paths, "Version lite", "lite", [], None)
        elif 4 <= n < 4 + len(RUBRIQUES):
            t, s_, it = RUBRIQUES[n - 4]
            _ecran_rubrique(cfg, paths, t, s_, it)


COMMANDS = {
    "status": cmd_status, "setup": cmd_setup, "download": cmd_download, "prep-env": cmd_prep_env, "prep-batiments": cmd_prep_batiments, "prep-vegetation": cmd_prep_vegetation, "env-complet": cmd_env_complet, "visible": cmd_visible,
    "prep-particules": cmd_prep_particules, "terrain": cmd_terrain, "views": cmd_views, "test360": cmd_test360,
    "valider-env": cmd_valider_env, "prep-eau": cmd_prep_eau, "brouillon": cmd_brouillon, "montage": cmd_montage, "images-test": cmd_images_test, "apercu-complet": cmd_apercu_complet, "apercu-alea": cmd_apercu_alea, "images-finales": cmd_images_finales, "cap": cmd_cap, "empreinte-alea": cmd_empreinte_alea, "lite": cmd_lite, "open": cmd_open, "voir360": cmd_voir360, "bench": cmd_bench, "test-clip": cmd_test_clip, "meta360": cmd_meta360, "bench-compare": cmd_bench_compare, "render": cmd_render, "menu": cmd_menu,
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
