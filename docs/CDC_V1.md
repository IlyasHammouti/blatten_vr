# Cahier des charges V1 (31 octobre 2026, mis à jour le 1er novembre)

Remplace la partie pilotage de `docs/PLAN_V1.md`. Marqué (défaut) : choisi par Claude, à corriger par Ilyas si besoin.

## 1. Livrables et calendrier

- **Brouillon HD plat** : lancé quand Ilyas dit « go ». Sert à voir les détails et à corriger.
- **V1** : vidéo 360° YouTube, 3840x1920 mono, 30 i/s, son spatial ambisonique (AmbiX, 4 canaux). Livrée le **25 novembre** au plus tard.
  Rendu V1 lancé par Claude quand le brouillon plaît à Ilyas (au plus tard vers le 12 novembre).
- Méthode : Pareto. Réaliste, pas parfait. Les retours d'Ilyas sur les vidéos de l'événement servent à la version suivante.

## 2. Déroulé du film (69 s: 1 830 images rendues + 8 s d'outro au montage)

| Partie | Durée | Contenu |
|---|---|---|
| Intro | 8 s (5 s + 3 s de calme ajoutées) | Paysage calme, eau et arbres qui bougent. Texte « Blatten, Switzerland / 28 May 2025, 15:24 » dans le ciel, vers la vue de départ (cap ~200°), légèrement caché par le sommet du versant d'en face. Visible 5 s puis s'efface. Aspect : lettres sombres (choisi le 1er nov. sur les images tests, le blanc se lit mal sur le ciel couvert). |
| Événement | t = 0 à 53 s simulées | Simulation de Johan. Fondu au noir rapide de 52 à 53 s, la vue est obstruée par la matière et la poussière. |
| Outro | 8 s (défaut) | Écran noir, texte blanc simple, posé à l'horizon dans la direction de l'événement (cap ~128° en 360, 150° dans la bande pour qu'il tienne entier). Texte et balises dans `reglages/outro.json`. Image fixe rendue dans Blender (`src/scene/outro.py`), fondus d'entrée et de sortie au montage. |

L'heure 15:24 (13:24 UTC) vient de l'étude sismique de l'effondrement principal.

## 3. Scène

- **Caméra** : inchangée (`camera.json`).
- **Disparition des arbres et maisons** : désactivée.
- **Matière** : peau « mixte » actuelle. Couleur de base #BEAB98, blocs plus clairs et plus sombres.
- **Poussière** : nouveau modèle en 3 étapes, plusieurs foyers simultanés.
  1. Fusées : jets de poussière qui partent de la masse, trajectoire surtout horizontale, légère montée puis retombée (courbe convexe).
  2. Champignons : à l'impact au sol, bouffées qui gonflent et montent.
  3. Nuage : les champignons grossissent dans la vallée, deviennent moins définis et se fondent en un plus grand nuage.
  Couleurs : base #B9AB98, ombre #635B4E. Réglages dans `reglages/poussiere_v3.json` (fusées: 35 % des sources hautes, arc de 60 m; champignons: sources à moins de 250 m du fond de vallée, chapeau qui monte de 180 m avec un pied; nuage: de 10 à 25 s d'âge, grossit et devient flou). Ajustés plus tard avec les commentaires d'Ilyas.
- **Bug du nuage coupé net** (vers 26 s du brouillon 360) : non reproduit hors de la scène. Cause probable: chaque bouffée changeait brutalement de classe de densité (sauts d'un facteur 2,2). La V3 décompose la densité sur des niveaux 1, 1/2, 1/4, 1/8 (sauts de 1/16 au plus). À vérifier sur le brouillon HD.
- **Arbres** :
  - Modèles proches (< 120 m) : épicéa et mélèze générés avec plus d'étages, irréguliers et retombants; feuillus en plusieurs masses. (Le modèle d'épicéa téléchargé est abandonné pour la V1: pas d'accès réseau aux banques de modèles depuis l'environnement de travail.)
  - Vent : balancement léger mais visible, plus fort en hauteur, et frémissement des branches. Fini l'effet de paysage figé.
  - Arbres couchés vers l'aval à l'arrivée du front (souffle et débris, observés dans les vidéos et l'étude de 2026): rotation de 75° autour du pied en 2 s, 1,5 s avant la matière, direction donnée par l'avancée du front (17 653 arbres concernés).
- **Eau** : polygones numérisés par Ilyas, reflets d'écoulement (inchangé).

## 4. Brouillon HD plat (option B, décidée le 31 oct.)

- Bande équirectangulaire 2560x1280 découpée dans le 360: caps 105° à 235° (130°), hauteurs -30° à +35°. Contient la vue de départ (titre) et l'événement. Environ 20 px par degré, presque deux fois plus net que le 360 final.
- Mêmes réglages de scène que le final. 24 échantillons avec débruitage (le final en a 96): 2 à 5 min par image sur la RTX 2060.
- 15 images/s calculées, recopiées à 30 i/s (`--pas 2 --intro-pas 2`): 915 images.
- Lancement: `Lancer_brouillon_hd.bat` (= `python blatten.py render --qualite bande --pas 2 --intro-pas 2`, puis `finir --format bande`). Chaque rendu a son dossier daté, rien n'est écrasé.

## 5. V1 360 HD

- Préréglage final actuel, rendu partageable entre plusieurs PC (`--de` / `--a`).
- Vérification automatique des images, nouveau rendu des images suspectes, puis montage.

## 6. Son (script Python, `src/audio/son.py`)

- Sons dans `<données>/sons` (originaux dans `sons/brut`, licences dans `sons.json`): forêt, tempête (souffle), G43-02 « thunderous » (départ et impacts, utilisé aussi à la place du « distant »), grondement sourd, séisme. Pas de rivière (on ne l'entend pas dans les vidéos).
- Direction, distance et énergie de l'écoulement lues dans les sources de poussière du cache (particules rapides toutes les 2 s). Retard du son à 343 m/s: le premier son arrive environ 9 s après le début de l'effondrement. Aigus étouffés avec la distance. Souffle quand le front est à moins de 1 km. Compression douce, forêt à environ -36 dBFS. Coupure avec le fondu au noir, outro muette.
- Sorties: `son_ambix.wav` (4 canaux AmbiX, face = cap 200°) pour le 360, `son_stereo.wav` (face = cap 170°) pour la bande.
- Réglages des volumes: `reglages/son.json` (facultatif, valeurs par défaut dans le script).

## 7. Montage (script Python)

`src/scene/montage_film.py` (ffmpeg, ou le paquet Python imageio-ffmpeg): images -> fondu au noir sur la dernière seconde -> outro -> son -> MP4 H.264; métadonnées 360 pour le format 360 (`inject_360.py`). Les métadonnées d'audio spatial YouTube (boîte SA3D) restent à ajouter pour la V1. `python blatten.py finir --format bande|360` refait outro, son et montage d'un rendu.

Vérification: `src/scene/verif_images.py` repère les images vides et les sauts isolés (comparaison par tuiles).

## 8. Organisation du code

- Un script par brique, lançable seul : installation et vérification (`setup.py` : Blender, GPU, Python, téléchargement des données, préparation, mesure d'une image et estimation du temps total), rendu, poussière, titres (intro et outro), son, montage, vérification des images.
- `blatten.py` : lanceur avec menus organisés, permet tout depuis un seul script.
- Fonctionne sous Windows et Linux (PC de Johan probable). Données de particules en paquet zip à héberger.

## 9. Hors V1

Mesure de la hauteur du nuage sur les vidéos, MATTER (préparation du stage), PC de Johan, pin du premier plan.

## 10. Reste à fournir

- Texte final de l'intro et de l'outro (balises en attendant).
- Vérifier sur Freesound la licence CC0 de G43-01 et G43-02 (craigsmith).
- Modèle de GPU du PC de Johan.
- Hébergement du paquet de particules: pas nécessaire tant que le rendu se fait sur les PC du groupe.
