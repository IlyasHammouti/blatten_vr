# Journal ALEA (matière: avalanche, dépôt, poussière)

Écrit par la conversation ALEA. La conversation ENV le lit au début de chaque séance (après `git pull`). Les plus récents en haut.

## Demandes à ENV
(une ligne par demande: quoi, pourquoi, urgence)
- 2026-10-14 : `camera.json` final (confirmed: true, X -643,73) n'est pas commité: seule la copie locale d'Ilyas l'a, `main` a encore l'ancienne. Pourquoi: tout clone (Maxime, 2e PC de rendu) rendrait avec la mauvaise caméra. Urgence: avant le premier test commun.
- 2026-10-14 : confirmer que le centre de l'image ne regarde plus la zone de départ. Avec rot (90, 0, -69), le centre pointe vers l'ENE (azimut +21°); la zone de départ est à ~60° à droite, le centre du dépôt à ~110° à droite (calcul, à vérifier sur un rendu). Pas de cap initial dans `inject_360.py`: sur YouTube, le spectateur démarre face à l'ENE, sans l'événement dans le champ. Intentionnel? Urgence: avant de figer la fenêtre de temps.
- 2026-10-14 : `empreinte_alea.py` dit « rien ne manque » car grille de 4 m = taille d'une particule, vrai seulement à stride 1. À stride 5 (espacement ~7 m) `zfin` et `tarr` ont des trous. Quel stride a servi pour `alea_empreinte.npz`? Si > 1, soit recalculer à stride 1 (CPU, une fois), soit dilater. Urgence: avant que j'utilise `zfin` pour le dépôt.

## Séances
(date, ce qui marche, ce qui reste, décisions du contrat à changer, temps de rendu mesurés)

## 2026-10-17 (conversation unifiée) mémoire, aperçu sans orthophoto, peau du dépôt
- **Rendu de la vraie scène dans le cloud** : les 202 fichiers de particules et le cache `env` (sans les arbres pré-calculés lourds) ont été copiés depuis le PC; Blender 5.2.2 en module (CPU, 2 coeurs, 7 Go). Sert à regarder les images sans faire lancer chaque essai à Ilyas.
- **Masques de visibilité** recalculés dans le cloud: identiques bit à bit à ceux du PC (le `visible_meta.json` du PC a des pourcentages périmés, les masques sont bons).
- **Coupe automatique du relief invisible** (`cull=None`): active si les masques existent et ont été calculés pour la caméra actuelle (1 m en plan, 3 m en altitude), sinon relief complet. `--no-cull` pour comparer. Gain mesuré sur les vraies données: 5,82 -> 4,68 M faces avec la HD (-20 %, l'anneau 0,5 m est presque tout visible), 2,28 -> 1,25 M sans la HD (-45 %).
- **`--no-ortho`** : relief sans image aérienne drapée (couleurs procédurales). Les couleurs des toits et des arbres restent lues dans l'image (CPU, aucun coût mémoire graphique).
- **Aperçu de l'aléa** (demande d'Ilyas): environnement complet (arbres, bâtiments, rivière, poussière) sans orthophoto ni relief 0,5 m. Mesuré dans le cloud à t = 43 s, 1280x640, 8 éch.: 532 000 arbres visibles (5,7 M triangles), relief 1,25 M faces, 731 bâtiments, pic 5,2 Go de RAM (CPU).
- **Peau du dépôt** (`src/matiere/depot.py`, `--no-depot` pour la couper): surface continue sous les roches, recalculée à chaque image (cases de 5 m, au moins 4 particules dans le 3 x 3, un demi-rayon sous la particule la plus haute, bords enfoncés de 3 m). 20 000 à 38 000 faces, 0,03 s par image.
- **`--border x0 x1 y0 y1`** : ne rend qu'un cadre de l'image (zoom d'essai à pleine résolution).
- **Images finales** : si une image plante, nouvel essai avec arbres limités à 2,5 km, puis sans HD; l'image allégée est signalée (`ALLEGEE.txt`).

## 2026-10-14 (séance 3, matière A, interpolation, banc de test)
- **Banc de test** `src/matiere/banc_test.py` (cloud ou PC, `pip install bpy`): terrain et particules synthétiques, caméra à 2 m, dépôt à ~540 m, même densité angulaire que la vidéo (960x540 à 90 degrés). Sert à juger FORME et COÛT, pas la couleur (dépend de l'ortho et de la brume).
- **Matière A** `src/matiere/matiere_roches.py` (`--matiere matiere_roches`): 4 variantes de roches irrégulières (80 faces), rotation et proportions aléatoires par particule, bump procédural en coordonnées objet, couleur aléatoire + éclaircie par la vitesse (attribut `speed` lu en Instancer, vérifié). Réglages dans `REGLAGES`, remplaçables par `src/matiere/reglages_matiere.json`. Même coût de reconstruction que le gabarit (positions + vitesse seulement).
  Résultat banc (104 000 particules, espacement 6,8 m): les billes lisses du gabarit deviennent une masse irrégulière, plus rocheuse. Limite: à cette échelle ça se lit comme un lit de graviers, pas encore comme une masse qui coule; la poussière et le contraste restent à faire dans la vraie scène.
  Coût CPU (2 coeurs, pas représentatif d'une RTX 2060): 32,7 s contre 21,7 s pour le gabarit (+50 %). À mesurer avec `bench` sur le PC.
- **Interpolation**: la méthode de `Sequence.state` (fondu des extrapolations avant/arrière) n'est exacte qu'à l'ordre 1: à mi-chemin elle ajoute (dt/4)(v0-v1) au lieu de (dt/8)(v0-v1), erreur a·dt²/8 pour une accélération constante (comme un fondu linéaire des positions, de signe opposé). Remplacée dans ma matière par Hermite cubique (`src/matiere/interpolation.py`, option `interpolation: "scene"` pour comparer). Sur données synthétiques à 1 s d'écart: erreur médiane 0,06 m contre 2,2 m. **À confirmer sur les vraies données** avec `test_interpolation.py`.
- `test_interpolation.py` estime aussi le pas de temps réel entre fichiers (1,0 s ou 1,04 s) à partir des vitesses: retrouve 1,044 s sur des données synthétiques à 1,04 s. Répond à la question à Johan sans le déranger.
- Proposition ENV (non urgente): si Hermite se confirme, remplacer `Sequence.state` par `interpolation.etat` dans la scène pour que `empreinte-alea`, la matière par défaut et les futurs modules partagent la même interpolation.
- Pas fait: B' (surface cuite hors ligne): en attente du rendu A sur la vraie scène; dépôt (attend `zfin` fiable); poussière et couleur (attendent l'environnement réel).

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


## 2026-10-16 (conversation unifiée) série complète
- 202 PLY convertis (stride 5, 233 762 particules, origine conservée), ancien `all_particles_1500` rangé dans `cache/_ancien`.
- analyse_temps : mouvement dès t = 2 s, pic 75,3 m/s à 31 s, 50 % de la distance à 34 s, 90 % à 53 s, traîne jusqu'à 202 s.
- test_interpolation (écart 2 s) : Hermite 0,02 m médiane (pire instant 2,27 m) contre 0,21 m (4,96 m) pour l'ancien fondu ; pas de temps 1,000 s. Hermite branché dans `Sequence.state`.
- Empreinte complète : 2,99 km2. **La caméra est dans l'empreinte** : matière à < 30 m dès t = 49-50 s, jusqu'à ~20 m au-dessus de la caméra entre 50 et 58 s, puis drainage (rien à < 50 m à t = 201 s). Décision D1 demandée à Ilyas (impact puis noir, ou déplacer la caméra).
- Cap : rotation Z -150 (centre de l'image au 150 deg, départ 129 deg, dépôt 184 deg).
