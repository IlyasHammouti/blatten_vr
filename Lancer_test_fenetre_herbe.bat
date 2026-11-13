@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - test herbe puis oiseaux (fenetres plates, conditions du film final)
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q pillow
python blatten.py test-fenetre herbe
python blatten.py test-oiseaux
echo.
echo Termine. Images: render\tests\fenetre et video dans D:\Blatten_render\tests_oiseaux. Claude les recupere lui-meme.
pause
exit /b
)
