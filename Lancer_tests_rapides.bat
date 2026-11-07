@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - tests rapides: son, polices, couleurs, eau
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow
python blatten.py test-son
python blatten.py titre-test --polices
python blatten.py test-couleurs
python blatten.py test-eau
echo.
echo Termine. Son: D:\Blatten_render\tests_son. Images: render\tests. Claude les recupere lui-meme.
pause
exit /b
)
