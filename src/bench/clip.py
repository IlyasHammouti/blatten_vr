"""Test grandeur nature : quelques secondes de l'événement, dans l'environnement, avec les vrais fichiers de Johan.

Lancé par `python blatten.py test-clip` (voir blatten.py). Trois choses sont produites dans render/test_clip/ :
  1. des images 3840x1920 au milieu du clip, avec plusieurs nombres d'échantillons (qualité / temps),
  2. un clip en demi-résolution (une image sur `every`), image par image, REPRENABLE si on l'interrompt,
  3. un JSON de temps dans bench_results/ (clip_<machine>_<date>.json).

Limites : caméra provisoire (camera.json non confirmé), particules en sphères, relief 2 m. C'est un test de temps et d'aspect,
pas une image finale.
"""
import datetime
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time


def prepare(cfg):
    """Fige les réglages avant la construction de la scène (appelé tôt dans main())."""
    cfg["preset"] = "final"
    cfg["stereo"] = False
    cfg["vue"] = None
    cfg["views"] = False
    cfg["render_frame"] = None
    cfg["render_anim"] = False
    cfg["save"] = False
    cfg["time_scale"] = 1.0
    n = int(round(float(cfg["clip_seconds"]) * cfg["fps"]))
    cfg["frames"] = (1, 1 + n)


def _stills(bpy, scene, out_dir, samples, log, bench):
    r = scene.render
    r.image_settings.file_format = "PNG"
    r.image_settings.color_depth = "8"
    kf = scene.frame_start + (scene.frame_end - scene.frame_start) // 2
    scene.frame_set(kf)
    res = []
    for s in samples:
        path = os.path.join(out_dir, f"image_{r.resolution_x}x{r.resolution_y}_{s:03d}spp")
        sec = bench._render(bpy, scene, s, write_path=path)
        log(f"image pleine résolution, {s} échantillons : {sec:.0f} s ({path}.png)")
        res.append(dict(samples=s, seconds=round(sec, 1), file=os.path.basename(path) + ".png"))
    return kf, res


def _video(bpy, scene, vdir, cfg, log, bench):
    r = scene.render
    r.image_settings.file_format = "JPEG"
    r.image_settings.quality = 92
    r.image_settings.color_depth = "8"
    every = max(1, int(cfg["clip_every"]))
    frames = list(range(scene.frame_start, scene.frame_end + 1, every))
    times, done = [], 0
    t_all = time.perf_counter()
    for i, f in enumerate(frames):
        path = os.path.join(vdir, f"f_{f:04d}")
        if os.path.exists(path + ".jpg"):
            done += 1
            continue
        scene.frame_set(f)
        sec = bench._render(bpy, scene, int(cfg["clip_quality"]), write_path=path)
        times.append(sec)
        left = len(frames) - i - 1
        log(f"clip : image {i + 1}/{len(frames)} (numéro {f}) : {sec:.0f} s, reste environ {bench._fmt(left * statistics.mean(times))}")
    if done:
        log(f"clip : {done} image(s) déjà rendue(s), conservée(s)")
    return frames, times, time.perf_counter() - t_all


def _assemble(bpy, frames, vdir, out_mp4, scene, cfg, log):
    files = [os.path.join(vdir, f"f_{f:04d}.jpg") for f in frames]
    files = [f for f in files if os.path.exists(f)]
    if not files:
        return None
    fps = max(1, int(round(cfg["fps"] / max(1, int(cfg["clip_every"])))))
    ff = shutil.which("ffmpeg")
    if ff:
        lst = os.path.join(vdir, "liste.txt")
        with open(lst, "w") as fh:
            for f in files:
                fh.write(f"file '{os.path.basename(f)}'\nduration {1 / fps}\n")
            fh.write(f"file '{os.path.basename(files[-1])}'\n")   # le dernier "duration" est ignoré sans cette ligne
        rc = subprocess.call([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                              "-vf", f"fps={fps},format=yuv420p", "-c:v", "libx264", "-crf", "20", out_mp4])
        if rc == 0 and os.path.exists(out_mp4):
            return out_mp4
    try:  # sans ffmpeg: montage par le séquenceur de Blender
        sc = bpy.data.scenes.new("assemblage")
        sc.render.fps = fps
        sc.render.resolution_x, sc.render.resolution_y = scene.render.resolution_x, scene.render.resolution_y
        sc.render.resolution_percentage = 100
        sc.view_settings.view_transform = "Standard"
        sed = sc.sequence_editor_create()
        strips = sed.strips if hasattr(sed, "strips") else sed.sequences
        st = strips.new_image("clip", files[0], channel=1, frame_start=1)
        for f in files[1:]:
            st.elements.append(os.path.basename(f))
        sc.frame_start, sc.frame_end = 1, len(files)
        sc.render.image_settings.file_format = "FFMPEG"
        for attr, val in (("format", "MPEG4"), ("codec", "H264"), ("constant_rate_factor", "HIGH")):
            try:
                setattr(sc.render.ffmpeg, attr, val)
            except Exception:
                pass
        sc.render.use_sequencer = True
        sc.render.filepath = out_mp4
        bpy.ops.render.render(animation=True, scene=sc.name)
        for cand in (out_mp4, out_mp4 + ".mp4"):
            if os.path.exists(cand):
                return cand
    except Exception as e:
        log("montage vidéo impossible:", e)
    log(f"Les images du clip sont dans {vdir}. Pour en faire une vidéo : installer ffmpeg (commande Windows : winget install ffmpeg), "
        "puis relancer la même commande avec --no-keys (les images déjà rendues sont conservées, seul le montage est refait).")
    return None


def run(scene, root, cfg, log, presets, extra=None, data_dir=None, bench=None):
    import bpy

    mode, devs = bench._devices(scene)
    gpu = mode == "GPU"
    final = presets["final"]
    fx, fy = final["res"]
    if cfg.get("clip_fullscale") and cfg["clip_fullscale"] != 1.0:   # machine faible ou test: images "pleines" réduites
        fx, fy = max(64, int(fx * cfg["clip_fullscale"]) // 2 * 2), max(32, int(fy * cfg["clip_fullscale"]) // 2 * 2)
    cy, r = scene.cycles, scene.render
    cy.use_adaptive_sampling = False
    r.use_persistent_data = bool(cfg.get("persistent"))
    out_dir = os.path.join(cfg.get("out") or os.path.join(root, "render"), "test_clip")
    vdir = os.path.join(out_dir, "clip")
    os.makedirs(vdir, exist_ok=True)
    nfr = scene.frame_end - scene.frame_start + 1
    log(f"TEST-CLIP : {'GPU' if gpu else 'CPU'} {devs or platform.processor()}, {nfr} images à {cfg['fps']} i/s, "
        f"images fixes {cfg['clip_samples']} échantillons, clip {cfg['clip_scale']:g} x résolution à {cfg['clip_quality']} échantillons")

    scene.frame_set(scene.frame_start)
    r.resolution_x, r.resolution_y, r.resolution_percentage = 64, 32, 100
    t_warm = bench._render(bpy, scene, 1)
    log(f"échauffement : {t_warm:.1f} s")

    result = dict(
        machine=platform.node(), date=datetime.datetime.now().isoformat(timespec="seconds"), blender=bpy.app.version_string,
        device=mode, devices=devs, ram_gb=bench._ram_gb(), clip_seconds=cfg["clip_seconds"], fps=cfg["fps"],
        images=nfr, resolution_finale=[fx, fy], camera=list(cfg["cam"]) if cfg.get("cam") else None,
        camera_confirmee=bool(cfg.get("camera_confirmed")), reglages={k: cfg.get(k) for k in bench.REGLAGES_CLE},
        persistent=bool(cfg.get("persistent")), extra=extra or {},
    )

    r.resolution_x, r.resolution_y = fx, fy
    if not cfg.get("clip_no_keys"):
        kf, keys = _stills(bpy, scene, out_dir, cfg["clip_samples"], log, bench)
        result["images_fixes"] = dict(numero_image=kf, mesures=keys)

    if not cfg.get("clip_no_video"):
        vx = max(64, int(fx * cfg["clip_scale"]) // 2 * 2)
        vy = max(32, int(fy * cfg["clip_scale"]) // 2 * 2)
        r.resolution_x, r.resolution_y = vx, vy
        frames, times, total = _video(bpy, scene, vdir, cfg, log, bench)
        mp4 = _assemble(bpy, frames, vdir, os.path.join(out_dir, "clip_apercu.mp4"), scene, cfg, log)
        v = dict(resolution=[vx, vy], samples=cfg["clip_quality"], une_image_sur=cfg["clip_every"],
                 images_rendues=len(times), total_s=round(total, 1), video=mp4)
        if times:
            v.update(moyenne_s=round(statistics.mean(times), 1), mediane_s=round(statistics.median(times), 1),
                     min_s=round(min(times), 1), max_s=round(max(times), 1), par_image_s=[round(t, 1) for t in times])
        if mp4:
            log("vidéo d'aperçu :", mp4)
            try:   # métadonnées 360 : sans elles, YouTube et VLC montrent une vidéo plate
                sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scene"))
                import inject_360
                m360 = mp4[:-4] + "_360.mp4"
                inject_360.inject(mp4, m360)
                v["video_360"] = m360
                log("vidéo avec métadonnées 360 (à ouvrir dans VLC ou à envoyer sur YouTube) :", m360)
            except Exception as e:
                log("métadonnées 360 non ajoutées:", e)
        result["clip"] = v

    # Estimation du rendu final à partir des images fixes (même caméra, même matière, mêmes réglages)
    est = {}
    reduit = bool(cfg.get("clip_fullscale") and cfg["clip_fullscale"] != 1.0)
    for m in (result.get("images_fixes") or {}).get("mesures", []):
        est[str(m["samples"])] = {str(n): round(m["seconds"] * n / 3600, 1) for n in (1200, 1800)}
    if est and not reduit:
        result["estimation_heures_toutes_images_un_pc"] = est
    out_json = os.path.join(root, "bench_results", f"clip_{platform.node() or 'machine'}_{datetime.datetime.now():%Y%m%d-%H%M}.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    log("=" * 60)
    log("RESULTATS (JSON :", out_json + ")")
    for m in (result.get("images_fixes") or {}).get("mesures", []):
        if reduit:
            log(f"  {fx}x{fy}, {m['samples']:>3} échantillons : {m['seconds']:>6.0f} s/image (résolution réduite, pas d'estimation)")
            continue
        e = est[str(m["samples"])]
        log(f"  {fx}x{fy}, {m['samples']:>3} échantillons : {m['seconds']:>6.0f} s/image   "
            f"-> 1200 images : {e['1200']} h, 1800 images : {e['1800']} h (un PC)")
    if "moyenne_s" in result.get("clip", {}):
        c = result["clip"]
        log(f"  clip {c['resolution'][0]}x{c['resolution'][1]}, {c['samples']} échantillons : {c['moyenne_s']} s/image en moyenne")
    log("Images et clip : ", out_dir)
    log("A regarder : l'aspect des particules (sphères), la netteté à 24/48/96/192, la fluidité du clip.")
