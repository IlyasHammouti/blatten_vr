@echo off
rem Extrait 360 en 3840x1920 (resolution du film final), aux reglages du rendu final: t = 27,5 a 32,5 s de l evenement (images 1066 a 1215), avec le son spatial.
rem Avant: test des arbres (7 min) pour les couleurs. Environ 15 h en tout sur la 2060 (12 a 24 h): a lancer le soir. Chiffre reel affiche apres le premier paquet de 40 images; arret et reprise possibles.
cd /d C:\Dev\blatten-vr
title Blatten 360 - extrait 360 4K aux reglages finaux (t = 27,5 a 32,5 s), avec le son
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow
python blatten.py test-arbres
python blatten.py extrait --t 30 --duree 5 --res 3840x1920
echo.
echo Termine. Video: D:\Blatten_render\extraits (film_360_360.mp4). Claude la recupere lui-meme.
pause
exit /b
)
