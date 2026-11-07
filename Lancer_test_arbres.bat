@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - test des arbres: detail jusqu a 0, 200, 500, 1000 m et couleurs
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
