@echo off
rem Film complet en HD (3840x1920, 96 echantillons) avec les reglages du film (reglages/film.json). Plusieurs jours.
rem Images dans D:\Blatten_render\final, video final.mp4 au bout. Reprise automatique: relancer ce fichier apres une coupure.
cd /d C:\Dev\blatten-vr
git fetch -q origin
git reset -q --hard origin/main
python blatten.py render --intro-pas 3
pause
