@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - test des arbres puis image finale (couleurs, temps, memoire)
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q pillow
python blatten.py test-arbres
python blatten.py test-final --sans-variantes
echo.
echo Termine. Images: render\tests\arbres et render\tests\final. Claude les recupere lui-meme.
pause
exit /b
)
