@echo off
rem Brouillon HD plat, derniers 10 s de l evenement + fondu au noir + outro (images 1531 a 1830), puis montage avec le son.
rem 150 images a calculer, environ 10 h. Dossier separe: le rendu precedent n est pas touche.
cd /d C:\Dev\blatten-vr
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg
python blatten.py render --qualite bande --pas 2 --intro-pas 2 --version 20261103_0001_fin --de 1531 --a 1830 && (git fetch -q origin & git reset -q --hard origin/main & python blatten.py finir --format bande --dir D:\Blatten_render\film_bande\20261103_0001_fin)
echo Termine.
pause
exit /b
)
