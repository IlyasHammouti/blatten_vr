# Audio spatialisé (à faire)

Rien n'est codé ici pour l'instant. Plan:

1. Un script exporte, image par image, la direction (azimut, élévation) et la distance du front
   d'écoulement vue de la caméra: `trajectoire_son.csv`.
2. Montage dans un logiciel audio (Reaper) avec des plugins ambisoniques gratuits (IEM, SPARTA),
   format AmbiX du premier ordre (4 canaux).
3. Option de réalisme: retard du son (343 m/s, soit environ 6 s à 2 km), atténuation et filtrage
   passe-bas avec la distance. A décider en groupe.
4. Injection des métadonnées spatiales YouTube 360 dans la vidéo finale.
