@echo off
cd /d C:\Dev\blatten-vr
(
git fetch -q origin
git reset -q --hard origin/main
python blatten.py apercu-alea
echo.
echo Termine. Vous pouvez fermer cette fenetre.
pause
exit /b
)
