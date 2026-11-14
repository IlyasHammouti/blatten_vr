"""
projet_oiseaux_qgis.py : projet QGIS prêt à ouvrir pour placer les oiseaux (python blatten.py qgis-oiseaux).

Écrit dans <sortie> (par défaut render/qgis_oiseaux), en LV95 (EPSG:2056):
  oiseaux.qgs                  le projet (double-clic)
  fond_ortho_2m.jpg/.jgw       orthophoto de la scène (copie + fichier monde), fond_ortho_50cm.jpg/.jgw si présente
  emprise_5s.geojson           emprise de la masse toutes les 5 s (polygones, champ t en s de simulation)
  camera.geojson               position de la caméra
  oiseaux.gpkg                 DEUX COUCHES VIDES à remplir: oiseaux_depart (points: groupe, t_envol, nombre)
                               et oiseaux_direction (lignes: du départ vers où ils vont, champ groupe)
Sans geopandas ni rasterio (numpy, pillow, matplotlib, sqlite3).
"""
import argparse
import json
import os
import shutil
import sqlite3
import struct

import numpy as np

CRS_WKT = ('PROJCS["CH1903+ / LV95",GEOGCS["CH1903+",DATUM["CH1903+",SPHEROID["Bessel 1841",6377397.155,299.1528128]],'
           'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Hotine_Oblique_Mercator_Azimuth_Center"],'
           'PARAMETER["latitude_of_center",46.9524055555556],PARAMETER["longitude_of_center",7.43958333333333],'
           'PARAMETER["azimuth",90],PARAMETER["rectified_grid_angle",90],PARAMETER["scale_factor",1],'
           'PARAMETER["false_easting",2600000],PARAMETER["false_northing",1200000],UNIT["metre",1],AUTHORITY["EPSG","2056"]]')
SRS_XML = "<spatialrefsys><authid>EPSG:2056</authid></spatialrefsys>"


def log(*a):
    print("[qgis-oiseaux]", *a, flush=True)


def gpkg_vide(chemin):
    """GeoPackage avec deux couches vides éditables (points et lignes, EPSG:2056)."""
    if os.path.exists(chemin):
        os.remove(chemin)
    c = sqlite3.connect(chemin)
    c.execute("PRAGMA application_id = 1196444487")
    c.execute("PRAGMA user_version = 10300")
    c.executescript("""
    CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
      organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
    CREATE TABLE gpkg_contents (table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
      description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER);
    CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
      srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL, CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));
    """)
    c.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)", [
        ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", None),
        ("Undefined geographic SRS", 0, "NONE", 0, "undefined", None),
        ("WGS 84", 4326, "EPSG", 4326, 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
         'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]', None),
        ("CH1903+ / LV95", 2056, "EPSG", 2056, CRS_WKT, None)])
    for nom, typ, champs in (("oiseaux_depart", "POINT", "groupe INTEGER, t_envol REAL, nombre INTEGER, note TEXT"),
                             ("oiseaux_direction", "LINESTRING", "groupe INTEGER, note TEXT")):
        c.execute(f"CREATE TABLE {nom} (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, geom {typ}, {champs})")
        c.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id) VALUES (?, 'features', ?, 2056)", (nom, nom))
        c.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, 2056, 0, 0)", (nom, typ))
    c.commit()
    c.close()


def emprise(env, out, pas=5.0):
    f = os.path.join(env, "alea_empreinte.npz")
    if not os.path.exists(f):
        log("pas d'alea_empreinte.npz: emprise non écrite")
        return False
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    z = np.load(f)
    tarr = np.array(z["tarr"], np.float64)
    x0, y1, s = float(z["x0"]), float(z["y1"]), float(z["step"])
    ny, nx = tarr.shape
    gE = x0 + (np.arange(nx) + 0.5) * s
    gN = y1 - (np.arange(ny) + 0.5) * s
    ok = np.isfinite(tarr)
    tmax = float(tarr[ok].max()) if ok.any() else 0.0
    tt = np.where(ok, tarr, 1e9)
    feats = []

    def aire(r):
        return 0.5 * float(np.sum(r[:, 0] * np.roll(r[:, 1], -1) - np.roll(r[:, 0], -1) * r[:, 1]))
    for t in np.arange(pas, tmax + pas, pas):
        fig, ax = plt.subplots()
        cs = ax.contourf(gE, gN, tt, levels=[-1.0, float(t)])
        anneaux = [r for p in cs.get_paths() for r in p.to_polygons()]
        plt.close(fig)
        polys = []
        for r in anneaux:
            if len(r) < 4 or abs(aire(r)) < 1.0:
                continue
            if not polys or (aire(r) > 0) == (aire(polys[0][0]) > 0):
                polys.append([r])
            else:
                polys[-1].append(r)
        if polys:
            feats.append({"type": "Feature", "properties": {"t": int(round(t))},
                          "geometry": {"type": "MultiPolygon",
                                       "coordinates": [[[[round(x, 1), round(y, 1)] for x, y in r] for r in p] for p in polys]}})
    json.dump({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2056"}},
               "features": feats[::-1]}, open(os.path.join(out, "emprise_5s.geojson"), "w"))
    log(f"emprise: {len(feats)} instants (toutes les {pas:g} s jusqu'à {tmax:.0f} s)")
    return [int(f_["properties"]["t"]) for f_ in feats]


def _fond(env, info, nom, out):
    src = os.path.join(env, info["file"])
    if not os.path.exists(src):
        return None
    ext = os.path.splitext(src)[1].lower()
    dst = os.path.join(out, nom + ext)
    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
        shutil.copyfile(src, dst)
    s = float(info["step"])
    w = {".jpg": ".jgw", ".jpeg": ".jgw", ".png": ".pgw", ".tif": ".tfw"}.get(ext, ".wld")
    open(os.path.join(out, nom + w), "w").write(f"{s}\n0\n0\n{-s}\n{info['x0'] + s / 2}\n{info['y1'] - s / 2}\n")
    return nom + ext


def _couleur(k, n):
    # jaune -> rouge -> violet
    stops = [(255, 230, 50), (255, 140, 0), (220, 30, 30), (150, 30, 200), (60, 60, 255)]
    x = (k / max(1, n - 1)) * (len(stops) - 1)
    i = min(int(x), len(stops) - 2)
    f = x - i
    return tuple(int(stops[i][j] * (1 - f) + stops[i + 1][j] * f) for j in range(3))


def _symbole_fill(nom, rgb, alpha, contour_rgb, largeur):
    return (f'<symbol type="fill" name="{nom}" alpha="1" clip_to_extent="1" force_rhr="0">'
            f'<layer class="SimpleFill" enabled="1" locked="0" pass="0">'
            f'<Option type="Map">'
            f'<Option type="QString" name="color" value="{rgb[0]},{rgb[1]},{rgb[2]},{alpha}"/>'
            f'<Option type="QString" name="outline_color" value="{contour_rgb[0]},{contour_rgb[1]},{contour_rgb[2]},255"/>'
            f'<Option type="QString" name="outline_style" value="solid"/>'
            f'<Option type="QString" name="outline_width" value="{largeur}"/>'
            f'<Option type="QString" name="outline_width_unit" value="MM"/>'
            f'<Option type="QString" name="style" value="solid"/>'
            f'</Option></layer></symbol>')


def _symbole_ligne(nom, rgb, largeur):
    return (f'<symbol type="line" name="{nom}" alpha="1" clip_to_extent="1" force_rhr="0">'
            f'<layer class="SimpleLine" enabled="1" locked="0" pass="0"><Option type="Map">'
            f'<Option type="QString" name="line_color" value="{rgb[0]},{rgb[1]},{rgb[2]},255"/>'
            f'<Option type="QString" name="line_style" value="solid"/>'
            f'<Option type="QString" name="line_width" value="{largeur}"/>'
            f'<Option type="QString" name="line_width_unit" value="MM"/>'
            f'</Option></layer>'
            f'<layer class="ArrowLine" enabled="1" locked="0" pass="0"><Option type="Map">'
            f'<Option type="QString" name="arrow_type" value="0"/>'
            f'<Option type="QString" name="arrow_width" value="0.8"/>'
            f'<Option type="QString" name="arrow_start_width" value="0.8"/>'
            f'<Option type="QString" name="head_length" value="4"/>'
            f'<Option type="QString" name="head_thickness" value="2.5"/>'
            f'<Option type="QString" name="head_type" value="0"/>'
            f'<Option type="QString" name="is_curved" value="0"/>'
            f'<Option type="QString" name="is_repeated" value="0"/>'
            f'</Option>'
            f'<symbol type="fill" name="@{nom}@1" alpha="1" clip_to_extent="1" force_rhr="0">'
            f'<layer class="SimpleFill" enabled="1" locked="0" pass="0"><Option type="Map">'
            f'<Option type="QString" name="color" value="{rgb[0]},{rgb[1]},{rgb[2]},255"/>'
            f'<Option type="QString" name="outline_style" value="no"/><Option type="QString" name="style" value="solid"/>'
            f'</Option></layer></symbol></layer></symbol>')


def _symbole_point(nom, rgb, forme, taille):
    return (f'<symbol type="marker" name="{nom}" alpha="1" clip_to_extent="1" force_rhr="0">'
            f'<layer class="SimpleMarker" enabled="1" locked="0" pass="0"><Option type="Map">'
            f'<Option type="QString" name="color" value="{rgb[0]},{rgb[1]},{rgb[2]},255"/>'
            f'<Option type="QString" name="name" value="{forme}"/>'
            f'<Option type="QString" name="outline_color" value="0,0,0,255"/>'
            f'<Option type="QString" name="outline_width" value="0.4"/>'
            f'<Option type="QString" name="size" value="{taille}"/>'
            f'<Option type="QString" name="size_unit" value="MM"/>'
            f'</Option></layer></symbol>')


def _couche_raster(lid, nom, fichier):
    return (f'<maplayer type="raster" hasScaleBasedVisibilityFlag="0" refreshOnNotifyEnabled="0" autoRefreshEnabled="0">'
            f'<id>{lid}</id><datasource>./{fichier}</datasource><layername>{nom}</layername>'
            f'<srs>{SRS_XML}</srs><provider>gdal</provider>'
            f'<pipe><rasterrenderer type="multibandcolor" opacity="1" alphaBand="-1" redBand="1" greenBand="2" blueBand="3" nodataColor="">'
            f'<rasterTransparency/></rasterrenderer><brightnesscontrast brightness="0" contrast="0"/>'
            f'<huesaturation saturation="0" grayscaleMode="0" colorizeOn="0"/><rasterresampler maxOversampling="2" zoomedInResampler="bilinear" zoomedOutResampler="bilinear"/></pipe>'
            f'<blendMode>0</blendMode></maplayer>')


def _couche_vecteur(lid, nom, source, geom, renderer, labels=""):
    return (f'<maplayer type="vector" geometry="{geom}" hasScaleBasedVisibilityFlag="0" readOnly="0" autoRefreshEnabled="0" '
            f'refreshOnNotifyEnabled="0" simplifyDrawingHints="0" labelsEnabled="{1 if labels else 0}">'
            f'<id>{lid}</id><datasource>{source}</datasource><layername>{nom}</layername>'
            f'<srs>{SRS_XML}</srs><provider encoding="UTF-8">ogr</provider>{renderer}{labels}'
            f'<blendMode>0</blendMode><featureBlendMode>0</featureBlendMode><layerOpacity>1</layerOpacity></maplayer>')


def _etiquettes(champ, taille, rgb):
    return (f'<labeling type="simple"><settings calloutType="simple">'
            f'<text-style fieldName="{champ}" isExpression="0" fontFamily="Arial" fontSize="{taille}" fontSizeUnit="Point" '
            f'textColor="{rgb[0]},{rgb[1]},{rgb[2]},255" textOpacity="1" fontWeight="75" multilineHeight="1" namedStyle="Bold">'
            f'<text-buffer bufferDraw="1" bufferSize="1" bufferSizeUnits="MM" bufferColor="0,0,0,255" bufferOpacity="1" bufferJoinStyle="128" bufferNoFill="1"/>'
            f'</text-style><placement placement="0" dist="1" distUnits="MM" placementFlags="10"/>'
            f'<rendering obstacle="1" scaleVisibility="0" drawLabels="1" displayAll="1"/></settings></labeling>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    env, out = a.env, a.out
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(env, "env_meta.json")))

    rasters = []
    f2 = _fond(env, meta["ortho"], "fond_ortho_2m", out)
    if f2:
        rasters.append(("fond_ortho_2m", "Orthophoto 2 m", f2))
    for p in meta.get("ortho_patches", []):
        if abs(p["step"] - 0.5) < 1e-6:
            f5 = _fond(env, p, "fond_ortho_50cm", out)
            if f5:
                rasters.append(("fond_ortho_50cm", "Orthophoto 50 cm", f5))
    log("fonds:", ", ".join(r[2] for r in rasters) or "aucun")

    instants = emprise(env, out) or []

    cam = None
    vm = os.path.join(env, "visible", "visible_meta.json")
    if os.path.exists(vm):
        c = json.load(open(vm))
        cam = (float(c["E"]), float(c["N"]))
    if cam:
        json.dump({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2056"}},
                   "features": [{"type": "Feature", "properties": {"nom": "caméra"},
                                 "geometry": {"type": "Point", "coordinates": list(cam)}}]},
                  open(os.path.join(out, "camera.geojson"), "w"))

    gp = os.path.join(out, "oiseaux.gpkg")
    if os.path.exists(gp):
        log("oiseaux.gpkg existe déjà: gardé (tes points ne sont pas effacés)")
    else:
        gpkg_vide(gp)

    # --- projet
    couches, ordre = [], []
    if os.path.exists(gp):
        r = (f'<renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0"><symbols>'
             f'{_symbole_point("0", (255, 40, 40), "star", 6)}</symbols></renderer-v2>')
        couches.append(_couche_vecteur("oiseaux_depart", "oiseaux_depart (à remplir)", "./oiseaux.gpkg|layername=oiseaux_depart",
                                       "Point", r, _etiquettes("groupe", 12, (255, 80, 80))))
        r = (f'<renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0"><symbols>'
             f'{_symbole_ligne("0", (255, 40, 40), 0.8)}</symbols></renderer-v2>')
        couches.append(_couche_vecteur("oiseaux_direction", "oiseaux_direction (à remplir)",
                                       "./oiseaux.gpkg|layername=oiseaux_direction", "Line", r))
        ordre += ["oiseaux_depart", "oiseaux_direction"]
    if cam:
        r = (f'<renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0"><symbols>'
             f'{_symbole_point("0", (255, 255, 255), "triangle", 5)}</symbols></renderer-v2>')
        couches.append(_couche_vecteur("camera", "caméra", "./camera.geojson", "Point", r, _etiquettes("nom", 11, (255, 255, 255))))
        ordre.append("camera")
    if instants:
        cats, syms = [], []
        for k, t in enumerate(sorted(instants)):
            col = _couleur(k, len(instants))
            cats.append(f'<category symbol="{k}" value="{t}" label="t = {t} s" render="true"/>')
            syms.append(_symbole_fill(str(k), col, 25, col, 0.6))
        r = (f'<renderer-v2 type="categorizedSymbol" attr="t" symbollevels="0" enableorderby="0" forceraster="0">'
             f'<categories>{"".join(cats)}</categories><symbols>{"".join(syms)}</symbols></renderer-v2>')
        couches.append(_couche_vecteur("emprise_5s", "emprise de la masse toutes les 5 s", "./emprise_5s.geojson", "Polygon", r))
        ordre.append("emprise_5s")
    for lid, nom, fichier in reversed(rasters):
        couches.append(_couche_raster(lid, nom, fichier))
        ordre.append(lid)

    if cam:
        ext = (cam[0] - 2000, cam[1] - 1500, cam[0] + 2000, cam[1] + 2500)
    else:
        o = meta["ortho"]
        ext = (o["x0"], o["y1"] - 4000, o["x0"] + 4000, o["y1"])
    arbre = "".join(f'<layer-tree-layer id="{l}" name="{l}" checked="Qt::Checked" expanded="1" source=""/>' for l in ordre)
    lo = "".join('<layer id="%s"/>' % l for l in ordre)
    qgs = (f'<!DOCTYPE qgis PUBLIC \'http://mrcc.com/qgis.dtd\' \'SYSTEM\'>\n'
           f'<qgis projectname="Blatten oiseaux" version="3.34.0">'
           f'<title>Blatten: placer les oiseaux</title>'
           f'<projectCrs>{SRS_XML}</projectCrs>'
           f'<layer-tree-group>{arbre}</layer-tree-group>'
           f'<mapcanvas name="theMapCanvas"><units>meters</units>'
           f'<extent><xmin>{ext[0]}</xmin><ymin>{ext[1]}</ymin><xmax>{ext[2]}</xmax><ymax>{ext[3]}</ymax></extent>'
           f'<rotation>0</rotation><destinationsrs>{SRS_XML}</destinationsrs><rendermaptile>0</rendermaptile></mapcanvas>'
           f'<projectlayers>{"".join(couches)}</projectlayers>'
           f'<layerorder>{lo}</layerorder>'
           f'<properties><Paths><Absolute type="bool">false</Absolute></Paths></properties>'
           f'</qgis>\n')
    open(os.path.join(out, "oiseaux.qgs"), "w", encoding="utf-8").write(qgs)
    log("projet:", os.path.join(out, "oiseaux.qgs"))


if __name__ == "__main__":
    main()
