@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - test des oiseaux: clip plat de l envol
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q pillow
python blatten.py test-oiseaux
echo.
echo Termine. Video: dossier tests_oiseaux. Claude la recupere lui-meme.
pause
exit /b
)
