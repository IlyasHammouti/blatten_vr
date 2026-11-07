"""
duo.py : rendu du film 360 à deux PC (PC d'Ilyas + PC du frère), sans serveur ni compte à installer.

COMMENT ÇA MARCHE
  - Les deux PC rendent avec exactement le même code, les mêmes réglages et les mêmes données: le paquet du frère est une copie
    figée, et le PC d'Ilyas rend avec la même copie (dossier duo/<session>/code), quoi qu'il arrive ensuite au dépôt.
  - Ilyas part du début du film, le frère de la fin. Chacun prend un paquet de quelques images à la fois et annonce sur un canal de
    messages (ntfy.sh, sujet secret tiré au hasard) ce qu'il a fini et ce qu'il est en train de faire. Quand les deux se
    rapprochent, le reste est coupé selon la vitesse mesurée de chacun, pour finir ensemble (aucun PC n'attend l'autre des heures).
  - Si un PC se tait plus de 2 h (arrêt, plantage, veille), l'autre reprend ses images en cours. Rien n'est perdu: chaque PC garde
    ses images, et relancer un PC reprend là où il en était.
  - Les images du frère partent chez Ilyas par lots (zip de JPEG, environ 1 Mo par image): automatiquement par GitHub (dépôt privé
    de transfert) ou par un dossier partagé (Google Drive, OneDrive, réseau), ou en une fois à la fin (SwissTransfer, clé USB).
  - Le PC d'Ilyas importe les lots au fil de l'eau, refait lui-même les images ratées, puis lance le montage (outro, son, 360).
  - Le même canal envoie des notifications au téléphone (application ntfy, ou la page https://ntfy.sh/<sujet>).
Bibliothèque standard seulement: tourne avec le Python livré avec Blender sur le PC du frère.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

PROTO = 1
ROLES = ("ilyas", "frere")
NOMS = {"ilyas": "PC d'Ilyas", "frere": "PC du frère"}
SERVEUR = "https://ntfy.sh"
# Réglages de rythme (secondes). Les variables d'environnement servent aux tests (tout en accéléré).
SILENCE_MAX = float(os.environ.get("BLATTEN_DUO_SILENCE", 7200))   # sans nouvelles depuis 2 h: l'autre PC est considéré arrêté
POULS = float(os.environ.get("BLATTEN_DUO_POULS", 2700))          # nouvelles envoyées toutes les 45 min pendant un paquet
ATTENTE = float(os.environ.get("BLATTEN_DUO_ATTENTE", 180))       # vérification toutes les 3 min quand on attend
CONFLIT = float(os.environ.get("BLATTEN_DUO_CONFLIT", 15))        # délai avant de vérifier qu'on n'a pas pris les mêmes images
SURCOUT_H = 0.05          # h: construction de la scène dans Blender au début de chaque paquet (environ 3 min)
JOURS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


# ----------------------------------------------------------------------------------
# Listes d'images compactes: "1-239:2,241-900,1601-1830"
# ----------------------------------------------------------------------------------
def plages(nums):
    nums = sorted({int(x) for x in nums})
    out, i = [], 0
    while i < len(nums):
        a = nums[i]
        if i + 1 < len(nums):
            s = nums[i + 1] - a
            j = i + 1
            while j + 1 < len(nums) and nums[j + 1] - nums[j] == s:
                j += 1
            if j - i >= 2 or s == 1:
                out.append(f"{a}-{nums[j]}" + (f":{s}" if s != 1 else ""))
                i = j + 1
                continue
        out.append(str(a))
        i += 1
    return ",".join(out)


def deplages(s):
    out = []
    for p in str(s or "").split(","):
        m = re.fullmatch(r"\s*(\d+)(?:-(\d+)(?::(\d+))?)?\s*", p)
        if m:
            a = int(m.group(1))
            b = int(m.group(2) or a)
            out.extend(range(a, b + 1, max(1, int(m.group(3) or 1))))
    return out


# ----------------------------------------------------------------------------------
# Plan du film: quelles images calculer, lesquelles recopier
# ----------------------------------------------------------------------------------
def plan(n, n_intro=0, k_intro=1, k_film=1):
    """Images à calculer, dans l'ordre du film: liste de (numéro, pas). Pendant l'intro (paysage immobile), une image sur k_intro,
    recopiée sur les suivantes (comme render --intro-pas). Ensuite une image sur k_film (1 pour le film final)."""
    p, debut = [], 1
    n_intro = min(int(n_intro or 0), n)
    if k_intro > 1 and n_intro > 1:
        p += [(f, k_intro) for f in range(1, n_intro + 1, k_intro)]
        debut = n_intro + 1
    p += [(f, k_film) for f in range(debut, n + 1) if (f - 1) % k_film == 0]
    return p


def copies(pl, n):
    """(source, destination) des images non calculées, recopiées de l'image calculée qui les précède."""
    calc = {f for f, _ in pl}
    return [(f, j) for f, s in pl for j in range(f + 1, min(f + s, n + 1)) if j not in calc]


# ----------------------------------------------------------------------------------
# Choix du prochain paquet
# ----------------------------------------------------------------------------------
def est_vivant(autre, maintenant, silence_max=None):
    """L'autre PC rend-il en ce moment (nouvelles récentes, ni fini ni arrêté)?"""
    if not autre:
        return False
    if autre.get("etat") in ("fini", "arret", "complet"):
        return False
    return maintenant - float(autre.get("maj") or 0) < (SILENCE_MAX if silence_max is None else silence_max)


def reste_autre(autre, maintenant, vit_autre):
    """Images encore à faire dans le paquet en cours de l'autre PC (ce qu'il annonce, corrigé par le temps écoulé depuis)."""
    if not autre:
        return 0.0
    r = float(len(autre["cours"] - autre["fait"]))
    debut = autre.get("t_cours_serveur") or autre.get("tc")      # heure du serveur si connue (horloges des PC décalées)
    if debut and vit_autre:
        ecoule = max(0.0, maintenant - float(debut) - SURCOUT_H * 3600)
        r = min(r, max(0.0, len(autre["cours"]) - ecoule / 3600.0 * vit_autre))
    return r


def choisir(ordre, pas, faits, autre, sens, K, vit_moi, vit_autre, maintenant, vivant, limite=None, limite_autre=None):
    """Prochain paquet de ce PC.
        ordre   images à calculer (ordre du film)     pas   {image: pas}
        faits   images déjà présentes sur ce PC       autre état de l'autre PC (decoder()), ou None
        sens    +1: on part du début, -1: de la fin    K     taille maximale d'un paquet
        vit_*   images par heure (None si inconnu)     vivant: l'autre PC rend en ce moment
        limite  fonction image -> bool qui restreint le choix (frère sans aucune nouvelle d'Ilyas, --max-image, carte pleine)
        limite_autre  images que l'autre PC peut prendre (il a annoncé une limite): celles qu'il ne peut pas faire ne sont
                jamais laissées à l'attente (sinon les deux PC s'attendraient)
    Rend (images, raison): raison "paquet", "attendre" (l'autre finira plus tôt en les faisant lui-même) ou "rien"."""
    pris = set(faits)
    R = 0.0
    if autre:
        pris |= autre["fait"]
        if vivant:
            pris |= autre["cours"]
            R = reste_autre(autre, maintenant, vit_autre)
    dispo = [f for f in ordre if f not in pris and (limite is None or limite(f))]
    if not dispo:
        return [], "rien"
    G = len(dispo)
    kmax = min(K, G)
    k = kmax
    if vivant and vit_moi and vit_autre:
        def duree(k):
            moi = (SURCOUT_H + k / vit_moi) if k else 0.0
            lui = (R + G - k) / vit_autre + (SURCOUT_H if G - k > 0 else 0.0)
            return max(moi, lui)
        x = vit_moi * (R + G) / (vit_moi + vit_autre)
        cands = {0, kmax, max(0, min(kmax, int(x))), max(0, min(kmax, int(x) + 1))}
        k = min(cands, key=lambda c: (round(duree(c), 6), -c))
        if limite_autre is not None:
            k = max(k, min(kmax, sum(1 for f in dispo if not limite_autre(f))))
    if k == 0:
        return [], "attendre"
    idx = {f: i for i, f in enumerate(ordre)}
    seq = dispo if sens > 0 else dispo[::-1]
    pris_ = [seq[0]]
    for f in seq[1:]:
        if len(pris_) >= k or idx[f] != idx[pris_[-1]] + sens or pas[f] != pas[pris_[-1]]:
            break
        pris_.append(f)
    return sorted(pris_), "paquet"


def retirer_conflit(mien, autre, sens, mon_temps, mon_role):
    """Après avoir annoncé un paquet: si l'autre PC a annoncé les mêmes images au même moment, le premier arrivé (heure du serveur,
    puis Ilyas en cas d'égalité) les garde. Rend la partie de mon paquet que je garde (images consécutives depuis mon bout)."""
    if not autre or not (set(mien) & autre["cours"]):
        return list(mien)
    t_lui = float(autre.get("t_cours_serveur") or autre.get("maj") or 0)
    if (t_lui, autre.get("role") != "ilyas") > (mon_temps, mon_role != "ilyas"):
        return list(mien)                     # j'étais là avant: c'est lui qui recule
    seq = sorted(mien) if sens > 0 else sorted(mien, reverse=True)
    garde = []
    for f in seq:
        if f in autre["cours"]:
            break
        garde.append(f)
    return sorted(garde)


# ----------------------------------------------------------------------------------
# Canal de messages (ntfy.sh): états des deux PC + notifications du téléphone
# ----------------------------------------------------------------------------------
def _contexte_ssl():
    import ssl
    try:
        import certifi   # livré avec Blender (et souvent avec Python)
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _ouvrir(req, timeout, suivre=True):
    gestionnaires = [urllib.request.HTTPSHandler(context=_contexte_ssl())]
    if not suivre:
        gestionnaires.append(_SansRedirection())
    return urllib.request.build_opener(*gestionnaires).open(req, timeout=timeout)


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None       # la redirection remonte en HTTPError (3xx), on la suit nous-mêmes sans l'en-tête d'authentification


def decoder(m):
    """Message brut -> état exploitable (ensembles d'images)."""
    if not m:
        return None
    return dict(role=m.get("r"), etat=m.get("etat", "?"), fait=set(deplages(m.get("fait"))), cours=set(deplages(m.get("cours"))),
                envoye=set(deplages(m.get("envoye"))), tc=m.get("tc"), t_cours_serveur=m.get("tcs"), vit=m.get("vit"),
                gpu=m.get("gpu"), ec=m.get("ec"), maj=m.get("maj", 0), t=m.get("t", 0), msg=m.get("msg"), n=m.get("n"),
                lim=tuple(m["lim"]) if isinstance(m.get("lim"), (list, tuple)) and len(m["lim"]) == 2 else None)


def borne_fn(lim):
    """(première, dernière) image qu'un PC accepte de prendre -> fonction image -> bool (None: pas de limite)."""
    if not lim:
        return None
    lo, hi = int(lim[0]), int(lim[1])
    return lambda f: lo <= f <= hi


def memoire_pleine(txt):
    """Le journal de Blender montre-t-il une carte graphique à court de mémoire ?"""
    return bool(re.search(r"out of [a-z ]{0,40}memory|CUDA_ERROR_OUT_OF_MEMORY|OPTIX_ERROR_[A-Z_]*OUT_OF_MEMORY", txt or "", re.I))


class Canal:
    """États des PC sur le sujet <sujet>-etat (un message JSON par mise à jour, silencieux), notifications lisibles sur <sujet>.
    Une panne du réseau ne bloque jamais le rendu: on garde le dernier état connu (aussi enregistré sur le disque)."""

    def __init__(self, serveur, sujet, session, role, cache=None, timeout=20):
        self.url = (serveur or SERVEUR).rstrip("/")
        self.sujet, self.sujet_etat = sujet, sujet + "-etat"
        self.session, self.role, self.timeout, self.cache = session, role, timeout, cache
        self.derniers = {}
        self.decalage = 0.0     # heure du serveur - heure de ce PC (mesuré à chaque publication)
        self.ok = None          # heure du dernier échange réussi
        self.erreur = None
        self._verrou = threading.Lock()
        if cache and os.path.exists(cache):
            try:
                self.derniers = json.load(open(cache, encoding="utf-8"))
            except Exception:
                self.derniers = {}

    def _post(self, charge):
        req = urllib.request.Request(self.url + "/", data=json.dumps(charge).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "blatten-duo"})
        with _ouvrir(req, self.timeout) as r:
            txt = r.read().decode("utf-8", "replace")
        self.ok, self.erreur = time.time(), None
        try:
            return json.loads(txt or "{}")
        except ValueError:
            return {}

    def publier(self, etat):
        """Publie l'état de ce PC. Rend l'heure du serveur du message (ou None si le réseau a échoué)."""
        m = dict(etat, proto=PROTO, s=self.session, r=self.role, t=round(time.time(), 1))
        txt = json.dumps(m, separators=(",", ":"), ensure_ascii=False)
        if len(txt) > 3900:   # limite des messages ntfy (4 Ko): on retire le détail le moins utile
            m.pop("envoye", None)
            txt = json.dumps(m, separators=(",", ":"), ensure_ascii=False)
        try:
            t0 = time.time()
            with self._verrou:
                rep = self._post({"topic": self.sujet_etat, "message": txt, "priority": 1})
            if rep.get("time"):
                self.decalage = float(rep["time"]) - (t0 + time.time()) / 2
                return float(rep["time"])
            return time.time() + self.decalage
        except Exception as e:
            self.erreur = f"{type(e).__name__}: {e}"
            return None

    def prevenir(self, titre, texte, priorite=3, tags=None):
        """Notification lisible (téléphone). priorite 1 à 5: 2 = discrète, 3 = normale, 4 = importante."""
        try:
            with self._verrou:
                self._post({"topic": self.sujet, "title": titre, "message": texte, "priority": int(priorite), "tags": tags or []})
            return True
        except Exception as e:
            self.erreur = f"{type(e).__name__}: {e}"
            return False

    def maintenant(self):
        """Heure du serveur, estimée (sert à juger si l'autre PC donne encore des nouvelles)."""
        return time.time() + self.decalage

    def lire(self, depuis="12h"):
        """Derniers états connus de chaque PC de cette session: {role: message brut + 'maj' (heure du serveur)}."""
        url = f"{self.url}/{urllib.parse.quote(self.sujet_etat)}/json?poll=1&since={depuis}"
        try:
            with _ouvrir(urllib.request.Request(url, headers={"User-Agent": "blatten-duo"}), self.timeout) as r:
                lignes = r.read().decode("utf-8", "replace").splitlines()
            self.ok, self.erreur = time.time(), None
        except Exception as e:
            self.erreur = f"{type(e).__name__}: {e}"
            return dict(self.derniers)
        for l in lignes:
            try:
                ev = json.loads(l)
                if ev.get("event") != "message":
                    continue
                m = json.loads(ev.get("message") or "{}")
            except ValueError:
                continue
            if m.get("proto") != PROTO or m.get("s") != self.session or m.get("r") not in ROLES:
                continue
            m["maj"] = float(ev.get("time") or 0)
            ancien = self.derniers.get(m["r"])
            if not ancien or (m["maj"], m.get("t", 0)) >= (ancien.get("maj", 0), ancien.get("t", 0)):
                self.derniers[m["r"]] = m
        if self.cache:
            try:
                tmp = self.cache + ".part"
                json.dump(self.derniers, open(tmp, "w", encoding="utf-8"))
                os.replace(tmp, self.cache)
            except OSError:
                pass
        return dict(self.derniers)


# ----------------------------------------------------------------------------------
# Lots d'images (zip) et import
# ----------------------------------------------------------------------------------
def nom_lot(session, role, frames):
    return f"Blatten_{session}_{role}_{min(frames):04d}-{max(frames):04d}.zip"


def creer_lot(out, frames, ext, dest, session, role):
    """Zip sans compression (les JPEG sont déjà compressés) avec un manifeste. Écrit d'abord en .part, puis renomme."""
    tmp = dest + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        z.writestr("manifeste.json", json.dumps(dict(session=session, role=role, images=plages(frames),
                                                     cree=time.strftime("%Y-%m-%d %H:%M:%S")), ensure_ascii=False))
        for f in sorted(frames):
            z.write(os.path.join(out, f"frame_{f:04d}{ext}"), f"frame_{f:04d}{ext}")
    os.replace(tmp, dest)
    return dest


def importer_zip(chemin, out, session, ext=".jpg", _profondeur=0):
    """Ajoute dans out les images d'un lot de cette session (celles déjà présentes ne sont pas touchées). Accepte aussi un zip qui
    contient des lots (téléchargement groupé). Rend la liste des images ajoutées, ou None si le zip n'appartient pas à la session.
    Un zip abîmé lève zipfile.BadZipFile (somme de contrôle vérifiée à la lecture)."""
    ajout = []
    with zipfile.ZipFile(chemin) as z:
        noms = z.namelist()
        internes = [n for n in noms if n.lower().endswith(".zip") and session in os.path.basename(n)]
        if "manifeste.json" in noms:
            man = json.loads(z.read("manifeste.json").decode("utf-8"))
            if man.get("session") != session:
                return None
        elif not internes and session not in os.path.basename(chemin):
            return None
        for n in noms:
            m = re.fullmatch(r"(?:.*/)?frame_(\d{4,})" + re.escape(ext), n)
            if not m:
                continue
            f = int(m.group(1))
            dst = os.path.join(out, f"frame_{f:04d}{ext}")
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                continue
            tmp = dst + ".part"
            with z.open(n) as src, open(tmp, "wb") as d:
                shutil.copyfileobj(src, d, 1 << 20)
            if os.path.getsize(tmp) == 0:
                os.remove(tmp)
                continue
            os.replace(tmp, dst)
            ajout.append(f)
        if _profondeur == 0 and internes:
            tmpdir = os.path.join(out, "_import_tmp")
            os.makedirs(tmpdir, exist_ok=True)
            for n in internes:
                p = z.extract(n, tmpdir)
                try:
                    ajout += importer_zip(p, out, session, ext, 1) or []
                finally:
                    os.remove(p)
            shutil.rmtree(tmpdir, ignore_errors=True)
    return ajout


# ----------------------------------------------------------------------------------
# Transports des lots du frère vers le PC d'Ilyas
# ----------------------------------------------------------------------------------
class Transport:
    """Manuel: rien ne part tout seul. Le frère envoie un seul zip à la fin (SwissTransfer, clé USB), Ilyas le met dans ses
    Téléchargements (ou dans duo/<session>/apports): son PC le trouve et l'importe."""
    type = "manuel"
    auto = False

    def deposer(self, chemin):
        return False

    def lots(self):
        return []      # [(nom, taille, fonction(dossier) -> chemin local du zip)]

    def verifier(self):
        return True, "envoi manuel à la fin"


class TransportDossier(Transport):
    """Dossier partagé (Google Drive pour ordinateur, OneDrive, Dropbox, dossier réseau...): le frère y dépose les lots, le PC
    d'Ilyas les y lit. Le chemin peut différer d'un PC à l'autre: on cherche le dossier par son nom aux endroits habituels."""
    type = "dossier"
    auto = True

    def __init__(self, chemin, nom=None):
        self.chemin, self.nom = chemin, nom

    def _resoudre(self):
        if not (self.chemin and os.path.isdir(self.chemin)) and self.nom:
            self.chemin = chercher_dossier(self.nom) or self.chemin     # le dossier synchronisé peut apparaître plus tard
        return self.chemin

    def verifier(self):
        self._resoudre()
        if not self.chemin or not os.path.isdir(self.chemin):
            return False, f"dossier partagé introuvable: {self.chemin}"
        try:
            t = os.path.join(self.chemin, f".test_ecriture_{os.getpid()}")
            open(t, "w").write("ok")
            os.remove(t)
        except OSError as e:
            return False, f"dossier partagé non inscriptible ({e})"
        return True, f"dossier partagé {self.chemin}"

    def deposer(self, chemin):
        if not self._resoudre() or not os.path.isdir(self.chemin):
            raise OSError(f"dossier partagé introuvable ({self.nom or self.chemin})")
        dest = os.path.join(self.chemin, os.path.basename(chemin))
        if os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(chemin):
            return True
        tmp = dest + ".part"
        shutil.copyfile(chemin, tmp)
        os.replace(tmp, dest)
        return True

    def lots(self):
        if not self._resoudre() or not os.path.isdir(self.chemin):
            return []
        return [(f, os.path.getsize(os.path.join(self.chemin, f)), (lambda d, p=os.path.join(self.chemin, f): p))
                for f in sorted(os.listdir(self.chemin)) if f.lower().endswith(".zip")]


def chercher_dossier(nom_ou_chemin):
    """Chemin d'un dossier partagé: tel quel s'il existe, sinon cherché par son nom (Google Drive, OneDrive, Dropbox)."""
    if not nom_ou_chemin:
        return None
    if os.path.isdir(nom_ou_chemin):
        return os.path.abspath(nom_ou_chemin)
    nom = os.path.basename(os.path.normpath(nom_ou_chemin))
    cands = []
    if os.name == "nt":
        import string
        for L in string.ascii_uppercase:
            for sous in ("Mon Drive", "My Drive", "Mein Ablagebereich", ""):
                cands.append(os.path.join(f"{L}:\\", sous, nom) if sous else os.path.join(f"{L}:\\", nom))
    home = os.path.expanduser("~")
    for base in ("OneDrive", "Dropbox", "Google Drive", os.path.join("Google Drive", "Mon Drive"), os.path.join("Google Drive", "My Drive")):
        cands.append(os.path.join(home, base, nom))
    try:
        cands += [os.path.join(home, d, nom) for d in os.listdir(home) if d.startswith("OneDrive")]
    except OSError:
        pass
    return next((c for c in cands if os.path.isdir(c)), None)


class TransportGithub(Transport):
    """Dépôt GitHub PRIVÉ réservé au transfert: chaque lot devient un fichier joint d'une « release » (2 Go max par fichier, pas de
    limite de total). Jeton à accès fin limité à ce dépôt (Contents: read and write): s'il fuitait, seul ce dépôt serait exposé."""
    type = "github"
    auto = True
    API = "https://api.github.com"

    def __init__(self, depot, jeton, tag, api=None, uploads=None):
        self.depot, self.jeton, self.tag = depot.strip().strip("/"), jeton.strip(), tag
        self.api = (api or os.environ.get("BLATTEN_DUO_GITHUB_API") or self.API).rstrip("/")
        self.uploads = (uploads or os.environ.get("BLATTEN_DUO_GITHUB_UPLOADS") or "https://uploads.github.com").rstrip("/")
        self._rel = None

    def _req(self, methode, url, donnees=None, entetes=None, timeout=60, suivre=True):
        h = {"Authorization": f"Bearer {self.jeton}", "Accept": "application/vnd.github+json", "User-Agent": "blatten-duo",
             "X-GitHub-Api-Version": "2022-11-28"}
        h.update(entetes or {})
        if isinstance(donnees, (dict, list)):
            donnees = json.dumps(donnees).encode("utf-8")
            h["Content-Type"] = "application/json"
        return _ouvrir(urllib.request.Request(url, data=donnees, method=methode, headers=h), timeout, suivre)

    def _json(self, methode, url, donnees=None):
        with self._req(methode, url, donnees) as r:
            txt = r.read().decode("utf-8")
        return json.loads(txt) if txt else {}

    def release(self):
        if self._rel:
            return self._rel
        url_tag = f"{self.api}/repos/{self.depot}/releases/tags/{urllib.parse.quote(self.tag)}"
        try:
            self._rel = self._json("GET", url_tag)
            return self._rel
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        corps = {"tag_name": self.tag, "name": f"Blatten duo {self.tag}", "prerelease": True,
                 "body": "Lots d'images du rendu à deux PC (créé automatiquement par blatten.py)."}
        for essai in range(2):
            try:
                self._rel = self._json("POST", f"{self.api}/repos/{self.depot}/releases", corps)
                return self._rel
            except urllib.error.HTTPError as e:
                txt = e.read().decode("utf-8", "replace")
                if e.code == 422 and "already_exists" in txt:        # l'autre PC l'a créée au même moment
                    self._rel = self._json("GET", url_tag)
                    return self._rel
                if essai == 0 and e.code in (409, 422) and ("empty" in txt.lower() or "Repository is empty" in txt):
                    # dépôt vide: une release a besoin d'un premier commit
                    import base64
                    self._json("PUT", f"{self.api}/repos/{self.depot}/contents/LISEZMOI.md",
                               {"message": "Dépôt de transfert Blatten", "content": base64.b64encode(
                                   "Transfert des images du rendu à deux PC (Blatten 360).\n".encode("utf-8")).decode("ascii")})
                    continue
                raise urllib.error.HTTPError(e.url, e.code, f"{e.reason}: {txt[:300]}", e.headers, None)

    def assets(self):
        rel = self.release()
        out, page = [], 1
        while True:
            lot = self._json("GET", f"{self.api}/repos/{self.depot}/releases/{rel['id']}/assets?per_page=100&page={page}")
            out += lot
            if len(lot) < 100:
                return out
            page += 1

    def verifier(self):
        try:
            self.release()
            return True, f"GitHub {self.depot} (release {self.tag})"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, "GitHub: jeton refusé (expiré ou mal copié)"
            if e.code in (403, 404):
                return False, f"GitHub: dépôt {self.depot} introuvable pour ce jeton, ou droit « Contents: Read and write » manquant ({e.code})"
            return False, f"GitHub: erreur {e.code} {e.reason}"
        except Exception as e:
            return False, f"GitHub injoignable: {type(e).__name__}: {e}"

    def deposer(self, chemin):
        nom, taille = os.path.basename(chemin), os.path.getsize(chemin)
        rel = self.release()
        for a in self.assets():
            if a["name"] == nom:
                if a.get("size") == taille and a.get("state") == "uploaded":
                    return True
                with self._req("DELETE", f"{self.api}/repos/{self.depot}/releases/assets/{a['id']}"):
                    pass
        url = f"{self.uploads}/repos/{self.depot}/releases/{rel['id']}/assets?name={urllib.parse.quote(nom)}"
        with open(chemin, "rb") as f:
            with self._req("POST", url, f, {"Content-Type": "application/zip", "Content-Length": str(taille)}, timeout=900) as r:
                r.read()
        return True

    def lots(self):
        return [(a["name"], a.get("size", 0), (lambda d, a=a: self._telecharger(a, d)))
                for a in self.assets() if a.get("state", "uploaded") == "uploaded" and a["name"].lower().endswith(".zip")]

    def _telecharger(self, a, dossier):
        os.makedirs(dossier, exist_ok=True)
        dest = os.path.join(dossier, a["name"])
        if os.path.exists(dest) and os.path.getsize(dest) == a.get("size"):
            return dest
        url = f"{self.api}/repos/{self.depot}/releases/assets/{a['id']}"
        try:
            r = self._req("GET", url, entetes={"Accept": "application/octet-stream"}, timeout=120, suivre=False)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308) or not e.headers.get("Location"):
                raise
            # lien temporaire signé (stockage de GitHub): sans l'en-tête d'authentification
            r = _ouvrir(urllib.request.Request(e.headers["Location"], headers={"User-Agent": "blatten-duo"}), 300)
        tmp = dest + ".part"
        with r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        os.replace(tmp, dest)
        return dest


def transport(cfg_t, chemin_local=None):
    """Transport décrit dans la session ({"type": ..., ...})."""
    t = (cfg_t or {}).get("type", "manuel")
    if t == "github":
        return TransportGithub(cfg_t["depot"], cfg_t["jeton"], cfg_t.get("tag") or "duo")
    if t == "dossier":
        return TransportDossier(chemin_local or chercher_dossier(cfg_t.get("chemin") or cfg_t.get("nom")), cfg_t.get("nom"))
    return Transport()


# ----------------------------------------------------------------------------------
# Empreintes (même code, mêmes données des deux côtés)
# ----------------------------------------------------------------------------------
def fichiers_scene(racine):
    """Fichiers qui changent les images: tout src/, les réglages, la caméra et config.json."""
    out = []
    for base in ("src", "reglages"):
        for d, sous, fs in os.walk(os.path.join(racine, base)):
            sous[:] = sorted(x for x in sous if x != "__pycache__")
            out += [os.path.relpath(os.path.join(d, f), racine) for f in sorted(fs) if not f.endswith((".pyc", ".pyo"))]
    out += [f for f in ("camera.json", "config.json") if os.path.exists(os.path.join(racine, f))]
    return sorted(x.replace("\\", "/") for x in out)


def empreinte_code(racine):
    h = hashlib.sha1()
    for rel in fichiers_scene(racine):
        h.update(rel.encode("utf-8") + b"\0")
        with open(os.path.join(racine, rel), "rb") as f:
            h.update(f.read().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def etat_donnees(base, rels):
    """[(chemin relatif, taille, date)] des fichiers de données: si l'un change pendant le rendu, les images ne seraient plus
    identiques à celles de l'autre PC."""
    out = []
    for rel in rels:
        p = os.path.join(base, rel)
        try:
            st = os.stat(p)
            out.append([rel, st.st_size, int(st.st_mtime)])
        except OSError:
            out.append([rel, -1, 0])
    return out


# ----------------------------------------------------------------------------------
# Affichage
# ----------------------------------------------------------------------------------
def heure_fr(ts):
    lt = time.localtime(ts)
    return f"{JOURS[lt.tm_wday]} {lt.tm_mday:02d}/{lt.tm_mon:02d} {lt.tm_hour:02d}:{lt.tm_min:02d}"


def duree_fr(h):
    if h is None:
        return "?"
    m = int(round(h * 60))
    return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"


def estimer_fin(reste, vit_moi, vit_autre, vivant):
    """Heures restantes pour finir le film à ce rythme (None si inconnu)."""
    v = (vit_moi or 0) + ((vit_autre or 0) if vivant else 0)
    return reste / v if v > 0 else None


class Pouls(threading.Thread):
    """Envoie des nouvelles régulièrement pendant qu'un paquet tourne (sans cela l'autre PC nous croirait arrêtés)."""

    def __init__(self, fonction, intervalle=None):
        super().__init__(daemon=True)
        self.fonction, self.intervalle = fonction, POULS if intervalle is None else intervalle
        self.arret = threading.Event()

    def run(self):
        while not self.arret.wait(self.intervalle):
            try:
                self.fonction()
            except Exception:
                pass

    def stop(self):
        self.arret.set()
