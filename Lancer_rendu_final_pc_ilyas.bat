@echo off
rem PC d Ilyas: rend le film final (version final_v1) DU DEBUT VERS LA FIN, a partir de l image 41 (Samy a fait 1 a 40 puis rend de la fin vers le debut).
rem Pas de limite: la carte 6 Go ne tient pas la poussiere du bout (apres l image ~950). Si Blender manque de memoire, la commande s arrete seule apres 2 paquets rates.
rem Arret propre a la fin du paquet en cours: creer le fichier render\ARRET.txt. Reprise: supprimer ce fichier et relancer ce .bat (les images faites sont sautees).
rem A lancer seulement sur ordre d Ilyas, apres tools\verifier_donnees.py (memes valeurs que Samy).
cd /d "%~dp0"
git fetch -q origin
git reset -q --hard origin/main
python blatten.py render --version final_v1 --de 41 --paquet 12
pause
