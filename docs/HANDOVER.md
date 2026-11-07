# Handover Blatten VR (état au 30 octobre 2026)

**Feuille de route (à relire avant chaque rendu ou ajout de fonction): [FEUILLE_DE_ROUTE.md](FEUILLE_DE_ROUTE.md)**

À donner au début d'une nouvelle conversation Claude, avec le dépôt `github.com/IlyasHammouti/blatten_vr` (branche `main`, public).
Remplace le handover unifié du 15 octobre (rangé dans `docs/archive/`). Référence de pilotage: `docs/PLAN_V1.md`; mémoire détaillée: `docs/journal/alea.md` et `env.md`.

## 1. Projet

- Vidéo 360° (YouTube, 3840x1920 mono, 30 i/s, muette dans le dépôt) de l'avalanche de roche et de glace de **Blatten** (28 mai 2025, 15 h 24), pour le colloque
  « Mouvements de terrain : aléas et réponses des sociétés » (CNRS Thiais, 3 et 4 décembre 2026). **V1 le 25 novembre**; le rendu final doit partir **vers le 12 novembre**.
- Film: 1 590 images = 5 s de paysage + 48 s d'événement (t = 0 à 48 s simulées), image f -> t = (f - 1) / 30 - 5. La matière atteint la caméra vers t = 49 s.
- Simulation MPM de **Johan Gaume** (ETH/SLF): 202 fichiers (1 par seconde), cachés en `.npy` à 1 point sur 5 (233 762 traceurs). **Confirmé par Johan (20 oct.)**:
  simulation réalisée APRÈS l'événement et calée pour le reproduire (pas la prédiction). Les points sont des traceurs du mouvement, pas des blocs.
- Rendu Blender 5.2.2 LTS (Cycles, OptiX) sur le PC d'Ilyas (Ryzen 5 3600, 16 Go, RTX 2060 6 Go, Windows 11). PC du frère disponible: RTX 3060 12 Go, 16 Go.
- Ilyas: français, bref, direct, sans flatterie, **jamais de tiret cadratin**, veut qu'on le contredise quand il le faut et des recommandations calibrées. Il lance peu de choses à la main:
  privilégier les `.bat` en double-clic. Johan a proposé un stage à Ilyas (projet Flims, MPM + Houdini): relation à soigner, mails écrits par Ilyas.

## 2. Ce qui marche (30 oct.)

- **Environnement**: relief swisstopo 0,5 m autour de la caméra (anneaux jusqu'à 128 m), images 2 m / 50 cm / 10 cm, 731 bâtiments 3D, 532 000 arbres, ciel couvert, brume, eau.
  Coupe du relief invisible depuis la caméra. Grain fin du sol à moins de 40 m de la caméra (`detail_proche`).
- **Réglages sans code**: `reglages/<nom>.json` (sections `scene`, `matiere`, `depot`, `poussiere`, `herite`), `--reglages a b`, `--set section.cle=valeur`. Défauts commentés en tête de
  `src/matiere/matiere_roches.py`, `poussiere.py`, `depot.py` et dans `CFG` de `src/scene/blatten_blender.py`. Le film lit `reglages/film.json` (via `config.json`). Trace `reglages_effectifs.json` à côté des images.
- **Matière** (`matiere_roches.py`, `matiere.rendu`): `roches` (une roche de 3-5 m par traceur, rendu du 19 oct.), `surface` (peau continue: Points to SDF Grid, rayon selon la densité 3D,
  lissage, retrait, Grid to Mesh 2 m, texture qui suit les traceurs; `src/matiere/surface.py`), `mixte` (peau + blocs 0,4-2,5 m sur les traceurs proches de la peau et sur les traceurs isolés).
- **Poussière**: V1 par défaut, V2 dans `reglages/poussiere_v2.json` (moins de bouffées, plus grandes, freinage plus long, montée réduite, nuage naissant transparent). Modèle visuel, pas de données.
- **Disparition** des arbres, bâtiments et rivière: à l'arrivée de la matière, arrondie vers le haut (avant: jusqu'à 3,5 s trop tôt). Option `ensevelissement` (épaisseurs
  `tep`/`niveaux` dans `alea_empreinte.npz`): essais à 50 % et 10 % de la hauteur écartés, des arbres restaient debout dans la coulée là où la nappe est mince.
- **Commandes** (`python blatten.py ...` à la racine): `variantes` (même instant, plusieurs jeux; `Lancer_variantes.bat`), `camera --lv95 E N | --wgs84 LAT LON [--hauteur 2] [--cap 200]`,
  `render [--qualite brouillon] [--pas 2] [--de N --a M] [--intro-pas 3]` (`Lancer_film_brouillon.bat`, `Lancer_film_hd.bat`; temps par paquet dans `chrono.json`), `paquet` + `duo` + `duo-etat` (rendu à deux PC: docs/RENDU_A_DEUX.md), `images-finales`, `apercu-alea`, `empreinte-alea`, `montage`.
- **Temps mesurés** (t = 43 s, qualité finale, scène complète, RTX 2060): 9 à 10 min par image construction comprise, quelle que soit la matière. GPU jusqu'à 5,6 Go sur 6,1.
  Film: ~175 h sur ce PC seul, ~75 h à deux PC (estimation, PC du frère non testé). `--persistent`: 18 % plus lent, abandonné.
- **Comparaison du 30 oct. au soir** (`render/variantes/t43s/`: `actuel`, `mixte`, `mixte+poussiere_v2`, plus `mixte_v1_19h`; visionneuse claude.ai « Variantes de rendu Blatten »):
  la peau corrigée remplace bien les roches de 3-5 m, mais à t = 43 s la poussière cache l'essentiel de la matière; la V2 fait un voile plus large et plus diffus. Ilyas a choisi peau + poussière V2: `reglages/film.json` hérite de `mixte` et `poussiere_v2`.
  `mixte` 9,8 min, `mixte+poussiere_v2` 8,9 min. Visionneuse GitHub corrigée (sortie sRGB: les images s'affichaient plus sombres que le rendu).

## 3. Ce qui reste (ordre proposé à Ilyas le 30 oct.)

0. **7 nov. (soir)**: tous les tests faits, décisions visuelles prises et écrites dans `reglages/film.json` (journal de docs/FEUILLE_DE_ROUTE.md).
   Rendu final mesuré: environ 160 h seul, 62 h à deux. Fin du film presque noire à 53 s (caméra dans le nuage), gardée.
   Prochaines étapes: `Lancer_test_bande.bat` (contrôle des réglages retenus ensemble, raccord du sol nettoyé près de la caméra),
   choix de l'envoi des images du frère (GitHub), `Lancer_preparer_duo.bat`, `Lancer_rendu_duo.bat`. Outro et son: montage seulement.

1. **Caméra**: Johan conseille un point de vue proche des vidéos SRF (une montre la lave sortir du nuage). Critère d'Ilyas: le spectateur regarde l'aval / Blatten et est surpris
   par l'événement (son, vision périphérique). Décision visée: 4 novembre. Commande `camera`, puis `download --jeux 05m 10cm`, `prep-env --hires`, `visible`.
2. **Choix de la matière et réglage de la poussière** sur les vidéos SRF (transparence voulue par Ilyas, échelle des panaches), puis recopier le choix dans `reglages/film.json`.
3. **PC du frère**: rendu à deux PC codé le 7 nov. (docs/RENDU_A_DEUX.md): `Lancer_preparer_duo.bat` (session, paquet en un zip avec Blender, test du paquet), `Lancer_rendu_duo.bat` chez Ilyas, `LANCER_RENDU.bat` chez le frère. Partage dynamique par messages ntfy.sh, images du frère par GitHub (dépôt privé de transfert), dossier partagé ou SwissTransfer.
   Simulation: le PC d'Ilyas s'arrête vers l'image 970 à 1150 (t = 32 à 38 s), la fin du film (poussière, la plus lourde) va à la 3060 (12 Go).
   Carte de 6 Go pleine sur une image (« out of memory » dans le journal de Blender): le PC qui la rend se limite tout seul et laisse
   les images suivantes à l'autre (annonce `lim` dans son état; sans ça, les deux PC pouvaient s'attendre à la fin). `--max-image N` à la main.
   Réglage `scene.rendu_tuile` (1024 ou 512): moins de mémoire sur la carte; `test-final` l'essaie tout seul si la carte est pleine.
   Essai de fumée du 7 nov. (bpy dans le conteneur, données factices): matériau du sol et de l'eau, titre, réglages de rendu, forêt
   complète (toutes les distances, grappes et lisses): aucune erreur.
4. Pas faits faute d'éléments: rivières tracées à la main (couche `eau_manuel` vide dans `Blatten/QGIS/blatten_alea.gpkg`), pin du premier plan (D4, modèle à fournir).
5. Son, crédits (formulation à demander à Johan plus tard), montage, QR code, test sur téléphone.

## 4. Pièges

- Le shell de l'appareil (`device_bash`) est une VM Linux sans suppression: ne pas y lancer git (verrous laissés dans `.git`). Les `.bat` font `git fetch` + `git reset --hard origin/main` sous Windows.
- Le code se pousse depuis le conteneur cloud (`/home/claude/blatten_vr`); le PC le récupère au prochain `.bat`.
- Blender ne se lance pas depuis la VM: double-clic sur un `.bat` via l'Explorateur (accès « click », fenêtres sur deux écrans, Spotify et Claude prennent de la RAM:
  `blatten.py` attend 7 Go libres jusqu'à 15 min puis part quand même).
- Dans le conteneur: `pip install bpy==5.2.2` permet de tester la scène sans environnement (`--no-env`, terrain de Johan), données du cache récupérées par `device_stage_files`.
  `SDF Grid Offset` avec une distance positive GONFLE la peau.
- Données: `D:\OneDrive\Université\Master Dynarisk\M2\Blatten\pipeline\cache` (particules, `env/`), Blender `F:\Program Files (x86)\Blender\blender.exe`, rendus finaux `D:\Blatten_render`.
- Rangement du 30 oct.: `archive/`, `docs/archive/` (dépôt), `render/_archive/` et `_archive/` (PC, non versionnés). Rien n'a été supprimé.
