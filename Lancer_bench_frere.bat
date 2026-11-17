@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - banc d'essai du PC (echantillons, distances, volumes)
echo Fermez le navigateur et Spotify. Duree: environ 2 h 30 sur une RTX 3060.
echo Cinq reglages, chaque image 360 finale est mesuree (temps, memoire de la carte, RAM libre).
echo A la fin le bilan est ecrit dans render\bench_frere\bilan_bench.txt, envoyez-le a Claude.
echo.
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow numpy
if not exist render\bench_frere mkdir render\bench_frere
del /q render\bench_frere\ordre.txt 2>nul
echo debut> render\bench_frere\debut.txt
echo.
echo === 1/5 Reference: 96 echantillons (reglages du film), t = 5, 30, 45 s ===
echo n1_96_echantillons>> render\bench_frere\ordre.txt
python blatten.py test-final --temps 5 30 45 --sans-variantes
echo.
echo === 2/5 48 echantillons, seuil 0.02 ===
echo n2_48_echantillons>> render\bench_frere\ordre.txt
python blatten.py test-final --temps 5 30 45 --sans-variantes --set scene.rendu_echantillons=48 --set scene.rendu_seuil=0.02
echo.
echo === 3/5 48 echantillons, herbe jusqu'a 120 m au lieu de 250 m ===
echo n3_48_herbe120>> render\bench_frere\ordre.txt
python blatten.py test-final --temps 5 30 --sans-variantes --set scene.rendu_echantillons=48 --set scene.rendu_seuil=0.02 --set scene.herbe_rayon=120
echo.
echo === 4/5 48 echantillons, arbres 3D jusqu'a 600 m au lieu de 1000 m ===
echo n4_48_arbres600>> render\bench_frere\ordre.txt
python blatten.py test-final --temps 5 30 --sans-variantes --set scene.rendu_echantillons=48 --set scene.rendu_seuil=0.02 --set scene.arbres_modeles_dist=600
echo.
echo === 5/5 48 echantillons, volumes biaises (nuage de poussiere) ===
echo n5_48_volumes_biaises>> render\bench_frere\ordre.txt
python blatten.py test-final --temps 30 45 --sans-variantes --set scene.rendu_echantillons=48 --set scene.rendu_seuil=0.02 --set scene.rendu_volumes_biaises=true --set scene.rendu_pas_volumes=2
echo.
python tools\bench_frere.py
echo.
echo Termine. Envoyez render\bench_frere\bilan_bench.txt a Claude.
pause
