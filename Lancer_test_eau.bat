@echo off
cd /d C:\Dev\blatten-vr
(
git fetch -q origin
git reset -q --hard origin/main
python blatten.py test-eau
echo.
echo Termine. Images dans render\tests\eau. Vous pouvez fermer cette fenetre.
pause
exit /b
)
