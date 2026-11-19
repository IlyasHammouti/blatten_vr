@echo off
rem PC d Ilyas: rend le film final (version final_v1) DE LA FIN VERS LE DEBUT, en partant de l image 950, par paquets de 12.
rem Samy rend du debut vers la fin sur l autre PC. Le plafond 950 (t=30 s) tient compte de la carte 6 Go: au-dela, la poussiere est trop lourde.
rem Arret propre a la fin du paquet en cours: creer le fichier render\ARRET.txt. Reprise: supprimer ce fichier et relancer ce .bat (les images faites sont sautees).
rem A lancer seulement sur ordre d Ilyas, apres tools\verifier_donnees.py (memes valeurs que Samy).
cd /d "%~dp0"
git fetch -q origin
git reset -q --hard origin/main
python blatten.py render --version final_v1 --inverse --de 1 --a 950 --paquet 12
pause
