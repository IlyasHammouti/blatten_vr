@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - tests de validation: carte, herbe, eau
echo Fermez l'app Claude, le navigateur et Spotify pour liberer la RAM. Ce lot dure environ 1 h a 2 h.
echo Chaque test se lance apres le precedent. Les resultats sont ecrits dans render.
echo.
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow matplotlib
echo.
echo === 1/4 Carte vue du ciel: emprise de la masse toutes les 5 s et oiseaux ===
python blatten.py carte-oiseaux
echo.
echo === 2/4 Herbe detaillee jusqu'a 50 m puis jusqu'a 250 m, vert unique: 3 fenetres ===
python blatten.py test-fenetre herbe3
echo.
echo === 3/4 Eau brillante: 3 images, sans, 3 et 8 ===
python blatten.py test-fenetre eau
echo.
echo === 4/4 Eau brillante: clip de 2 s ===
python blatten.py test-eau-clip
echo.
echo Termine.
echo Carte: render\carte_oiseaux\carte_oiseaux.png, couches QGIS dans render\carte_oiseaux\couches
echo Herbe: render\tests\fenetre\herbe3
echo Eau: render\tests\fenetre\eau et render\tests_eau_clip
pause
