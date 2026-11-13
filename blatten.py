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
    python blatten.py camera [--lv95 E N | --wgs84 LAT LON] [--hauteur 2] [--cap 200]   caméra en coordonnées suisses
    python blatten.py variantes --temps 43 --jeux actuel mixte "mixte poussiere_v2"   même instant, plusieurs jeux de réglages (reglages/)
    python blatten.py render [--de N --a M] [--intro-pas 3]   rendu final (garde-fous: voir docs/); --de/--a: une partie du film;
                                      --intro-pas K: une image sur K pendant les 5 s d'intro (paysage immobile), recopiée
    python blatten.py paquet          rendu à deux PC: prépare la session et le paquet du frère (un seul zip), voir docs/RENDU_A_DEUX.md
    python blatten.py duo             rend la part de ce PC (Ilyas ou frère), partage en direct, montage final chez Ilyas
    python blatten.py duo-etat        où en sont les deux PC
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
    "outro": os.path.join(SRC, "scene", "outro.py"),
    "son": os.path.join(SRC, "audio", "son.py"),
    "test_son": os.path.join(SRC, "audio", "test_son.py"),
    "montage_film": os.path.join(SRC, "scene", "montage_film.py"),
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


def cmd_eau_manuel(cfg, paths, extra):
    """Remplace le masque d'eau automatique par les polygones de la couche eau_manuel (QGIS). --auto remet l'automatique."""
    return subprocess.call([sys.executable, os.path.join(SRC, "environnement", "eau_manuel.py"), "--data", paths.cache] + extra)


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


def _images_suspectes(out, ext=".png"):
    """Numéros des images dont le fichier est vide ou beaucoup plus petit que celui de ses voisines: rendu raté (image noire quand la
    mémoire vive a manqué, « Calloc returns null » dans le journal). Un PNG noir pèse 0,7 Mo contre 4,6 Mo pour une image normale."""
    taille = {}
    for f in glob.glob(os.path.join(out, "frame_*" + ext)):
        m = re.search(r"frame_(\d+)", os.path.basename(f))
        if m:
            taille[int(m.group(1))] = os.path.getsize(f)
    ks = sorted(taille)
    mauvaises = []
    for j, i in enumerate(ks):
        vois = sorted(taille[x] for x in ks[max(0, j - 3):j] + ks[j + 1:j + 4] if taille[x] > 0)
        if taille[i] == 0 or (len(vois) >= 2 and taille[i] < 0.3 * vois[len(vois) // 2]):
            mauvaises.append(i)
    return mauvaises


def _nettoyer(out, ext=".png"):
    os.makedirs(out, exist_ok=True)
    for f in glob.glob(os.path.join(out, "frame_*" + ext)):
        if os.path.getsize(f) == 0:      # image commencée puis interrompue: à refaire
            os.remove(f)
    mauvaises = _images_suspectes(out, ext)
    if mauvaises:                         # image noire ou presque: mise de côté pour être refaite
        coin = os.path.join(out, "_images_ratees")
        os.makedirs(coin, exist_ok=True)
        for i in mauvaises:
            f = os.path.join(out, f"frame_{i:04d}{ext}")
            if os.path.exists(f):
                shutil.move(f, os.path.join(coin, time.strftime("%H%M%S_") + os.path.basename(f)))
        print(f"!! {len(mauvaises)} image(s) ratée(s) mises de côté (_images_ratees) pour être refaites: {mauvaises[:12]}", flush=True)
    return len(glob.glob(os.path.join(out, "frame_*" + ext)))


def _options_nuit(extra, paquet):
    """Options d'un rendu par soirées, retirées de la liste transmise à Blender:
      --jusqu-a HH:MM   s'arrête proprement avant cette heure (le prochain paquet n'est lancé que s'il a le temps de finir); relancer la même commande le lendemain reprend à la première image manquante
      --paquet N        N images par Blender (plus petit = mémoire remise à zéro plus souvent)
      --pause S         S secondes de repos entre deux paquets (refroidissement de la carte graphique)"""
    extra = list(extra)
    fin = pause = None
    plage = [None, None]
    for flag in ("--de", "--a"):          # plage d'images (partage du rendu entre deux PC): --de 700 --a 1590
        if flag in extra:
            i = extra.index(flag)
            if i + 1 >= len(extra) or not extra[i + 1].isdigit():
                sys.exit(f"{flag} demande un numéro d'image (exemple: --de 700 --a 1590)")
            plage[flag == "--a"] = int(extra[i + 1])
            del extra[i:i + 2]
    PLAGE.update(de=plage[0], a=plage[1])
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


PLAGE = dict(de=None, a=None)
DERNIER_DOSSIER = dict(out=None)     # dossier du dernier rendu de film (pour le montage d'un extrait)


def _empecher_veille():
    """Windows: pas de mise en veille tant que ce programme tourne (l'écran peut s'éteindre); l'effet cesse à sa fermeture."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except Exception:
            pass


def _rendre_film(cfg, paths, preset, out_rel, n, fps_video, extra, paquet=40, ram_min=7.0, extrait=False):
    _empecher_veille()
    extra, paquet, pause, heure_fin = _options_nuit(extra, paquet)
    out = os.path.join(ROOT, out_rel)
    # Les images du rendu FINAL (plusieurs Go) peuvent aller sur un autre disque: clé "render_dir" de config.local.json
    # (exemple "D:/Blatten_render"). Les aperçus et les journaux restent dans render/ du dépôt.
    rd = (cfg.get("render_dir") or "").strip()
    if rd and preset in ("final", "brouillon", "bande"):
        out = os.path.join(rd, os.path.basename(out_rel))
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            sys.exit(f"Dossier de rendu impossible ({rd}): {e}")
        print(f"Images finales écrites dans {out} (render_dir)", flush=True)
    out, extra = _dossier_version(out, extra)
    DERNIER_DOSSIER["out"] = out
    ext = _ext(preset, extra)
    deja = _nettoyer(out, ext)
    pas_intro, extra = _option(extra, "--intro-pas", 1)
    # --pas K: une image sur K pour tout le film, recopiée sur les K-1 suivantes (vidéo de contrôle plus rapide; mouvement saccadé à 30/K images/s)
    pas_film, extra = _option(extra, "--pas", 1)
    k_film = max(1, int(pas_film[0])) if pas_film else 1
    print(f"Film {preset}: {n} images, {deja} déjà rendues dans {out_rel}; reprise automatique en cas de coupure (relancer la même commande).")
    a = scene_args(cfg, paths) + ["--preset", preset, "--mono", "--render-anim", "--frames", "1", str(n), "--out", out] + extra
    # Par paquets: un Blender neuf tous les PAQUET images repart avec une mémoire (graphique et vive) propre, ce qui évite
    # l'accumulation dans un processus long. En cas d'arrêt, on réessaie; on abandonne après 2 paquets de suite sans image.
    # --origine 1 garde le calcul du temps de simulation identique quel que soit le paquet.
    PAQUET = paquet
    echecs = 0
    rc = 0
    duree_paquet = 0.0
    # Intro (paysage immobile, seuls l'eau et les arbres proches bougent): --intro-pas K ne rend qu'une image sur K des 5 premières
    # secondes et recopie chaque image sur les K-1 suivantes (gain: (K-1)/K des 150 images d'intro; l'eau et le vent avancent alors à 30/K images/s).
    k_intro = int(pas_intro[0]) if pas_intro else 1
    n_intro = min(n, int(round(float((cfg.get("scene") or {}).get("intro", 0.0)) * int((cfg.get("scene") or {}).get("fps", 30)))))
    if k_intro > 1 and n_intro > 1 and (PLAGE["de"] or 1) <= n_intro:
        cles = [i for i in range(1, n_intro + 1, k_intro)]
        if any(not os.path.exists(os.path.join(out, f"frame_{i:04d}{ext}")) for i in cles):
            i_ = a.index("--frames")
            b_args = a[:i_] + ["--frames", "1", str(cles[-1]), "--frame-step", str(k_intro), "--origine", "1"] + a[i_ + 3:]
            print(f"\n>>> intro: {len(cles)} images clés sur {n_intro} (une sur {k_intro})", flush=True)
            _attendre_ram(ram_min)
            run_blender(cfg, SCRIPTS["scene"], b_args, fond=True)
            _nettoyer(out, ext)
        for c in cles:
            src = os.path.join(out, f"frame_{c:04d}{ext}")
            if os.path.exists(src) and os.path.getsize(src) > 0:
                for i in range(c + 1, min(c + k_intro, n_intro + 1)):
                    dst = os.path.join(out, f"frame_{i:04d}{ext}")
                    if not os.path.exists(dst):
                        shutil.copy(src, dst)
    if heure_fin:
        print(f"Rendu de nuit: arrêt propre avant {time.strftime('%d/%m %H:%M', time.localtime(heure_fin))}; relancer la même commande pour reprendre.", flush=True)
    de, a_ = max(1, PLAGE["de"] or 1), min(n, PLAGE["a"] or n)
    if (PLAGE["de"] or PLAGE["a"]):
        print(f"Plage d'images: {de} à {a_}" + ("" if extrait else " (le reste est rendu sur un autre PC)"), flush=True)
    def _faite(i):
        return os.path.exists(os.path.join(out, f"frame_{i:04d}{ext}"))
    cibles = [i for i in range(de, a_ + 1) if (i - 1) % k_film == 0]
    if k_film > 1:
        print(f"Une image sur {k_film}: {len(cibles)} images à calculer sur {a_ - de + 1}", flush=True)
    done0 = len([i for i in cibles if _faite(i)])
    print(f"==== AVANCEMENT: {100.0 * done0 / max(len(cibles), 1):.0f} % du film au départ ({done0}/{len(cibles)} images) ====", flush=True)
    chrono_f = os.path.join(out, "chrono.json")
    try:
        chrono = json.load(open(chrono_f, encoding="utf-8"))
    except Exception:
        chrono = []
    while True:
        manquantes = [i for i in cibles if not _faite(i)]
        if not manquantes:
            rc = 0
            break
        d0 = manquantes[0]
        d1 = min(d0 + (PAQUET - 1) * k_film, a_)
        suivante = min((i for i in cibles if i > d0 and _faite(i)), default=None)
        if suivante:                      # ne pas refaire les images déjà rendues au-delà d'un trou
            d1 = min(d1, suivante - k_film)
        if heure_fin and duree_paquet and time.time() + 1.15 * duree_paquet > heure_fin:
            print(f"\nHeure limite atteinte: le prochain paquet (~{duree_paquet / 60:.0f} min) ne finirait pas à temps. "
                  f"{len(manquantes)} images restantes; relancer la même commande pour reprendre à l'image {d0}.", flush=True)
            return 0
        print(f"\n>>> paquet d'images {d0} à {d1} sur {n} ({len(manquantes)} restantes)", flush=True)
        i = a.index("--frames")
        b_args = a[:i] + ["--frames", str(d0), str(d1), "--origine", "1"] + (["--frame-step", str(k_film)] if k_film > 1 else []) + a[i + 3:]
        avant = len(manquantes)
        _attendre_ram(ram_min)
        t_paquet = time.time()
        rc = run_blender(cfg, SCRIPTS["scene"], b_args, fond=True)
        duree_paquet = max(duree_paquet * 0.5, time.time() - t_paquet) if duree_paquet else time.time() - t_paquet
        _nettoyer(out, ext)
        apres = len([i for i in cibles if not _faite(i)])
        faites = avant - apres
        if faites > 0:
            # chronométrage: temps par image (construction de la scène comprise, une fois par paquet) et fin estimée
            chrono.append(dict(date=time.strftime("%Y-%m-%d %H:%M"), de=d0, a=d1, images=faites, secondes=round(time.time() - t_paquet)))
            try:
                json.dump(chrono, open(chrono_f, "w", encoding="utf-8"), indent=1)
            except OSError:
                pass
            mn = (time.time() - t_paquet) / 60 / faites
            pct = 100.0 * (len(cibles) - apres) / max(len(cibles), 1)
            print(f"\n==== AVANCEMENT: {pct:.0f} % du film ({len(cibles) - apres}/{len(cibles)} images) ====", flush=True)
            try:
                open(os.path.join(ROOT, "render", "progression.txt"), "w", encoding="utf-8").write(
                    f"{time.strftime('%d/%m %H:%M')}  {pct:.1f} %  ({len(cibles) - apres}/{len(cibles)} images)  {out}\n")
            except OSError:
                pass
            print(f"\n[chrono] {faites} images en {(time.time() - t_paquet) / 60:.0f} min ({mn:.2f} min par image); "
                  f"reste {apres} images, environ {apres * mn / 60:.1f} h à ce rythme (le coût monte avec la poussière)", flush=True)
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
    if rc == 0 and k_film > 1:
        for j in range(de, a_ + 1):
            src = os.path.join(out, f"frame_{1 + ((j - 1) // k_film) * k_film:04d}{ext}")
            dst = os.path.join(out, f"frame_{j:04d}{ext}")
            if not os.path.exists(dst) and os.path.exists(src):
                shutil.copy(src, dst)
    if rc == 0 and (de, a_) != (1, n):
        if not extrait:
            print(f"Plage {de}-{a_} terminée. Le montage se fait une fois toutes les images réunies dans le même dossier.", flush=True)
    elif rc == 0:
        if preset in ("bande", "final"):     # montage complet: fondu, outro, son (un échec du montage n'invalide pas le rendu)
            if _finir_film(cfg, out, "bande" if preset == "bande" else "360", fps_video) != 0:
                print("!! montage en échec: les images sont faites, relancer  python blatten.py finir", flush=True)
                return 0
        else:
            rc = run_blender(cfg, SCRIPTS["montage"], ["--dir", out, "--fps", str(fps_video), "--out", os.path.join(out, f"{preset}.mp4")])
        if rc == 0:
            _marquer_termine(out)
    return rc


def _finir_film(cfg, out, fmt, fps=30):
    """Outro (Blender), bande son (son.py), puis montage (montage_film.py) dans le dossier du rendu `out`."""
    d_outro = os.path.join(out, "outro")
    png = os.path.join(d_outro, f"outro_{fmt}.png")
    rc = run_blender(cfg, SCRIPTS["outro"], ["--format", fmt, "--out", d_outro])
    if rc != 0 or not os.path.exists(png):
        print("!! outro non rendue, montage sans outro", flush=True)
        png = None
    d_son = os.path.join(out, "son")
    rs = subprocess.call([sys.executable, SCRIPTS["son"], "--out", d_son])
    wav = os.path.join(d_son, "son_stereo.wav" if fmt == "bande" else "son_ambix.wav")
    if rs != 0 or not os.path.exists(wav):
        print("!! son non calculé, montage sans son", flush=True)
        wav = None
    a = ["--dir", out, "--format", fmt, "--fps", str(fps)] + (["--outro", png] if png else []) + (["--son", wav] if wav else [])
    return subprocess.call([sys.executable, SCRIPTS["montage_film"]] + a)


def _reparer_images(out, fmt, k=2):
    """Refait les images ratées (noires) d'un rendu bande terminé, par suites consécutives, 3 passes au plus."""
    if fmt != "bande":
        mv = _images_suspectes(out, ".jpg")
        if mv:
            print(f"!! images suspectes (non réparées automatiquement en 360): {mv[:20]}", flush=True)
        return not mv
    for passe in range(3):
        mauvaises = _images_suspectes(out, ".png")
        if not mauvaises:
            return True
        coin = os.path.join(out, "_images_ratees")
        os.makedirs(coin, exist_ok=True)
        for j in mauvaises:
            f = os.path.join(out, f"frame_{j:04d}.png")
            if os.path.exists(f):
                shutil.move(f, os.path.join(coin, f"p{passe}_{os.path.basename(f)}"))
        bases = sorted({1 + ((j - 1) // k) * k for j in mauvaises})
        suites = []
        for b in bases:
            if suites and b == suites[-1][1] + k:
                suites[-1][1] = b
            else:
                suites.append([b, b])
        print(f"\n>>> réparation (passe {passe + 1}/3): images {bases[:20]}{'...' if len(bases) > 20 else ''}", flush=True)
        tf = os.path.join(out, "TERMINE.txt")
        if os.path.exists(tf):
            os.remove(tf)
        for d0, d1 in suites:
            subprocess.call([sys.executable, os.path.join(ROOT, "blatten.py"), "render", "--qualite", "bande", "--pas", str(k),
                             "--intro-pas", "2", "--version", os.path.basename(os.path.normpath(out)), "--de", str(d0), "--a", str(d1 + k - 1)])
    ok = not _images_suspectes(out, ".png")
    _marquer_termine(out)
    return ok


def cmd_finir(cfg, paths, extra):
    """Outro, son et montage d'un rendu de film déjà fait (le plus récent si --dir n'est pas donné).
        python blatten.py finir [--format bande|360] [--dir D:/Blatten_render/film_bande/20261101_0200]"""
    fmt, extra = _option(extra, "--format", 1)
    fmt = (fmt or ["bande"])[0]
    d, extra = _option(extra, "--dir", 1)
    if d:
        out = d[0]
    else:
        rd = (cfg.get("render_dir") or "").strip() or os.path.join(ROOT, "render")
        base = os.path.join(rd, "film_bande" if fmt == "bande" else "final")
        vs = sorted(x for x in os.listdir(base) if re.fullmatch(r"\d{8}_\d{4}.*", x)) if os.path.isdir(base) else []
        if not vs:
            sys.exit(f"Aucun rendu dans {base}")
        out = os.path.join(base, vs[-1])
    print(f"Montage de {out}", flush=True)
    try:
        if not _reparer_images(out, fmt):
            print("!! des images restent suspectes après réparation, voir _images_ratees et verif", flush=True)
    except Exception:
        traceback.print_exc()
    rc = _finir_film(cfg, out, fmt)
    if rc == 0:
        _marquer_termine(out)
    return rc


def cmd_son(cfg, paths, extra):
    """Bande son seule (AmbiX + stéréo): python blatten.py son [--out dossier]"""
    o, extra = _option(extra, "--out", 1)
    out = o[0] if o else os.path.join(ROOT, "render", "son")
    return subprocess.call([sys.executable, SCRIPTS["son"], "--out", out])


def cmd_outro(cfg, paths, extra):
    """Image de l'outro seule: python blatten.py outro [--format bande|360]"""
    fmt, extra = _option(extra, "--format", 1)
    return run_blender(cfg, SCRIPTS["outro"], ["--format", (fmt or ["360"])[0], "--out", os.path.join(ROOT, "render", "outro")])


def _marquer_termine(out):
    try:
        open(os.path.join(out, "TERMINE.txt"), "w", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M") + "\n")
    except OSError:
        pass


def _dossier_version(base, extra):
    """Chaque rendu de film a son propre dossier daté dans `base` (base/AAAAMMJJ_HHMM): rien n'est écrasé, on garde la trace
    de chaque version. Relancer la même commande reprend le dernier rendu NON terminé (pas de TERMINE.txt); une fois terminé,
    le rendu suivant crée un nouveau dossier.
        --nouveau          force un nouveau dossier même si le dernier n'est pas fini
        --version NOM      écrit dans base/NOM (reprise d'une version précise, partage entre PC: même NOM sur chaque PC)"""
    nouveau = "--nouveau" in extra
    extra = [x for x in extra if x != "--nouveau"]
    nom, extra = _option(extra, "--version", 1)
    os.makedirs(base, exist_ok=True)
    if nom:
        d = os.path.join(base, nom[0])
    else:
        versions = sorted(x for x in os.listdir(base) if re.fullmatch(r"\d{8}_\d{4}.*", x) and os.path.isdir(os.path.join(base, x)))
        en_cours = [x for x in versions if not os.path.exists(os.path.join(base, x, "TERMINE.txt"))]
        if en_cours and not nouveau:
            d = os.path.join(base, en_cours[-1])
            print(f"Reprise du rendu en cours: {d}", flush=True)
        else:
            d = os.path.join(base, time.strftime("%Y%m%d_%H%M"))
            print(f"Nouveau rendu: {d} (les rendus précédents sont conservés)", flush=True)
    os.makedirs(d, exist_ok=True)
    return d, extra


def cmd_render(cfg, paths, extra):
    """Film complet (fenêtre du film de config.json, réglages reglages/film.json), reprise automatique.
        python blatten.py render                          HD: 3840x1920, 96 échantillons (preset final) -> render/final (ou render_dir/final)
        python blatten.py render --qualite brouillon      basse définition: 1920x960, 16 échantillons -> render/film_brouillon
        options: --pas 2 (une image sur deux), --intro-pas 3, --de N --a M (partage entre deux PC), --jusqu-a 07:00, --paquet N"""
    n, fps = _film(cfg)
    q, extra = _option(extra, "--qualite", 1)
    q = (q or ["final"])[0]
    if q not in ("final", "brouillon", "bande"):
        sys.exit("--qualite final (HD 360), bande (brouillon HD plat 2560x1280) ou brouillon (basse définition)")
    if q == "final":
        return _rendre_film(cfg, paths, "final", os.path.join("render", "final"), n, fps, ["--camera-confirmed"] + extra)
    if q == "bande":     # brouillon HD plat (1er nov.): même scène et mêmes réglages que le final, cadrage 130 x 65 degrés
        return _rendre_film(cfg, paths, "bande", os.path.join("render", "film_bande"), n, fps, ["--camera-confirmed"] + extra, paquet=20)
    pas, _ = _option(extra, "--pas", 1)
    nom = "film_brouillon" + (f"_pas{pas[0]}" if pas and pas[0] != "1" else "")
    return _rendre_film(cfg, paths, "brouillon", os.path.join("render", nom), n, fps, ["--camera-confirmed"] + extra, paquet=30)


def cmd_extrait(cfg, paths, extra):
    """Extrait du film dans les conditions du rendu final (preset final: 96 échantillons, poussière, matière, eau, arbres et
    réglages du film), à la définition voulue, puis vidéo 360 avec le son spatial (métadonnées 360 et AmbiX), sans fondu
    ni outro. Sert à tout vérifier sur quelques secondes avant le rendu complet.
        python blatten.py extrait [--t 30] [--duree 5] [--res 3840x1920] [--nouveau]   (+ options de render: --pas 2, --jusqu-a 07:00...)
    --t: instant de l'événement (s) au milieu de l'extrait. Dossier render_dir/extraits/<date>_t<T>s_<largeur>: relancer la
    même commande reprend l'extrait s'il n'est pas fini (même un autre jour); un extrait fini n'est jamais écrasé (nouveau
    dossier, suffixe _b, _c...); --nouveau en commence un autre même si le précédent n'est pas fini."""
    t, extra = _option(extra, "--t", 1)
    du, extra = _option(extra, "--duree", 1)
    rs, extra = _option(extra, "--res", 1)
    t = float(t[0]) if t else 30.0
    du = float(du[0]) if du else 5.0
    try:
        w, h = (int(x) for x in (rs[0] if rs else "3840x1920").lower().split("x"))
    except ValueError:
        sys.exit("--res attend LARGEURxHAUTEUR, par exemple 1920x960")
    n, fps = _film(cfg)
    sc = cfg.get("scene") or {}
    intro, t0, ts = float(sc.get("intro", 0.0)), float(sc.get("t0", 0.0)), float(sc.get("time_scale", 1.0))
    # l'image k du film (1 = première) montre l'instant t = t0 + ((k - 1) / fps - intro) / ts de l'événement
    de = max(1, int(round((intro + (t - du / 2 - t0) * ts) * fps)) + 1)
    a = min(n, de + int(round(du * fps)) - 1)
    rd = (cfg.get("render_dir") or "").strip() or os.path.join(ROOT, "render")
    base = os.path.join(rd, "extraits")
    nouveau = "--nouveau" in extra
    extra = [x for x in extra if x != "--nouveau"]
    motif = re.compile(rf"\d{{8}}_t{re.escape(f'{t:g}')}s_{w}(_[b-z])?")
    en_cours = sorted(x for x in (os.listdir(base) if os.path.isdir(base) else [])
                      if motif.fullmatch(x) and not os.path.exists(os.path.join(base, x, "TERMINE.txt")))
    if en_cours and not nouveau:          # même extrait pas fini (même un autre jour): on le reprend
        nom = en_cours[-1]
    else:
        nom = f"{time.strftime('%Y%m%d')}_t{t:g}s_{w}"
        for suf in [""] + [f"_{c}" for c in "bcdefghijklmnopqrstuvwxyz"]:
            if not os.path.exists(os.path.join(base, nom + suf)):
                nom += suf
                break
    print(f"Extrait {w} x {h}, réglages du rendu final: t = {t - du / 2:g} à {t + du / 2:g} s de l'événement, "
          f"images {de} à {a} du film ({a - de + 1} images) -> {os.path.join(base, nom)}", flush=True)
    rc = _rendre_film(cfg, paths, "final", os.path.join("render", "extraits"), n, fps,
                      ["--camera-confirmed", "--de", str(de), "--a", str(a), "--version", nom,
                       "--set", f"scene.rendu_res=[{w},{h}]"] + extra, extrait=True)
    out = DERNIER_DOSSIER["out"]
    if rc != 0 or not out:
        return rc
    ext = _ext("final", extra)
    if any(not os.path.exists(os.path.join(out, f"frame_{i:04d}{ext}")) for i in range(de, a + 1)):
        print("Images manquantes: relancer la même commande pour finir l'extrait.", flush=True)
        return 1
    mv = _images_suspectes(out, ext)
    if mv:
        print(f"!! images suspectes (noires?): {mv[:20]}", flush=True)
    d_son = os.path.join(out, "son")
    r_son = subprocess.call([sys.executable, SCRIPTS["son"], "--out", d_son])
    wav = os.path.join(d_son, "son_ambix.wav")
    if r_son != 0 or not os.path.exists(wav):
        print("!! son non calculé, vidéo sans son", flush=True)
        wav = None
    rc = subprocess.call([sys.executable, SCRIPTS["montage_film"], "--dir", out, "--format", "360", "--fps", str(fps),
                          "--fondu", "0"] + (["--son", wav] if wav else []))
    if rc == 0:
        _marquer_termine(out)
        print(f"\nExtrait prêt: {os.path.join(out, 'film_360_360.mp4')} (vidéo 360 avec le son spatial, à mettre sur YouTube "
              f"en non répertorié ou à ouvrir dans un lecteur 360)", flush=True)
    return rc


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


def _option(extra, flag, n=None):
    """Retire --flag v1 v2 ... de extra (jusqu'au prochain --option). Rend (valeurs ou None, extra restant)."""
    extra = list(extra)
    if flag not in extra:
        return None, extra
    i = extra.index(flag)
    j = i + 1
    while j < len(extra) and not extra[j].startswith("--") and (n is None or j - i <= n):
        j += 1
    vals = extra[i + 1:j]
    del extra[i:j]
    return vals, extra


def cmd_test_bande(cfg, paths, extra):
    """Images fixes du brouillon HD plat (preset bande, réglages du film) à quelques instants de l'événement, avec le temps
    de rendu de chacune: render/tests/bande/<date>/t<T>s/. Sert à valider l'aspect et estimer la durée du film.
        python blatten.py test-bande [--temps 15 30 45]"""
    temps, extra = _option(extra, "--temps")
    temps = [float(x) for x in (temps or ["15", "30", "45"])]
    base = os.path.join(ROOT, "render", "tests", "bande", time.strftime("%Y%m%d_%H%M"))
    rc = 0
    bilan = []
    for t in temps:
        out = os.path.join(base, f"t{t:g}s")
        os.makedirs(out, exist_ok=True)
        print(f"\n>>> bande t = {t:g} s -> {out}", flush=True)
        _attendre_ram(7.0)
        t0 = time.time()
        r = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "bande", "--mono", "--camera-confirmed",
                        "--render-frame", "1", "--render-time", str(t), "--out", out] + extra, fond=True)
        ok = os.path.exists(os.path.join(out, "frame_0001.png"))
        bilan.append(dict(t=t, ok=ok, minutes=round((time.time() - t0) / 60, 2)))
        print(f"{'OK' if ok else 'ÉCHEC'}: t = {t:g} s, {(time.time() - t0) / 60:.1f} min (construction de la scène comprise)", flush=True)
        rc = rc or (0 if ok else (r or 1))
    json.dump(bilan, open(os.path.join(base, "bilan.json"), "w", encoding="utf-8"), indent=1)
    print(f"\nImages: {base}")
    return rc


def cmd_test_eau(cfg, paths, extra):
    """Eau: sans / avec le scintillement lointain qui descend le courant (sens nord-est vers sud-ouest), et 1 s plus tard, pour voir
    le déplacement. render/tests/eau/<date>/<nom>/ (bande plate HD, avant l'événement).
        python blatten.py test-eau [--temps 10]"""
    temps, extra = _option(extra, "--temps", 1)
    t0_ = float(temps[0]) if temps else 10.0
    # l'eau avance avec le numéro d'image (30 images = 1 s), la simulation reste figée à t0_
    variantes = [("A_sans_scintillement", 1, ["scene.eau_loin=0"]), ("B_avec", 1, []), ("C_avec_plus_1s", 31, [])]
    base = os.path.join(ROOT, "render", "tests", "eau", time.strftime("%Y%m%d_%H%M"))
    rc = 0
    for nom, fr, sets in variantes:
        out = os.path.join(base, nom)
        os.makedirs(out, exist_ok=True)
        print(f"\n>>> {nom} (image {fr}, simulation à {t0_:g} s) -> {out}", flush=True)
        _attendre_ram(7.0)
        t1 = time.time()
        sa = []
        for x in sets:
            sa += ["--set", x]
        r = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "bande", "--mono", "--camera-confirmed",
                        "--render-frame", str(fr), "--render-time", f"{t0_:g}", "--out", out] + sa + extra, fond=True)
        ok = os.path.exists(os.path.join(out, f"frame_{fr:04d}.png"))
        print(f"{'OK' if ok else 'ÉCHEC'}: {nom}, {(time.time() - t1) / 60:.1f} min", flush=True)
        rc = rc or (0 if ok else (r or 1))
    print(f"\nImages: {base}")
    return rc


def _sonde_bilan(chemin, depuis):
    """Pic de mémoire de la carte (Mo), mémoire totale (Mo) et RAM libre minimale (Go) relevés par la sonde dans le journal,
    à partir de l'octet `depuis`."""
    gpu, tot, ram = 0, 0, None
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            f.seek(depuis)
            for l in f:
                m = re.search(r"\[sonde\] GPU\(index, Mo utilisés, Mo total\): \d+, (\d+), (\d+)", l)
                if m:
                    gpu, tot = max(gpu, int(m.group(1))), int(m.group(2))
                m = re.search(r"RAM libre: ([\d.]+) Go", l)
                if m:
                    ram = float(m.group(1)) if ram is None else min(ram, float(m.group(1)))
    except OSError:
        pass
    return gpu, tot, ram


def cmd_test_final(cfg, paths, extra):
    """Une image FINALE (3840x1920, réglages du film) aux instants les plus lourds: temps, pic de mémoire de la carte, RAM libre
    minimale; puis deux réglages plus rapides au moment le plus lourd, à comparer à l'oeil. Donne une estimation du film entier.
        python blatten.py test-final [--temps 15 43 53] [--sans-variantes]
    -> render/tests/final/<date>/<variante>_t<T>s/frame_0001.jpg et bilan.json"""
    temps, extra = _option(extra, "--temps")
    temps = [float(x) for x in (temps or ["15", "43", "53"])]
    sans_var = "--sans-variantes" in extra
    extra = [x for x in extra if x != "--sans-variantes"]
    lourd = max(temps)
    essais = [("A_film", t, []) for t in temps]
    if not sans_var:
        essais += [("B_volumes_rapides", lourd, ["scene.rendu_pas_volumes=3"]),
                   ("C_rapide", lourd, ["scene.rendu_pas_volumes=3", "scene.rendu_echantillons=64", "scene.rendu_seuil=0.02"])]
    base = os.path.join(ROOT, "render", "tests", "final", time.strftime("%Y%m%d_%H%M"))
    bilan = []
    for nom, t, sets in essais:
        out = os.path.join(base, f"{nom}_t{t:g}s")
        os.makedirs(out, exist_ok=True)
        print(f"\n>>> image finale {nom}, t = {t:g} s -> {out}", flush=True)
        _attendre_ram(7.0)
        j = LOG_COURANT.get("chemin")
        depuis = os.path.getsize(j) if j and os.path.exists(j) else 0
        t0 = time.time()
        sa = []
        for x in sets:
            sa += ["--set", x]
        r = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "final", "--mono", "--camera-confirmed",
                        "--render-frame", "1", "--render-time", f"{t:g}", "--out", out] + sa + extra, fond=True)
        dt = (time.time() - t0) / 60
        ok = os.path.exists(os.path.join(out, "frame_0001.jpg")) and os.path.getsize(os.path.join(out, "frame_0001.jpg")) > 200000
        gpu, tot, ram = _sonde_bilan(LOG_COURANT.get("chemin"), depuis if j == LOG_COURANT.get("chemin") else 0)
        bilan.append(dict(variante=nom, t=t, ok=ok, minutes=round(dt, 2), carte_mo_max=gpu, carte_mo_total=tot,
                          ram_libre_min_go=ram, reglages=sets))
        print(f"{'OK' if ok else 'ÉCHEC'}: {nom} t = {t:g} s: {dt:.1f} min (construction comprise), carte {gpu}/{tot} Mo, "
              f"RAM libre mini {ram if ram is not None else '?'} Go", flush=True)
        json.dump(bilan, open(os.path.join(base, "bilan.json"), "w", encoding="utf-8"), indent=1)
        if nom == "A_film" and (not ok or (tot and gpu >= 0.97 * tot)):
            # carte pleine (ou échec): même instant avec des tuiles de 1024 pixels, qui prennent moins de mémoire
            print(f"   carte pleine ou échec à t = {t:g} s: essai supplémentaire avec des tuiles de 1024 pixels", flush=True)
            essais.append(("D_tuiles_1024", t, ["scene.rendu_tuile=1024"]))
    A = sorted((b["t"], b["minutes"]) for b in bilan if b["variante"] == "A_film" and b["ok"])
    if len(A) >= 2:
        try:
            import numpy as np
            n, fps = _film(cfg)
            n_intro = int(round(float((cfg.get("scene") or {}).get("intro", 8.0)) * fps))
            ts, ms = [a for a, _ in A], [max(0.5, m - 1.0) for _, m in A]     # ~1 min de construction de scène retirée
            evt = np.interp(np.arange(n - n_intro) / fps, ts, ms).sum()
            tot_min = evt + (n_intro // 2) * float(np.interp(0.0, ts, ms))   # intro: une image sur deux, paysage seul
            print(f"\nEstimation du film final ({n - n_intro} images de l'événement + {n_intro // 2} de l'intro): {tot_min / 60:.0f} h "
                  f"sur ce PC seul, environ {tot_min / 60 / 2.6:.0f} h à deux si la 3060 va 1,6 fois plus vite.", flush=True)
            bilan.append(dict(estimation_heures_seul=round(tot_min / 60, 1), estimation_heures_a_deux=round(tot_min / 60 / 2.6, 1)))
            json.dump(bilan, open(os.path.join(base, "bilan.json"), "w", encoding="utf-8"), indent=1)
        except Exception as e:
            print("estimation impossible:", e)
    if any(not b.get("ok", True) or (b.get("carte_mo_total") and b["carte_mo_max"] >= 0.97 * b["carte_mo_total"])
           for b in bilan if b.get("variante") == "A_film" and b.get("t", 0) > 35):
        print("\nÀ deux PC, la fin du film (après t = 30 à 38 s selon les vitesses) revient au PC du frère (carte de 12 Go). Si la "
              "carte d'ici manque de mémoire sur une image, ce PC laisse tout seul les images suivantes au frère.", flush=True)
    print(f"\nImages et bilan: {base}")
    return 0 if all(b.get("ok", True) for b in bilan) else 1


def cmd_prep_sol(cfg, paths, extra):
    """Images aériennes « nettoyées » pour le sol (src/scene/prep_sol.py): cimes et ombres des arbres remplacées (fini le sol noir
    sous les arbres 3D), trame de l'image 10 cm lissée. Écrit ortho_*_sol.jpg à côté des originaux (inchangés). Utilisées par la
    scène si scene.ortho_sol vaut true.     python blatten.py prep-sol [--sombre 0.72] [--lisse 1.0]"""
    env = os.path.join(paths.cache, "env")
    return subprocess.call([sys.executable, os.path.join(SRC, "scene", "prep_sol.py"), "--env", env] + extra)


def cmd_test_aspect(cfg, paths, extra):
    """Arbres et sol, avant / après les changements du 7 nov., même image (bande plate HD, avant l'arrivée de la poussière):
    render/tests/aspect/<date>/<nom>/. A avant (couronnes lisses, image aérienne d'origine), B arbres en grappes, C arbres en
    grappes + sol nettoyé (prep-sol). Le sol nettoyé demande d'avoir lancé python blatten.py prep-sol.
        python blatten.py test-aspect [--temps 20]"""
    temps, extra = _option(extra, "--temps", 1)
    t = temps[0] if temps else "20"
    variantes = [("A_avant", ["scene.arbres_grappes=false", "scene.ortho_sol=false"]),
                 ("B_arbres_grappes", ["scene.arbres_grappes=true", "scene.ortho_sol=false"]),
                 ("C_arbres_grappes_sol_nettoye", ["scene.arbres_grappes=true", "scene.ortho_sol=true"])]
    base = os.path.join(ROOT, "render", "tests", "aspect", time.strftime("%Y%m%d_%H%M"))
    rc = 0
    for nom, sets in variantes:
        out = os.path.join(base, nom)
        os.makedirs(out, exist_ok=True)
        print(f"\n>>> {nom} (t = {t} s) -> {out}", flush=True)
        _attendre_ram(7.0)
        t0 = time.time()
        sa = []
        for x in sets:
            sa += ["--set", x]
        r = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "bande", "--mono", "--camera-confirmed",
                        "--render-frame", "1", "--render-time", t, "--out", out] + sa + extra, fond=True)
        ok = os.path.exists(os.path.join(out, "frame_0001.png"))
        print(f"{'OK' if ok else 'ÉCHEC'}: {nom}, {(time.time() - t0) / 60:.1f} min", flush=True)
        rc = rc or (0 if ok else (r or 1))
    print(f"\nImages: {base}")
    return rc


# Fenêtres plates pour tester UNE caractéristique dans les conditions réelles, sans rendre le 360 entier: même scène, mêmes
# réglages et mêmes échantillons que le film final, découpés dans la sphère. Densité = celle du film 3840 x 1920
# (10,667 pixels par degré), donc ce qu'on voit ici est ce que verra le spectateur du 360.
PX_PAR_DEGRE = 3840 / 360.0
FENETRES = {
    "proche": dict(cap=(285.0, 375.0), haut=(-55.0, 70.0), doc="sol et grand arbre tout près de la caméra (cap 330)"),
    "versant": dict(cap=(110.0, 230.0), haut=(-25.0, 15.0), doc="versant d'en face, vallée et forêt lointaine"),
}
_LUM = "scene.arbres_luminosite=0.9"
_NET = "scene.ortho_sol_suffixe=_sol_net"
JEUX_FENETRE = {
    # (nom de variante, fenêtre, réglages en plus)
    "sol_arbres": [("A_actuel", "proche", []), ("B_arbres_90pct", "proche", [_LUM]), ("C_arbres_90pct_sol_net", "proche", [_LUM, _NET]),
                   ("A_actuel", "versant", []), ("B_arbres_90pct", "versant", [_LUM])],
    # herbe: même fenêtre proche, avec le sol net et les arbres à 90 % (référence C du jeu précédent) puis avec les touffes
    "herbe": [("D_herbe", "proche", [_LUM, "scene.herbe=true"]), ("E_herbe_dense", "proche", [_LUM, "scene.herbe=true", "scene.herbe_densite=35"])],
}


def cmd_test_fenetre(cfg, paths, extra):
    """Test d'une caractéristique sur une fenêtre plate à la densité du film final (96 échantillons, réglages du film):
    render/tests/fenetre/<jeu>/<date>/<fenetre>__<variante>/frame_0001.png
        python blatten.py test-fenetre sol_arbres [--temps 15]      (jeux: voir JEUX_FENETRE)"""
    jeux = [x for x in extra if not x.startswith("-")]
    temps, extra = _option([x for x in extra if x not in jeux], "--temps", 1)
    t = temps[0] if temps else "15"
    nom_jeu = jeux[0] if jeux else "sol_arbres"
    if nom_jeu not in JEUX_FENETRE:
        sys.exit(f"jeu inconnu: {nom_jeu} (disponibles: {', '.join(JEUX_FENETRE)})")
    base = os.path.join(ROOT, "render", "tests", "fenetre", nom_jeu, time.strftime("%Y%m%d_%H%M"))
    rc = 0
    for var, fen, sets in JEUX_FENETRE[nom_jeu]:
        f = FENETRES[fen]
        w = int(round((f["cap"][1] - f["cap"][0]) * PX_PAR_DEGRE))
        h = int(round((f["haut"][1] - f["haut"][0]) * PX_PAR_DEGRE))
        out = os.path.join(base, f"{fen}__{var}")
        os.makedirs(out, exist_ok=True)
        print(f"\n>>> {fen} / {var} ({w}x{h}, t = {t} s) -> {out}", flush=True)
        _attendre_ram(7.0)
        t0 = time.time()
        sa = []
        for x in [f"scene.bande_cap=[{f['cap'][0]},{f['cap'][1]}]", f"scene.bande_haut=[{f['haut'][0]},{f['haut'][1]}]",
                  f"scene.rendu_res=[{w},{h}]", "scene.rendu_echantillons=96"] + sets:
            sa += ["--set", x]
        r = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "bande", "--mono", "--camera-confirmed",
                        "--render-frame", "1", "--render-time", t, "--out", out] + sa + extra, fond=True)
        ok = os.path.exists(os.path.join(out, "frame_0001.png"))
        print(f"{'OK' if ok else 'ÉCHEC'}: {fen} / {var}, {(time.time() - t0) / 60:.1f} min", flush=True)
        rc = rc or (0 if ok else (r or 1))
    print(f"\nImages: {base}")
    try:
        open(os.path.join(base, "TERMINE.txt"), "w", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M") + "\n")
    except OSError:
        pass
    return rc


def cmd_test_oiseaux(cfg, paths, extra):
    """Envol d'oiseaux: clip plat (fenêtre 90 x 40 degrés à la densité du film final, 96 échantillons, réglages du film + sol net,
    arbres à 90 %, herbe) de t = 9 à 12,5 s de l'événement, puis vidéo mp4 30 images/s.
        python blatten.py test-oiseaux [--t0 9] [--t1 12.5]"""
    a0, extra = _option(extra, "--t0", 1)
    a1, extra = _option(extra, "--t1", 1)
    t0, t1 = float(a0[0]) if a0 else 9.0, float(a1[0]) if a1 else 12.5
    n, fps = _film(cfg)
    sc = cfg.get("scene") or {}
    intro, ts = float(sc.get("intro", 0.0)), float(sc.get("time_scale", 1.0))
    de = int(round((intro + t0 * ts) * fps)) + 1
    a = min(n, int(round((intro + t1 * ts) * fps)) + 1)
    cap, haut = (160.0, 250.0), (0.0, 40.0)
    w, h = int(round((cap[1] - cap[0]) * PX_PAR_DEGRE)), int(round((haut[1] - haut[0]) * PX_PAR_DEGRE))
    nom = time.strftime("%Y%m%d_%H%M")
    sets = [f"scene.bande_cap=[{cap[0]},{cap[1]}]", f"scene.bande_haut=[{haut[0]},{haut[1]}]", f"scene.rendu_res=[{w},{h}]",
            "scene.rendu_echantillons=96", _LUM, "scene.herbe=true", "scene.oiseaux=true"]
    sa = []
    for x in sets:
        sa += ["--set", x]
    print(f"Envol d'oiseaux {w}x{h}: t = {t0:g} à {t1:g} s, images {de} à {a} ({a - de + 1})", flush=True)
    rc = _rendre_film(cfg, paths, "bande", os.path.join("render", "tests_oiseaux"), n, fps,
                      ["--camera-confirmed", "--de", str(de), "--a", str(a), "--version", nom] + sa + extra, extrait=True)
    out = DERNIER_DOSSIER["out"]
    if rc != 0 or not out:
        return rc
    return subprocess.call([sys.executable, SCRIPTS["montage_film"], "--dir", out, "--format", "bande", "--fps", str(fps),
                            "--fondu", "0", "--crf", "14", "--out", os.path.join(out, "oiseaux_test.mp4")])


def _lin_srgb(a):
    import numpy as np
    a = np.asarray(a, np.float64) / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _gains_arbres(ref, avec, avant=None, seuil=0.02, lignes=None):
    """Gains (r, v, b) qui donnent aux pixels de feuillage des arbres 3D (avec vs ref, ou avec vs avant) la couleur moyenne de
    l'image aérienne en dessous (ref: rendu sans arbres). Exclus: ciel, pixels saturés, et ombres portées (pixels plus
    sombres de même teinte que l'image). lignes=(début, fin): seulement ces lignes de l'image. Rend (gains, nb pixels)."""
    import numpy as np
    autre = ref if avant is None else avant
    w = np.array([0.2126, 0.7152, 0.0722])
    m = (np.abs(avec - autre).sum(-1) > seuil) & (np.abs(avec - ref).sum(-1) > seuil) & ((ref @ w) < 0.45) \
        & (avec.max(-1) < 0.98) & (ref.max(-1) < 0.98)
    eps = 1e-4
    ch = lambda X: np.stack([X[..., 0] / (X[..., 1] + eps), X[..., 2] / (X[..., 1] + eps)], -1)
    ombre = (np.abs(ch(avec) - ch(ref)).sum(-1) < 0.08) & ((avec @ w) < (ref @ w))
    m &= ~ombre
    if lignes:
        m[:lignes[0]] = False
        m[lignes[1]:] = False
    if m.sum() < 500:
        return None, int(m.sum())
    g = ref[m].mean(0) / np.maximum(avec[m].mean(0), 1e-6)
    return [round(float(x), 3) for x in g], int(m.sum())


def cmd_test_arbres(cfg, paths, extra):
    """Arbres détaillés (jusqu'à quelle distance ?) et couleur des arbres face à l'image aérienne, sur une image fixe
    (bande HD plate, réglages du film, sol d'origine partout): render/tests/arbres/<date>/.
      R0 sans arbres: référence, la forêt telle que l'image aérienne la montre;
      D0, D200, D500, D1000: arbres détaillés jusqu'à 0 (aucun), 200, 500, 1000 m.
    Pour chaque image: temps de rendu. Puis les gains de couleur (rouge, vert, bleu) qui donneraient aux arbres simples (D0)
    et aux arbres détaillés (D200) la couleur moyenne de la forêt de l'image aérienne qu'ils recouvrent: bilan.json.
        python blatten.py test-arbres [--temps 15] [--distances 0 1000]     (le 7 nov.: 0 200 500 1000)"""
    import numpy as np
    from PIL import Image
    temps, extra = _option(extra, "--temps", 1)
    t = temps[0] if temps else "15"
    dists, extra = _option(extra, "--distances")
    dists = [float(x) for x in (dists or ["0", "1000"])]
    variantes = [("R0_sans_arbres", ["scene.no_trees=true"])]
    for dd in dists:
        variantes.append((f"D{dd:g}", [f"scene.arbres_modeles={'true' if dd > 0 else 'false'}", f"scene.arbres_modeles_dist={dd:g}"]))
    base = os.path.join(ROOT, "render", "tests", "arbres", time.strftime("%Y%m%d_%H%M"))
    bilan, imgs, rc = [], {}, 0
    for nom, sets in variantes:
        out = os.path.join(base, nom)
        os.makedirs(out, exist_ok=True)
        print(f"\n>>> {nom} (t = {t} s) -> {out}", flush=True)
        _attendre_ram(7.0)
        j = LOG_COURANT.get("chemin")
        depuis = os.path.getsize(j) if j and os.path.exists(j) else 0
        t0 = time.time()
        sa = ["--set", "scene.ortho_sol=false"]
        for x in sets:
            sa += ["--set", x]
        r = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "bande", "--mono", "--camera-confirmed",
                        "--render-frame", "1", "--render-time", t, "--out", out] + sa + extra, fond=True)
        f = os.path.join(out, "frame_0001.png")
        ok = os.path.exists(f)
        dt = (time.time() - t0) / 60
        gpu, tot, ram = _sonde_bilan(LOG_COURANT.get("chemin"), depuis if j == LOG_COURANT.get("chemin") else 0)
        bilan.append(dict(variante=nom, ok=ok, minutes=round(dt, 2), carte_mo_max=gpu, carte_mo_total=tot, ram_libre_min_go=ram))
        print(f"{'OK' if ok else 'ÉCHEC'}: {nom}, {dt:.1f} min (construction comprise), carte {gpu}/{tot} Mo, "
              f"RAM libre mini {ram if ram is not None else '?'} Go", flush=True)
        rc = rc or (0 if ok else (r or 1))
        if ok:
            imgs[nom] = _lin_srgb(np.asarray(Image.open(f).convert("RGB")))
        json.dump(bilan, open(os.path.join(base, "bilan.json"), "w", encoding="utf-8"), indent=1)
    ref = imgs.get("R0_sans_arbres")
    if ref is not None and "D0" in imgs:
        import numpy as np
        H = ref.shape[0]
        dmax = max([dd for dd in dists if f"D{dd:g}" in imgs] or [0.0])
        fin = imgs[f"D{dmax:g}"]
        res = dict(distance_detail=dmax)
        # arbres simples tels qu'ils restent dans le film: pixels d'arbres de D0 inchangés dans la variante la plus détaillée
        garde = np.abs(fin - imgs["D0"]).sum(-1) < 0.01
        bandes = (("", None), ("_loin", (0, int(H * 0.39))), ("_milieu", (int(H * 0.39), int(H * 0.66))), ("_proche", (int(H * 0.66), H)))
        for suf, lg in bandes:
            d0 = np.where(garde[..., None], imgs["D0"], ref)          # hors arbres simples restants: comme la référence
            g, n = _gains_arbres(ref, d0, lignes=lg)
            res[f"gains_simples{suf}"], res[f"pixels_simples{suf}"] = g, n
        if dmax > 0:
            for suf, lg in bandes:
                g, n = _gains_arbres(ref, fin, avant=imgs["D0"], lignes=lg)
                res[f"gains_detailles{suf}"], res[f"pixels_detailles{suf}"] = g, n
        # critère principal: une zone de forêt entière (arbres, trouées, sol) doit garder la couleur moyenne de la photo
        wl = np.array([0.2126, 0.7152, 0.0722])
        W = ref.shape[1]
        zones = {"versant_haut": (0.258, 0.406, 0.273, 0.410), "versant_bas": (0.469, 0.625, 0.254, 0.410),
                 "vallee": (0.703, 0.898, 0.020, 0.176), "proche": (0.664, 0.859, 0.840, 0.977)}
        print("\nZones de forêt (photo / rendu: 1 = même couleur moyenne que la photo seule):", flush=True)
        for nz, (r0, r1, c0, c1) in zones.items():
            zr = ref[int(r0 * H):int(r1 * H), int(c0 * W):int(c1 * W)].reshape(-1, 3).mean(0)
            for nv in ("D0", f"D{dmax:g}"):
                if nv not in imgs:
                    continue
                zt = imgs[nv][int(r0 * H):int(r1 * H), int(c0 * W):int(c1 * W)].reshape(-1, 3).mean(0)
                lum = float((zr @ wl) / max(zt @ wl, 1e-6))
                rg = float((zr[0] / zr[1]) / max(zt[0] / zt[1], 1e-6))
                bg = float((zr[2] / zr[1]) / max(zt[2] / zt[1], 1e-6))
                res[f"zone_{nz}_{nv}"] = dict(luminosite=round(lum, 3), rouge_vert=round(rg, 3), bleu_vert=round(bg, 3))
                print(f"  {nz:13s} {nv:6s} luminosité {lum:.2f}  rouge/vert {rg:.2f}  bleu/vert {bg:.2f}", flush=True)
        bilan.append(res)
        json.dump(bilan, open(os.path.join(base, "bilan.json"), "w", encoding="utf-8"), indent=1)
        print("\nGains pixel par pixel (indicatifs: biaisés pour les arbres vus de côté):", flush=True)
        for k, v in res.items():
            if k.startswith("gains_"):
                print(f"  {k[6:]:22s} {v}", flush=True)
    print(f"\nImages et bilan: {base}")
    return rc


def cmd_test_couleurs(cfg, paths, extra):
    """Même image (la première du film, bande plate HD) avec plusieurs réglages de couleur et de forêt, pour comparer:
    render/tests/couleurs/<date>/<nom>/. A actuel (saturation 0,8), B saturation 1,0, C saturation 1,25, D = B + couronnes x1,3.
        python blatten.py test-couleurs [--temps 0]"""
    temps, extra = _option(extra, "--temps", 1)
    variantes = [("A_actuel_sat0.8", []), ("B_sat1.0", ["scene.ortho_saturation=1.0"]), ("C_sat1.25", ["scene.ortho_saturation=1.25"]),
                 ("D_sat1.0_couronnes1.3", ["scene.ortho_saturation=1.0", "scene.tree_couronne=1.3"])]
    base = os.path.join(ROOT, "render", "tests", "couleurs", time.strftime("%Y%m%d_%H%M"))
    rc = 0
    for nom, sets in variantes:
        out = os.path.join(base, nom)
        os.makedirs(out, exist_ok=True)
        print(f"\n>>> {nom} -> {out}", flush=True)
        _attendre_ram(7.0)
        t0 = time.time()
        args = ["--render-frame", "1"] + (["--render-time", temps[0]] if temps else [])
        sa = []
        for x in sets:
            sa += ["--set", x]
        r = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "bande", "--mono", "--camera-confirmed"] + args
                        + ["--out", out] + sa + extra, fond=True)
        ok = os.path.exists(os.path.join(out, "frame_0001.png"))
        print(f"{'OK' if ok else 'ÉCHEC'}: {nom}, {(time.time() - t0) / 60:.1f} min", flush=True)
        rc = rc or (0 if ok else (r or 1))
    print(f"\nImages: {base}")
    return rc


POLICES_TITRE = ["georgia", "pala", "constan", "segoeuil", "candara", "times"]


def _police_windows(nom):
    """Chemin d'une police de C:/Windows/Fonts d'après un nom de fichier sans extension (georgia, pala...), ou un chemin complet."""
    if os.path.isfile(nom):
        return nom
    d = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
    if os.path.isdir(d):
        for f in os.listdir(d):
            if os.path.splitext(f)[0].lower() == nom.lower() and f.lower().endswith((".ttf", ".otf")):
                return os.path.join(d, f)
    return None


def cmd_titre_test(cfg, paths, extra):
    """Une image de l'intro (image 1 du film) en bande plate HD par variante du titre: render/tests/titre/<date>/<variante>/.
        python blatten.py titre-test [--styles blanc sombre]            couleurs
        python blatten.py titre-test --polices georgia pala constan     polices (noms de fichiers de C:/Windows/Fonts sans extension), style du film
    Sans option: les couleurs, ou les polices ci-dessus si le fichier de réglages en choisit déjà une."""
    styles, extra = _option(extra, "--styles")
    polices, extra = _option(extra, "--polices")
    if polices is not None and not polices:
        polices = POLICES_TITRE
    variantes = []          # (nom, options --set)
    if polices:
        for nom in polices:
            ch = _police_windows(nom)
            if not ch:
                print(f"police {nom} introuvable, ignorée", flush=True)
                continue
            variantes.append((f"police_{nom}", ["--set", f"scene.titre_police={ch.replace(chr(92), '/')}"]))
    else:
        for st in (styles or ["blanc", "sombre"]):
            variantes.append((st, ["--set", f"scene.titre_style={st}"]))
    base = os.path.join(ROOT, "render", "tests", "titre", time.strftime("%Y%m%d_%H%M"))
    rc = 0
    for nom, opts in variantes:
        out = os.path.join(base, nom)
        os.makedirs(out, exist_ok=True)
        print(f"\n>>> titre {nom} -> {out}", flush=True)
        _attendre_ram(7.0)
        t0 = time.time()
        r = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", "bande", "--mono", "--camera-confirmed",
                        "--render-frame", "1", "--out", out, "--set", "scene.titre=true"] + opts + extra, fond=True)
        ok = os.path.exists(os.path.join(out, "frame_0001.png"))
        print(f"{'OK' if ok else 'ÉCHEC'}: titre {nom}, {(time.time() - t0) / 60:.1f} min", flush=True)
        rc = rc or (0 if ok else (r or 1))
    print(f"\nImages: {base}")
    return rc


def cmd_test_son(cfg, paths, extra):
    """Mini vidéo 360 (25 s, sans Blender) pour vérifier que le son tourne avec la tête: bruits de calibrage (avant, gauche,
    arrière, droite) puis 15 s du vrai son en plein événement. À mettre sur YouTube en non répertorié.
        python blatten.py test-son [--debut 45] [--duree 15]   -> <render_dir>/tests_son/<date>/test_son_360.mp4"""
    deb, extra = _option(extra, "--debut", 1)
    dur, extra = _option(extra, "--duree", 1)
    rd = (cfg.get("render_dir") or "").strip() or os.path.join(ROOT, "render")
    out = os.path.join(rd, "tests_son", time.strftime("%Y%m%d_%H%M"))
    os.makedirs(out, exist_ok=True)
    d_son = os.path.join(out, "son")
    if subprocess.call([sys.executable, SCRIPTS["son"], "--out", d_son]) != 0:
        print("!! son non calculé", flush=True)
        return 1
    a = ["--ambix", os.path.join(d_son, "son_ambix.wav"), "--out", out] + (["--debut", deb[0]] if deb else []) + (["--duree", dur[0]] if dur else [])
    rc = subprocess.call([sys.executable, SCRIPTS["test_son"]] + a)
    if rc == 0:
        print(f"\nVidéo de test: {os.path.join(out, 'test_son_360.mp4')}", flush=True)
    return rc


def cmd_variantes(cfg, paths, extra):
    """Le MÊME instant rendu avec plusieurs jeux de réglages (dossier reglages/), pour comparer avant de choisir.
        python blatten.py variantes [--temps 43 30] [--jeux actuel mixte "mixte poussiere_v2"] [--qualite final|brouillon] [--refaire]
    Un jeu entre guillemets peut en combiner plusieurs (appliqués dans l'ordre). Images: render/variantes/t43s/<jeu>/,
    avec le temps de rendu et les réglages effectifs (reglages_effectifs.json). Une variante déjà rendue est sautée (--refaire pour la refaire).
    Les options inconnues (ex. --set poussiere.densite=0.02) s'appliquent à toutes les variantes."""
    sys.path.insert(0, SRC)
    import reglages as R
    temps, extra = _option(extra, "--temps")
    jeux, extra = _option(extra, "--jeux")
    qual, extra = _option(extra, "--qualite", 1)
    refaire = "--refaire" in extra
    extra = [x for x in extra if x != "--refaire"]
    temps = [float(t) for t in (temps or ["43"])]
    jeux = jeux or ["actuel", "mixte", "mixte poussiere_v2"]
    qual = (qual or ["final"])[0]
    if qual not in ("final", "brouillon", "test"):
        sys.exit("--qualite final, brouillon ou test")
    dispo = R.lister()
    for j in jeux:
        for nom in j.split():
            if nom not in dispo:
                sys.exit(f"Jeu de réglages inconnu: {nom} (disponibles: {', '.join(dispo)})")
    ext = _ext(qual, extra)
    bilan = []
    for t in temps:
        for j in jeux:
            noms = j.split()
            label = "+".join(noms)
            out = os.path.join(ROOT, "render", "variantes", f"t{t:g}s", label)
            os.makedirs(out, exist_ok=True)
            f = os.path.join(out, "frame_0001" + ext)
            if os.path.exists(f) and os.path.getsize(f) > 0 and not refaire:
                print(f"t = {t:g} s, {label}: déjà rendue, sautée (--refaire pour la refaire)")
                bilan.append(dict(temps=t, jeu=label, statut="deja"))
                continue
            print(f"\n>>> t = {t:g} s, réglages {label} -> render/variantes/t{t:g}s/{label}", flush=True)
            _attendre_ram(7.0)
            t0 = time.time()
            rc = run_blender(cfg, SCRIPTS["scene"], scene_args(cfg, paths) + ["--preset", qual, "--mono", "--camera-confirmed",
                             "--render-frame", "1", "--render-time", str(t), "--out", out, "--reglages"] + noms + extra, fond=True)
            ok = os.path.exists(f) and os.path.getsize(f) > 0
            d = time.time() - t0
            bilan.append(dict(temps=t, jeu=label, statut="ok" if ok else f"echec (code {rc})", minutes=round(d / 60, 1)))
            print(f"{'OK' if ok else 'ÉCHEC'}: t = {t:g} s, {label}, {d / 60:.1f} min (construction de la scène comprise)", flush=True)
    with open(os.path.join(ROOT, "render", "variantes", "bilan.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(date=time.strftime("%Y-%m-%d %H:%M"), qualite=qual, variantes=bilan), fh, indent=2, ensure_ascii=False)
    print("\nBilan:")
    for b in bilan:
        print(f"  t = {b['temps']:g} s  {b['jeu']:<30} {b['statut']}" + (f"  ({b['minutes']} min)" if "minutes" in b else ""))
    return 0 if all(b["statut"] in ("ok", "deja") for b in bilan) else 1


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


def _npy_valeur(path, r, c):
    """Une valeur d'un tableau .npy 2D (float32/float64), sans numpy: lecture directe dans le fichier."""
    import ast
    import struct
    with open(path, "rb") as f:
        if f.read(6) != b"\x93NUMPY":
            raise ValueError(f"{path}: pas un fichier .npy")
        major = f.read(2)[0]
        hl = struct.unpack("<H" if major == 1 else "<I", f.read(2 if major == 1 else 4))[0]
        h = ast.literal_eval(f.read(hl).decode("latin1"))
        H, W = h["shape"][:2]
        code = {"<f4": "<f", "<f8": "<d"}[h["descr"]]
        size = struct.calcsize(code)
        r, c = min(max(int(r), 0), H - 1), min(max(int(c), 0), W - 1)
        idx = c * H + r if h.get("fortran_order") else r * W + c
        f.seek(f.tell() + idx * size)
        return struct.unpack(code, f.read(size))[0]


def _wgs84_vers_lv95(lat, lon):
    """Formules approchées de swisstopo (précision ~1 m)."""
    p, l = (lat * 3600 - 169028.66) / 10000, (lon * 3600 - 26782.5) / 10000
    E = 2600072.37 + 211455.93 * l - 10938.51 * l * p - 0.36 * l * p * p - 44.54 * l ** 3
    N = 1200147.07 + 308807.95 * p + 3745.25 * l * l + 76.63 * p * p - 194.56 * l * l * p + 119.79 * p ** 3
    return E, N


# zone haute résolution nécessaire autour de la caméra (anneaux du relief 0,5/1 m et images 50 cm/10 cm de la scène)
MARGE_RELIEF_05 = 800.0
MARGE_IMAGE_10 = 1000.0


def cmd_camera(cfg, paths, extra):
    """Position de la caméra en coordonnées suisses (LV95), sans passer par Blender.
        python blatten.py camera                                    affiche la caméra actuelle (LV95, altitude, couverture haute résolution)
        python blatten.py camera --lv95 2628474 1140885 [--hauteur 2] [--cap 200]
        python blatten.py camera --wgs84 46.4205 7.8195 [--hauteur 2] [--cap 200]   (coordonnées lues sur une carte)
    La hauteur est comptée au-dessus du sol (relief 0,5 m si disponible, sinon 2 m). Le cap (degrés, 0 = nord, 90 = est) oriente la vue de départ.
    L'ancienne caméra est gardée dans camera_precedente.json. Si la nouvelle position sort de la zone haute résolution, les dalles manquantes
    sont ajoutées aux listes de téléchargement (data_sources/swisstopo) et la suite à lancer est affichée."""
    mp = os.path.join(paths.cache, "env", "env_meta.json")
    if not os.path.exists(mp):
        sys.exit("Environnement non préparé (env_meta.json): lancer d'abord la préparation du relief (prep-env).")
    m = _load_json(mp)
    fc = os.path.join(ROOT, "camera.json")
    cam = _load_json(fc) if os.path.exists(fc) else {}
    lv, extra = _option(extra, "--lv95", 2)
    wg, extra = _option(extra, "--wgs84", 2)
    hv, extra = _option(extra, "--hauteur", 1)
    cv, extra = _option(extra, "--cap", 1)
    dz = m.get("dz", 0.0) if abs(m.get("dz", 0.0)) < 30 else 0.0

    def sol(E, N):
        for cle in ("dem05", "dem2", "dem8"):
            d = m.get(cle)
            f = d and os.path.join(paths.cache, "env", d["file"])
            if not d or not os.path.exists(f):
                continue
            c, r = (E - d["x0"]) / d["step"], (d["y1"] - N) / d["step"]
            if 0 <= c < d["shape"][1] - 1 and 0 <= r < d["shape"][0] - 1:
                return _npy_valeur(f, round(r), round(c)) + dz, cle
        return None, None

    def couverture(E, N):
        d5 = m.get("dem05")
        ok5 = bool(d5) and (d5["x0"] + MARGE_RELIEF_05 <= E <= d5["x0"] + d5["shape"][1] * d5["step"] - MARGE_RELIEF_05
                            and d5["y1"] - d5["shape"][0] * d5["step"] + MARGE_RELIEF_05 <= N <= d5["y1"] - MARGE_RELIEF_05)
        return ok5

    if not lv and not wg:
        if not cam.get("cam"):
            sys.exit("Pas de camera.json.")
        x, y, z = cam["cam"]
        E, N = m["scene_E0"] + x, m["scene_N0"] + m["flip"] * y
        zs, src = sol(E, N)
        print(f"Caméra actuelle: LV95 E {E:.1f} N {N:.1f}, altitude {z:.1f} m"
              + (f" ({z - zs:.1f} m au-dessus du sol, relief {src})" if zs is not None else ""))
        print(f"Cap de la vue de départ: {(-cam.get('rot_deg', [90, 0, 0])[2]) % 360:.0f} degrés; confirmée par le groupe: {bool(cam.get('confirmed'))}")
        print("Zone haute résolution (relief 0,5 m):", "couvre la caméra" if couverture(E, N) else "NE couvre PAS la caméra")
        return 0
    if wg:
        E, N = _wgs84_vers_lv95(float(wg[0]), float(wg[1]))
        print(f"WGS84 {wg[0]}, {wg[1]} -> LV95 E {E:.1f} N {N:.1f}")
    else:
        E, N = float(lv[0]), float(lv[1])
    h = float(hv[0]) if hv else float(cam.get("z_sol_plus", 2.0))
    cap = float(cv[0]) if cv else (-cam.get("rot_deg", [90, 0, -200])[2]) % 360
    zs, src = sol(E, N)
    if zs is None:
        sys.exit(f"LV95 E {E:.0f} N {N:.0f}: hors du relief préparé (dem 0,5/2/8 m). Position trop loin de la vallée?")
    if os.path.exists(fc):
        shutil.copy(fc, os.path.join(ROOT, "camera_precedente.json"))
    nouv = dict(cam=[round(E - m["scene_E0"], 2), round((N - m["scene_N0"]) * m["flip"], 2), round(zs + h, 2)],
                rot_deg=[90.0, 0.0, round(-cap, 1)], confirmed=False, lv95=[round(E, 1), round(N, 1)], z_sol_plus=h,
                note=f"Caméra posée le {time.strftime('%Y-%m-%d')} par python blatten.py camera (LV95 E {E:.0f} N {N:.0f}, {h:g} m au-dessus du sol, "
                     f"relief {src}, cap {cap:.0f}). À valider avec le groupe (confirmed: true).")
    json.dump(nouv, open(fc, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"camera.json écrit: scène {nouv['cam']}, sol {zs:.1f} m ({src}), cap {cap:.0f} degrés (ancienne caméra: camera_precedente.json)")
    print("La caméra n'est pas confirmée: le rendu final refusera de partir tant que \"confirmed\" n'est pas true dans camera.json.")
    if couverture(E, N):
        print("Zone haute résolution: déjà couverte. Suite: python blatten.py prep-env --hires (images 10 cm recentrées), "
              "python blatten.py visible, puis une image test.")
        return 0
    # dalles de 1 km manquantes autour de la caméra (relief 0,5 m et images 10 cm), ajoutées aux listes avec l'année à deviner
    ajout = 0
    for csv, motif, marge in (("swissalti3d_05m.csv", "https://data.geo.admin.ch/ch.swisstopo.swissalti3d/swissalti3d_YYYY_{k}/swissalti3d_YYYY_{k}_0.5_2056_5728.tif", MARGE_RELIEF_05 + 400),
                              ("swissimage_10cm.csv", "https://data.geo.admin.ch/ch.swisstopo.swissimage-dop10/swissimage-dop10_YYYY_{k}/swissimage-dop10_YYYY_{k}_0.1_2056.tif", MARGE_IMAGE_10)):
        f = os.path.join(paths.csv, csv)
        txt = open(f, encoding="utf-8-sig").read() if os.path.exists(f) else ""
        lignes = []
        for ek in range(int((E - marge) // 1000), int((E + marge) // 1000) + 1):
            for nk in range(int((N - marge) // 1000), int((N + marge) // 1000) + 1):
                k = f"{ek}-{nk}"
                if f"_{k}" not in txt:
                    lignes.append(motif.format(k=k))
        if lignes:
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(("" if txt.endswith("\n") or not txt else "\n") + "\n".join(lignes) + "\n")
            ajout += len(lignes)
            print(f"  {csv}: {len(lignes)} dalle(s) ajoutée(s)")
    print(f"La caméra sort de la zone haute résolution: {ajout} dalle(s) à télécharger. Suite, dans l'ordre:\n"
          "  python blatten.py download --jeux 05m 10cm\n  python blatten.py prep-env --hires\n  python blatten.py visible\n"
          "  puis une image test (si la caméra a bougé de plus de 500 m: refaire aussi env-complet pour la végétation et les bâtiments).")
    return 0


_MODULES = {}


def _module(nom, chemin):
    if nom not in _MODULES:
        import importlib.util
        spec = importlib.util.spec_from_file_location(nom, chemin)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MODULES[nom] = m
    return _MODULES[nom]


def _duo(nom_commande):
    """Rendu à deux PC: src/partage/duo.py (protocole) et duo_commandes.py (commandes). Mode d'emploi: docs/RENDU_A_DEUX.md."""
    D = _module("duo", os.path.join(SRC, "partage", "duo.py"))
    C = _module("duo_commandes", os.path.join(SRC, "partage", "duo_commandes.py"))
    f = getattr(C, nom_commande)
    return lambda cfg, paths, extra: f(sys.modules[__name__], D, cfg, paths, extra)


def cmd_paquet(cfg, paths, extra):
    """Prépare le rendu du film 360 à deux PC (Ilyas + frère): session, code figé, paquet du frère en UN zip (code, données,
    Blender, lanceurs), test du paquet. Voir docs/RENDU_A_DEUX.md.
        python blatten.py paquet [--transport github|dossier|manuel] [--sans-blender] [--sans-test] [--oui]"""
    return _duo("cmd_paquet")(cfg, paths, extra)


def cmd_duo(cfg, paths, extra):
    """Rend la part de ce PC (Ilyas: du début, frère: de la fin), partage en direct, montage final sur le PC d'Ilyas.
        python blatten.py duo [--jusqu-a 07:00] [--tout-rendre]"""
    return _duo("cmd_duo")(cfg, paths, extra)


def cmd_duo_etat(cfg, paths, extra):
    return _duo("cmd_duo_etat")(cfg, paths, extra)


def cmd_duo_envoyer(cfg, paths, extra):
    return _duo("cmd_duo_envoyer")(cfg, paths, extra)


def cmd_duo_importer(cfg, paths, extra):
    return _duo("cmd_duo_importer")(cfg, paths, extra)


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
        origin = [1117.4016956592827, 0.0, -1121.1231332002285]    # repère de la simulation (voir docs/archive/CONTRAT_MATIERE.md)
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
    "valider-env": cmd_valider_env, "prep-eau": cmd_prep_eau, "eau-manuel": cmd_eau_manuel, "brouillon": cmd_brouillon, "montage": cmd_montage, "images-test": cmd_images_test, "apercu-complet": cmd_apercu_complet, "apercu-alea": cmd_apercu_alea, "images-finales": cmd_images_finales, "variantes": cmd_variantes, "titre-test": cmd_titre_test, "test-son": cmd_test_son, "test-couleurs": cmd_test_couleurs, "test-eau": cmd_test_eau, "test-final": cmd_test_final, "prep-sol": cmd_prep_sol, "test-aspect": cmd_test_aspect, "test-fenetre": cmd_test_fenetre, "test-oiseaux": cmd_test_oiseaux, "test-arbres": cmd_test_arbres, "extrait": cmd_extrait, "test-bande": cmd_test_bande, "finir": cmd_finir, "son": cmd_son, "outro": cmd_outro, "cap": cmd_cap, "camera": cmd_camera, "paquet": cmd_paquet, "duo": cmd_duo, "duo-etat": cmd_duo_etat, "duo-envoyer": cmd_duo_envoyer, "duo-importer": cmd_duo_importer, "empreinte-alea": cmd_empreinte_alea, "lite": cmd_lite, "open": cmd_open, "voir360": cmd_voir360, "bench": cmd_bench, "test-clip": cmd_test_clip, "meta360": cmd_meta360, "bench-compare": cmd_bench_compare, "render": cmd_render, "menu": cmd_menu,
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
    if a.jeux:      # --jeux sert aussi à d'autres commandes (variantes): on le leur rend
        extra = extra + ["--jeux"] + a.jeux
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
