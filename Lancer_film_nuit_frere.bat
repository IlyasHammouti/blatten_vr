@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - rendu FINAL, debut de l'evenement (images 201 a 451, t = 0 a 10 s)
echo RENDU FINAL. Ne fermez pas cette fenetre, ne mettez pas le PC en veille, fermez navigateur et Spotify.
echo Arret propre avant 08:00. Images dans D:\BLATTEN_Ilyas\render\final\final_v1 (reprise automatique: relancer ce fichier).
echo.
git fetch -q origin
git reset -q --hard origin/main
python blatten.py render --version final_v1 --de 201 --a 451 --paquet 40 --jusqu-a 08:00
echo.
echo Termine ou arrete proprement. Les images faites sont conservees.
pause
