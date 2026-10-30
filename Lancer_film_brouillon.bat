@echo off
rem Film complet en basse definition (1920x960, 16 echantillons) avec les reglages du film (reglages/film.json).
rem Images dans D:\Blatten_render\film_brouillon, video brouillon.mp4 au bout. Reprise automatique: relancer ce fichier apres une coupure.
cd /d C:\Dev\blatten-vr
git fetch -q origin
git reset -q --hard origin/main
python blatten.py render --qualite brouillon
pause
