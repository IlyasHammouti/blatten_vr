@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - veilleur de nuit: tests lances par Claude, ne pas fermer
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q pillow
python tools\veilleur.py
echo.
echo Veilleur arrete.
pause
exit /b
)
