"""
montage_film.py : vidéo finale à partir des images rendues, sans logiciel de montage.

    images du film (frame_0001...) -> fondu au noir sur la dernière seconde -> outro (image fixe, fondus d'entrée et de
    sortie) -> son (stéréo pour la bande, AmbiX 4 canaux pour le 360) -> MP4 H.264
Pour le 360, les métadonnées sphériques sont ajoutées ensuite (inject_360.py).

    python montage_film.py --dir D:/Blatten_render/film_bande/20261101_0200 --format bande \
        --outro render/outro/outro_bande.png --son D:/Blatten_render/son/son_stereo.wav
ffmpeg installé, ou paquet Python imageio-ffmpeg.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def log(*a):
    print("[montage]", *a, flush=True)


def ffmpeg_exe():
    f = shutil.which("ffmpeg")
    if f:
        return f
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg introuvable: installer ffmpeg ou  pip install imageio-ffmpeg")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="montage_film")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--format", choices=("bande", "360"), default="bande")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--fondu", type=float, default=1.0, help="s de fondu au noir à la fin du film")
    ap.add_argument("--outro")
    ap.add_argument("--outro-duree", type=float, default=8.0)
    ap.add_argument("--son")
    ap.add_argument("--out")
    ap.add_argument("--crf", type=int, default=16)
    a = ap.parse_args(argv)
    files = sorted(glob.glob(os.path.join(a.dir, "frame_*.png")) + glob.glob(os.path.join(a.dir, "frame_*.jpg")))
    files = [f for f in files if os.path.getsize(f) > 0]
    if not files:
        sys.exit(f"Aucune image dans {a.dir}")
    ext = os.path.splitext(files[0])[1]
    nums = sorted(int(re.search(r"frame_(\d+)", f).group(1)) for f in files if f.endswith(ext))
    n = nums[-1] - nums[0] + 1
    if len(nums) != n:
        log(f"!! {n - len(nums)} images manquantes entre {nums[0]} et {nums[-1]}: la vidéo s'arrêtera à la première manquante")
    duree = n / a.fps
    out = a.out or os.path.join(a.dir, f"film_{a.format}.mp4")
    ff = ffmpeg_exe()
    cmd = [ff, "-y", "-v", "error", "-stats", "-framerate", f"{a.fps:g}", "-start_number", str(nums[0]),
           "-i", os.path.join(a.dir, f"frame_%04d{ext}")]
    if a.fondu > 0:
        filt = f"[0:v]format=yuv420p,fade=t=out:st={max(0.0, duree - a.fondu):.3f}:d={a.fondu:g}[film]"
    else:              # extrait au milieu du film: pas de fondu au noir
        filt = "[0:v]format=yuv420p[film]"
    vids = "[film]"
    k = 1
    if a.outro and os.path.exists(a.outro):
        cmd += ["-loop", "1", "-framerate", f"{a.fps:g}", "-t", f"{a.outro_duree:g}", "-i", a.outro]
        filt += (f";[{k}:v]scale=iw:ih,format=yuv420p,fade=t=in:st=0:d=1,"
                 f"fade=t=out:st={max(0.0, a.outro_duree - 1.0):g}:d=1[outro];[film][outro]concat=n=2:v=1:a=0[v]")
        vids = "[v]"
        k += 1
    else:
        filt += ";[film]null[v]"
        vids = "[v]"
    sortie = ["-map", vids]
    if a.son and os.path.exists(a.son):
        decal = (nums[0] - 1) / a.fps     # film partiel (ex. dernières secondes): le son démarre à l'instant de la première image
        cmd += (["-ss", f"{decal:.3f}"] if decal > 0 else []) + ["-i", a.son]
        sortie += ["-map", f"{k}:a", "-c:a", "aac", "-b:a", "320k" if a.format == "bande" else "512k", "-shortest"]
    cmd += ["-filter_complex", filt] + sortie
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    log(f"{n} images ({duree:.1f} s) + outro {a.outro_duree if a.outro else 0:g} s, son: {os.path.basename(a.son) if a.son else 'aucun'}")
    rc = subprocess.call(cmd)
    if rc != 0:
        sys.exit(f"ffmpeg a échoué ({rc})")
    if a.format == "360":
        fin = out.replace(".mp4", "_360.mp4")
        subprocess.call([sys.executable, os.path.join(HERE, "inject_360.py"), out, fin])
        log("vidéo 360:", fin)
    log("vidéo:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
