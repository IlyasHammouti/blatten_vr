# Handover unifié : Blatten VR (environnement + aléa dans une seule conversation)

État au 15 octobre 2026. À coller au début d'une nouvelle conversation Claude, dépôt `C:\Dev\blatten-vr` connecté.
Ce document remplace `docs/HANDOVER_ALEA.md` (ses sections techniques restent valables) et regroupe ce qui était réparti entre les conversations ENV
(environnement, caméra, relief, bâtiments, arbres, ciel, brume, bench) et ALEA (avalanche, dépôt, poussière). **La nouvelle conversation tient les deux.**
Ilyas est l'humain.

## 0. Pour démarrer (dans cet ordre)

1. `git status`, `git log --oneline -8`, `git fetch`. Lire `docs/journal/env.md` et `docs/journal/alea.md` (le journal est la mémoire du projet).
2. Se placer sur la branche `alea` (voir §4). Ne jamais faire `git checkout .` ni `git add -A` (voir pièges §4).
3. Demander à Ilyas les trois résultats en attente (§9) avant de prendre une décision de fond.
4. Faire un `TaskCreate` pour la séance, et finir par une entrée de journal (§10).

## 1. Projet en six lignes

- Vidéo immersive 360° de l'avalanche de roche et de glace de **Blatten** (Valais, 28 mai 2025, 15 h 24 CEST), pour le colloque
  « Mouvements de terrain : aléas et réponses des sociétés » (CNRS Thiais, 3 et 4 décembre 2026). **Première version (V1) à rendre le 25 novembre 2026.**
- Simulation MPM de **Johan Gaume** (ETH/SLF) : 202 fichiers PLY (un par seconde simulée), 1 168 808 particules chacun, résolution 4 m.
- Rendu **Blender 5.2 LTS (Cycles)**, équirectangulaire 3840x1920 mono, 30 images/s, environ 1 minute (5 s d'intro paysage, ~40 s d'événement, générique de fin).
  Caméra fixe, un seul point de vue, ciel couvert, brume avec la hauteur. Diffusion : YouTube 360, consultation individuelle sur smartphone via QR code.
- **Priorité décidée : immersion et réalisme d'abord, exactitude scientifique ensuite.** Ne pas déformer la simulation sans raison, mais un rendu crédible prime.
- Vidéo muette dans le dépôt. Le son (ambisonique 1er ordre AmbiX 4 canaux, Reaper + IEM Plugin Suite) est un chantier d'Ilyas, hors code du dépôt.
- Crédits de fin à Johan Gaume, qui peut réutiliser la vidéo. Il n'a pas à être sollicité sauf blocage (questions au §8).

## 2. Personnes et façon de travailler avec Ilyas

- **Ilyas** (M2 Géographie, parcours Dynarisk, Paris 1) : décide, lance les rendus, renvoie les images. Code le projet en « vibe coding » avec l'IA, sans compétences de modélisation 3D de base :
  il faut donc des commandes exactes à copier et des messages d'erreur lisibles.
- **Maxime Lescarret** (camarade M2) : a dit le 7 octobre vouloir prendre la matière (particules) avec son propre assistant et partager son code sur GitHub, fusion prévue ensuite
  (voir `docs/HANDOVER_IA_MATIERE.md`). Le 8 octobre, Ilyas a dit qu'il se chargerait lui-même du rendu de l'aléa. **Non clarifié depuis : à demander à Ilyas** si Maxime produit sa propre matière
  (sinon on risque de refaire le même travail). Toute décision du contrat contraire à un choix du groupe doit être annoncée à Ilyas, qui préviendra Maxime et Johan avant.
- **Johan Gaume** : fournisseur des données. Ne le déranger que si on est bloqué, via Ilyas.

**Préférences d'Ilyas (à respecter dans chaque réponse) :**
- Français, direct, bref, sans flatterie. **Jamais de tirets cadratins** (utiliser virgules, deux-points, parenthèses).
- Il veut qu'on dise quand quelque chose est faible, incertain ou n'en vaut pas la peine, et qu'on le contredise quand les faits l'exigent, y compris sur une décision déjà prise.
  Recommandations calibrées : distinguer le solide du plausible.
- Il veut un pipeline compréhensible par tous (Maxime, plus tard Johan). Tous les scripts lancés par double-clic doivent attendre Entrée avant de fermer la fenêtre (pour lire les erreurs).
- Il n'a pas le temps d'apprendre Blender en profondeur : minimiser ce qu'il doit faire à la main.

## 3. État au 15 octobre

### Environnement (ENV) : figé le 13 octobre

- **Caméra finale validée par Ilyas** (`camera.json`, `confirmed: true`) : position Blender (-643,73 ; 769,57 ; 1685,6), rotation (90 ; 0 ; -69), hauteur d'yeux 2 m (`z_sol_plus: 2.0`).
  Ne pas la changer sans raison : le masque de visibilité en dépend.
- Relief swisstopo en anneaux 0,5 / 1 / 2 / 8 / 32 / 128 m, images 2 m, 50 cm, 10 cm. Bâtiments swissBUILDINGS3D (1 841 sur 7 km, motifs procéduraux par type), arbres (essences OFEV,
  jusqu'à 4,6 km, arbustes en avant-plan, vent léger), rivière animée (OpenStreetMap), ciel couvert, brume.
- **Zone visible** (`python blatten.py visible`) : coupe le relief invisible depuis la caméra (~85 % du relief caché). Un couloir protégé autour de l'empreinte de la matière n'est jamais coupé.
- **Empreinte de l'aléa** (`python blatten.py empreinte-alea`, écrit `cache/env/alea_empreinte.npz`, grille 4 m LV95) : `occ` (où passe la matière), `tarr` (première arrivée, s depuis le fichier 1),
  `zfin` (surface du dépôt), `zmax`. Bâtiments et arbres dans l'empreinte sont masqués à `tarr` (balayés).
- Reste côté environnement : modèles d'arbres plus réalistes (décision à prendre), ombres visibles seulement en vue Rendu, **empreinte sur la série complète** (voir risque stride, §8).
- Pas encore d'option `--no-ensevelis` (pour l'éviter : supprimer `alea_empreinte.npz`).

### Matière (ALEA)

- **Interface** (inchangée, ne pas changer la signature sans raison) : `--matiere <nom>` charge `src/matiere/<nom>.py` avec `build(scene, seq, coll, cfg, log, helpers)` et `update(scene, t, seq)`.
  `helpers` : `to_blender`, `frame_to_time`, `apply_height_fog`, `new_collection`, `build_default`. Gabarit : `rendu_matiere.py` (une sphère par particule).
- **Matière A, écrite et commitée** : `src/matiere/matiere_roches.py` (`--matiere matiere_roches`). 4 variantes de roches irrégulières (80 faces) instanciées par Geometry Nodes, rotation et proportions
  aléatoires par particule, bump procédural en coordonnées objet, couleur aléatoire éclaircie par la vitesse (attribut `speed`, vérifié). Réglages dans `REGLAGES`, surchargeables par
  `src/matiere/reglages_matiere.json`. Même coût de reconstruction que le gabarit (positions et vitesse seulement).
  **Testée seulement dans le banc synthétique, jamais dans la vraie scène.**
- **Résultat du banc** (104 000 particules, espacement 6,8 m, 960x540 à 90 degrés = même densité angulaire que la vidéo) : les billes lisses deviennent une masse irrégulière, plus rocheuse.
  Limite honnête : à cette échelle ça se lit comme un **lit de graviers**, pas comme une masse qui coule. Poussière, contraste et cohésion de la masse restent à faire dans la vraie scène.
  Coût sur le CPU du cloud (2 cœurs, non représentatif) : +50 % de temps de rendu par rapport au gabarit (32,7 s contre 21,7 s). **À mesurer avec `bench` sur la RTX 2060.**
- **Interpolation** : `Sequence.state` (scène) fait un fondu des extrapolations avant/arrière : à mi-chemin elle ajoute `(dt/4)(v0-v1)` au lieu de `(dt/8)(v0-v1)`, donc rate le terme d'accélération
  (erreur `a·dt²/8`, de même grandeur qu'un fondu linéaire). `src/matiere/interpolation.py` fournit `etat(seq, t)` en Hermite cubique (retombe sur `seq.state` hors plage ou si la séquence n'a pas `.times/.arr`).
  Sur données **synthétiques** à 1 s d'écart : erreur médiane 0,06 m contre 2,2 m. **À confirmer sur les vraies données.** Si confirmé, proposer à soi-même (ex-ENV) de remplacer `Sequence.state` dans la scène,
  pour que `empreinte-alea` et la matière par défaut partagent la même interpolation.
- **Outils d'analyse écrits, pas encore lancés par Ilyas** (§9) : `analyse_temps.py` (chronologie, fenêtre de temps), `test_interpolation.py` (erreur d'interpolation et pas de temps réel entre fichiers).
- **Banc de test** `src/matiere/banc_test.py` : terrain et particules synthétiques, caméra à 2 m, dépôt à ~540 m. Juge la forme et le coût, pas la couleur finale (dépend de l'ortho et de la brume réelles).
- **Pas fait** : surface cuite hors ligne (B'), dépôt (recouvrement du fond de vallée avec `zfin`), poussière et nuage, retrait de la matière cachée derrière les crêtes (masque `visible_2m`), mesure `bench` complète.

## 4. Dépôt, git et pièges de cette machine

- Remote : `github.com/IlyasHammouti/blatten_vr`. `main` contient tout le travail ENV jusqu'à `ee09fea`. Branche **`alea`** (locale, **non poussée à ma dernière vérification le 14 octobre**) = `main` + trois commits `[alea]` :
  `a8f7be2` (journal séance 1, `analyse_temps.py`), `a4fb518` (journal séance 2, plan, demandes à ENV), `dddaa6c` (matière A, interpolation, test d'interpolation, banc de test).
  Un commit de plus s'ajoutera avec ce document. Avant de pousser : `git pull --rebase origin main`, jamais de `push --force`, fusion dans `main` par pull request.
- Convention : petits commits, un sujet par commit, préfixe `[env]` ou `[alea]`. Ajouter les fichiers **un par un** (`git add <fichier>`), jamais `git add -A` ni `git add .`. Données lourdes jamais dans git (`.ply .npy .vdb .blend .tif`, dossier `render/`).
- **Fichiers modifiés non commités qui ne sont pas à toi** : `camera.json` (la caméra finale validée existe seulement dans la copie locale d'Ilyas, `main` a l'ancienne : à faire commiter, avec l'accord d'Ilyas,
  sinon tout autre clone rend avec la mauvaise caméra), `src/environnement/prep_vegetation.py` et `src/matiere/analyse_temps.py` (changements de fins de ligne seulement). Dossier `_to_delete/` à la racine (fichiers écartés par ENV).
- **Pièges de la session** :
  - Les fichiers du dépôt sont en CRLF dans le dossier de travail Windows alors que l'index est en LF (`core.autocrlf` non défini) : `git status` montre des fichiers « modifiés » sans vrai changement.
    Vérifier avec `git diff --ignore-cr-at-eol --stat`. Ne jamais réécrire un fichier de l'index avec des fins de ligne converties sans le vouloir.
  - Le shell de l'appareil (`device_bash`) tourne dans une VM Linux sans suppression : git y laisse des `.lock` et des `tmp_obj_*` qui bloquent les commandes suivantes. Après un `commit` ou un `fetch` :
    `mv .git/HEAD.lock .git/stale-HEAD.lock-<n>` (idem `maintenance.lock`, `index.lock`), jamais sous `.git/refs`, et jamais un verrou qu'un git en cours pourrait tenir. Ou demander `device_request_delete_permission` (une seule fois, pour `C:\Dev\blatten-vr`).
  - Identité git absente : committer avec `git -c user.name="Ilyas Hammouti" -c user.email="e.hammouti01@gmail.com" commit ...`, sans toucher à la config globale.
  - Le shell peut mettre 30 à 60 s à démarrer (« Workspace still starting ») : réessayer.
- Fins de commit demandées par l'environnement : `Co-Authored-By: Claude <modèle courant> <noreply@anthropic.com>` et la ligne `Claude-Session:` fournie en début de session.

## 5. Accès, outils et limites d'une session Claude

- La conversation voit **seulement `C:\Dev\blatten-vr`** (monté sous `$HOME/mnt/blatten-vr` dans le shell de l'appareil). **Pas** les données (PLY, `.npy`, swisstopo : `D:\OneDrive\...\Blatten`) ni Blender (`F:\Program Files (x86)\Blender\blender.exe`).
  Les chemins locaux d'Ilyas sont dans `config.local.json` (non versionné).
- `device_bash` = shell Linux sur l'appareil, pas de Python Windows ni de Blender. Les rendus et mesures sur vraies données sont lancés **par Ilyas**, qui renvoie résumés et images.
  Pour voir une image du dépôt : la copier dans un dossier du dépôt (par ex. `render/_tmp/`, ignoré par git), `device_stage_files`, puis `Read`. Pour écrire un fichier dans le dépôt depuis le cloud : le placer dans
  `/mnt/user-data/outputs/` puis `device_commit_files`.
- **Banc de test dans le cloud** : `pip install bpy` (5.2.2 LTS, Python 3.13, même version majeure que le projet), 2 cœurs, 7 Go de RAM. Les rendus CPU sont lents mais suffisants pour juger une forme (960x540 en 20 à 35 s).
  `python src/matiere/banc_test.py --module matiere_roches --t 38 --out x.png` (`--module rendu_matiere` pour comparer au gabarit ; `--spacing 4.0` = stride 1, `6.8` = stride 5).
- Le module `bpy` pip n'a pas l'encodeur vidéo FFMPEG : images PNG seulement dans le cloud.

## 6. Pipeline : commandes (sur le PC d'Ilyas, depuis la racine du dépôt)

Menu lanceur : `lancer_blatten.bat` (rubriques « Préparer l'environnement », « Aléa (matière) », etc.). Guides : `README.md`, `TUTO.md`. Références que je n'ai pas relues : `docs/ARCHITECTURE.md`, `docs/PREREQUIS_VERSION_FINALE.md`.

- Images test : `python blatten.py test360 --mono --matiere <nom> --frames 1 4000 --render-frame 601` (image 601 = t = 20 s à 30 images/s). **Toujours `--mono`** pour les images fixes. Sans environnement (plus rapide) : `--no-env`.
- Quelques secondes d'événement : `python blatten.py test-clip --start 50 --seconds 3 --stride 5 --matiere <nom>` (`--clip-scale 1.0` pour la pleine résolution, le défaut 0,5 est un piège).
- Temps de rendu de la scène : `python blatten.py bench` (à relancer après un gros changement de matière).
- Environnement : `download`, `prep-env --hires`, `visible` (mêmes niveaux que la scène : `--no-hires` si la scène est lancée ainsi), `empreinte-alea` (relancer `visible` après), `voir360` (visionneuse locale `tools/voir360.html`), `lite`, `comparer`.
- Données de Johan : `src/matiere/prep_particules.py` (PLY vers `.npy` colonnes `x y z vx vy vz mu_b`, vitesses en m/s, `meta.json`, option `--stride N`).
- Analyses ALEA : `python src/matiere/analyse_temps.py`, `python src/matiere/test_interpolation.py` (sorties dans `render/alea/`).

## 7. Faits techniques à connaître

- **Repère.** Johan est en Y vertical, Blender en Z vertical : `(x, y, z) -> (x - Ox, -(z - Oz), y - Oy)`, `O = [1117.4016956592827, 0.0, -1121.1231332002285]` (dans `meta.json`). Z Blender = altitude réelle.
  Coordonnées suisses : `E = 2629118.28 + X`, `N = 1140115.05 + Y`. Calage médian 0,69 m. **Ne pas changer le repère** : le terrain ne serait plus aligné.
- **Temps.** Un fichier = 1,0 s de simulation (`dt_per_step = 1.0` dans `config.json`), le contrat évoque ~1,04 s : `test_interpolation.py` le mesure. Image `f` de la vidéo : `t = (f - image_début) / fps / time_scale`.
  Fichier 0 au repos, mouvement dès le fichier 1, vitesse moyenne ~58 m/s vers t = 20 s, quasi arrêt vers le fichier 150.
- **Géométrie.** Particules de 4 m, rayon par défaut 0,6 fois la distance médiane au plus proche voisin (~2 m). À ~0,5 km, 1 pixel de la vidéo ≈ 0,9 m : **une particule couvre 4 à 5 pixels**, d'où l'effet de perles. Les particules sortent dans le même ordre d'un fichier à l'autre (vérifié) : interpolation par indice valide.
- **Positions repères depuis la caméra finale** (calculées, à vérifier sur un rendu) : centre du dépôt ~540 m, ~200 m en contrebas ; zone de départ ~3 km et ~1 060 m plus haut ; dépôt final X de -1417 à 214, Y de -428 à 908, altitude 1430 à 1545 m.
  **Cap :** avec la rotation (90, 0, -69) le centre de l'image pointe vers l'ENE ; la zone de départ est ~60° à droite et le centre du dépôt ~110° à droite. Aucune métadonnée de cap initial dans l'injection 360 (`src/scene/inject_360.py`).
- **Rendu.** Machine d'Ilyas : Ryzen 5 3600, 16 Go de RAM, RTX 2060 6 Go, Windows 11, ~1,2 To libres. Mesures (234 000 particules, stride 5, 3840x1920 mono) : 24 échantillons 49 s, 48 : 58 s, 96 : 77 s, 192 : 122 s par image (≈ 40 s de coût fixe + 0,43 s par échantillon).
  Le contrat citait 69 s + 0,62 s (plus pessimiste, ancienne mesure). **La mémoire GPU de 6 Go est la limite dure** (terrain HD + matière + textures). Plus de la moitié du temps d'image est un coût fixe de reconstruction : une matière légère à reconstruire vaut mieux qu'une matière très chargée.
- **Brume et visibilité.** Brume en shader (`--fog 0.6`) : à 2,5 km l'avalanche est presque invisible, à 0,5 km c'est moins vrai mais le contraste de la matière reste à travailler. Ciel couvert (lumière diffuse, comme le 28 mai 2025).
- **Poussière.** Aucune donnée de Johan : à inventer de façon plausible, sans prétendre à l'exactitude. Ilyas compte décrire le ciel et le nuage d'après des vidéos de Blatten. Interagit avec la brume.

## 8. Décisions ouvertes et risques (calibrés)

1. **Fenêtre de temps** (202 s de simulation, ~40 s de vidéo, le contrat dit « pas d'accélération », hypothèse non tranchée). À 1x on risque de ne jamais montrer le dépôt. `analyse_temps.py` donne début, pic, 90 % de la distance, arrêt et facteur d'accélération nécessaire. **C'est la décision qui conditionne le plus la suite.**
2. **Cap de la caméra** : l'événement n'est plus au centre de l'image. Intentionnel ? Sinon : modifier la rotation (en prévenant, le masque `visible` dépend de la caméra) ou injecter un cap initial YouTube. À trancher avant de figer la fenêtre de temps.
3. **Stride du cache et empreinte** : `empreinte_alea.py` dit « rien ne manque » (grille 4 m = taille d'une particule), vrai seulement à stride 1. À stride 5 (espacement ~7 m) `zfin` et `tarr` ont des trous.
   Vérifier le `stride` de `meta.json`. Si > 1 : recalculer l'empreinte à stride 1 (CPU, une fois) ou dilater. ENV signale aussi que l'empreinte sur la série complète reste à faire (le cache est peut-être partiel : `analyse_temps.py` peut échouer ou être partiel).
4. **Budget de rendu sur un seul PC** : Ilyas pense ne pouvoir compter que sur son propre PC (le PC d'un ami en Intel Arc ne compte pas ; Maxime a peut-être une meilleure config, non confirmé). Le plan « deux PC » du contrat n'est donc pas acquis.
   Ordre de grandeur : 1 200 images × 77 s (96 échantillons) ≈ 26 h sans la matière ; avec une matière +30 à +50 % (estimation, non mesurée sur GPU) ≈ 33 à 39 h. Faisable, mais sans marge en cas de bug. Leviers : 48 échantillons (58 s, ≈ 19 h), moins d'images calculées (interpolation vidéo : à éviter, le contrat dit pas de rendu intermédiaire à 1 image/s), débruitage.
   **Le rendu final doit démarrer au plus tard le 12 à 15 novembre** pour livrer le 25.
5. **Dépôt** : le terrain swisstopo est celui d'avant l'événement, il faut le recouvrir par la matière (`zfin`, maillage ou mélange avec le relief). Question à Johan : son terrain de simulation est-il d'avant ou d'après ?
6. **Lisibilité à 0,5 km** : A améliore la forme mais reste un lit de graviers. Pistes si la vraie scène le confirme : (a) surface cuite hors ligne par image (densité des particules, marching cubes, maillage allégé chargé dans `update`) avec relief procédural, plus des roches instanciées sur le bord ; (b) lissage et variations de teinte à grande échelle ;
   (c) poussière en volume ou en particules secondaires pour casser le motif. B' est plus risquée (cohérence temporelle de la surface, mémoire GPU) : ne l'engager que sur preuve visuelle.
7. **Maxime** : qui produit la matière (§2) ?
8. **Questions pour Johan, seulement si bloqué (via Ilyas)** : instant du premier fichier par rapport à 15 h 24 ; pas de temps exact (1,0 ou 1,04 s, peut être mesuré sans lui) ; sens de `mu_b` (constant dans l'extrait lu) ; présence de poussière dans la simulation ; terrain avant ou après ;
   fenêtre de 2 m et de 24 images par seconde évoquée plus tôt (à préciser avec Ilyas).

## 9. Prochaines actions immédiates

**À demander à Ilyas, dans cet ordre (il les lance sur son PC, depuis la racine du dépôt) :**
1. `python src/matiere/analyse_temps.py` : coller le résumé (fenêtre de temps).
2. `python src/matiere/test_interpolation.py` : coller le résumé (erreur d'interpolation, pas de temps réel). Lui demander aussi le `stride` de `meta.json`.
3. `python blatten.py test360 --mono --matiere matiere_roches --frames 1 4000 --render-frame 601` puis le même avec `--matiere rendu_matiere` : envoyer les deux images. En cas d'erreur, coller le message. Un `test-clip` de 3 s suivra.

**Selon les résultats :**
- Interpolation Hermite confirmée (erreur nettement plus faible que la méthode actuelle) : remplacer `Sequence.state` par `interpolation.etat` dans la scène, en le journalisant.
- A tient dans la vraie scène : régler couleur, contraste, poussière dans l'environnement réel, mesurer `bench`, puis décider si B' vaut le coup.
- A ne tient pas : lire l'erreur, corriger, ne pas empiler d'autres chantiers.
- Fenêtre de temps choisie : choisir `time_scale` et la plage de fichiers, régler l'intro (5 s) et le générique avec Ilyas, et refaire `empreinte-alea` si la plage change.
- Faire commiter `camera.json` (accord d'Ilyas) et pousser `alea` pour sortir du « tout en local ».

## 10. Plan jusqu'à la V1 (dates visées)

| Dates | Tâche |
|---|---|
| 15-17 oct | Résultats des 3 commandes, décision de fenêtre de temps, réponse sur le cap, stride du cache |
| 17-24 oct | Matière A dans la vraie scène (couleur, contraste, coût), `bench`, décision B' |
| 24-31 oct | Interpolation validée, choix de la représentation, retrait de la matière cachée (`visible_2m`) |
| 1-8 nov | Dépôt (recouvrement du fond de vallée avec `zfin`), poussière et nuage à budget mesuré |
| 8-12 nov | Gel de la matière, `bench` complet, aperçu basse résolution des ~40 s, décision de répartition (1 ou 2 PC) |
| 12-22 nov | Rendu des 1 200 images (marge ×1,5), encodage, métadonnées 360, test YouTube |
| 22-25 nov | Marge, intro et générique, livraison de la V1 |

Pour chaque jalon, dire à Ilyas ce qui est réellement fait, ce qui reste, et signaler tôt si une échéance est menacée.

## 11. Fin de séance

Écrire dans `docs/journal/alea.md` (et `env.md` pour ce qui touche l'environnement) : date, ce qui marche, ce qui reste, décisions du contrat à changer, temps de rendu mesurés, demandes en attente. `git pull --rebase origin main`, commits ciblés, pousser `alea`, dire à Ilyas quoi relire ou lancer.
Mettre à jour `docs/CONTRAT_MATIERE.md` quand une décision change (ce document-ci n'est pas un contrat). Si ce handover devient obsolète, le réécrire plutôt que d'en empiler un autre.

## 12. Fichiers ajoutés côté ALEA (tous dans `src/matiere/` sauf mention)

`matiere_roches.py` (matière A), `interpolation.py` (Hermite), `analyse_temps.py` (chronologie), `test_interpolation.py` (erreur et pas de temps), `banc_test.py` (banc synthétique), `reglages_matiere.json` (facultatif, non créé), `docs/journal/alea.md`.
Gabarit d'origine conservé : `rendu_matiere.py`.
