@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - tests du matin: carte des oiseaux, herbe 250 m, eau
echo Fermez l'app Claude, le navigateur et Spotify pour liberer la RAM. Ce lot dure environ 1 h a 2 h.
echo Les resultats sont ecrits dans render. Claude ne tourne pas pendant ce temps.
echo.
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow
echo.
echo === 1/4 Carte des oiseaux et du glissement ===
python blatten.py carte-oiseaux
echo.
echo === 2/4 Herbe a 250 m, vert unique, plus dense: 3 fenetres ===
python blatten.py test-fenetre herbe3
echo.
echo === 3/4 Eau: eclats de soleil, 3 images ===
python blatten.py test-fenetre eau
echo.
echo === 4/4 Eau: clip de 2 s ===
python blatten.py test-eau-clip
echo.
echo Termine.
echo Carte: render\carte_oiseaux\carte_oiseaux.png et .txt
echo Herbe: render\tests\fenetre\herbe3
echo Eau: render\tests\fenetre\eau et render\tests_eau_clip
pause
