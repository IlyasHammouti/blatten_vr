@echo off
cd /d C:\Dev\blatten-vr
(
git fetch -q origin
git reset -q --hard origin/main
python blatten.py titre-test --polices
echo.
echo Termine. Images dans render\tests\titre. Vous pouvez fermer cette fenetre.
pause
exit /b
)
