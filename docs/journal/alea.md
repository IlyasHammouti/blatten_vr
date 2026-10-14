# Journal ALEA (matière: avalanche, dépôt, poussière)

Écrit par la conversation ALEA. La conversation ENV le lit au début de chaque séance (après `git pull`). Les plus récents en haut.

## Demandes à ENV
(une ligne par demande: quoi, pourquoi, urgence)
- 2026-10-14 : `camera.json` final (confirmed: true, X -643,73) n'est pas commité: seule la copie locale d'Ilyas l'a, `main` a encore l'ancienne. Pourquoi: tout clone (Maxime, 2e PC de rendu) rendrait avec la mauvaise caméra. Urgence: avant le premier test commun.
- 2026-10-14 : confirmer que le centre de l'image ne regarde plus la zone de départ. Avec rot (90, 0, -69), le centre pointe vers l'ENE (azimut +21°); la zone de départ est à ~60° à droite, le centre du dépôt à ~110° à droite (calcul, à vérifier sur un rendu). Pas de cap initial dans `inject_360.py`: sur YouTube, le spectateur démarre face à l'ENE, sans l'événement dans le champ. Intentionnel? Urgence: avant de figer la fenêtre de temps.
- 2026-10-14 : `empreinte_alea.py` dit « rien ne manque » car grille de 4 m = taille d'une particule, vrai seulement à stride 1. À stride 5 (espacement ~7 m) `zfin` et `tarr` ont des trous. Quel stride a servi pour `alea_empreinte.npz`? Si > 1, soit recalculer à stride 1 (CPU, une fois), soit dilater. Urgence: avant que j'utilise `zfin` pour le dépôt.

## Séances
(date, ce qui marche, ce qui reste, décisions du contrat à changer, temps de rendu mesurés)

## 2026-10-14 (séance 2, mise à jour et plan)
- `alea` contient déjà tout `main` (ENV jusqu'à ee09fea: caméra finale, relief HD, bâtiments, arbres, rivière, `empreinte-alea`). Interface `build`/`update` et helpers inchangés. Rien à pull de plus.
- À retenir pour la matière: caméra finale à 2 m du sol, centre du dépôt à ~540 m (horizontal), 200 m en contrebas; bâtiments et arbres balayés masqués à `tarr`; `zfin` disponible pour le dépôt (sous réserve du stride, voir demandes).
- Plan (dates visées, rendu final lancé au plus tard le 15 nov pour tenir le 25 nov):
  1. 14-17 oct: `analyse_temps.py` sur les vraies données, décision fenêtre de temps; vérifier stride du cache.
  2. 17-24 oct: matière A (roches instanciées + bump + couleur/contraste) vs B' (surface cuite hors ligne) sur 3 s, nouvelle caméra, environnement complet; `bench`.
  3. 24-31 oct: interpolation (fluidité 30 i/s, pas de traversée du terrain), choix de la représentation, retrait de la matière cachée (masque `visible_2m`).
  4. 1-8 nov: dépôt (recouvrement du fond de vallée avec `zfin`), poussière et nuage à budget mesuré.
  5. 8-12 nov: gel de la matière, `bench` complet, répartition sur 2 PC, aperçu basse résolution des ~40 s.
  6. 12-22 nov: rendu 1 200 images (marge x1,5), encodage, métadonnées 360, test YouTube.
  7. 22-25 nov: marge, intro/générique, livraison.

## 2026-10-10 (séance 1, mise en place)
- Dépôt à jour (`main` 6f0cf7a), branche `alea` créée. Lu : contrat, `rendu_matiere.py` (gabarit), journal ENV.
- **Limite de cette séance** : la conversation ALEA n'a accès qu'au dépôt (pas aux PLY/`.npy` ni à Blender de D:/F:). Les rendus se font sur le PC d'Ilyas, qui renvoie les images.
- Constat sur le rendu existant (`render/test_clip`, 96 spp) : à ~0,5 km la masse se lit comme un tas de billes lisses et grises, peu de contraste avec la forêt, aucune poussière. Priorité 1 confirmée.
- Ajout : `src/matiere/analyse_temps.py` (chronologie vitesse/distance/arrêt des 202 fichiers) pour trancher la fenêtre de temps avec des chiffres.
- Écarts à noter : `camera.json` (-776,4 / 754,9 / 1708,07, rot z -117,4, `confirmed: false`) diffère de la position citée dans le handover ; budget de rendu du contrat (69 s fixes + 0,62 s/éch.) plus pessimiste que la mesure récente (40 s + 0,43 s/éch.).

