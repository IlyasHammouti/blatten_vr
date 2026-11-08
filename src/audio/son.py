"""
son.py : bande son du film, calculée depuis la simulation (pas de logiciel audio).

ENTRÉES
  - sons WAV mono ou stéréo du dossier <data_root>/sons (liste et licences: sons.json), découpés par Ilyas;
  - sources de poussière du cache (poussiere_sources_*.npz: positions des particules rapides toutes les 2 s, poids selon la
    vitesse), qui donnent la direction, la distance et l'énergie de l'écoulement vues de la caméra;
  - camera.json, config.json (durée de l'intro, nombre d'images du film), reglages/son.json (volumes).

MIXAGE (reglages/son.json)
  ambiance   forêt, fixe autour de la caméra, s'efface quand l'écoulement couvre tout
  depart     grand éboulement (G43-02 « thunderous ») dans la direction de l'écoulement, au départ
  grondement grondement sourd + séisme, direction et énergie de l'écoulement, aigus étouffés avec la distance
  impacts    second éboulement, quand la matière atteint le fond de vallée (champignons)
  souffle    tempête, quand le front approche de la caméra (moins de ~1 km), depuis la direction du front
  Chaque son de l'écoulement arrive avec le retard distance / 343 m/s. Coupure avec le fondu au noir, outro muette.

SORTIES (dans --out)
  son_ambix.wav    4 canaux AmbiX (ACN W Y Z X, SN3D), 48 kHz, face = centre de la vidéo 360 (cap 200 degrés)
  son_stereo.wav   stéréo pour le brouillon plat (face = centre de la bande, cap 170 degrés)

    python son.py --out D:/Blatten_render/son [--outro 8]      (ou: python blatten.py son)
Lecture des WAV par ffmpeg (installé, ou paquet Python imageio-ffmpeg). numpy seulement.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SR = 48000
C = 343.0

DEFAUTS = dict(
    ambiance_db=-30.0, ambiance_fond_db=-42.0,    # niveau RMS de la forêt (dBFS) au calme et sous l'écoulement
    depart=0.9, grondement=0.8, seisme=0.8, impacts=0.8, souffle=1.1,   # 8 nov.: séisme 0,5 -> 0,8, impacts 0,7 -> 0,8, souffle 0,9 -> 1,1
    distance_ref=1500.0,          # m: distance où le gain de distance vaut 1
    passe_bas_proche=4000.0, passe_bas_loin=350.0,   # Hz: aigus étouffés avec la distance
    souffle_distance=1000.0,      # m: le souffle commence quand le front est à cette distance
    cap_face_360=200.0, cap_face_bande=170.0,
    fondu_fin=1.0, outro=8.0,
    # 8 nov. (Ilyas: « encore plus fort et assourdissant »): graves renforcés, compression plus forte, limiteur commun aux
    # 4 canaux (la direction des sons est gardée quand il écrête)
    graves_db=8.0, graves_freq=120.0,          # étagère de graves sur l'écoulement (sous ~120 Hz), dB
    compression_ratio=3.0, compression_seuil=0.3, compression_max_db=22.0,   # ancien réglage: ~1,7:1, seuil 0,25, +15 dB au plus
    volume_db=4.0,                             # gain avant le limiteur
    plafond=0.89,                              # crête maximale (-1 dBFS) après le limiteur
)


def log(*a):
    print("[son]", *a, flush=True)


def ffmpeg_exe():
    f = shutil.which("ffmpeg")
    if f:
        return f
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg introuvable: installer ffmpeg ou  pip install imageio-ffmpeg")


def lire(path, canaux=1):
    """WAV quelconque -> float32 (n, canaux) à 48 kHz, via ffmpeg."""
    r = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", path, "-f", "f32le", "-ac", str(canaux), "-ar", str(SR), "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32).reshape(-1, canaux).copy()


def ecrire(path, x):
    """float (n, c) -> WAV PCM 24 bits."""
    x = np.clip(x, -1.0, 1.0)
    i = (x * 8388607.0).astype(np.int32)
    b = i.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(b)


def passe_bas(x, fc):
    """Passe-bas doux par FFT (pente ~12 dB/octave)."""
    n = len(x)
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    h = 1.0 / (1.0 + (f / fc) ** 2)
    return np.fft.irfft(X * h[:, None] if X.ndim > 1 else X * h, n=n, axis=0).astype(np.float32)


def place(src, n, debut):
    """Copie src (mono) dans un tableau de n échantillons à partir de debut (s), coupée au besoin."""
    out = np.zeros(n, np.float32)
    i0 = int(round(debut * SR))
    if i0 >= n:
        return out
    s = src[max(0, -i0):]
    i0 = max(0, i0)
    k = min(len(s), n - i0)
    out[i0:i0 + k] = s[:k]
    return out


def limiteur(x, plafond=0.89, attaque=0.002, relache=0.15):
    """Limiteur doux commun à tous les canaux: même gain pour W, Y, Z, X (la direction des sons est gardée). Le niveau
    instantané (max de |W| et de la norme de X, Y, Z) passe par une courbe douce (tanh) au-dessus de 0,6 x plafond; gain
    lissé (attaque 2 ms, relâche 150 ms) puis écrêtage final de sécurité au plafond."""
    m = np.maximum(np.abs(x[:, 0]), np.sqrt((x[:, 1:] ** 2).sum(1))) if x.shape[1] >= 4 else np.abs(x).max(1)
    g_ = 0.6 * plafond
    cible = np.where(m > g_, g_ + (plafond - g_) * np.tanh((m - g_) / (plafond - g_)), m)
    g = np.where(m > 1e-9, cible / np.maximum(m, 1e-9), 1.0).astype(np.float64)
    # lissage: descente rapide (attaque), remontée lente (relâche), par blocs de 1 ms pour aller vite
    b = SR // 1000
    nb = len(g) // b + 1
    gb = np.ones(nb)
    gpad = np.concatenate([g, np.ones(nb * b - len(g))]).reshape(nb, b).min(1)
    a_up = np.exp(-1.0 / (relache * 1000)); a_dn = np.exp(-1.0 / (attaque * 1000))
    cur = 1.0
    for i in range(nb):
        v = gpad[i]
        cur = a_dn * cur + (1 - a_dn) * v if v < cur else a_up * cur + (1 - a_up) * v
        cur = min(cur, v) if v < cur else cur
        gb[i] = cur
    gs = np.repeat(gb, b)[:len(g)]
    y = x * gs[:, None]
    return np.clip(y, -plafond, plafond).astype(np.float32)


def boucle(src, n):
    reps = int(np.ceil(n / len(src)))
    return np.tile(src, (reps, 1) if src.ndim > 1 else reps)[:n]


def trajectoire(sources, cam, intro):
    """Paramètres de l'écoulement vus de la caméra, en fonction du temps du FILM où le son arrive à la caméra:
    rend (temps d'arrivée, cap, élévation, distance, énergie 0-1, distance du point le plus proche, cap du plus proche)."""
    z = np.load(sources)
    P, W, T = z["P"].astype(np.float64), z["W"].astype(np.float64), z["T"].astype(np.float64)
    v = P - cam[None, None, :]
    d = np.linalg.norm(v, axis=2)
    w = W + 1e-9
    # direction moyenne pondérée par l'énergie (vecteurs unitaires), distance pondérée
    u = v / d[..., None]
    um = (u * w[..., None]).sum(1)
    um /= np.linalg.norm(um, axis=1, keepdims=True)
    cap = np.degrees(np.arctan2(um[:, 0], um[:, 1])) % 360
    el = np.degrees(np.arcsin(np.clip(um[:, 2], -1, 1)))
    dm = (d * w).sum(1) / w.sum(1)
    e = W.sum(1)
    e = e / max(e.max(), 1e-9)
    j = np.argmin(np.where(W > 0.1, d, np.inf), axis=1)
    dmin = d[np.arange(len(T)), j]
    capmin = np.degrees(np.arctan2(v[np.arange(len(T)), j, 0], v[np.arange(len(T)), j, 1])) % 360
    arr = intro + T + dm / C
    return dict(arr=arr, cap=cap, el=el, dist=dm, e=e, dmin=dmin, capmin=capmin, arr_min=intro + T + dmin / C)


def interp(t, x, y, angle=False):
    o = np.argsort(x)
    x, y = x[o], y[o]
    if angle:
        r = np.unwrap(np.radians(y))
        return np.degrees(np.interp(t, x, r))
    return np.interp(t, x, y)


def encoder(sig, cap, el, face):
    """Mono (n,) + direction par échantillon -> AmbiX (n,4) W Y Z X (SN3D). Azimut positif vers la gauche."""
    az = np.radians(-(cap - face))
    e = np.radians(el)
    return np.stack([sig, sig * np.sin(az) * np.cos(e), sig * np.sin(e), sig * np.cos(az) * np.cos(e)], 1)


def stereo_depuis(amb, face_amb, face_st):
    """AmbiX -> stéréo (cardioïdes virtuels à +-60 degrés), après rotation de la face 360 vers la face de la bande."""
    W, Y, Z, X = amb.T
    rot = np.radians(-(face_st - face_amb))      # tourner la scène pour que la face soit face_st
    Xr = X * np.cos(rot) + Y * np.sin(rot)
    Yr = -X * np.sin(rot) + Y * np.cos(rot)
    out = []
    for a in (np.radians(60), np.radians(-60)):
        out.append(0.5 * (W + Xr * np.cos(a) + Yr * np.sin(a)))
    return np.stack(out, 1)


def main():
    ap = argparse.ArgumentParser(prog="son")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sons")
    ap.add_argument("--cache")
    ap.add_argument("--outro", type=float)
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    loc = os.path.join(ROOT, "config.local.json")
    if os.path.exists(loc):
        cfg.update(json.load(open(loc, encoding="utf-8")))
    R = dict(DEFAUTS)
    rs = os.path.join(ROOT, "reglages", "son.json")
    if os.path.exists(rs):
        R.update({k: v for k, v in json.load(open(rs, encoding="utf-8")).items() if not k.startswith("_")})
    if a.outro is not None:
        R["outro"] = a.outro
    data = cfg.get("data_root", "data")
    data = data if os.path.isabs(data) else os.path.join(ROOT, data)
    sons = a.sons or os.path.join(data, "sons")
    cache = a.cache or cfg.get("cache_dir") or os.path.join(data, "pipeline", "cache")
    srcs = sorted(glob.glob(os.path.join(cache, "poussiere_sources_*.npz")), key=os.path.getmtime)
    if not srcs:
        sys.exit(f"Pas de poussiere_sources_*.npz dans {cache} (lancer un rendu avec la poussière une fois)")
    cam = np.array(json.load(open(os.path.join(ROOT, "camera.json"), encoding="utf-8"))["cam"], np.float64)
    sc = cfg.get("scene") or {}
    intro, fps = float(sc.get("intro", 0.0)), float(sc.get("fps", 30))
    film = int((cfg.get("film") or {}).get("images", 1830)) / fps
    total = film + float(R["outro"])
    n = int(round(total * SR))
    t = np.arange(n) / SR
    log(f"film {film:.1f} s (intro {intro:g} s) + outro {R['outro']:g} s; sources {os.path.basename(srcs[-1])}")
    tr = trajectoire(srcs[-1], cam, intro)
    cap = interp(t, tr["arr"], tr["cap"], angle=True)
    el = interp(t, tr["arr"], tr["el"])
    dist = interp(t, tr["arr"], tr["dist"])
    ener = interp(t, tr["arr"], tr["e"])
    ener[t < tr["arr"].min()] = 0.0
    gd = np.clip(R["distance_ref"] / np.maximum(dist, 50.0), 0.0, 2.0)
    # proportion d'aigus gardés selon la distance (log entre proche et loin)
    fc = np.exp(np.interp(np.log(np.maximum(dist, 1.0)), np.log([300.0, 3000.0]),
                          np.log([R["passe_bas_proche"], R["passe_bas_loin"]])))
    aigus = np.clip((np.log(fc) - np.log(R["passe_bas_loin"])) / (np.log(R["passe_bas_proche"]) - np.log(R["passe_bas_loin"])), 0, 1)

    def filtre_distance(x):
        lo = passe_bas(x, R["passe_bas_loin"])
        return lo + (x - lo) * aigus

    lis = lambda nom, c=1: lire(os.path.join(sons, nom), c)
    amb = np.zeros((n, 4), np.float32)
    # 2. départ: grand éboulement à l'arrivée du premier son
    t0 = float(tr["arr"].min())
    ton = lis("eboulement_tonnerre.wav")[:, 0]
    dep = filtre_distance(place(ton, n, t0)) * R["depart"] * gd * np.clip(0.4 + ener, 0, 1.2)
    amb += encoder(dep, cap, el, R["cap_face_360"])
    # 3. grondement continu (grondement sourd + séisme), suit l'énergie
    gr = place(lis("grondement_sourd.wav")[:, 0], n, t0 - 1.0) * R["grondement"] + place(lis("seisme_grondement.wav")[:, 0], n, t0 + 2.0) * R["seisme"]
    gr = filtre_distance(gr) * gd * ener
    amb += encoder(gr, cap, el, R["cap_face_360"])
    # 4. impacts dans la vallée: même éboulement (second départ dans le fichier), quand l'énergie au fond est forte
    z = np.load(srcs[-1])
    zf = np.percentile(z["P"][..., 2][z["W"] > 0.05], 2)
    bas = ((z["P"][..., 2] < zf + 250.0) * z["W"]).sum(1)
    if bas.max() > 0:
        k = int(np.argmax(bas > 0.25 * bas.max()))
        t_imp = intro + float(z["T"][k]) + float(tr["dist"][k]) / C
        imp = filtre_distance(place(ton[int(8 * SR):], n, t_imp)) * R["impacts"] * gd
        amb += encoder(imp, cap, el, R["cap_face_360"])
        log(f"impacts dans la vallée: son à {t_imp:.1f} s du film")
    # 5. souffle quand le front approche, depuis la direction du point le plus proche
    dmin = interp(t, tr["arr_min"], tr["dmin"])
    capm = interp(t, tr["arr_min"], tr["capmin"], angle=True)
    g_s = np.clip((R["souffle_distance"] - dmin) / (0.7 * R["souffle_distance"]), 0, 1) ** 1.5
    g_s[t < tr["arr_min"].min()] = 0.0
    sf = boucle(lis("souffle_tempete.wav", 1), n)[:, 0] * R["souffle"] * g_s
    amb += encoder(sf, capm, np.zeros(n), R["cap_face_360"])
    # graves renforcés (étagère sous graves_freq): le grondement se sent plus qu'il ne s'entend
    if R["graves_db"]:
        amb += (10 ** (R["graves_db"] / 20) - 1.0) * passe_bas(amb, R["graves_freq"])
    # écoulement normalisé (crête à -2 dBFS), puis compression (rapport compression_ratio:1 sous le seuil): le début est
    # vite fort, la fin reste la plus forte
    amb *= 0.8 / max(np.abs(amb).max(), 1e-6)
    env = np.sqrt(np.convolve(amb[:, 0] ** 2, np.ones(SR // 10) / (SR // 10), mode="same"))
    k_c = 1.0 - 1.0 / max(float(R["compression_ratio"]), 1.0)
    gain = np.clip((np.maximum(env, 1e-4) / R["compression_seuil"]) ** (-k_c), 1.0, 10 ** (R["compression_max_db"] / 20))
    amb *= gain[:, None] * 10 ** (R["volume_db"] / 20)
    # 1. ambiance forêt (stéréo -> W + Y), à un niveau fixe en dBFS, baisse sous l'écoulement
    foret = boucle(lis("ambiance_foret.wav", 2), n)
    rms = np.sqrt((foret ** 2).mean()) + 1e-9
    db = R["ambiance_db"] + (R["ambiance_fond_db"] - R["ambiance_db"]) * np.clip(env * gain / 0.2, 0, 1)
    g_amb = (10 ** (db / 20)) / rms
    amb[:, 0] += g_amb * 0.5 * (foret[:, 0] + foret[:, 1])
    amb[:, 1] += g_amb * 0.5 * (foret[:, 0] - foret[:, 1])
    amb = limiteur(amb, R["plafond"])
    # coupure: fondu de fin du film puis silence (outro)
    fin = np.clip((film - t) / max(R["fondu_fin"], 1e-3), 0, 1)
    amb *= fin[:, None]
    os.makedirs(a.out, exist_ok=True)
    ecrire(os.path.join(a.out, "son_ambix.wav"), amb)
    st = stereo_depuis(amb, R["cap_face_360"], R["cap_face_bande"])
    st *= 0.89 / max(np.abs(st).max(), 1e-6)
    ecrire(os.path.join(a.out, "son_stereo.wav"), st)
    log(f"écrit: {a.out}/son_ambix.wav (4 canaux AmbiX) et son_stereo.wav, {total:.1f} s; premier son à {t0:.1f} s du film "
        f"(retard du son {t0 - intro:.1f} s), front au plus près {tr['dmin'].min():.0f} m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
