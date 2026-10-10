"""
visible.py : zone du relief VISIBLE depuis la caméra (ligne de vue), sans toucher aux données existantes.

Pour chaque direction autour de la caméra, on suit le relief vers l'extérieur et on note les cellules
qui dépassent tout ce qui les précède (angle d'élévation croissant): ce sont celles qu'on voit. Le relief lu est
le plus fin disponible à chaque distance (0,5 m près de la caméra, puis 2 m, puis 8 m), comme dans le maillage de la scène.
Pas de limite de distance autre que l'emprise des données (relief 2 m puis 8 m).

Écrit, dans <cache>/env/visible/ (les fichiers du dossier env/ ne sont JAMAIS modifiés):
  visible_05m.npy (si le relief 0,5 m existe), visible_2m.npy, visible_8m.npy   masques booléens sur la grille de chaque relief, avec marge
  dem_2m_visible.npy               copie du relief 2 m, NaN là où c'est caché (la "version visible seulement")
  visible_meta.json                caméra utilisée, hauteur d'yeux, marge, pourcentages
  visible_apercu.png               vue d'ensemble: relief ombré, zone cachée assombrie, caméra en rouge

Utilisation (via blatten.py, qui lance Blender pour disposer de numpy):
  python blatten.py visible                       caméra de camera.json, Z tel quel
  python blatten.py visible --eye 1.7             Z recalculé: sol + 1,7 m (hauteur d'homme)
  python blatten.py visible --eye 1.7 --ecrire-camera   idem, et écrit ce Z dans camera.json
  python blatten.py visible --marge 20            marge autour de la zone visible (m, défaut 12)

La scène n'utilise ces masques que si on l'y invite (option --cull), pour pouvoir comparer et revenir.
Limite connue: la végétation et les bâtiments ne sont pas des obstacles ici (c'est le relief nu), donc la
zone visible est un peu SURESTIMÉE: on ne retire jamais ce qui pourrait se voir.
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
ROOT = os.environ.get("BLATTEN_ROOT") or os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, ".pylibs"))
try:
    import imagecodecs
except ImportError:
    imagecodecs = None


def log(*a):
    print("[visible]", *a, flush=True)


def _dilate(mask, r):
    """Dilatation carrée de r cellules (décalages successifs, sans bibliothèque externe)."""
    out = mask.copy()
    for _ in range(r):
        o = out.copy()
        o[1:] |= out[:-1]
        o[:-1] |= out[1:]
        out = o
        o = out.copy()
        o[:, 1:] |= out[:, :-1]
        o[:, :-1] |= out[:, 1:]
        out = o
    return out


def _extent(L):
    H, W = L["D"].shape
    return L["x0"], L["x0"] + W * L["step"], L["y1"] - H * L["step"], L["y1"]


def block_any(v, f):
    h, w = v.shape[0] // f * f, v.shape[1] // f * f
    return v[:h, :w].reshape(h // f, f, w // f, f).any(axis=(1, 3))


def viewshed_multi(levels, Ec, Nc, zeye, rmax=None):
    """Visibilité depuis (Ec, Nc, zeye) sur plusieurs relief emboîtés (le plus fin d'abord).
    Chaque point d'un rayon est lu dans le relief le plus fin qui le couvre: l'avant-plan est donc vu à la résolution du
    maillage réellement construit, et le lointain en plus grossier. Renvoie un masque booléen par niveau (sur sa propre grille)."""
    exts = [_extent(L) for L in levels]
    rad = []
    for (xa, xb, ya, yb) in exts:
        R = math.hypot(max(abs(xa - Ec), abs(xb - Ec)), max(abs(ya - Nc), abs(yb - Nc)))
        rad.append(min(R, rmax) if rmax else R)
    rs_l, id_l = [], []
    for k, L in enumerate(levels):
        n = int(rad[k] / L["step"])
        rs_l.append(np.arange(1, n + 1) * L["step"])
        id_l.append(np.full(n, k))
    rs = np.concatenate(rs_l)
    lid = np.concatenate(id_l)
    order = np.argsort(rs, kind="stable")
    rs, lid = rs[order], lid[order]
    cols = [np.nonzero(lid == k)[0] for k in range(len(levels))]
    na = int(max(math.ceil(2 * math.pi * rad[k] / (0.8 * levels[k]["step"])) for k in range(len(levels))))
    vis = [np.zeros(L["D"].shape, bool) for L in levels]
    B = 48
    for k0 in range(0, na, B):
        a = 2 * np.pi * np.arange(k0, min(k0 + B, na)) / na
        sa, ca = np.sin(a)[:, None], np.cos(a)[:, None]
        E = Ec + sa * rs[None, :]
        N = Nc + ca * rs[None, :]
        ang = np.full(E.shape, -np.inf)
        info = []
        for k, L in enumerate(levels):
            c = cols[k]
            if not len(c):
                info.append(None)
                continue
            e, nn = E[:, c], N[:, c]
            xa, xb, ya, yb = exts[k]
            ok = (e >= xa) & (e < xb) & (nn > ya) & (nn <= yb)
            for j in range(k):                      # pas dans un relief plus fin
                fa, fb, ga, gb = exts[j]
                ok &= ~((e >= fa) & (e < fb) & (nn > ga) & (nn <= gb))
            ii = np.clip(np.floor((e - L["x0"]) / L["step"]).astype(np.int64), 0, L["D"].shape[1] - 1)
            jj = np.clip(np.floor((L["y1"] - nn) / L["step"]).astype(np.int64), 0, L["D"].shape[0] - 1)
            z = L["D"][jj, ii].astype(np.float64)
            ang[:, c] = np.where(ok, (z - zeye) / rs[None, c], -np.inf)
            info.append((c, ok, ii, jj))
        hm = np.maximum.accumulate(ang, axis=1)
        prev = np.concatenate([np.full((ang.shape[0], 1), -np.inf), hm[:, :-1]], axis=1)
        seen = (ang >= prev) & np.isfinite(ang)
        for k, inf in enumerate(info):
            if inf is None:
                continue
            c, ok, ii, jj = inf
            v = seen[:, c] & ok
            vis[k][jj[v], ii[v]] = True
    L0 = levels[0]
    ci, cj = int((Ec - L0["x0"]) / L0["step"]), int((L0["y1"] - Nc) / L0["step"])
    r = max(2, int(round(3.0 / L0["step"])))
    if 0 <= ci < L0["D"].shape[1] and 0 <= cj < L0["D"].shape[0]:   # autour de la caméra
        vis[0][max(cj - r, 0):cj + r + 1, max(ci - r, 0):ci + r + 1] = True
    return vis


def _ground(level, E, N):
    arr, x0, y1, step = level
    u = np.clip((E - x0) / step - 0.5, 0, arr.shape[1] - 1.001)
    v = np.clip((y1 - N) / step - 0.5, 0, arr.shape[0] - 1.001)
    i, j = int(v), int(u)
    fy, fx = v - i, u - j
    return float((1 - fy) * ((1 - fx) * arr[i, j] + fx * arr[i, j + 1]) + fy * ((1 - fx) * arr[i + 1, j] + fx * arr[i + 1, j + 1]))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(prog="visible")
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--swisstopo")  # ignoré (transmis par blatten.py)
    ap.add_argument("--camera", type=float, nargs=3, metavar=("X", "Y", "Z"), help="caméra (repère Blender), sinon camera.json")
    ap.add_argument("--eye", type=float, help="hauteur d'yeux au-dessus du sol (m): remplace le Z de la caméra")
    ap.add_argument("--ecrire-camera", action="store_true", help="avec --eye: écrit le Z obtenu dans camera.json")
    ap.add_argument("--marge", type=float, default=12.0, help="marge (m) ajoutée autour de la zone visible")
    ap.add_argument("--rmax", type=float, help="distance maximale (m); défaut: aucune, jusqu'au bord des données")
    a = ap.parse_args(argv)

    env = os.path.join(a.data, "env")
    m = json.load(open(os.path.join(env, "env_meta.json")))
    cam_path = os.path.join(ROOT, "camera.json")
    camj = json.load(open(cam_path)) if os.path.exists(cam_path) else {}
    cam = list(a.camera) if a.camera else camj.get("cam")
    if not cam:
        sys.exit("Aucune caméra: renseigner camera.json ou --camera X Y Z")
    flip, dz = m["flip"], m.get("dz", 0.0)
    dz = dz if abs(dz) < 30 else 0.0
    Ec, Nc = m["scene_E0"] + cam[0], m["scene_N0"] + flip * cam[1]
    d2, d8 = m["dem2"], m["dem8"]
    D2 = np.load(os.path.join(env, d2["file"]))
    D8 = np.load(os.path.join(env, d8["file"]))
    best = (D2, d2["x0"], d2["y1"], d2["step"])
    if m.get("dem05"):
        d5 = m["dem05"]
        best = (np.load(os.path.join(env, d5["file"]), mmap_mode="r"), d5["x0"], d5["y1"], d5["step"])
    ground = _ground(best, Ec, Nc)
    log(f"caméra LV95 E {Ec:.2f} N {Nc:.2f}, sol à {ground + dz:.2f} m (relief {best[3]:g} m), Z actuel {cam[2]:.2f} m "
        f"= {cam[2] - ground - dz:+.2f} m au-dessus du sol")
    if a.eye is not None:
        cam[2] = round(ground + dz + a.eye, 2)
        log(f"hauteur d'yeux {a.eye:g} m: Z = {cam[2]:.2f} m")
        if a.ecrire_camera:
            camj["cam"] = cam
            camj["z_sol_plus"] = a.eye
            with open(cam_path, "w", encoding="utf-8") as fh:
                json.dump(camj, fh, indent=2, ensure_ascii=False)
            log("Z écrit dans camera.json")
    zeye = cam[2] - dz

    t0 = time.time()
    out = os.path.join(env, "visible")
    os.makedirs(out, exist_ok=True)
    levels = []
    if m.get("dem05"):
        d5 = m["dem05"]
        levels.append(dict(name="05m", D=np.asarray(best[0]), x0=d5["x0"], y1=d5["y1"], step=d5["step"]))
    levels.append(dict(name="2m", D=D2, x0=d2["x0"], y1=d2["y1"], step=d2["step"]))
    levels.append(dict(name="8m", D=D8, x0=d8["x0"], y1=d8["y1"], step=d8["step"]))
    log("niveaux: " + ", ".join(f"{L['name']} ({L['D'].shape[1]}x{L['D'].shape[0]})" for L in levels))
    vs = viewshed_multi(levels, Ec, Nc, zeye, a.rmax)
    for L, v in zip(levels, vs):
        log(f"  {L['name']}: {v.mean() * 100:.1f} % de sa grille visible ({time.time() - t0:.0f} s)")

    def fill_from(fine, ffine, coarse, cc):
        """Dans la zone couverte par le niveau fin, le masque grossier est le 'ou' des cellules fines qu'il contient."""
        f = int(round(cc["step"] / ffine["step"]))
        pooled = block_any(fine, f)
        oi = (ffine["x0"] - cc["x0"]) / cc["step"]
        oj = (cc["y1"] - ffine["y1"]) / cc["step"]
        if abs(oi - round(oi)) > 1e-6 or abs(oj - round(oj)) > 1e-6:
            log("  grilles non alignées: masque grossier non complété")
            return coarse
        oi, oj = int(round(oi)), int(round(oj))
        h, w = pooled.shape
        if oi < 0 or oj < 0 or oj + h > coarse.shape[0] or oi + w > coarse.shape[1]:
            h = min(h, coarse.shape[0] - oj)
            w = min(w, coarse.shape[1] - oi)
            pooled = pooled[:h, :w]
        coarse = coarse.copy()
        coarse[oj:oj + h, oi:oi + w] |= pooled
        return coarse

    for k in range(len(levels) - 1, 0, -1):          # du grossier au fin: le fin remplit le grossier
        vs[k] = fill_from(vs[k - 1], levels[k - 1], vs[k], levels[k])
    marks = {}
    for L, v in zip(levels, vs):
        v = _dilate(v, max(2, int(round(a.marge / L["step"]))))
        marks[L["name"]] = v
        np.save(os.path.join(out, f"visible_{L['name']}.npy"), v)
    v2, v8 = marks["2m"], marks["8m"]
    np.save(os.path.join(out, "dem_2m_visible.npy"), np.where(v2, D2, np.nan).astype(np.float32))

    meta = dict(camera=cam, E=Ec, N=Nc, z_sol=ground + dz, eye_above_ground=zeye + dz - (ground + dz), marge_m=a.marge,
                rmax_m=a.rmax, niveaux=[L["name"] for L in levels], pct={k: float(v.mean() * 100) for k, v in marks.items()},
                pct_2m=float(v2.mean() * 100), pct_8m=float(v8.mean() * 100),
                created=time.strftime("%Y-%m-%d %H:%M"))
    json.dump(meta, open(os.path.join(out, "visible_meta.json"), "w"), indent=2)
    log("avec marge " + f"{a.marge:g} m: " + ", ".join(f"{k} {v:.1f} %" for k, v in meta["pct"].items()))

    if imagecodecs is not None:  # aperçu: relief ombré réduit, zone cachée assombrie
        f = max(1, D2.shape[0] // 1100)
        z = D2[::f, ::f].astype(np.float32)
        gy, gx = np.gradient(z, d2["step"] * f)
        sh = np.clip(0.55 + 0.9 * (gx * 0.6 - gy * 0.8) / np.sqrt(1 + gx * gx + gy * gy), 0, 1)
        rgb = np.stack([sh * 0.85, sh * 0.9, sh * 0.8], -1)
        vm = v2[::f, ::f]
        rgb = np.where(vm[..., None], rgb, rgb * 0.35 + np.array([0.0, 0.03, 0.12]))
        ci, cj = int((Ec - d2["x0"]) / d2["step"] / f), int((d2["y1"] - Nc) / d2["step"] / f)
        rgb[max(cj - 4, 0):cj + 5, max(ci - 4, 0):ci + 5] = (1, 0, 0)
        imgp = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        with open(os.path.join(out, "visible_apercu.png"), "wb") as fh:
            fh.write(imagecodecs.png_encode(imgp))
        log("aperçu: visible_apercu.png")
    log(f"terminé en {time.time() - t0:.0f} s, fichiers dans {out}")


if __name__ == "__main__":
    main()
