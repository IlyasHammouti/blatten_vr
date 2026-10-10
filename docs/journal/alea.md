# Journal ALEA (matière: avalanche, dépôt, poussière)

Écrit par la conversation ALEA. La conversation ENV le lit au début de chaque séance (après `git pull`). Les plus récents en haut.

## Demandes à ENV
(une ligne par demande: quoi, pourquoi, urgence)

## Séances
(date, ce qui marche, ce qui reste, décisions du contrat à changer, temps de rendu mesurés)

## 2026-10-10 (séance 1, mise en place)
- Dépôt à jour (`main` 6f0cf7a), branche `alea` créée. Lu : contrat, `rendu_matiere.py` (gabarit), journal ENV.
- **Limite de cette séance** : la conversation ALEA n'a accès qu'au dépôt (pas aux PLY/`.npy` ni à Blender de D:/F:). Les rendus se font sur le PC d'Ilyas, qui renvoie les images.
- Constat sur le rendu existant (`render/test_clip`, 96 spp) : à ~0,5 km la masse se lit comme un tas de billes lisses et grises, peu de contraste avec la forêt, aucune poussière. Priorité 1 confirmée.
- Ajout : `src/matiere/analyse_temps.py` (chronologie vitesse/distance/arrêt des 202 fichiers) pour trancher la fenêtre de temps avec des chiffres.
- Écarts à noter : `camera.json` (-776,4 / 754,9 / 1708,07, rot z -117,4, `confirmed: false`) diffère de la position citée dans le handover ; budget de rendu du contrat (69 s fixes + 0,62 s/éch.) plus pessimiste que la mesure récente (40 s + 0,43 s/éch.).

