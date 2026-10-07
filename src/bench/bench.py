"""
bench.py : benchmark de rendu. Mesure la vitesse de CETTE machine sur la scène réelle et estime
la durée du rendu final. Permet aussi de comparer les machines entre elles (python blatten.py bench-compare).

Appelé par src/scene/blatten_blender.py avec l'option --bench (lancer: python blatten.py bench).

Principe
  - Caméra fixe (BENCH_CAM) et réglages de rendu figés: tout le monde mesure la même chose.
  - Trois rendus de la scène complète à 8, 32 et 64 échantillons, à la résolution finale
    (ou réduite par --bench-scale). Régression linéaire: temps = fixe + par_échantillon x n.
      fixe              : préparation de la scène (maillages, images), arbre de visibilité, débruitage
      par_échantillon   : coût du tracé de rayons, proportionnel aux pixels
  - Deux séries: "à froid" (la scène est reconstruite à chaque image) puis "persistant"
    (use_persistent_data: Blender garde en mémoire ce qui ne change pas d'une image à l'autre).
    Pour le persistant, on mesure le coût fixe sur 3 images consécutives (l'image change, les particules bougent).
  - Extrapolation à la résolution et au nombre d'échantillons du rendu final. Si le benchmark est
    réduit (échelle < 1), on donne une fourchette (coût fixe indépendant de la résolution, ou proportionnel).
  - Résultat écrit dans bench_results/ (JSON + image). Le JSON contient une "clé de comparabilité":
    deux machines sont comparables si leurs clés sont identiques (mêmes réglages, mêmes données).

Limites (à garder en tête)
  - Les particules finales (maillage de la matière, poussière) ne sont pas encore dans la scène:
    elles ajouteront du temps, surtout si la poussière est un volume. La marge indiquée (x1,3)
    est une HYPOTHESE, à remplacer par une mesure.
  - L'échantillonnage adaptatif est coupé pour que la mesure soit linéaire: le rendu réel,
    s'il l'active, ira un peu plus vite.
  - Le mode stéréo coûte environ deux fois le mono (deux yeux): estimation, pas mesure.
"""
import datetime
import glob
import hashlib
import json
import os
import platform
import time

# Caméra de référence (repère Blender recentré, Z = altitude). NE PAS MODIFIER: elle sert de
# référence commune. Ce n'est pas la caméra de la vidéo finale (voir camera.json).
BENCH_CAM = (-776.4, 754.9, 1708.07)
BENCH_ROT_DEG = (94.4, 0.0, -117.4)
SAMPLE_POINTS = (8, 32, 64)
FRAME_COUNTS = {"1 image": 1, "40 s (1200 images)": 1200, "60 s (1800 images)": 1800}
MARGE_MATIERE = 1.3   # HYPOTHESE, voir limites
# Réglages de la scène qui changent le temps de rendu: ils entrent dans la clé de comparabilité.
REGLAGES_CLE = ("sky", "sky_gain", "fog_mode", "fog", "mist", "detail", "snow", "snow_line", "ortho_gain",
                "exposure", "look", "color", "radius", "fps")


def prepare(cfg):
    """Fige les réglages avant la construction de la scène (appelé tôt dans main())."""
    cfg["preset"] = "final"
    cfg["stereo"] = False
    cfg["cam"] = BENCH_CAM
    cfg["cam_rot"] = BENCH_ROT_DEG
    cfg["vue"] = None
    cfg["views"] = False
    cfg["render_frame"] = None
    cfg["render_anim"] = False
    cfg["save"] = False


def _ram_gb():
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("tp", ctypes.c_ulonglong),
                            ("ap", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            ms = MS()
            ms.l = ctypes.sizeof(ms)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return round(ms.tp / 2**30, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except Exception:
        return None


def _devices(scene):
    import bpy
    out = []
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for d in prefs.devices:
            if d.use:
                out.append(f"{d.name} ({d.type})")
    except Exception:
        pass
    return scene.cycles.device, out


def _render(bpy, scene, samples, write_path=None):
    scene.cycles.samples = samples
    t0 = time.perf_counter()
    if write_path:
        scene.render.filepath = write_path
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(write_still=False)
    return time.perf_counter() - t0


def _fmt(sec):
    sec = float(sec)
    if sec < 90:
        return f"{sec:.0f} s"
    if sec < 5400:
        return f"{sec / 60:.0f} min"
    return f"{sec / 3600:.1f} h"


def _md5(path):
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:10]
    except Exception:
        return None


def _fit(pts):
    """Régression temps = a + b x échantillons. Retourne (a, b, écart maximal)."""
    import numpy as np
    n = np.array([p[0] for p in pts], float)
    t = np.array([p[1] for p in pts], float)
    b, a = np.polyfit(n, t, 1)
    resid = float(np.max(np.abs(t - (a + b * n))))
    return max(float(a), 0.0), float(b), resid


def _estimate(a, b, k, samples):
    lo = a + b * k * samples
    hi = a * k + b * k * samples
    return lo, hi, 0.5 * (lo + hi)


def run(scene, root, cfg, log, presets, extra=None, data_dir=None):
    import bpy

    scene.frame_set(1)
    final = presets["final"]
    fx, fy = final["res"]
    fs = final["samples"]
    mode, devs = _devices(scene)
    gpu = mode == "GPU"
    scale = cfg.get("bench_scale") or (1.0 if gpu else 0.25)
    bx, by = max(64, int(fx * scale) // 2 * 2), max(32, int(fy * scale) // 2 * 2)
    k = (fx * fy) / (bx * by)

    cy = scene.cycles
    cy.use_adaptive_sampling = False
    r = scene.render
    r.image_settings.file_format = "JPEG"
    r.image_settings.quality = 90
    r.image_settings.color_depth = "8"
    r.use_persistent_data = False
    warm = not cfg.get("bench_no_warm")

    log(f"BENCH: {'GPU' if gpu else 'CPU'} {devs or platform.processor()}, résolution {bx}x{by} (final {fx}x{fy}), "
        f"échantillons {SAMPLE_POINTS}, série persistante: {'oui' if warm else 'non'}")

    # Échauffement: chargement des noyaux (OptiX/CUDA compile au premier rendu), hors mesure.
    r.resolution_x, r.resolution_y, r.resolution_percentage = 64, 32, 100
    t_warm = _render(bpy, scene, 1)
    log(f"échauffement (noyaux, 1er rendu): {t_warm:.1f} s")

    r.resolution_x, r.resolution_y = bx, by
    out_dir = os.path.join(root, "bench_results")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    host = platform.node() or "machine"
    base = os.path.join(out_dir, f"bench_{host}_{stamp}")

    # --- série à froid: la scène est reconstruite à chaque rendu ---
    log("série à froid (scène reconstruite à chaque image)")
    cold = []
    for i, s in enumerate(SAMPLE_POINTS):
        last = i == len(SAMPLE_POINTS) - 1
        t = _render(bpy, scene, s, base if last else None)
        cold.append((s, t))
        log(f"  {s:>3} échantillons: {t:.1f} s")
    a_c, b_c, res_c = _fit(cold)

    # --- série persistante: Blender garde en mémoire ce qui ne change pas ---
    # Le nombre d'échantillons reste FIXE (changer le nombre d'échantillons dans une session persistante
    # n'est pas pris en compte de façon fiable). On mesure donc seulement le coût fixe par image, en
    # changeant d'image à chaque rendu comme dans l'animation (les particules bougent), et on réutilise
    # le coût par échantillon de la série à froid.
    warm_pts, a_w, b_w, res_w, t_load = [], None, None, None, None
    if warm:
        log("série persistante (use_persistent_data), 3 images consécutives à nombre d'échantillons fixe")
        r.use_persistent_data = True
        ns = SAMPLE_POINTS[0]
        t_load = _render(bpy, scene, ns)
        log(f"  chargement initial: {t_load:.1f} s")
        for i in range(3):
            scene.frame_set(2 + i)   # comme dans l'animation: l'image change, les particules bougent
            t = _render(bpy, scene, ns)
            warm_pts.append((ns, t))
            log(f"  image {i + 2}: {t:.1f} s")
        r.use_persistent_data = False
        b_w = b_c
        ts = sorted(p[1] for p in warm_pts)
        a_w = max(ts[len(ts) // 2] - b_c * ns, 0.0)
        res_w = ts[-1] - ts[0]

    for name, b in (("à froid", b_c), ("persistant", b_w)):
        if b is not None and b <= 0:
            log(f"ATTENTION: temps non croissant avec les échantillons ({name}), mesure peu fiable (machine chargée ?). Relancer.")

    lo_c, hi_c, mid_c = _estimate(a_c, max(b_c, 1e-6), k, fs)
    est = {"a_froid": {"bas": round(lo_c, 1), "milieu": round(mid_c, 1), "haut": round(hi_c, 1)}}
    mid_w = None
    if warm:
        lo_w, hi_w, mid_w = _estimate(a_w, max(b_w, 1e-6), k, fs)
        est["persistant"] = {"bas": round(lo_w, 1), "milieu": round(mid_w, 1), "haut": round(hi_w, 1)}

    reglages = {c: cfg.get(c) for c in REGLAGES_CLE}
    constantes = {"cam": BENCH_CAM, "rot": BENCH_ROT_DEG, "points": SAMPLE_POINTS, "final": final,
                  "blender": bpy.app.version_string}
    donnees = {"meta_json": _md5(os.path.join(data_dir, "meta.json")) if data_dir else None,
               "env_meta_json": _md5(os.path.join(data_dir, "env", "env_meta.json")) if data_dir else None}
    cle = hashlib.md5(json.dumps([reglages, constantes, donnees], sort_keys=True, default=str).encode()).hexdigest()[:10]

    res = {
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "machine": host,
        "systeme": f"{platform.system()} {platform.release()}",
        "processeur": platform.processor() or None,
        "coeurs": os.cpu_count(),
        "ram_go": _ram_gb(),
        "blender": bpy.app.version_string,
        "cycles_mode": mode,
        "peripheriques": devs,
        "scene": extra or {},
        "comparabilite": {"cle": cle, "reglages": reglages, "donnees": donnees},
        "benchmark": {"resolution": [bx, by], "echelle": scale, "echauffement_s": round(t_warm, 1),
                      "froid": {"points": [[int(p[0]), round(p[1], 2)] for p in cold], "fixe_s": round(a_c, 2),
                                "par_echantillon_s": round(b_c, 4), "ecart_max_s": round(res_c, 2)}},
        "final": {"resolution": [fx, fy], "echantillons": fs, "s_par_image": est},
        "hypotheses": ["particules finales et poussière absentes (marge x%.1f arbitraire)" % MARGE_MATIERE,
                       "échantillonnage adaptatif coupé (estimation prudente)",
                       "stéréo = 2 x mono (non mesuré)",
                       "mode persistant: coût fixe mesuré sur 3 images consécutives, seules les particules changent"],
        "durees": {},
    }
    if warm:
        res["benchmark"]["persistant"] = {"chargement_s": round(t_load, 1),
                                          "points": [[int(p[0]), round(p[1], 2)] for p in warm_pts],
                                          "fixe_s": round(a_w, 2), "par_echantillon_s": round(b_w, 4),
                                          "dispersion_s": round(res_w, 2)}
    for name, nf in FRAME_COUNTS.items():
        d = {"mono_froid_h": round(mid_c * nf / 3600, 2), "stereo_froid_h": round(2 * mid_c * nf / 3600, 2),
             "mono_froid_avec_marge_h": round(mid_c * MARGE_MATIERE * nf / 3600, 2)}
        if warm:
            d["mono_persistant_h"] = round(mid_w * nf / 3600, 2)
            d["mono_persistant_avec_marge_h"] = round(mid_w * MARGE_MATIERE * nf / 3600, 2)
        res["durees"][name] = d
    path = base + ".json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)

    log("=" * 68)
    log(f"RESULTAT {host}: {', '.join(devs) if devs else mode}   (clé de comparabilité {cle})")
    log(f"  à froid    : fixe {a_c:.0f} s + {b_c * 1000:.0f} ms par échantillon (écart de régression {res_c:.1f} s)")
    if warm:
        log(f"  persistant : fixe {a_w:.0f} s (3 images, dispersion {res_w:.1f} s), même coût par échantillon, chargement initial {t_load:.0f} s")
    if k > 1.001:
        log(f"  benchmark à {scale:g} de la résolution: estimations en fourchette")
    log(f"  image finale {fx}x{fy}, {fs} échantillons:")
    log(f"    à froid    {_fmt(lo_c)} à {_fmt(hi_c)} (milieu {_fmt(mid_c)})")
    if warm:
        log(f"    persistant {_fmt(lo_w)} à {_fmt(hi_w)} (milieu {_fmt(mid_w)})")
    for name, nf in FRAME_COUNTS.items():
        d = res["durees"][name]
        line = f"  {name:<20} à froid {d['mono_froid_h']:>6.1f} h (marge matière {d['mono_froid_avec_marge_h']:>6.1f} h)"
        if warm:
            line += f"   persistant {d['mono_persistant_h']:>6.1f} h (marge {d['mono_persistant_avec_marge_h']:>6.1f} h)"
        log(line)
    log(f"  fichier: {path}")
    log("  Comparer les machines: python blatten.py bench-compare")
    log("=" * 68)


def compare(results_dir, out=print):
    """Tableau des benchmarks enregistrés; signale ceux qui ne sont pas comparables au premier."""
    files = sorted(glob.glob(os.path.join(results_dir, "bench_*.json")))
    rows = []
    for f in files:
        try:
            rows.append(json.load(open(f, encoding="utf-8")))
        except Exception:
            out(f"illisible: {f}")
    if not rows:
        out("Aucun benchmark dans " + results_dir)
        return
    ref = rows[0].get("comparabilite", {})
    out(f"{'machine':<20} {'matériel':<34} {'froid s/img':>11} {'persist. s/img':>14} {'1200 img (h)':>13}  clé")
    for r in rows:
        c = r.get("comparabilite", {})
        hw = ", ".join(r.get("peripheriques") or []) or f"CPU {r.get('coeurs')} coeurs"
        hw = hw.replace("NVIDIA GeForce ", "").replace(" (CUDA)", "").replace(" (OPTIX)", "")
        est = r.get("final", {}).get("s_par_image", {})
        cold = est.get("a_froid", est.get("milieu"))
        cold = cold.get("milieu") if isinstance(cold, dict) else cold
        pers = (est.get("persistant") or {}).get("milieu")
        dur = (r.get("durees", {}).get("40 s (1200 images)") or {})
        h = dur.get("mono_persistant_h") or dur.get("mono_froid_h") or dur.get("mono_h")
        flag = "" if c.get("cle") == ref.get("cle") else "  <- NON COMPARABLE (réglages ou données différents)"
        out(f"{r.get('machine', '?'):<20} {hw[:34]:<34} {cold if cold is not None else '-':>11} "
            f"{pers if pers is not None else '-':>14} {h if h is not None else '-':>13}  {c.get('cle', '?')}{flag}")
    out("\nRéférence de comparaison: le premier fichier (clé " + str(ref.get("cle")) + ").")
    out("Les valeurs sont les secondes par image finale (milieu de fourchette), hors particules finales et poussière.")
