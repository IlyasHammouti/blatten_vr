@echo off
rem Prend les polygones de la couche eau_manuel (QGIS) comme masque d eau, puis rend une image test (t = 10 s) dans render\variantes\t10s\film.
cd /d C:\Dev\blatten-vr
git fetch -q origin
git reset -q --hard origin/main
python blatten.py eau-manuel
python blatten.py variantes --temps 10 --jeux film --refaire
pause
