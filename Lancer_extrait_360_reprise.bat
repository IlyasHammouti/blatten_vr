@echo off
rem Extrait 360 en 3840x1920 (resolution du film final), aux reglages du rendu final: t = 27,5 a 32,5 s de l evenement (images 1066 a 1215), avec le son spatial.
rem REPRISE apres une coupure: meme extrait, sans le test des arbres. Les images deja faites sont gardees, l image interrompue est refaite.
cd /d C:\Dev\blatten-vr
title Blatten 360 - REPRISE extrait 360 4K (t = 27,5 a 32,5 s), avec le son
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow
python blatten.py extrait --t 30 --duree 5 --res 3840x1920
echo.
echo Termine. Video: D:\Blatten_render\extraits, fichier film_360_360.mp4. Claude la recupere lui-meme.
pause
exit /b
)
