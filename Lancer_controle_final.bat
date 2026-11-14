@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - controle avant le rendu final
echo Fermez l'app Claude, le navigateur et Spotify pour liberer la RAM. Environ 40 min.
echo Trois images 360 avec les reglages du film: t = 5 s, 30 s et 45 s. Mesure aussi la memoire de la carte et la RAM.
echo.
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow
python blatten.py test-final --temps 5 30 45 --sans-variantes
echo.
echo Termine. Images et bilan.json dans render\tests\final, dossier le plus recent.
pause
