@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - tous les tests: son, polices, couleurs, eau, sol, arbres, rendu final
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow
python blatten.py test-son
python blatten.py titre-test --polices
python blatten.py test-couleurs
python blatten.py test-eau
python blatten.py prep-sol
python blatten.py test-aspect
python blatten.py test-final
echo.
echo Termine. Son: D:\Blatten_render\tests_son. Images: render\tests. Claude les recupere lui-meme.
pause
exit /b
)
