@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - test des arbres: couleurs (sans arbres, arbres simples, detailles jusqu a 1000 m), temps, memoire
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q pillow
python blatten.py test-arbres
echo.
echo Termine. Images: render\tests\arbres. Claude les recupere lui-meme.
pause
exit /b
)
