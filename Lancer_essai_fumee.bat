@echo off
cd /d "%~dp0"
title Blatten 360 - essai de fumee simulee
echo Essai de fumee simulee par Blender, basse resolution. Duree inconnue: de 20 min a 2 h selon le processeur.
echo.
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow
python blatten.py essai-fumee --res 128 --fps 15 --fin 45
echo.
echo Termine. Images et clip dans render\essai_fumee, dossier le plus recent.
pause
