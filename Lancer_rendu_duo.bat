@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - rendu a deux, PC d'Ilyas
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg
python blatten.py duo
echo.
echo Rendu arrete. Relancer ce fichier pour reprendre: rien n'est perdu.
pause
exit /b
)
