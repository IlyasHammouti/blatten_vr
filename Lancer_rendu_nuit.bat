@echo off
cd /d C:\Dev\blatten-vr
(
git fetch -q origin
git reset -q --hard origin/main
python blatten.py render --jusqu-a 07:00 --paquet 10 --pause 60
echo.
echo Arret propre. Relancer ce fichier demain soir pour reprendre.
pause
exit /b
)
