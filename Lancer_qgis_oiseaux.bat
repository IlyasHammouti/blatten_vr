@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - projet QGIS des oiseaux
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q pillow matplotlib
python blatten.py qgis-oiseaux
start "" "render\qgis_oiseaux\oiseaux.qgs"
echo.
echo Dans QGIS: couche oiseaux_depart, crayon, un point par groupe; couche oiseaux_direction, une ligne du depart vers ou ils vont.
echo Enregistrer les modifications, puis dire a Claude que c'est fait.
pause
