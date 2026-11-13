@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - test sur fenetre plate (une caracteristique, conditions du film final)
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q pillow
python blatten.py test-fenetre %1
echo.
echo Termine. Images: render\tests\fenetre. Claude les recupere lui-meme.
pause
exit /b
)
