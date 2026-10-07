# Prérequis de la version finale (Blatten 360)

Le rendu final (`python blatten.py render`) est bloqué par le programme tant que ces points ne sont pas réglés.

1. **Position de la caméra** validée par le groupe, puis enregistrée dans `camera.json` avec `"confirmed": true`.
2. **Relief swissALTI3D 0,5 m** : télécharger les dalles autour de la caméra (environ 2 km x 2 km).
3. **Image SWISSIMAGE 10 cm** : mêmes dalles, **à la bonne date** (la plus proche de fin mai ; l'image actuelle date de 2021 ou 2023).
4. Refaire la préparation de l'environnement (`python blatten.py prep-env`).
5. Confirmer avec Johan : pas de temps (`dt_per_step`) et échelle de temps.
6. Données de Johan reçues : lissage du dépôt, poussière.
7. Son spatialisé (monté à part) et métadonnées YouTube 360 (injection des métadonnées spatiales).

`--accept-lowres` permet de contourner les points 2 et 3 (déconseillé). Les points 1 et 4 ne se contournent pas.
