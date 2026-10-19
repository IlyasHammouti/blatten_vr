"""
export_qgis.py : prépare des fichiers à ouvrir dans QGIS (Lambert 95, EPSG:2056), tirés du cache de l'environnement.

Écrit dans <sortie> (par défaut <data>/QGIS):
  fond_ortho_2m.tif, fond_ortho_50cm.tif, fond_ortho_10cm.tif   orthophotos géoréférencées (les mêmes que la scène)
  fond_ombrage_2m.tif, fond_ombrage_50cm.tif                   relief ombré (les lits de rivière s'y voient mieux que sur l'ortho)
  zone_visible_2m.tif                                          1 là où le relief est visible depuis la caméra (inutile de vectoriser ailleurs)
  blatten_alea.gpkg  couches:
      emprise_cumulee_5s   surface atteinte par la matière depuis le début jusqu'à t (une entité tous les 5 s)
      bande_arrivee_5s     surface atteinte pendant les 5 s qui précèdent t (pour colorer l'avancée)
      camera               position de la caméra
      eau_osm              cours d'eau d'OpenStreetMap utilisés par la scène (lignes)
      eau_auto             eau détectée automatiquement (polygones, à corriger)
      eau_manuel           COUCHE VIDE à remplir à la main: l'eau qui sera utilisée par la scène (polygones)
Instants: secondes de simulation depuis le premier fichier (t = 0). Champ t_heure = 15:24:00 CEST du 28 mai 2025 + t.

Nécessite rasterio, geopandas, shapely, scipy, pillow (outil d'atelier, pas de Blender).
Utilisation: python export_qgis.py --env <cache>/env --out <dossier> [--pas 5]
"""
import argparse
import datetime as dt
import json
import os

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def log(*a):
    print("[qgis]", *a, flush=True)


def ecrire_tif(path, arr, x0, y1, step, jpeg=False, nodata=None, qualite=80):
    import rasterio
    from rasterio.transform import from_origin
    a = arr if arr.ndim == 3 else arr[None]
    a = np.moveaxis(a, -1, 0) if arr.ndim == 3 else a
    n, H, W = a.shape
    prof = dict(driver="GTiff", height=H, width=W, count=n, dtype="uint8", crs="EPSG:2056", transform=from_origin(x0, y1, step, step),
                tiled=True, blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER")
    if jpeg:
        prof.update(compress="jpeg", jpeg_quality=qualite)
        if n == 3:
            prof.update(photometric="ycbcr")
    else:
        prof.update(compress="deflate", predictor=2)
    if nodata is not None:
        prof["nodata"] = nodata
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(a)
        dst.build_overviews([2, 4, 8, 16], rasterio.enums.Resampling.average if not jpeg else rasterio.enums.Resampling.average)
    log(f"écrit {os.path.basename(path)}  {W} x {H}  {os.path.getsize(path) / 1e6:.1f} Mo")


def ombrage(dem, step, az=315.0, alt=40.0, z=1.5):
    d = np.asarray(dem, np.float32)
    bad = ~np.isfinite(d) | (d < -500)
    if bad.any():
        d = np.where(bad, np.nanmedian(d[~bad]), d)
    gy, gx = np.gradient(d, step)
    gx *= z
    gy *= z
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(gy, -gx)
    azr, altr = np.radians(360.0 - az + 90.0), np.radians(alt)
    h = np.sin(altr) * np.cos(slope) + np.cos(altr) * np.sin(slope) * np.cos(azr - aspect)
    return np.clip(h * 255.0, 0, 255).astype(np.uint8)


def polygones(masque, x0, y1, step, simplif):
    import shapely.geometry as sg
    from rasterio import features
    from rasterio.transform import from_origin
    tr = from_origin(x0, y1, step, step)
    out = [sg.shape(g) for g, v in features.shapes(masque.astype(np.uint8), mask=masque, transform=tr) if v == 1]
    if not out:
        return sg.MultiPolygon()
    from shapely.ops import unary_union
    u = unary_union(out)
    if simplif > 0:
        u = u.simplify(simplif, preserve_topology=True)
    return u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pas", type=float, default=5.0, help="intervalle des couches d'emprise (s)")
    a = ap.parse_args()
    import geopandas as gpd
    import shapely.geometry as sg
    from scipy import ndimage as ndi
    env, out = a.env, a.out
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(env, "env_meta.json")))

    # --- orthophotos
    o = meta["ortho"]
    ecrire_tif(os.path.join(out, "fond_ortho_2m.tif"), np.array(Image.open(os.path.join(env, o["file"])).convert("RGB")), o["x0"], o["y1"], o["step"], jpeg=True)
    for p in meta.get("ortho_patches", []):
        nom = "fond_ortho_" + ("50cm" if abs(p["step"] - 0.5) < 1e-6 else "10cm") + ".tif"
        ecrire_tif(os.path.join(out, nom), np.array(Image.open(os.path.join(env, p["file"])).convert("RGB")), p["x0"], p["y1"], p["step"], jpeg=True)

    # --- relief ombré
    d2 = meta["dem2"]
    ecrire_tif(os.path.join(out, "fond_ombrage_2m.tif"), ombrage(np.load(os.path.join(env, d2["file"]), mmap_mode="r"), d2["step"]), d2["x0"], d2["y1"], d2["step"], jpeg=True, qualite=72)
    if "dem05" in meta:
        d5 = meta["dem05"]
        ecrire_tif(os.path.join(out, "fond_ombrage_50cm.tif"), ombrage(np.load(os.path.join(env, d5["file"]), mmap_mode="r"), d5["step"]), d5["x0"], d5["y1"], d5["step"], jpeg=True, qualite=85)

    # --- zone visible
    vp = os.path.join(env, "visible", "visible_2m.npy")
    if os.path.exists(vp):
        v = np.load(vp, mmap_mode="r")
        ecrire_tif(os.path.join(out, "zone_visible_2m.tif"), np.asarray(v).astype(np.uint8), d2["x0"], d2["y1"], d2["step"], nodata=None)

    # --- emprises
    z = np.load(os.path.join(env, "alea_empreinte.npz"))
    occ, tarr, gx0, gy1, gs = z["occ"], z["tarr"], float(z["x0"]), float(z["y1"]), float(z["step"])
    t_ref = dt.datetime(2025, 5, 28, 15, 24, 0)
    tmax = float(np.nanmax(tarr))
    instants = list(np.arange(0.0, tmax + 1e-6, a.pas))
    if instants[-1] < tmax:
        instants.append(tmax)
    gpkg = os.path.join(out, "blatten_alea.gpkg")
    if os.path.exists(gpkg):
        os.remove(gpkg)
    cum, band = [], []
    prec = None
    for t in instants:
        m = occ & np.isfinite(tarr) & (tarr <= t + 1e-6)
        g = polygones(m, gx0, gy1, gs, 2.0)
        cum.append(dict(t_s=float(t), t_heure=(t_ref + dt.timedelta(seconds=float(t))).strftime("%H:%M:%S"), aire_km2=float(m.sum() * gs * gs / 1e6), geometry=g))
        mb = m if prec is None else (m & ~prec)
        band.append(dict(t_s=float(t), t_debut_s=float(t - a.pas) if prec is not None else 0.0, aire_km2=float(mb.sum() * gs * gs / 1e6), geometry=polygones(mb, gx0, gy1, gs, 2.0)))
        prec = m
    crs = "EPSG:2056"
    gpd.GeoDataFrame(cum, crs=crs).to_file(gpkg, layer="emprise_cumulee_5s", driver="GPKG")
    gpd.GeoDataFrame(band, crs=crs).to_file(gpkg, layer="bande_arrivee_5s", driver="GPKG")
    log(f"emprises: {len(instants)} instants de 0 à {tmax:.0f} s")

    # --- caméra
    vm = os.path.join(env, "visible", "visible_meta.json")
    if os.path.exists(vm):
        c = json.load(open(vm))
        gpd.GeoDataFrame([dict(nom="camera", altitude_m=float(c["z_sol"] + c["eye_above_ground"]), geometry=sg.Point(c["E"], c["N"]))], crs=crs).to_file(gpkg, layer="camera", driver="GPKG")

    # --- eau
    e = np.load(os.path.join(env, "eau.npz"))
    pts, deb, larg, typ, noms = e["pts"], e["debut"], e["larg"], e["type"], e["noms"]
    fin = list(deb[1:]) + [len(pts)]
    lignes = []
    for k, (s, f) in enumerate(zip(deb, fin)):
        if f - s >= 2:
            lignes.append(dict(nom=str(noms[k]) if len(noms) > k else "", largeur_m=float(larg[k]), type=int(typ[k]), geometry=sg.LineString(pts[s:f])))
    if lignes:
        gpd.GeoDataFrame(lignes, crs=crs).to_file(gpkg, layer="eau_osm", driver="GPKG")
    eau = []
    em = meta.get("eau_masque", {})
    for niv in ("grossier", "fin"):
        if niv in em:
            q = em[niv]
            m = np.array(Image.open(os.path.join(env, q["file"]))) > 127
            m = ndi.binary_opening(m, iterations=1)
            eau.append(dict(niveau=niv, aire_m2=float(m.sum() * q["step"] ** 2), geometry=polygones(m, q["x0"], q["y1"], q["step"], q["step"] * 0.5)))
    if eau:
        gpd.GeoDataFrame(eau, crs=crs).explode(index_parts=False).to_file(gpkg, layer="eau_auto", driver="GPKG")
    import pandas as pd
    import pyogrio
    vide = gpd.GeoDataFrame({"nom": pd.Series(dtype="object"), "remarque": pd.Series(dtype="object")}, geometry=gpd.GeoSeries([], crs=crs))
    pyogrio.write_dataframe(vide, gpkg, layer="eau_manuel", driver="GPKG", geometry_type="MultiPolygon")
    log("écrit", gpkg)


main()
