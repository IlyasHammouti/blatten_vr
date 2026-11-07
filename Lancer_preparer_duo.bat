@echo off
cd /d C:\Dev\blatten-vr
title Blatten 360 - preparation du rendu a deux
(
git fetch -q origin
git reset -q --hard origin/main
python blatten.py paquet
echo.
echo Dossier de la session: D:\Blatten_render\duo. Lire A_LIRE.txt, puis donner le zip au frere.
pause
exit /b
)
