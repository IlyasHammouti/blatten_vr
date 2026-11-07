"""
duo_commandes.py : commandes du rendu à deux PC, appelées par blatten.py (principe: src/partage/duo.py, mode d'emploi:
docs/RENDU_A_DEUX.md).

    paquet        (PC d'Ilyas) prépare la session, une copie figée du code, le paquet du frère (un seul zip) et le teste
    duo           rend la part de ce PC; sur le PC d'Ilyas, importe les images du frère puis fait le montage final
    duo-etat      où en sont les deux PC
    duo-envoyer   (PC du frère) un seul zip de toutes ses images, à envoyer à Ilyas (SwissTransfer, clé USB)
    duo-importer  (PC d'Ilyas) importe un zip ou un dossier d'images du frère

Chaque fonction reçoit B (le module blatten.py: Blender, chemins, nettoyage des images) et D (src/partage/duo.py).
"""
import getpass
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

EXT = ".jpg"                     # images du preset final (JPEG qualité 95, environ 1 Mo)
K_DEFAUT = 12                    # images par paquet: une construction de scène (~3 min) par paquet, mémoire remise à zéro
VITESSE_FRERE = 1.6              # RTX 3060 / RTX 2060 (estimation, corrigée en direct par les vitesses mesurées)
IMAGE_TEST = 1531                # image du test du paquet: t = 43 s, la plus chargée (poussière, matière)
SWISSTRANSFER = "https://www.swisstransfer.com/"
JOURNAL = {"f": None}

GUIDE_GITHUB = """
Réglage GitHub (une seule fois, 3 minutes), dans le navigateur:
  1. github.com, bouton + en haut à droite, New repository. Nom: blatten-transfert. Cocher Private et « Add a README file ».
     Create repository.
  2. Photo de profil, Settings, Developer settings, Personal access tokens, Fine-grained tokens, Generate new token.
     Token name: blatten-duo. Expiration: 30 days. Repository access: Only select repositories, choisir blatten-transfert.
     Permissions, Repository permissions, Contents: Read and write. Generate token, puis copier le jeton (github_pat_...).
  Ce jeton n'ouvre QUE le dépôt de transfert: il voyage dans le paquet du frère sans exposer ton code.
"""

GPU_SCRIPT = '''import bpy
p = bpy.context.preferences.addons["cycles"].preferences
trouve = None
for k in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
    try:
        p.compute_device_type = k
        p.get_devices()
        g = sorted({d.name for d in p.devices if d.type != "CPU"})
        if g:
            trouve = (k, " | ".join(g))
            break
    except Exception:
        pass
print("DUO_GPU", trouve[0] if trouve else "AUCUN", trouve[1] if trouve else "-", flush=True)
'''


def log(*a):
    ligne = f"[duo {time.strftime('%H:%M:%S')}] " + " ".join(str(x) for x in a)
    try:
        print(ligne, flush=True)
    except Exception:
        pass
    if JOURNAL["f"]:
        try:
            with open(JOURNAL["f"], "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d ") + ligne + "\n")
        except OSError:
            pass


def _lire_json(p, defaut):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defaut


def _ecrire_json(p, d):
    tmp = p + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def _rd(B, cfg):
    return B._path((cfg.get("render_dir") or "").strip() or os.path.join(B.ROOT, "render"))


def _images(out, ordre_set=None):
    """Numéros des images présentes (fichier non vide) dans out."""
    res = set()
    try:
        noms = os.listdir(out)
    except OSError:
        return res
    for nm in noms:
        m = re.fullmatch(r"frame_(\d{4,})" + re.escape(EXT), nm)
        if m:
            f = int(m.group(1))
            if ordre_set is None or f in ordre_set:
                try:
                    if os.path.getsize(os.path.join(out, nm)) > 0:
                        res.add(f)
                except OSError:
                    pass
    return res


def _ouvrir(cible, selection=False):
    """Ouvre un dossier, un fichier (sélectionné dans l'Explorateur) ou une adresse web. Sans effet hors Windows."""
    if os.name != "nt":
        return
    try:
        if selection:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(cible)])
        else:
            os.startfile(cible)
    except Exception:
        pass


def _telechargements():
    """Dossier Téléchargements de Windows (même s'il a été déplacé), sinon ~/Downloads."""
    if os.environ.get("BLATTEN_DUO_TELECHARGEMENTS"):
        return os.environ["BLATTEN_DUO_TELECHARGEMENTS"]
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
            g = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                r = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                return r
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def _empecher_veille():
    """Windows: pas de mise en veille tant que ce programme tourne (l'écran peut s'éteindre). Rien à rétablir: l'effet cesse à la
    fermeture de la fenêtre."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        except Exception:
            pass


_GARDE = []


def _sur_fermeture(fonction):
    """Windows: à la fermeture de la fenêtre (ou Ctrl+C), prévient l'autre PC que nos images en cours sont libres (au mieux:
    Windows laisse quelques secondes)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        PROTO = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

        def gestion(evt):
            if evt in (0, 1, 2, 5, 6):
                try:
                    fonction()
                except Exception:
                    pass
            return 0
        h = PROTO(gestion)
        _GARDE.append(h)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(h, True)
    except Exception:
        pass


def _verifier_gpu(B, cfg):
    """(nom de la carte, None) si Blender voit une carte graphique, sinon (None, explication)."""
    try:
        exe = B.find_blender(cfg, ask=False)
    except SystemExit as e:
        return None, str(e)
    script = os.path.join(tempfile.gettempdir(), "blatten_duo_gpu.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(GPU_SCRIPT)
    try:
        r = subprocess.run([exe, "-b", "--factory-startup", "--python", script], capture_output=True, text=True, timeout=600,
                           encoding="utf-8", errors="replace")
    except Exception as e:
        return None, f"Blender ne démarre pas: {e}"
    m = re.search(r"DUO_GPU (\S+) (.+)", r.stdout or "")
    if m and m.group(1) != "AUCUN":
        return f"{m.group(2).strip()} ({m.group(1)})", None
    fin = "\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-8:])
    return None, "Blender ne voit aucune carte graphique NVIDIA (pilote à mettre à jour ?)\n" + fin


def _version_blender(exe):
    try:
        o = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace").stdout
        m = re.search(r"Blender (\d+\.\d+\.\d+)", o)
        return m.group(1) if m else None
    except Exception:
        return None


# ----------------------------------------------------------------------------------
# Session
# ----------------------------------------------------------------------------------
def charger_session(B, cfg, extra):
    """Session du PC du frère (fichier duo_session.json dans le paquet) ou du PC d'Ilyas (la plus récente de render_dir/duo,
    ou --session ID). Ajoute _role, _racine (code figé qui fait les images), _out (dossier des images), _base."""
    f = os.path.join(B.ROOT, "duo_session.json")
    if os.path.exists(f):
        s = _lire_json(f, None)
        if not s:
            sys.exit(f"{f} illisible")
        s["_role"], s["_racine"] = "frere", B.ROOT
        rd = B._path((cfg.get("render_dir") or "").strip() or os.path.join(B.ROOT, "..", "images"))
        s["_out"] = os.path.join(rd, "final_" + s["session"])
        s["_base"] = os.path.dirname(B.ROOT)
        s["_lots"] = os.path.join(rd, "lots_" + s["session"])
        return s, extra
    sid, extra = B._option(extra, "--session", 1)
    base = os.path.join(_rd(B, cfg), "duo")
    if sid:
        sid = sid[0]
    else:
        cands = sorted((os.path.getmtime(os.path.join(base, d, "session.json")), d) for d in (os.listdir(base) if os.path.isdir(base) else [])
                       if os.path.exists(os.path.join(base, d, "session.json")))
        if not cands:
            sys.exit("Aucune session de rendu à deux: la préparer d'abord (Lancer_preparer_duo.bat, ou python blatten.py paquet).")
        sid = cands[-1][1]
    s = _lire_json(os.path.join(base, sid, "session.json"), None)
    if not s:
        sys.exit(f"Session {sid} introuvable dans {base}")
    s["_role"], s["_racine"] = "ilyas", os.path.join(base, sid, "code")
    s["_out"], s["_base"] = s["dossier_film"], os.path.join(base, sid)
    s["_lots"] = os.path.join(base, sid, "telecharges")
    return s, extra


def _plan(D, s):
    p = s["plan"]
    pl = D.plan(p["n"], p.get("n_intro", 0), p.get("k_intro", 1), p.get("k_film", 1))
    return pl, [f for f, _ in pl], dict(pl)


def _canal(D, s, role, cache=None):
    return D.Canal(s.get("serveur"), s["sujet"], s["session"], role, cache=cache)


def _transport(D, s, role):
    t = dict(s.get("transport") or {"type": "manuel"})
    chemin = None
    if t.get("type") == "dossier":
        chemin = D.chercher_dossier(t.get("chemin_ilyas") if role == "ilyas" else (t.get("chemin_frere") or t.get("nom")))
        chemin = chemin or D.chercher_dossier(t.get("nom"))
    return D.transport(t, chemin)


# ----------------------------------------------------------------------------------
# paquet: préparation sur le PC d'Ilyas
# ----------------------------------------------------------------------------------
def _rappel_feuille_de_route(B):
    f = os.path.join(B.ROOT, "docs", "FEUILLE_DE_ROUTE.md")
    try:
        txt = open(f, encoding="utf-8").read()
    except OSError:
        txt = ""
    blocs = []
    for titre in ("## Avant le rendu 360 final", "## Décisions en attente d'Ilyas"):
        i = txt.find(titre)
        if i >= 0:
            j = txt.find("\n## ", i + 3)
            blocs.append(txt[i:j if j > 0 else None].strip())
    if blocs:
        print("\n" + "=" * 78 + "\nFEUILLE DE ROUTE (docs/FEUILLE_DE_ROUTE.md), à vérifier avant le rendu final\n" + "=" * 78)
        print("\n\n".join(blocs))
        print("=" * 78)
    if not (sys.stdin and sys.stdin.isatty()):
        return True
    r = input("\nLes images rendues à partir de maintenant ne pourront plus changer (réglages, arbres, eau, titre...).\n"
              "Tout est décidé ? (o/n) ").strip().lower()
    return r[:1] in ("o", "y")


def _choisir_transport(B, cfg, tr_opt, dos_opt):
    loc = dict(cfg.get("duo") or {})
    tty = bool(sys.stdin and sys.stdin.isatty())
    t = tr_opt or loc.get("transport")
    if not t and tty:
        print("\nComment les images du frère arrivent-elles sur ce PC ?\n"
              "  1. GitHub, automatique (recommandé): 3 minutes de réglage une fois, puis tout arrive seul pendant le rendu\n"
              "  2. Dossier partagé, automatique: Google Drive pour ordinateur, OneDrive, Dropbox ou dossier réseau sur les deux PC\n"
              "  3. À la main, à la fin: le frère t'envoie un seul fichier (SwissTransfer ou clé USB). Rien à régler.")
        t = {"1": "github", "2": "dossier", "3": "manuel"}.get(input("Choix (1, 2 ou 3) ? ").strip(), "manuel")
    t = t or "manuel"
    if t == "github":
        depot, jeton = loc.get("depot"), loc.get("jeton")
        if not (depot and jeton):
            if not tty:
                sys.exit('GitHub: renseigner "duo": {"depot": "...", "jeton": "..."} dans config.local.json, ou --transport manuel')
            print(GUIDE_GITHUB)
            depot = input("Dépôt (ex. IlyasHammouti/blatten-transfert) ? ").strip().strip("/")
            depot = re.sub(r"^https?://github\.com/", "", depot)
            jeton = getpass.getpass("Jeton (collé avec clic droit; il ne s'affiche pas) ? ").strip()
        loc.update(transport="github", depot=depot, jeton=jeton)
        B.save_local("duo", loc)
        return {"type": "github", "depot": depot, "jeton": jeton}
    if t == "dossier":
        chemin = dos_opt or loc.get("chemin")
        if not chemin and tty:
            chemin = input("Chemin du dossier partagé sur CE PC (ex. G:\\Mon Drive\\Blatten_partage) ? ").strip().strip('"')
        if not chemin or not os.path.isdir(chemin):
            sys.exit(f"Dossier partagé introuvable: {chemin}. Le créer (et le partager avec le frère) puis relancer.")
        chemin = os.path.abspath(chemin)
        loc.update(transport="dossier", chemin=chemin)
        B.save_local("duo", loc)
        return {"type": "dossier", "nom": os.path.basename(os.path.normpath(chemin)), "chemin_ilyas": chemin}
    loc.update(transport="manuel")
    B.save_local("duo", loc)
    return {"type": "manuel"}


def _fichiers_suivis(B):
    try:
        o = subprocess.run(["git", "-C", B.ROOT, "-c", "core.quotepath=off", "ls-files", "-z"], capture_output=True, check=True).stdout
        fs = [x for x in o.decode("utf-8", "replace").split("\0") if x]
        if fs:
            return fs
    except Exception:
        pass
    out = []
    for d, sous, fs in os.walk(B.ROOT):
        sous[:] = [x for x in sous if x not in (".git", "render", "__pycache__", "_archive", "_to_delete", ".pylibs")]
        out += [os.path.relpath(os.path.join(d, f), B.ROOT).replace("\\", "/") for f in fs if f != "config.local.json"]
    return out


def _donnees_paquet(paths):
    """Données nécessaires au rendu (relatives au dossier cache): particules, sources de poussière, environnement préparé.
    Pas les fichiers bruts swisstopo ni les volumes de Johan (inutiles quand l'environnement existe)."""
    rels = []
    for f in sorted(os.listdir(paths.cache)):
        p = os.path.join(paths.cache, f)
        if os.path.isfile(p) and (re.match(r"all_particles_\d+\.npy$", f) or f == "meta.json" or f.startswith("poussiere_sources_")):
            if f != "all_particles_1500.npy":
                rels.append(f)
    env = os.path.join(paths.cache, "env")
    for d, sous, fs in os.walk(env):
        sous.sort()
        rels += [os.path.relpath(os.path.join(d, f), paths.cache).replace("\\", "/") for f in sorted(fs)]
    return rels


COMPRESSER = (".npy", ".json", ".txt", ".py", ".md", ".bat", ".csv", ".html", ".ply", ".obj", ".asc", ".geojson", ".xyz")


def _ecrire_zip(dest, entrees, titre):
    """entrees: [(fichier source, nom dans le zip, compresser)] ou [(None, nom, octets)]. Écrit dest.part puis renomme."""
    tmp = dest + ".part"
    total = sum(os.path.getsize(e[0]) for e in entrees if e[0]) or 1
    fait, palier = 0, 0
    with zipfile.ZipFile(tmp, "w", allowZip64=True) as z:
        for src, arc, opt in entrees:
            if src is None:
                z.writestr(arc, opt, compress_type=zipfile.ZIP_DEFLATED)
                continue
            if opt:
                z.write(src, arc, compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
            else:
                z.write(src, arc, compress_type=zipfile.ZIP_STORED)
            fait += os.path.getsize(src)
            if fait * 20 // total > palier:
                palier = fait * 20 // total
                log(f"{titre}: {5 * palier} % ({fait / 1e9:.2f}/{total / 1e9:.2f} Go)")
    os.replace(tmp, dest)
    return dest


def _zip_blender(B, cfg, dest):
    """Copie zippée du Blender de ce PC (même version des deux côtés: images identiques, rien à installer chez le frère)."""
    if os.path.exists(dest):
        return dest
    exe = B.find_blender(cfg, ask=False)
    dossier = os.path.dirname(exe)
    entrees = []
    for d, sous, fs in os.walk(dossier):
        sous[:] = [x for x in sous if x != "__pycache__"]
        for f in fs:
            p = os.path.join(d, f)
            entrees.append((p, os.path.relpath(p, dossier).replace("\\", "/"), True))
    log(f"Copie de Blender ({dossier}, {len(entrees)} fichiers), une fois pour toutes les sessions...")
    tmp = dest + ".part"
    with zipfile.ZipFile(tmp, "w", allowZip64=True) as z:
        for k, (p, arc, _c) in enumerate(entrees, 1):
            z.write(p, arc, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
            if k % 2000 == 0:
                log(f"  Blender: {k}/{len(entrees)} fichiers")
    os.replace(tmp, dest)
    return dest


def _bat(nom_commande, titre, ver, url):
    """Lanceur du PC du frère (ASCII seulement: les accents passent mal dans les .bat)."""
    return f"""@echo off
setlocal
cd /d "%~dp0"
title Blatten 360 - {titre}
if not exist "code\\blatten.py" goto pas_extrait
call :blender
if errorlevel 1 goto fin
call :python
if errorlevel 1 goto fin
"%PY%" code\\blatten.py {nom_commande}
:fin
echo.
pause
exit /b

:pas_extrait
echo Il faut d'abord extraire le zip: clic droit sur le fichier zip, Extraire tout, puis relancer depuis le dossier extrait.
pause
exit /b 1

:blender
if exist "blender\\blender.exe" exit /b 0
if exist "blender.zip" goto extraire
echo Telechargement de Blender {ver} (environ 400 Mo, une seule fois)...
curl.exe -L --fail --retry 3 -o blender_officiel.zip "{url}"
if errorlevel 1 goto echec_telechargement
echo Installation de Blender...
tar -xf blender_officiel.zip
if exist "blender-{ver}-windows-x64\\blender.exe" ren "blender-{ver}-windows-x64" blender
del blender_officiel.zip
if exist "blender\\blender.exe" exit /b 0
goto echec_installation
:extraire
echo Installation de Blender (1 a 3 minutes, une seule fois)...
mkdir blender 2>nul
tar -xf blender.zip -C blender
if not exist "blender\\blender.exe" powershell -NoProfile -Command "Expand-Archive -Force -LiteralPath 'blender.zip' -DestinationPath 'blender'"
if not exist "blender\\blender.exe" goto echec_installation
del blender.zip
exit /b 0
:echec_telechargement
echo ERREUR: telechargement de Blender impossible. Verifier la connexion internet, puis relancer.
exit /b 1
:echec_installation
echo ERREUR: installation de Blender impossible. Prevenir Ilyas (photo de cette fenetre).
exit /b 1

:python
set "PY="
for /d %%D in ("blender\\*") do if exist "%%~fD\\python\\bin\\python.exe" set "PY=%%~fD\\python\\bin\\python.exe"
if defined PY exit /b 0
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY exit /b 0
echo ERREUR: le Python de Blender est introuvable. Prevenir Ilyas.
exit /b 1
"""


def _lisezmoi_frere(s, transport_type):
    fin = {"github": "Les images partent toutes seules chez Ilyas au fur et à mesure (internet nécessaire). Rien à envoyer à la main.",
           "dossier": "Les images partent toutes seules chez Ilyas par le dossier partagé (Google Drive, OneDrive...), qui doit "
                      "être installé et synchronisé sur ce PC. Rien à envoyer à la main.",
           "manuel": "À la fin, la fenêtre ouvre le fichier à envoyer (dossier ENVOI) et le site SwissTransfer: glisser le fichier "
                     "dans la page, mettre l'adresse e-mail d'Ilyas, Envoyer. Ou le copier sur une clé USB."}[transport_type]
    return f"""BLATTEN 360 : rendu du film sur ton PC. Merci !

Ton PC et celui d'Ilyas rendent le film ensemble: Ilyas part du début, toi de la fin, et le partage se règle tout seul
selon la vitesse de chaque PC. Rien à régler, rien à installer.

1. Extraire ce zip (clic droit, Extraire tout) de préférence directement dans C:\\ (chemin court).
   Il faut environ 10 Go libres sur le disque.
2. Double-cliquer LANCER_RENDU.bat. La première fois, Blender s'installe tout seul (1 à 3 minutes).
   Si Windows affiche un avertissement (éditeur inconnu, SmartScreen): « Informations complémentaires », puis
   « Exécuter quand même ».
3. Laisser la fenêtre ouverte, même écran éteint: le PC ne se met pas en veille tant que le rendu tourne.
   Besoin du PC (jeu, autre chose de lourd) ? Fermer la fenêtre: rien n'est perdu. Relancer LANCER_RENDU.bat reprend
   là où ça s'était arrêté. Si ton PC reste arrêté plus de 2 h, celui d'Ilyas reprend tes images en cours.
4. {fin}

Avant de lancer (conseillé):
  - Pilote NVIDIA à jour (application NVIDIA ou GeForce Experience).
  - Mises à jour Windows suspendues pendant le rendu: Paramètres, Windows Update, Suspendre pendant 1 semaine
    (sinon Windows peut redémarrer le PC la nuit; le rendu reprendrait quand même à la relance).
  - Ne pas jouer pendant le rendu: la carte graphique est utilisée à fond.

ETAT.bat : où en sont les deux PC (images faites, fin estimée).
ENVOYER_IMAGES.bat : fabrique un seul fichier avec toutes tes images (en cas d'envoi à la main).
Un problème ? Une photo de la fenêtre à Ilyas.

Session {s['session']}.
"""


def cmd_paquet(B, D, cfg, paths, extra):
    """Prépare le rendu à deux PC, sur le PC d'Ilyas (mode d'emploi: docs/RENDU_A_DEUX.md).
        python blatten.py paquet [--transport github|dossier|manuel] [--dossier CHEMIN] [--sans-blender] [--sans-test] [--oui]
                                 [--paquet-images 10] [--intro-pas 2] [--pas 1] [--vitesse-frere 1.6] [--ntfy URL]
    Écrit render_dir/duo/<session>/: session.json, code/ (copie figée du code qui fait les images, utilisée par les deux PC),
    Blatten_frere_<session>.zip (le seul fichier à donner au frère: code, données, Blender, lanceurs) et A_LIRE.txt.
    Puis teste le paquet: une petite zone d'une image finale rendue avec SES données et SON code (manque-t-il un fichier ?)."""
    oui = "--oui" in extra
    sans_blender = "--sans-blender" in extra
    sans_test = "--sans-test" in extra
    extra = [x for x in extra if x not in ("--oui", "--sans-blender", "--sans-test")]
    tr_o, extra = B._option(extra, "--transport", 1)
    dos_o, extra = B._option(extra, "--dossier", 1)
    k_o, extra = B._option(extra, "--paquet-images", 1)
    ki_o, extra = B._option(extra, "--intro-pas", 1)
    kf_o, extra = B._option(extra, "--pas", 1)
    vf_o, extra = B._option(extra, "--vitesse-frere", 1)
    srv_o, extra = B._option(extra, "--ntfy", 1)
    n_o, extra = B._option(extra, "--images", 1)           # essais: film raccourci
    ni_o, extra = B._option(extra, "--intro-images", 1)    # essais
    if os.path.exists(os.path.join(B.ROOT, "duo_session.json")):
        sys.exit("Ce dossier est le paquet du frère: le paquet se prépare sur le PC d'Ilyas.")
    if not oui and not _rappel_feuille_de_route(B):
        print("Préparation annulée. Revenir quand tout est décidé.")
        return 1
    rd = _rd(B, cfg)
    base_duo = os.path.join(rd, "duo")
    anciennes = sorted(d for d in (os.listdir(base_duo) if os.path.isdir(base_duo) else [])
                       if os.path.exists(os.path.join(base_duo, d, "session.json")))
    if anciennes and not oui and sys.stdin and sys.stdin.isatty():
        r = input(f"\nUne session existe déjà ({anciennes[-1]}). Une nouvelle session rend son paquet inutilisable (le frère devra\n"
                  "recevoir le nouveau). Continuer ? (o/n) ").strip().lower()
        if r[:1] not in ("o", "y"):
            return 1
    tconf = _choisir_transport(B, cfg, tr_o[0] if tr_o else None, dos_o[0] if dos_o else None)
    sid = time.strftime("%m%d") + "-" + secrets.token_hex(3)
    base = os.path.join(base_duo, sid)
    os.makedirs(os.path.join(base, "apports"), exist_ok=True)
    JOURNAL["f"] = os.path.join(base, "preparation.log")
    if tconf["type"] == "github":
        tconf["tag"] = "duo-" + sid
        for essai in range(3):
            ok, msg = D.TransportGithub(tconf["depot"], tconf["jeton"], tconf["tag"]).verifier()
            log(("OK " if ok else "!! ") + msg)
            if ok:
                break
            if essai == 2 or not (sys.stdin and sys.stdin.isatty()):
                sys.exit("Réglage GitHub à corriger (voir ci-dessus), ou relancer avec --transport manuel.")
            print(GUIDE_GITHUB)
            d_ = input(f"Dépôt [{tconf['depot']}] ? ").strip().strip("/")
            tconf["depot"] = re.sub(r"^https?://github\.com/", "", d_) if d_ else tconf["depot"]
            tconf["jeton"] = getpass.getpass("Jeton (collé avec clic droit; il ne s'affiche pas) ? ").strip() or tconf["jeton"]
            loc = dict(cfg.get("duo") or {})
            loc.update(transport="github", depot=tconf["depot"], jeton=tconf["jeton"])
            B.save_local("duo", loc)
    # 1. copie figée du code
    code = os.path.join(base, "code")
    fichiers = _fichiers_suivis(B)
    for rel in fichiers:
        src = os.path.join(B.ROOT, rel)
        if os.path.isfile(src):
            dst = os.path.join(code, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    ec = D.empreinte_code(code)
    log(f"Code figé: {len(fichiers)} fichiers, empreinte {ec}")
    # 2. plan et réglages
    cfg_code = B._load_json(os.path.join(code, "config.json"))
    sc = cfg_code.get("scene") or {}
    fps = int(sc.get("fps", 30))
    n = int(n_o[0]) if n_o else int((cfg_code.get("film") or {}).get("images", 1830))
    n_intro = int(ni_o[0]) if ni_o else int(round(float(sc.get("intro", 0.0)) * fps))
    plan = dict(n=n, n_intro=min(n_intro, n), k_intro=int(ki_o[0]) if ki_o else 2, k_film=int(kf_o[0]) if kf_o else 1, fps=fps)
    pl = D.plan(plan["n"], plan["n_intro"], plan["k_intro"], plan["k_film"])
    rels = _donnees_paquet(paths)
    taille_donnees = sum(os.path.getsize(os.path.join(paths.cache, r)) for r in rels)
    exe = B.find_blender(cfg, ask=False)
    ver = _version_blender(exe) or "5.2.2"
    s = dict(v=1, session=sid, sujet="blatten-" + secrets.token_hex(8), serveur=(srv_o[0] if srv_o else D.SERVEUR),
             cree=time.strftime("%Y-%m-%d %H:%M"), plan=plan, paquet=int(k_o[0]) if k_o else K_DEFAUT,
             vitesse_frere=float(vf_o[0]) if vf_o else VITESSE_FRERE, transport=tconf, empreinte_code=ec, blender=ver)
    film = os.path.join(rd, "final", time.strftime("%Y%m%d_%H%M") + "_duo_" + sid)
    s_ilyas = dict(s, dossier_film=film, depot=B.ROOT, donnees=D.etat_donnees(paths.cache, rels), donnees_base=paths.cache)
    _ecrire_json(os.path.join(base, "session.json"), s_ilyas)
    s_frere = dict(s)
    if tconf["type"] == "dossier":
        s_frere["transport"] = dict(tconf, chemin_ilyas=None)
    # 3. paquet du frère: un seul zip
    url = f"https://download.blender.org/release/Blender{'.'.join(ver.split('.')[:2])}/blender-{ver}-windows-x64.zip"
    P = "Blatten_frere/"
    entrees = [(os.path.join(code, rel), P + "code/" + rel, rel.lower().endswith(COMPRESSER))
               for rel in fichiers if os.path.isfile(os.path.join(code, rel))]
    entrees += [(None, P + "code/config.local.json", json.dumps(
        {"_doc": "PC du frère: chemins relatifs au dossier code", "data_root": "..", "cache_dir": "../cache",
         "render_dir": "../images", "blender": "../blender/blender.exe"}, indent=2).encode("utf-8")),
                (None, P + "code/duo_session.json", json.dumps(s_frere, indent=1, ensure_ascii=False).encode("utf-8")),
                (None, P + "LANCER_RENDU.bat", _bat("duo", "rendu (PC du frere)", ver, url).replace("\n", "\r\n").encode("ascii")),
                (None, P + "ENVOYER_IMAGES.bat", _bat("duo-envoyer", "envoi des images", ver, url).replace("\n", "\r\n").encode("ascii")),
                (None, P + "ETAT.bat", _bat("duo-etat", "etat du rendu", ver, url).replace("\n", "\r\n").encode("ascii")),
                (None, P + "LISEZ-MOI.txt", ("\ufeff" + _lisezmoi_frere(s, tconf["type"])).replace("\n", "\r\n").encode("utf-8"))]
    entrees += [(os.path.join(paths.cache, r), P + "cache/" + r, r.lower().endswith(COMPRESSER)) for r in rels]
    if not sans_blender:
        bz = os.path.join(base_duo, f"blender_{ver}.zip")
        try:
            _zip_blender(B, cfg, bz)
            entrees.append((bz, P + "blender.zip", False))
        except Exception as e:
            log(f"!! copie de Blender impossible ({e}): le PC du frère le téléchargera ({url})")
    paquet = os.path.join(base, f"Blatten_frere_{sid}.zip")
    log(f"Paquet du frère: {len(entrees)} fichiers, données {taille_donnees / 1e9:.2f} Go -> {paquet}")
    _ecrire_zip(paquet, entrees, "paquet")
    taille = os.path.getsize(paquet) / 1e9
    log(f"Paquet prêt: {taille:.2f} Go")
    # 4. test du paquet: ses données et son code suffisent-ils pour une image finale ?
    test_ok = None
    if not sans_test:
        test_ok = _tester_paquet(B, D, cfg, s_ilyas, code, rels, paths, min(IMAGE_TEST, n))
    # 5. canal et consignes
    canal = _canal(D, s, "ilyas")
    canal_ok = canal.prevenir("Blatten 360: session " + sid, f"Rendu à deux préparé. Notifications de ce rendu ici.", 3, ["clapper"])
    lien = f"{s['serveur'].rstrip('/')}/{s['sujet']}"
    envoi = {"github": f"automatique par GitHub ({tconf.get('depot')})",
             "dossier": f"automatique par le dossier partagé {tconf.get('chemin_ilyas')}",
             "manuel": "à la main à la fin (SwissTransfer ou clé USB): ton PC le trouvera dans Téléchargements ou dans "
                       + os.path.join(base, "apports")}[tconf["type"]]
    a_lire = f"""RENDU À DEUX PC, session {sid} (préparée le {s['cree']})

À FAIRE
1. Donner au frère le fichier {os.path.basename(paquet)} ({taille:.1f} Go): clé USB, ou swisstransfer.com (gratuit, jusqu'à 50 Go).
   Il l'extrait dans C:\\ et double-clique LANCER_RENDU.bat. Tout est expliqué dans LISEZ-MOI.txt du paquet.
2. Sur ce PC: double-cliquer Lancer_rendu_duo.bat (dans C:\\Dev\\blatten-vr). Pas besoin d'attendre le frère.
3. Suivre le rendu sur le téléphone: application ntfy (Android, iPhone), bouton +, sujet {s['sujet']}
   (serveur ntfy.sh), ou la page {lien} dans un navigateur.
4. Images du frère: {envoi}.
5. À la fin, ce PC fait le montage tout seul: {os.path.join(film, "film_360_360.mp4")}

Une coupure, un PC éteint ? Relancer le même fichier: rien n'est perdu. Si un PC se tait plus de 2 h, l'autre reprend ses
images en cours. Où on en est: Lancer_etat_duo.bat.

Film: {n} images, {len(pl)} à calculer (intro: une image sur {plan['k_intro']}), {s['paquet']} images par paquet.
Images: {film}
Ne pas modifier les données (python blatten.py prep-...) pendant le rendu: le PC d'Ilyas s'arrêterait (images différentes du frère).
"""
    with open(os.path.join(base, "A_LIRE.txt"), "w", encoding="utf-8-sig") as f:
        f.write(a_lire)
    print("\n" + "=" * 78 + "\n" + a_lire + "=" * 78)
    if test_ok is False:
        print("\n!! LE TEST DU PAQUET A ÉCHOUÉ: ne pas l'envoyer avant correction (voir le message de Blender plus haut).")
    if not canal_ok:
        print(f"\n!! Canal de messages injoignable depuis ce PC ({canal.erreur}). Le rendu marchera quand même, mais sans partage "
              "en direct (chaque PC fera sa moitié estimée). Vérifier internet.")
    _ouvrir(base)
    return 0 if test_ok is not False else 1


def _tester_paquet(B, D, cfg, s, code, rels, paths, image):
    """Rend une petite zone de l'image finale `image` avec le code figé et UNIQUEMENT les données du paquet (liens vers les
    fichiers, sans copie si possible): un fichier oublié dans le paquet ferait échouer le frère, autant le voir ici."""
    base = os.path.dirname(code)
    dtest, out = os.path.join(base, "_test_donnees"), os.path.join(base, "_test_image")
    shutil.rmtree(dtest, ignore_errors=True)
    for r in rels:
        src, dst = os.path.join(paths.cache, r), os.path.join(dtest, r)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    os.makedirs(out, exist_ok=True)

    class _P:
        cache = dtest
    cfg_code = B._load_json(os.path.join(code, "config.json"))
    c = dict(cfg)
    c["scene"] = cfg_code.get("scene") or {}
    a = B.scene_args(c, _P(), with_vdb=False) + ["--preset", "final", "--mono", "--render-frame", str(image),
                                                  "--border", "0.47", "0.53", "0.44", "0.56", "--out", out, "--camera-confirmed"]
    log(f"Test du paquet: image {image}, petite zone, avec les seules données du paquet (quelques minutes)...")
    B._attendre_ram(7.0)
    B.run_blender(cfg, os.path.join(code, "src", "scene", "blatten_blender.py"), a, fond=True, extra_env={"BLATTEN_ROOT": code})
    ok = os.path.exists(os.path.join(out, f"frame_{image:04d}{EXT}"))
    shutil.rmtree(dtest, ignore_errors=True)
    log("Test du paquet: " + ("OK, le paquet est complet." if ok else "ÉCHEC (voir le message de Blender ci-dessus)."))
    return ok


# ----------------------------------------------------------------------------------
# duo: la boucle de rendu (les deux PC)
# ----------------------------------------------------------------------------------
def _rendre_paquet(B, cfg, paths, racine, cfg_scene, out, images, pas):
    c = dict(cfg)
    c["scene"] = cfg_scene
    a = B.scene_args(c, paths, with_vdb=False) + ["--preset", "final", "--mono", "--render-anim",
                                                   "--frames", str(images[0]), str(images[-1]), "--origine", "1"]
    if pas > 1:
        a += ["--frame-step", str(pas)]
    a += ["--out", out, "--camera-confirmed"]
    return B.run_blender(cfg, os.path.join(racine, "src", "scene", "blatten_blender.py"), a, fond=True,
                         extra_env={"BLATTEN_ROOT": racine})


def _importer(D, tr, s, out, ordre_set, etat_imp):
    """PC d'Ilyas: importe les lots du frère qui ne l'ont pas encore été (transport automatique, Téléchargements, apports/)."""
    sources = []
    if tr.auto:
        try:
            sources += [(nom, t, f) for nom, t, f in tr.lots() if s["session"] in nom]
            etat_imp["erreur_transport"] = None
        except Exception as e:
            etat_imp["erreur_transport"] = f"{type(e).__name__}: {e}"
    for d in (os.path.join(s["_base"], "apports"), _telechargements()):
        try:
            for f in sorted(os.listdir(d)):
                p = os.path.join(d, f)
                if f.lower().endswith(".zip") and s["session"] in f:
                    sources.append((f, os.path.getsize(p), (lambda _d, p=p: p)))
                elif os.path.isdir(p) and d.endswith("apports"):
                    sources.append((f + "/", -1, (lambda _d, p=p: p)))
        except OSError:
            pass
    vus = etat_imp.setdefault("lots", {})
    ajout = []
    for nom, taille, recup in sources:
        cle = f"{nom}|{taille}"
        if cle in vus and taille != -1:
            continue
        try:
            chemin = recup(s["_lots"])
            if os.path.isdir(chemin):        # dossier d'images copié à la main (clé USB) dans apports/
                a = []
                for f in sorted(os.listdir(chemin)):
                    m = re.fullmatch(r"frame_(\d{4,})" + re.escape(EXT), f)
                    if m and int(m.group(1)) in ordre_set:
                        dst = os.path.join(out, f"frame_{int(m.group(1)):04d}{EXT}")
                        if not os.path.exists(dst) and os.path.getsize(os.path.join(chemin, f)) > 0:
                            shutil.copyfile(os.path.join(chemin, f), dst + ".part")
                            os.replace(dst + ".part", dst)
                            a.append(int(m.group(1)))
            else:
                a = D.importer_zip(chemin, out, s["session"], EXT)
                if tr.type == "github" and os.path.dirname(os.path.abspath(chemin)) == os.path.abspath(s["_lots"]):
                    try:
                        os.remove(chemin)          # copie téléchargée: les images sont maintenant dans le dossier du film
                    except OSError:
                        pass
            vus[cle] = time.strftime("%Y-%m-%d %H:%M")
            if a:
                ajout += a
                log(f"import: {len(a)} images du frère ({nom})")
        except zipfile.BadZipFile:
            log(f"!! lot abîmé ou incomplet, réessai plus tard: {nom}")
            try:
                if tr.type == "github":
                    os.remove(os.path.join(s["_lots"], nom))
            except OSError:
                pass
        except Exception as e:
            log(f"!! import impossible pour l'instant ({nom}): {type(e).__name__}: {e}")
    return ajout


def _envoyer_lots(D, tr, s, out, lots_etat, nouvelles, E):
    """PC du frère: un lot (zip) par paquet rendu, déposé par le transport automatique; les lots en échec sont retentés."""
    if not tr.auto:
        return
    os.makedirs(s["_lots"], exist_ok=True)
    couvertes = set()
    for info in lots_etat.values():
        couvertes |= set(D.deplages(info["images"]))
    orphelines = sorted(_images(out) - couvertes - set(nouvelles))
    groupes = [list(nouvelles)] if nouvelles else []
    groupes += [orphelines[i:i + 50] for i in range(0, len(orphelines), 50)]
    for g in groupes:
        nom = D.nom_lot(s["session"], "frere", g)
        try:
            D.creer_lot(out, g, EXT, os.path.join(s["_lots"], nom), s["session"], "frere")
            lots_etat[nom] = {"images": D.plages(g), "envoye": False}
        except Exception as e:
            log(f"!! lot non créé ({e})")
    for nom, info in sorted(lots_etat.items()):
        if info.get("envoye"):
            continue
        p = os.path.join(s["_lots"], nom)
        if not os.path.exists(p):
            imgs = [f for f in D.deplages(info["images"]) if os.path.exists(os.path.join(out, f"frame_{f:04d}{EXT}"))]
            if not imgs:
                info["envoye"] = True
                continue
            D.creer_lot(out, imgs, EXT, p, s["session"], "frere")
        try:
            tr.deposer(p)
            info["envoye"] = True
            E["envoye"] |= set(D.deplages(info["images"]))
            os.remove(p)
            log(f"envoyé: {nom}")
        except Exception as e:
            info["erreur"] = f"{type(e).__name__}: {e}"
            log(f"!! envoi de {nom} impossible pour l'instant ({info['erreur']}), réessai au prochain paquet")
    _ecrire_json(os.path.join(s["_lots"], "lots.json"), lots_etat)


def _zip_final_frere(D, s, out):
    """Un seul zip de toutes les images du frère, dans ENVOI/ à côté des lanceurs."""
    imgs = sorted(_images(out))
    if not imgs:
        return None
    d = os.path.join(s["_base"], "ENVOI")
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        if f.endswith(".zip") and s["session"] in f:
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    dest = os.path.join(d, f"Blatten_{s['session']}_frere_{len(imgs)}images.zip")
    log(f"Fichier à envoyer: {len(imgs)} images...")
    D.creer_lot(out, imgs, EXT, dest, s["session"], "frere")
    return dest


def cmd_duo(B, D, cfg, paths, extra):
    """Rend la part de CE PC du film 360 (PC d'Ilyas ou du frère, reconnu tout seul), en partageant avec l'autre PC.
        python blatten.py duo [--session ID] [--jusqu-a 07:00] [--tout-rendre] [--sans-montage]
    --jusqu-a HH:MM  s'arrête proprement avant cette heure (l'autre PC peut alors prendre la suite)
    --tout-rendre    (PC d'Ilyas) ne compte plus sur les images du frère: rend tout ce qui manque ici
    Relancer la même commande reprend là où on en était."""
    s, extra = charger_session(B, cfg, extra)
    role = s["_role"]
    maitre = role == "ilyas"
    autre_role = "frere" if maitre else "ilyas"
    sens = 1 if maitre else -1
    tout_rendre = "--tout-rendre" in extra
    sans_montage = "--sans-montage" in extra or os.environ.get("BLATTEN_DUO_SANS_MONTAGE") == "1"
    extra = [x for x in extra if x not in ("--tout-rendre", "--sans-montage")]
    jq, extra = B._option(extra, "--jusqu-a", 1)
    heure_fin = None
    if jq:
        m = re.match(r"^(\d{1,2})[:h](\d{2})$", jq[0])
        if not m:
            sys.exit("--jusqu-a attend une heure du type 07:00")
        lt = time.localtime()
        c = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(m.group(1)), int(m.group(2)), 0, 0, 0, -1))
        heure_fin = c if c > time.time() else c + 86400
    racine = s["_racine"]
    cfg_scene = B._load_json(os.path.join(racine, "config.json")).get("scene") or {}
    pl, ordre, pas = _plan(D, s)
    ordre_set, idx = set(ordre), {f: i for i, f in enumerate(ordre)}
    n, fps, K = s["plan"]["n"], s["plan"]["fps"], int(s.get("paquet") or K_DEFAUT)
    out = s["_out"]
    os.makedirs(out, exist_ok=True)
    os.makedirs(s["_lots"], exist_ok=True)
    JOURNAL["f"] = os.path.join(out, f"duo_{role}.log")
    nom = D.NOMS[role]
    ratio = float(s.get("vitesse_frere") or VITESSE_FRERE)
    ratio = ratio if maitre else 1.0 / ratio          # vitesse de l'autre / la mienne, avant toute mesure
    coupure = int(round(len(ordre) / (1.0 + float(s.get("vitesse_frere") or VITESSE_FRERE))))   # part d'Ilyas estimée
    log("=" * 70)
    log(f"Rendu à deux, session {s['session']}: {nom}, sens {'début -> fin' if maitre else 'fin -> début'}")
    log(f"Film: {n} images, {len(ordre)} à calculer. Images: {out}")
    # vérifications de départ
    ec = D.empreinte_code(racine)
    if ec != s.get("empreinte_code"):
        sys.exit(f"Le code figé de la session a changé ({racine}: empreinte {ec} au lieu de {s.get('empreinte_code')}). "
                 "Les images ne seraient plus identiques à celles de l'autre PC: refaire un paquet.")
    def donnees_changees():
        if not (maitre and s.get("donnees")):
            return []
        actuel = D.etat_donnees(s.get("donnees_base") or paths.cache, [r for r, _t, _m in s["donnees"]])
        return [a[0] for a, b in zip(actuel, s["donnees"]) if a[1:] != b[1:]]
    diff = donnees_changees()
    if diff:
        sys.exit(f"Les données ont changé depuis la préparation du paquet ({len(diff)} fichiers, ex. {diff[:3]}): les images "
                 "d'ici ne seraient plus identiques à celles du frère. Remettre les données, ou refaire un paquet.")
    canal = _canal(D, s, role, cache=os.path.join(out, "_duo_derniers_etats.json"))
    tr = _transport(D, s, role)
    ok_tr, msg_tr = tr.verifier()
    log(("Envoi des images: " if not maitre else "Arrivée des images du frère: ") + msg_tr + ("" if ok_tr else " (À CORRIGER)"))
    gpu, err = _verifier_gpu(B, cfg)
    if not gpu:
        log("!! " + err)
        canal.prevenir(f"{nom}: pas de carte graphique", "Blender ne voit pas la carte NVIDIA. Mettre à jour le pilote, redémarrer, "
                       "relancer.", 4, ["warning"])
        sys.exit("Rendu impossible sans carte graphique (sur le processeur, ce serait bien plus lent). Mettre à jour le pilote "
                 "NVIDIA (application NVIDIA ou GeForce Experience), redémarrer le PC, relancer.")
    log(f"Carte graphique: {gpu}")
    libre = shutil.disk_usage(out).free / 1e9
    if libre < 1.5:
        sys.exit(f"Disque presque plein ({libre:.1f} Go libres à côté de {out}): libérer au moins 4 Go et relancer.")
    if libre < 4:
        log(f"!! seulement {libre:.1f} Go libres: prévoir au moins 4 Go")
    _empecher_veille()
    E = dict(etat="demarrage", cours=[], tc=None, tcs=None, vit=None, envoye=set())
    lots_etat = _lire_json(os.path.join(s["_lots"], "lots.json"), {}) if not maitre else {}
    for info in lots_etat.values():
        if info.get("envoye"):
            E["envoye"] |= set(D.deplages(info["images"]))
    chrono_f = os.path.join(out, f"chrono_duo_{role}.json")
    chrono = _lire_json(chrono_f, [])
    if chrono:
        v = [c["images"] / max(c["secondes"], 1) * 3600 for c in chrono[-3:]]
        E["vit"] = sum(v) / len(v)
    imp_f = os.path.join(out, "_duo_imports.json")
    etat_imp = _lire_json(imp_f, {"lots": {}, "importes": [], "rejetes": []}) if maitre else {}
    importes = set(etat_imp.get("importes", []))
    rejetes = set(etat_imp.get("rejetes", []))

    def message(etat=None, msg=None):
        f = _images(out, ordre_set)
        m = dict(etat=etat or E["etat"], fait=D.plages(f), cours=D.plages(E["cours"]), tc=E["tc"], tcs=E["tcs"],
                 vit=round(E["vit"], 3) if E["vit"] else None, gpu=gpu, ec=ec[:8], n=len(f))
        if not maitre:
            m["envoye"] = D.plages(E["envoye"])
        if msg:
            m["msg"] = msg
        return m

    def publier(etat=None, msg=None):
        if etat:
            E["etat"] = etat
        E["pub"] = time.time()
        return canal.publier(message(etat, msg))

    alertes = {}

    def alerter(cle, titre, texte, prio=4, tous_les=6 * 3600, tags=("warning",)):
        if time.time() - alertes.get(cle, 0) >= tous_les:
            alertes[cle] = time.time()
            canal.prevenir(titre, texte, prio, list(tags))

    def a_l_arret():
        E["cours"] = []
        publier("arret", "fenêtre fermée")
    _sur_fermeture(a_l_arret)
    faits = _images(out, ordre_set)
    if not maitre and tr.auto and faits:
        _envoyer_lots(D, tr, s, out, lots_etat, [], E)     # images d'une session précédente pas encore parties
    publier("demarrage")
    canal.prevenir(f"{nom}: démarrage", f"Carte: {gpu}. {len(faits)} images déjà faites ici sur {len(ordre)} à calculer.", 3, ["rocket"])
    if canal.erreur:
        log(f"!! canal de messages injoignable pour l'instant ({canal.erreur}): rendu quand même, nouvel essai à chaque paquet")
    echecs = 0
    etait_vivant = None
    try:
        while True:
            maintenant = canal.maintenant()
            if maitre:
                nouv = _importer(D, tr, s, out, ordre_set, etat_imp)
                importes |= set(nouv)
            susp = B._images_suspectes(out, EXT)
            if susp:
                B._nettoyer(out, EXT)
                if maitre:
                    rejetes |= set(susp) & importes
                    importes -= set(susp)
                    if set(susp) & rejetes:
                        log(f"!! images du frère ratées (noires): {sorted(set(susp) & rejetes)[:10]}, refaites ici")
            if maitre:
                etat_imp.update(importes=sorted(importes), rejetes=sorted(rejetes))
                _ecrire_json(imp_f, etat_imp)
            faits = _images(out, ordre_set)
            derniers = canal.lire()
            autre = D.decoder(derniers.get(autre_role))
            if autre and autre.get("ec") and autre["ec"] != ec[:8]:
                alerter("code", "Codes différents sur les deux PC", f"{D.NOMS[autre_role]} n'a pas le même code (session "
                        f"{s['session']}). Refaire un paquet.", 5)
                if not maitre:
                    sys.exit("Le PC d'Ilyas rend avec un autre code: arrêt (images incompatibles). Prévenir Ilyas.")
                autre = None
            if autre and autre.get("etat") == "complet" and not maitre:
                log("Le film est complet chez Ilyas. Merci, tout est fini !")
                publier("fini")
                return 0
            vivant = D.est_vivant(autre, maintenant)
            if etait_vivant and not vivant and autre and autre.get("etat") not in ("fini", "arret", "complet"):
                alerter("silence", f"{D.NOMS[autre_role]} silencieux", f"Pas de nouvelles depuis "
                        f"{D.duree_fr((maintenant - float(autre.get('maj') or 0)) / 3600)}: ses images en cours sont reprises par le "
                        f"{nom}.", 4)
            etait_vivant = vivant
            vue = None if (tout_rendre or not autre) else dict(autre)
            if vue and maitre:
                vue["fait"] = vue["fait"] - rejetes
                if tr.auto and maintenant - float(autre.get("maj") or 0) > D.SILENCE_MAX:
                    vue["fait"] = vue["fait"] & (importes | vue["envoye"])     # restées sur un PC arrêté, jamais envoyées
            vm = E["vit"]
            va = (vue or {}).get("vit") or None
            if vm is None and va:
                vm = va / ratio
            if va is None and vm:
                va = vm * ratio
            limite = None
            if not maitre and autre is None:                  # aucune nouvelle d'Ilyas: on s'en tient à la part estimée du frère
                limite = (lambda f: idx[f] >= coupure)
            viv = vivant and vue is not None
            images, raison = D.choisir(ordre, pas, faits, vue, sens, K, vm, va, maintenant, viv, limite)
            if raison == "rien" and limite and D.choisir(ordre, pas, faits, vue, sens, K, vm, va, maintenant, viv)[0]:
                raison = "attendre"
            if images and heure_fin:
                duree_h = (D.SURCOUT_H + len(images) / vm) if vm else None
                if duree_h and time.time() + 1.1 * duree_h * 3600 > heure_fin:
                    log(f"Heure limite: le prochain paquet (~{D.duree_fr(duree_h)}) ne finirait pas avant "
                        f"{time.strftime('%H:%M', time.localtime(heure_fin))}. Arrêt propre; relancer pour reprendre.")
                    E["cours"] = []
                    publier("arret", "heure limite")
                    canal.prevenir(f"{nom}: pause", "Arrêt à l'heure prévue. L'autre PC peut continuer seul.", 2)
                    return 0
            if images and maitre and donnees_changees():
                E["cours"] = []
                publier("arret", "données modifiées")
                canal.prevenir("PC d'Ilyas: arrêt", "Les données du rendu ont changé pendant le rendu (commande prep-... ?). Le frère "
                               "continue seul. Remettre les données puis relancer.", 4, ["warning"])
                sys.exit("Les données ont changé pendant le rendu: arrêt (images différentes de celles du frère). Remettre les données "
                         "(ou refaire un paquet), puis relancer.")
            if images:
                p = pas[images[0]]
                E.update(cours=images, tc=time.time(), tcs=None)
                t_srv = publier("rend")
                E["tcs"] = t_srv
                if t_srv and vivant and D.CONFLIT > 0:
                    time.sleep(D.CONFLIT)
                    autre2 = D.decoder(canal.lire().get(autre_role))
                    garde = D.retirer_conflit(images, autre2, sens, t_srv, role)
                    if garde != images:
                        log(f"Images {D.plages(set(images) - set(garde))} prises au même moment par l'autre PC: je les lui laisse.")
                        if not garde:
                            E["cours"] = []
                            publier("attente")
                            continue
                        images = garde
                        E["cours"] = images
                        publier("rend")
                log(f">>> paquet {images[0]} à {images[-1]} ({len(images)} image" + ("s" if len(images) > 1 else "")
                    + (f", une sur {p}" if p > 1 else "") + ")")
                B._attendre_ram(7.0)
                pouls = D.Pouls(lambda: publier() if time.time() - E.get("pub", 0) > D.POULS / 2 else None)
                pouls.start()
                t0 = time.time()
                try:
                    _rendre_paquet(B, cfg, paths, racine, cfg_scene, out, images, p)
                finally:
                    pouls.stop()
                dt = time.time() - t0
                susp = B._images_suspectes(out, EXT)
                if susp:
                    B._nettoyer(out, EXT)
                faits2 = _images(out, ordre_set)
                nouvelles = [f for f in images if f in faits2]
                E.update(cours=[], tc=None, tcs=None)
                if nouvelles:
                    v = len(nouvelles) / max(dt / 3600.0, 1e-6)
                    E["vit"] = v if E["vit"] is None else 0.3 * E["vit"] + 0.7 * v
                    echecs = 0
                    chrono.append(dict(date=time.strftime("%Y-%m-%d %H:%M"), de=images[0], a=images[-1], images=len(nouvelles),
                                       secondes=round(dt)))
                    try:
                        _ecrire_json(chrono_f, chrono)
                    except OSError:
                        pass
                    if not maitre:
                        _envoyer_lots(D, tr, s, out, lots_etat, nouvelles, E)
                else:
                    echecs += 1
                    log(f"!! aucune image dans ce paquet (échec {echecs}). Journal de Blender: {B.LOG_COURANT.get('chemin', '')}")
                    if echecs >= 2:
                        alerter("echec", f"{nom}: Blender échoue", f"{echecs} paquets de suite sans image (images {images[0]} à "
                                f"{images[-1]}). Regarder la fenêtre.", 4, 3 * 3600)
                    if echecs >= 5:
                        E["cours"] = []
                        publier("arret", "Blender échoue")
                        sys.exit("Blender échoue sans arrêt: arrêt pour laisser l'autre PC continuer. Lire le message de Blender plus "
                                 "haut, corriger, relancer.")
                    publier("rend")
                    time.sleep(min(600, 60 * echecs))
                    continue
                publier("rend")
                autre = D.decoder(canal.derniers.get(autre_role))
                tous = (faits2 | ((autre or {}).get("fait") or set())) & ordre_set
                reste = len(ordre) - len(tous)
                eta = D.estimer_fin(reste, E["vit"], va, D.est_vivant(autre, canal.maintenant()))
                fin_txt = D.heure_fr(time.time() + eta * 3600) if eta else "?"
                log(f"==== {len(tous)}/{len(ordre)} images calculées ({100 * len(tous) / len(ordre):.0f} %): ce PC "
                    f"{E['vit']:.1f} images/h, {D.NOMS[autre_role]} {(f'{va:.1f}' if va else '?')} images/h. Fin estimée: {fin_txt} ====")
                if time.time() - E.get("notif", 0) >= float(os.environ.get("BLATTEN_DUO_NOTIF", 3 * 3600)):
                    E["notif"] = time.time()
                    canal.prevenir(f"{nom}: {len(tous)}/{len(ordre)} images ({100 * len(tous) / len(ordre):.0f} %)",
                                   f"Dernier paquet: images {images[0]} à {images[-1]} en {D.duree_fr(dt / 3600)} "
                                   f"({E['vit']:.1f} images/h). Fin estimée: {fin_txt}.", 2)
                if (maitre or tr.auto) and shutil.disk_usage(out).free < 1.5e9:
                    alerter("disque", f"{nom}: disque presque plein", "Moins de 1,5 Go libres: libérer de la place.", 4)
                continue
            # pas de paquet pour ce PC
            if raison == "attendre":
                if E["etat"] != "attente" or time.time() - E.get("pub", 0) > D.POULS:
                    publier("attente")
                    log(f"L'autre PC finira plus vite les {len([f for f in ordre if f not in faits])} images restantes: j'attends.")
                time.sleep(min(D.ATTENTE, 120))
                continue
            if maitre:
                manquantes = [f for f in ordre if f not in faits]
                if not manquantes:
                    return _finaliser(B, D, cfg, s, out, pl, n, fps, canal, publier, sans_montage)
                if E["etat"] != "attente":
                    publier("attente")
                    txt = (f"Ma part est finie. J'attends {len(manquantes)} images du frère "
                           + ("(arrivée automatique)." if tr.auto else "(fichier à mettre dans Téléchargements)."))
                    log(txt)
                    canal.prevenir("PC d'Ilyas: en attente du frère", txt, 3)
                elif time.time() - E.get("pub", 0) > D.POULS:
                    publier("attente")
                if etat_imp.get("erreur_transport"):
                    alerter("transport", "Arrivée des images bloquée", etat_imp["erreur_transport"], 4, 3 * 3600)
                if not tr.auto and autre and autre.get("etat") == "fini":
                    alerter("fichier", "Fichier du frère attendu", f"Le frère a fini: son fichier Blatten_{s['session']}_frere_... "
                            "est à mettre dans Téléchargements (ou duo/" + s["session"] + "/apports).", 4, 6 * 3600)
                time.sleep(D.ATTENTE)
                continue
            # PC du frère: plus rien à prendre
            if tr.auto and (E["etat"] != "fini" or not all(i.get("envoye") for i in lots_etat.values())):
                _envoyer_lots(D, tr, s, out, lots_etat, [], E)
            if E["etat"] != "fini":
                faits = _images(out, ordre_set)
                if tr.auto:
                    reste = [n_ for n_, i in lots_etat.items() if not i.get("envoye")]
                    txt = (f"Part du frère finie: {len(faits)} images." + (f" {len(reste)} lot(s) encore à envoyer, nouvel essai "
                           "toutes les 6 min." if reste else " Tout est envoyé."))
                    if reste:
                        z = _zip_final_frere(D, s, out)
                        log(f"En secours, fichier complet prêt à envoyer à la main: {z}")
                else:
                    z = _zip_final_frere(D, s, out)
                    txt = (f"Part du frère finie: {len(faits)} images. Fichier à envoyer à Ilyas: {os.path.basename(z) if z else '?'} "
                           f"({(os.path.getsize(z) / 1e9 if z else 0):.1f} Go).")
                    if z:
                        print("\n" + "=" * 70 + "\nC'EST FINI POUR TON PC, MERCI !\nDernière étape: envoyer le fichier "
                              f"{os.path.basename(z)} à Ilyas.\nLe dossier ENVOI et le site SwissTransfer vont s'ouvrir: glisser le "
                              "fichier dans la page, mettre l'adresse e-mail d'Ilyas, Envoyer.\n(Ou le copier sur une clé USB.)\n" + "=" * 70)
                        _ouvrir(z, selection=True)
                        _ouvrir(SWISSTRANSFER)
                log(txt)
                publier("fini")
                canal.prevenir("PC du frère: part finie", txt, 4, ["checkered_flag"])
                log("Fenêtre à laisser ouverte si possible: si le PC d'Ilyas s'arrête, ce PC reprendra ses images. "
                    "Sinon on peut la fermer, rien n'est perdu.")
            elif time.time() - E.get("pub", 0) > D.POULS:
                publier("fini")
            time.sleep(2 * D.ATTENTE)
    except KeyboardInterrupt:
        E["cours"] = []
        publier("arret", "interrompu")
        raise


def _finaliser(B, D, cfg, s, out, pl, n, fps, canal, publier, sans_montage):
    """PC d'Ilyas, toutes les images calculées: copies de l'intro, contrôle, montage (outro, son, 360)."""
    publier("montage")
    for src, dst in D.copies(pl, n):
        a, b = os.path.join(out, f"frame_{src:04d}{EXT}"), os.path.join(out, f"frame_{dst:04d}{EXT}")
        if os.path.exists(a) and (not os.path.exists(b) or os.path.getsize(b) == 0):
            shutil.copyfile(a, b)
    manque = [i for i in range(1, n + 1) if not os.path.exists(os.path.join(out, f"frame_{i:04d}{EXT}"))]
    if manque:
        log(f"!! {len(manque)} images manquent encore: {manque[:20]}")
        canal.prevenir("Images manquantes", f"{len(manque)} images manquent ({manque[:10]}). Relancer Lancer_rendu_duo.bat.", 4)
        publier("attente")
        return 1
    log(f"Toutes les images sont là ({n}).")
    canal.prevenir("Toutes les images sont réunies", f"{n} images. Montage en cours (outro, son, 360).", 3, ["film_frames"])
    if sans_montage:
        publier("complet")
        return 0
    rc = B._finir_film(cfg, out, "360", fps)
    film = os.path.join(out, "film_360_360.mp4")
    if rc == 0:
        B._marquer_termine(out)
        log(f"FILM 360 PRÊT: {film}")
        canal.prevenir("FILM 360 PRÊT", film, 4, ["tada"])
        publier("complet", "film prêt")
        _ouvrir(out)
    else:
        log("!! montage en échec: les images sont faites. Relancer: python blatten.py finir --format 360 --dir " + out)
        canal.prevenir("Montage en échec", "Les images sont toutes là. Relancer le montage (Lancer_finir...).", 4, ["warning"])
        publier("complet", "images complètes, montage à relancer")
    return rc


# ----------------------------------------------------------------------------------
# duo-etat, duo-envoyer, duo-importer
# ----------------------------------------------------------------------------------
def cmd_duo_etat(B, D, cfg, paths, extra):
    """Où en sont les deux PC (images faites, en cours, vitesse, fin estimée).   python blatten.py duo-etat [--session ID]"""
    s, extra = charger_session(B, cfg, extra)
    pl, ordre, pas = _plan(D, s)
    ordre_set = set(ordre)
    canal = _canal(D, s, s["_role"])
    d = canal.lire()
    maintenant = time.time()      # sans publication, pas de mesure du décalage d'horloge: heure de ce PC
    print(f"\nRendu à deux, session {s['session']} ({len(ordre)} images à calculer)")
    if canal.erreur:
        print(f"!! canal de messages injoignable: {canal.erreur}")
    etats = {r: D.decoder(d.get(r)) for r in D.ROLES}
    for r in D.ROLES:
        e = etats[r]
        if not e:
            print(f"  {D.NOMS[r]:16s} aucune nouvelle")
            continue
        il_y_a = D.duree_fr((maintenant - float(e.get("maj") or 0)) / 3600)
        vit = f"{e['vit']:.1f} images/h" if e.get("vit") else "vitesse ?"
        cours = f", en cours: {D.plages(e['cours'])}" if e["cours"] else ""
        print(f"  {D.NOMS[r]:16s} {e['etat']:9s} {len(e['fait'] & ordre_set):5d} images faites{cours}, {vit}, "
              f"nouvelles il y a {il_y_a}" + (f", {e['gpu']}" if e.get("gpu") else ""))
    tous = set()
    for e in etats.values():
        if e:
            tous |= e["fait"] & ordre_set
    vits = [(e.get("vit") or 0) for e in etats.values() if e and D.est_vivant(e, maintenant)]
    reste = len(ordre) - len(tous)
    print(f"\n  Film: {len(tous)}/{len(ordre)} images calculées ({100 * len(tous) / max(len(ordre), 1):.0f} %), reste {reste}.")
    if reste and sum(vits) > 0:
        print(f"  Fin estimée: {D.heure_fr(maintenant + reste / sum(vits) * 3600)} (si les PC continuent à ce rythme)")
    if s["_role"] == "ilyas":
        ici = _images(s["_out"], ordre_set)
        print(f"  Sur ce PC (images du frère importées comprises): {len(ici)}/{len(ordre)}. Dossier: {s['_out']}")
    print(f"\n  Notifications: application ntfy, sujet {s['sujet']} (ou {s.get('serveur', D.SERVEUR).rstrip('/')}/{s['sujet']})")
    return 0


def cmd_duo_envoyer(B, D, cfg, paths, extra):
    """PC du frère: un seul zip de toutes ses images (dossier ENVOI), puis ouvre le dossier et SwissTransfer."""
    s, extra = charger_session(B, cfg, extra)
    if s["_role"] != "frere":
        sys.exit("À lancer sur le PC du frère (ENVOYER_IMAGES.bat).")
    z = _zip_final_frere(D, s, s["_out"])
    if not z:
        print("Aucune image à envoyer pour l'instant.")
        return 1
    print(f"\nFichier prêt: {z} ({os.path.getsize(z) / 1e9:.2f} Go)\nL'envoyer à Ilyas: glisser le fichier dans la page SwissTransfer "
          "qui s'ouvre (gratuit, jusqu'à 50 Go), mettre son adresse e-mail, Envoyer. Ou le copier sur une clé USB.")
    _ouvrir(z, selection=True)
    _ouvrir(SWISSTRANSFER)
    _canal(D, s, "frere").prevenir("Fichier du frère prêt", f"{os.path.basename(z)} ({os.path.getsize(z) / 1e9:.1f} Go) va t'être envoyé.", 3)
    return 0


def cmd_duo_importer(B, D, cfg, paths, extra):
    """PC d'Ilyas: importe dans le film un zip (ou un dossier d'images) du frère.   python blatten.py duo-importer CHEMIN [...]"""
    s, extra = charger_session(B, cfg, extra)
    if s["_role"] != "ilyas":
        sys.exit("À lancer sur le PC d'Ilyas.")
    cibles = [x for x in extra if not x.startswith("--")]
    if not cibles:
        sys.exit("Indiquer le zip ou le dossier: python blatten.py duo-importer C:/Users/.../Downloads/Blatten_....zip")
    pl, ordre, pas = _plan(D, s)
    os.makedirs(s["_out"], exist_ok=True)
    total = 0
    for c in cibles:
        if os.path.isdir(c):
            n0 = len(_images(s["_out"]))
            for f in os.listdir(c):
                if re.fullmatch(r"frame_\d{4,}" + re.escape(EXT), f) and not os.path.exists(os.path.join(s["_out"], f)):
                    shutil.copyfile(os.path.join(c, f), os.path.join(s["_out"], f))
            total += len(_images(s["_out"])) - n0
        else:
            a = D.importer_zip(c, s["_out"], s["session"], EXT)
            if a is None:
                print(f"{c}: ce zip n'est pas de la session {s['session']}")
                continue
            total += len(a)
    print(f"{total} images importées dans {s['_out']}. Le rendu (Lancer_rendu_duo.bat) fera le reste.")
    return 0
