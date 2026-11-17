@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - rendu FINAL, debut de l'evenement (images 201 a 451, t = 0 a 10 s)
echo RENDU FINAL. Ne fermez pas cette fenetre, ne mettez pas le PC en veille, fermez navigateur et Spotify.
echo Images dans D:\BLATTEN_Ilyas\render\final\final_v1 (reprise automatique: relancer ce fichier).
echo Pour arreter proprement: creer le fichier render\ARRET.txt (fin du paquet en cours, 20 images au plus).
echo.
git fetch -q origin
git reset -q --hard origin/main
del /q render\ARRET.txt 2>nul
python blatten.py render --version final_v1 --de 201 --a 451 --paquet 20
echo.
echo Termine ou arrete proprement. Les images faites sont conservees.
pause
