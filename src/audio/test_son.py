"""
test_son.py : petite vidéo 360 de test pour vérifier que le son tourne avec la tête (audio spatial AmbiX), sans rendu Blender.

CONTENU (environ 25 s, 1920x960, 5 images/s, quelques Mo)
  0 à 8 s    bruit de calibrage qui vient successivement de : AVANT, GAUCHE, ARRIÈRE, DROITE (1,5 s chacun, 0,5 s de silence)
  8 à 10 s   silence
  10 s à fin extrait réel du film (son_ambix.wav) : par défaut 15 s à partir de 45 s, en plein événement
  Image : repère équirectangulaire fixe (AVANT au centre, GAUCHE à gauche du centre, DROITE à droite, ARRIÈRE aux bords).

    python test_son.py --ambix D:/Blatten_render/son/son_ambix.wav --out dossier [--debut 45] [--duree 15]
Les métadonnées sphériques et audio spatial (SA3D) sont ajoutées par inject_360.py. Bibliothèques: numpy, Pillow (installé si absent).
"""
import argparse
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(os.path.dirname(HERE), "scene")
SR = 48000


def log(*a):
    print("[test-son]", *a, flush=True)


def ffmpeg_exe():
    f = shutil.which("ffmpeg")
    if f:
        return f
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg introuvable: installer ffmpeg ou  pip install imageio-ffmpeg")


def lire_ambix(path, debut, duree):
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 4:
            sys.exit(f"{path}: {w.getnchannels()} canaux au lieu de 4 (AmbiX attendu)")
        sr, sw = w.getframerate(), w.getsampwidth()
        w.setpos(min(int(debut * sr), max(0, w.getnframes() - 1)))
        raw = w.readframes(int(duree * sr))
    if sr != SR:
        sys.exit(f"{path}: {sr} Hz au lieu de {SR}")
    if sw == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif sw == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        x = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)) << 8 >> 8).astype(np.float32) / 8388608.0
    else:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    return x.reshape(-1, 4)


def bruit(n, rng):
    """Bruit large bande 300 Hz - 4 kHz, enveloppe douce."""
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    X[(f < 300) | (f > 4000)] = 0
    x = np.fft.irfft(X, n)
    x /= np.abs(x).max()
    env = np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (0.05 * SR))
    return (x * env * 0.5).astype(np.float32)


def calibrage():
    """AmbiX (n,4) W Y Z X, SN3D. Azimut positif vers la gauche (convention de son.py)."""
    rng = np.random.default_rng(1)
    out = np.zeros((10 * SR, 4), np.float32)
    for k, az_deg in enumerate((0, 90, 180, -90)):        # avant, gauche, arrière, droite
        a = np.radians(az_deg)
        s = bruit(int(1.5 * SR), rng)
        i0 = k * 2 * SR
        out[i0:i0 + len(s)] = np.stack([s, s * np.sin(a), s * 0, s * np.cos(a)], 1)
    return out


def image_repere(path, w=1920, h=960):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        subprocess.call([sys.executable, "-m", "pip", "install", "-q", "pillow"])
        from PIL import Image, ImageDraw, ImageFont
    y = np.linspace(0, 1, h)[:, None, None]
    ciel, sol = np.array([70, 110, 160]), np.array([70, 80, 60])
    img = np.where(y < 0.5, ciel + (np.array([170, 200, 230]) - ciel) * (y / 0.5), np.array([100, 110, 90]) + (sol - np.array([100, 110, 90])) * ((y - 0.5) / 0.5))
    img = np.broadcast_to(img, (h, w, 3)).astype(np.uint8).copy()
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)
    for az in range(-180, 181, 30):                        # méridiens tous les 30 degrés (centre = avant, gauche = positif)
        x = int(w / 2 - az / 360 * w)
        d.line([(x, 0), (x, h)], fill=(255, 255, 255), width=3 if az % 90 == 0 else 1)
    d.line([(0, h // 2), (w, h // 2)], fill=(255, 255, 255), width=3)
    try:
        fnt = ImageFont.truetype("arial.ttf", 64)
    except Exception:
        try:
            fnt = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
        except Exception:
            fnt = ImageFont.load_default()
    def txt(x, t):
        bb = d.textbbox((0, 0), t, font=fnt)
        d.text((x - (bb[2] - bb[0]) / 2, h / 2 - (bb[3] - bb[1]) / 2 - 140), t, font=fnt, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    txt(w / 2, "AVANT")
    txt(w / 4, "GAUCHE")
    txt(3 * w / 4, "DROITE")
    txt(w * 0.09, "ARRIÈRE")
    txt(w * 0.91, "ARRIÈRE")
    im.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="test_son")
    ap.add_argument("--ambix", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--debut", type=float, default=45.0)
    ap.add_argument("--duree", type=float, default=15.0)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    ev = lire_ambix(a.ambix, a.debut, a.duree)
    if len(ev) < SR:
        sys.exit(f"extrait trop court ({len(ev) / SR:.1f} s): {a.ambix} commence-t-il avant {a.debut} s ?")
    n = min(len(ev), int(0.3 * SR))
    ev[:n] *= np.linspace(0, 1, n)[:, None]
    ev[-n:] *= np.linspace(1, 0, n)[:, None]
    x = np.concatenate([calibrage(), ev])
    wav = os.path.join(a.out, "test_son_ambix.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(4); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    png = os.path.join(a.out, "repere.png")
    image_repere(png)
    duree = len(x) / SR
    mp4 = os.path.join(a.out, "test_son.mp4")
    cmd = [ffmpeg_exe(), "-y", "-v", "error", "-loop", "1", "-framerate", "5", "-t", f"{duree:.2f}", "-i", png,
           "-channel_layout", "4.0", "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "512k", "-shortest", "-movflags", "+faststart", mp4]
    if subprocess.call(cmd) != 0:
        sys.exit("ffmpeg a échoué")
    fin = os.path.join(a.out, "test_son_360.mp4")
    if subprocess.call([sys.executable, os.path.join(SCENE, "inject_360.py"), mp4, fin]) != 0:
        sys.exit("injection des métadonnées échouée")
    log(f"{duree:.1f} s -> {fin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
