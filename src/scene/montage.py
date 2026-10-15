"""
montage.py : assemble les images PNG d'un rendu (frame_XXXX.png) en une vidéo MP4, puis ajoute les métadonnées 360.

ffmpeg s'il est installé (rapide), sinon le séquenceur de Blender. Lancé par blatten.py (brouillon, montage).
    blender -b --python montage.py -- --dir render/brouillon --fps 15 --out render/brouillon/brouillon.mp4
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def log(*a):
    print("[montage]", *a, flush=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(prog="montage")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    files = sorted(f for f in glob.glob(os.path.join(a.dir, "frame_*.png")) if os.path.getsize(f) > 0)
    if not files:
        sys.exit(f"Aucune image dans {a.dir}")
    log(f"{len(files)} images, {a.fps:g} images/s, {len(files) / a.fps:.1f} s")
    out = os.path.abspath(a.out)
    ok = False
    ff = shutil.which("ffmpeg")
    if ff:
        lst = os.path.join(a.dir, "liste.txt")
        with open(lst, "w") as fh:
            for f in files:
                fh.write(f"file '{os.path.basename(f)}'\nduration {1 / a.fps}\n")
            fh.write(f"file '{os.path.basename(files[-1])}'\n")
        rc = subprocess.call([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                              "-vf", f"fps={a.fps:g},format=yuv420p", "-c:v", "libx264", "-crf", "18", out])
        ok = rc == 0 and os.path.exists(out)
    if not ok:
        import bpy
        sc = bpy.data.scenes.new("montage")
        sc.render.fps = int(round(a.fps))
        w, h = bpy.data.images.load(files[0]).size
        sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w, h, 100
        sc.view_settings.view_transform = "Standard"
        sed = sc.sequence_editor_create()
        strips = sed.strips if hasattr(sed, "strips") else sed.sequences
        st = strips.new_image("film", files[0], channel=1, frame_start=1)
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
        sc.render.filepath = out
        bpy.ops.render.render(animation=True, scene=sc.name)
        for cand in (out, out + ".mp4"):
            if os.path.exists(cand):
                if cand != out:
                    os.replace(cand, out)
                ok = True
                break
    if not ok:
        sys.exit("Montage impossible (installer ffmpeg: winget install ffmpeg, puis relancer).")
    import importlib.util
    spec = importlib.util.spec_from_file_location("inject_360", os.path.join(HERE, "inject_360.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out360 = out[:-4] + "_360.mp4"
    mod.inject(out, out360)
    log("vidéo:", out)
    log("vidéo 360 (pour YouTube, VLC):", out360)


main()
