@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - etat du rendu a deux
(
git fetch -q origin
git reset -q --hard origin/main
python blatten.py duo-etat
echo.
echo Vous pouvez fermer cette fenetre.
pause
exit /b
)
