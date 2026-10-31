@echo off
rem Brouillon HD plat (bande 2560x1280, 15 images/s recopiees a 30), puis outro, son et montage. Eteint le PC si tout est fini.
cd /d C:\Dev\blatten-vr
(
git fetch -q origin
git reset -q --hard origin/main
python -m pip install -q imageio-ffmpeg
python blatten.py render --qualite bande --pas 2 --intro-pas 2 && (git fetch -q origin & git reset -q --hard origin/main & python blatten.py finir --format bande && shutdown /s /t 600 /c "Brouillon HD termine: extinction dans 10 min, shutdown /a pour annuler")
echo Termine.
exit /b
)
