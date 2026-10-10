# Handover : modélisation de l'aléa (conversation "ALEA")

À coller au début d'une nouvelle conversation Claude, avec le dépôt à jour (`git pull`). Ce document est fait pour que **deux conversations
travaillent en parallèle sans se gêner** : la conversation **ENV** (environnement, caméra, relief, bâtiments, arbres, ciel, brume, bench)
et la conversation **ALEA** (tout ce qui concerne la matière : avalanche, dépôt, poussière). Ilyas est l'humain des deux.

## 1. Projet en cinq lignes

Vidéo immersive 360° de l'avalanche de roche et de glace de Blatten (Suisse, 28 mai 2025, 15 h 24 CEST) pour le colloque
« Mouvements de terrain : aléas et réponses des sociétés » (CNRS Thiais, 3 et 4 décembre 2026). Première version à rendre le **25 novembre 2026**.
Simulation de Johan Gaume : 202 fichiers PLY (un par seconde simulée), 1 168 808 particules chacun, résolution 4 m.
Rendu Blender 5.2 LTS (Cycles), équirectangulaire 3840x1920 mono, 30 images/s, environ 1 minute (5 s d'intro, environ 40 s d'événement, générique),
diffusé sur YouTube 360 (QR code, smartphone). Priorité : **immersion et réalisme**, l'exactitude vient ensuite.

## 2. Ta mission (ALEA)

Transformer les particules de Johan en une matière crédible, fluide et assez légère à rendre : représentation (surface, instances, volume),
matériaux, interpolation entre fichiers, dépôt final fusionné avec le terrain, poussière et nuage. Tu t'en occupes **seul avec Ilyas**.
Les décisions déjà prises (Décidé, Hypothèse, Libre) sont dans `docs/CONTRAT_MATIERE.md` : c'est ton document, tu le tiens à jour.
Une décision du contrat n'est pas un interdit : si une bonne solution va contre, dis-le à Ilyas, qui préviendra le groupe (Maxime, Johan) avant.

## 3. Règles pour travailler en parallèle (à respecter)

**Qui possède quoi**

| Zone | Propriétaire | Règle |
|---|---|---|
| `src/matiere/` (dont `rendu_matiere.py`, `prep_particules.py`) | ALEA | tu modifies librement |
| `docs/CONTRAT_MATIERE.md`, `docs/journal/alea.md` | ALEA | tu tiens à jour |
| `src/scene/`, `src/environnement/`, `src/bench/`, `blatten.py`, `config.json`, `camera.json`, `data_sources/` | ENV | **tu ne les modifies pas** (voir « demander un changement ») |
| `docs/journal/env.md` | ENV | tu le lis, tu ne l'écris pas |

**Le point de contact unique avec la scène** est le module `src/matiere/rendu_matiere.py`, chargé par `--matiere rendu_matiere`
(`python blatten.py test360 --matiere rendu_matiere`). Deux fonctions, décrites en tête du fichier :
`build(scene, seq, coll, cfg, log, helpers)` et `update(scene, t, seq)`. Tu peux créer d'autres modules dans `src/matiere/` et les importer
depuis celui-là. Ne change pas la signature de ces deux fonctions sans prévenir ENV.

**Demander un changement à ENV** : écris-le dans `docs/journal/alea.md` (section « Demandes à ENV », une ligne : quoi, pourquoi, urgence) et dis-le à Ilyas.
ENV lit ce fichier au début de chaque séance. Même chose dans l'autre sens : ENV écrit ses changements qui te concernent dans `docs/journal/env.md` ;
**lis-le au début de chaque séance** après `git pull`.

**Git**
- Travaille sur la branche `alea` (`git checkout -b alea`). Fusion dans `main` par pull request quand ça tourne, jamais de `push --force`.
- Avant de pousser : `git pull --rebase origin main`. Petits commits, un sujet par commit, préfixe `[alea]`.
- N'utilise jamais `git add -A` ni `git add .` : ajoute les fichiers un par un. Les données lourdes (`.ply`, `.npy`, `.vdb`, `.blend`, `.tif`, dossier `render/`) ne vont pas dans git (voir `.gitignore`).
- Si un conflit touche un fichier ENV, **ne le résous pas toi-même** : garde la version `main` et préviens Ilyas.

**Ce qui est partagé et ne change pas sans prévenir l'autre conversation** : le repère (§5), le format de `meta.json`, `camera.json`,
la signature `build`/`update`, les noms de réglages de `CFG` (scène), `config.json`.

## 4. Ce qui existe déjà

- `src/matiere/prep_particules.py` : PLY de Johan vers `.npy` (colonnes `x, y, z, vx, vy, vz, mu_b`, vitesses en m/s) et `meta.json`
  (origine, `stride`, `vmax`, statistiques, liste des fichiers). Option `--stride N` (une particule sur N).
- `Sequence` (dans `src/scene/blatten_blender.py`) : lit les `.npy`, **interpole entre deux fichiers** en avançant les positions par les vitesses
  (`seq.state(t)` donne positions et vitesses au temps de simulation `t`, repère simulation, Y vertical).
- Matière par défaut : un point par particule rendu en sphère (Geometry Nodes), couleur aléatoire sombre, brume avec la hauteur.
  `rendu_matiere.py` la reproduit : c'est ton point de départ.
- Environnement : relief swisstopo en anneaux, image aérienne, ciel couvert, brume, soleil réel si `--sky clair`.
  Il est calé sur la simulation (écart médian 0,69 m). Tu n'as pas à t'en occuper, mais il faut tester la matière **dedans** : une matière jolie sans le terrain ne dit rien.

## 5. Faits techniques à connaître

**Repère.** Johan est en Y vertical, Blender en Z vertical : `(x, y, z) -> (x - Ox, -(z - Oz), y - Oy)`, origine
`O = [1117.4016956592827, 0.0, -1121.1231332002285]` (dans `meta.json`). Z Blender = altitude réelle. Coordonnées suisses :
`E = 2629118.28 + X`, `N = 1140115.05 + Y`. Ne change pas le repère : le terrain n'est plus aligné sinon.

**Temps.** Un fichier = 1,0 s de simulation (hypothèse à confirmer avec Johan, le contrat parle d'environ 1,04 s). Le réglage `dt_per_step` de la scène
valait 0,01 par défaut (ancien fichier de test) : **il est maintenant à 1,0 dans `config.json`**. Si tu lances la scène à la main (sans `blatten.py`),
ajoute `--dt-per-step 1.0`, sinon tout va 100 fois trop vite. Image `f` de la vidéo <-> `t = (f - image_début) / fps / time_scale`.
Le fichier 0 est au repos, le mouvement commence vers le fichier 1, à t = 20 s la vitesse moyenne vaut environ 58 m/s, et vers le fichier 150 tout est
presque arrêté.
**Question ouverte importante** : la simulation dure 202 s, l'événement dans la vidéo dure environ 40 s. Il faudra choisir une fenêtre de temps
et/ou une accélération (`time_scale`). Le contrat dit « pas d'accélération prévue » (Hypothèse) : à trancher avec Ilyas et le groupe, c'est la décision qui
conditionne le plus ton travail.

**Géométrie.** Particules de 4 m (rayon par défaut 0,6 fois la distance médiane au plus proche voisin, environ 2 m). Les particules sortent dans le même ordre d'un
fichier à l'autre (vérifié), donc l'interpolation par indice est valide. Depuis la caméra actuelle (voir plus bas), 1 pixel de la vidéo fait environ 0,9 m
à 540 m : **chaque particule couvre 4 à 5 pixels**, donc un amas de sphères ressemble à des perles. Il faut une vraie surface ou du détail.
Les particules isolées très proches de la caméra ressortent comme de grosses sphères.

**Caméra (provisoire, ENV la fixera).** Lire `camera.json` ; ne jamais coder la position en dur. Dernière position annoncée par Ilyas : X -731,88, Y 720,95, Z 1693,1,
rotation (94,4 ; 0 ; -129,38). Elle sera abaissée à hauteur d'homme (environ 1,7 m au-dessus du sol) et ajustée de quelques centimètres.
Repères depuis cette caméra : centre du dépôt à environ 0,5 km (Blender X -665, Y 229, Z 1487), zone de départ à environ 3 km et 1 060 m plus haut
(X 1666, Y -1084, Z 2750). Dépôt final : X de -1417 à 214, Y de -428 à 908, altitude 1430 à 1545 m. Le centre de l'image 360 regarde grossièrement vers la zone de départ,
mais vérifie sur un rendu.

**Rendu.** Machine d'Ilyas : RTX 2060 6 Go, 15,9 Go de RAM, Windows 11. Mesures avec 234 000 particules (stride 5), 3840x1920 mono :
24 échantillons 49 s, 48 : 58 s, 96 : 77 s, 192 : 122 s par image. Environ 40 s de coût fixe par image plus 0,43 s par échantillon. Pour 1 200 images, il faut
donc rester sous quelques dizaines d'heures : **une matière rapide à reconstruire vaut mieux qu'une matière très chargée**. Prévu : rendu sur deux PC.
La mémoire GPU de 6 Go est la limite dure (terrain haute résolution + matière + textures).

**Brume et visibilité.** La brume en shader (`--fog 0.6`) blanchit le lointain : à 2,5 km, l'avalanche est presque invisible. À 0,5 km c'est moins vrai, mais le contraste de
la matière est à travailler (c'est une de tes tâches). Le ciel couvert est le choix du groupe (lumière diffuse, comme le 28 mai 2025).

**Poussière.** Pas de donnée de Johan là-dessus : à inventer de façon plausible, sans prétendre à l'exactitude. Elle interagit avec la brume (réglage ENV) : coordonne-toi.

## 6. Comment tester

- Où tu travailles change ce qui est possible. **Sur le PC d'Ilyas** : données réelles, GPU, Windows ; `python blatten.py <commande>`. **Dans un cloud** : pas de GPU, 8 Go de RAM,
  pas d'accès à swisstopo ni aux PLY ; on teste avec `pip install bpy` (Blender comme module Python) via un petit lanceur qui fait semblant d'être `blender`
  (script `fakeblender` : il lit `--python script -- arguments`, voir `config.local.json` pour pointer `blender_exe` dessus). Les rendus CPU sont lents (1 à 2 min pour 1024x512).
  Le module `bpy` pip n'a pas l'encodeur vidéo FFMPEG : on rend des images PNG.
- Image test 360 : `python blatten.py test360 --mono --matiere rendu_matiere --render-frame 601` (image 601 = t = 20 s à 30 images/s, avec `--frames 1 4000`).
  **Toujours `--mono`** pour les images fixes (la stéréo par défaut déforme).
- Quelques secondes d'événement : `python blatten.py test-clip --start 50 --seconds 3 --stride 5 --matiere rendu_matiere`
  (images fixes à plusieurs échantillons, clip, temps mesuré). `--clip-scale 1.0` pour la pleine résolution (le défaut est 0,5 : piège).
- Temps de rendu de toute la scène : `python blatten.py bench`. À relancer après un gros changement de matière.
- Sans environnement (plus rapide, matière seule) : `--no-env`.
- Les images du dossier `render/` ne sont pas dans git. Envoie à Ilyas les images utiles.

## 7. À faire, par ordre de valeur

1. **Rendre la matière lisible à 0,5 km** : surface ou détail à la place des perles, contraste avec le sol, brume (en lien avec ENV pour la brume).
2. **Fenêtre de temps** de l'événement (§5) : la proposer à Ilyas avec un exemple rendu.
3. **Dépôt** : épaisseur, étalement, fusion avec le terrain (le terrain swisstopo est celui d'avant l'événement : il faut le recouvrir par le dépôt, ENV peut fournir la zone ensevelie).
4. **Poussière et nuage** (volume ou particules secondaires), à budget de rendu mesuré.
5. **Interpolation** : vérifier qu'elle est fluide à 30 images/s (1 fichier par seconde simulée), sans saccades ni particules qui traversent le terrain.
6. **Budget** : mesurer avec `bench`, annoncer les temps à Ilyas (objectif : rester compatible avec deux PC et le délai du 25 novembre).

## 8. Questions pour Johan (seulement si bloqué, via Ilyas)

Instant du premier fichier par rapport à 15 h 24 ; pas de temps exact (1,0 ou 1,04 s) ; sens de `mu_b` (constant dans l'extrait lu) ; présence de poussière dans la simulation ;
fenêtre de 2 m et de 24 images par seconde évoquée plus tôt (à préciser avec Ilyas).

## 9. En fin de séance

Écris dans `docs/journal/alea.md` : date, ce qui marche, ce qui reste, décisions du contrat qu'on voudrait changer, demandes à ENV, temps de rendu mesurés. Fais un `git pull --rebase`,
pousse ta branche, et dis à Ilyas quoi relire.
