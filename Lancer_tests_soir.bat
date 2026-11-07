@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - lot de tests du soir: sol, arbres, temps du rendu final
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg pillow
python blatten.py prep-sol
python blatten.py test-aspect
python blatten.py test-final
echo.
echo Termine. Images: render\tests\aspect et render\tests\final. Claude les recupere lui-meme.
pause
exit /b
)
