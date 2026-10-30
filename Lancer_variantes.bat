@echo off
cd /d C:\Dev\blatten-vr
(
git fetch -q origin
git reset -q --hard origin/main
python blatten.py variantes
echo.
echo Termine. Images dans render\variantes. Vous pouvez fermer cette fenetre.
pause
exit /b
)
