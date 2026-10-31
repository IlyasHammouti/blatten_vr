@echo off
cd /d C:\Dev\blatten-vr
(
git fetch -q origin
git reset -q --hard origin/main
python blatten.py test-bande
echo.
echo Termine. Images dans render\tests\bande. Vous pouvez fermer cette fenetre.
exit /b
)
