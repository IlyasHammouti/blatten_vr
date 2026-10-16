# PLAN V1 : de l'état actuel à la vidéo finale muette

Mis à jour le 15 octobre 2026. **Document de référence unique** (remplace, pour le pilotage, `docs/HANDOVER_ALEA.md` et le handover unifié ;
leurs sections techniques restent valables comme mémoire). Une conversation Claude, une branche (`main`).

## 0. L'objectif, et la règle qui protège l'objectif

**Livrable V1 (25 novembre)** : une vidéo 360° muette, YouTube, 3840x1920, 30 images/s, ~45 s : 5 s de paysage calme, l'avalanche
(accélérée si nécessaire), le dépôt, quelques secondes de fin avec crédits. Regardée **sur smartphone** via QR code.

**Exigence** : un résultat impeccable sur téléphone dans YouTube 360. Le spectateur qui tourne la tête voit une scène crédible de bout en bout :
la masse qui descend, la poussière, le fond de vallée enseveli, un décor sans défaut (pas de trou, pas de scintillement, pas d'objet faux).
On juge les images dans la visionneuse 360 (`voir360`) ou sur téléphone : la vue 3D de Blender ne montre ni le soleil ni les ombres de la scène.

**Répartition** : Claude fait tout ce qui ne demande pas Blender (code, préparation des données, analyses, git) directement sur le PC.
Ilyas lance ce qui demande Blender (images test, brouillons, rendu final) et regarde les résultats. Tout le rendu se fait sur le PC d'Ilyas.

## 1. Recul (honnête)

- Le sujet, l'avalanche, **n'a encore jamais été vue dans la vraie scène** : c'est le risque n° 1, l'environnement est très avancé.
- Les 202 fichiers PLY sont sur le PC (`Data_Johan\wetransfer_blatten-data_2026-10-07_1149`, 6,2 Go) mais **le cache n'en contient qu'un**
  (`all_particles_1500`). Toute la partie aléa attend cette conversion de 20 minutes.
- La caméra 360 voit dans toutes les directions : **tourner le cap ne change rien à la zone visible** (`visible.py` n'utilise que la position).
  On peut donc mettre l'événement face au spectateur sans rien recalculer.
- Mémoire GPU (6 Go) : la version lite a déjà saturé avec 628 000 arbres. Avec la matière en plus, c'est le 2e risque.
- Temps de rendu final estimé 25 à 40 h sur un seul PC : le rendu final doit **commencer au plus tard le 12 novembre**.

## 2. Chemin critique

```
A. Remise à plat (15-17 oct) -> B. Brouillon du film entier (18-24 oct) -> C. Corrections et finitions (25 oct-7 nov)
   -> D. Gel, réglages, rendu final (8-21 nov) -> E. Montage, crédits, YouTube (22-25 nov)
```

## 3. Décisions à prendre maintenant (avec recommandation)

| # | Décision | Recommandation | Statut |
|---|---|---|---|
| D1 | Fenêtre de temps | La coulée passe sur la caméra (matière à moins de 30 m dès t = 49 s, jusqu'à ~20 m au-dessus entre 50 et 58 s, puis drainage). Ilyas garde la caméra (c'est un atout). Décision de coupe (noir à l'impact ou suite) **après l'aperçu complet** de toute la simulation (B). | après B |
| D2 | Vue de départ | Sur le paysage, pas sur l'événement (surprise, inciter à tourner la tête). Provisoire : fond de vallée vers l'aval (cap 200°). Ilyas choisit l'angle exact (la petite maison) avec la visionneuse 360 et `python blatten.py cap N`. Repères : départ 129° (3 km, 1 050 m plus haut), dépôt 184° (590 m). | à choisir par Ilyas |
| D3 | Matière | Une seule matière, la nôtre (`matiere_roches`), rendue par Ilyas. | décidé |
| D4 | Modèles d'arbres réalistes | Pour les arbres proches (< 120 m, ~240) : modèles importés par essence (épicéa d'abord), choisis par Ilyas (licence CC0/CC-BY). Étape C. | modèle à fournir |
| D5 | Rendu final | Tout sur le PC d'Ilyas (le PC de Maxime ne suffit pas). Le rendu final doit donc démarrer au plus tard le 12 novembre. | décidé |

## 4. Les tâches

Format : **qui** (PC = Ilyas lance, Claude = code dans le cloud), **comment**, **durée**, **ce qu'on renvoie**, **fini quand**.
Toutes les commandes se lancent dans PowerShell depuis `C:\Dev\blatten-vr`.

### Étape A : remise à plat (15-17 octobre)

**A1 : FAIT (Claude, 16 oct)**, `main` contient tout (branche `alea` fusionnée, caméra commitée). Pour mémoire, la marche à suivre :
```
git add camera.json
git -c user.name="Ilyas Hammouti" -c user.email="e.hammouti01@gmail.com" commit -m "[env] Caméra finale validée"
git pull --rebase --autostash origin main
git checkout main
git pull --ff-only origin main
git merge --ff-only alea
git push origin main
```
Fini quand : `git log --oneline -3` montre le handover `[alea]` en tête et `git status` ne montre plus `camera.json`.

**A2 : FAIT (Claude, 16 oct)**, 202 fichiers, 233 762 particules chacun (stride 5), vmax 100 m/s, ancien fichier rangé dans `cache\_ancien\`. Pour mémoire :
Déplacer d'abord `pipeline\cache\all_particles_1500.npy` dans un sous-dossier `pipeline\cache\_ancien\` (sinon il se mélange à la série). Puis :
```
python blatten.py prep-particules "D:\OneDrive\Université\Master Dynarisk\M2\Blatten\Data_Johan\wetransfer_blatten-data_2026-10-07_1149" --stride 5 --reset --origin 1117.4016956592827 0.0 -1121.1231332002285
```
(`--origin` garde exactement le calage actuel avec le terrain ; ne pas l'enlever.)
Renvoyer : la dernière ligne (`meta.json écrit (202 fichier(s)), vmax=...`).

**A3 : FAIT (Claude, 16 oct)**, résultats dans D1 ; interpolation Hermite 10 fois plus précise, branchée dans la scène. Pour mémoire :
```
python src/matiere/analyse_temps.py
python src/matiere/test_interpolation.py
```
Renvoyer : les deux résumés collés tels quels.

**A4 : FAIT (Claude, 16 oct)** : empreinte 2,99 km2 sur 201 s, zone visible avec couloir recalculée.

**A5** : intégrée à l'aperçu complet (B1).

**A6 : FAIT (Claude, 16 oct)** : masque d'eau 2 m et 50 cm (0,53 km2), aperçus `cache\env\eau_apercu_*.png`.

**C1 (Claude, fait le 15 oct)** : préréglage `brouillon`, commandes `brouillon` et `montage`, rendu final avec reprise automatique, `t0`/`intro` dans la scène.
**C2 : FAIT** (cap, D2).
**C3 : FAIT** (Hermite dans la scène). Reste : fixer la fenêtre selon D1.

### Étape B : aperçu complet (18-24 octobre)

**B1 (PC, ~8 h sans surveillance)** : menu `7` « APERÇU COMPLET », ou `python blatten.py apercu-complet`.
Rend d'abord deux images test (t = 30 s et 43 s, dans `render\tests\`), puis le **brouillon de toute la simulation** (0 à 202 s) :
1920x960, 16 échantillons, 6 images par seconde simulée de 0 à 70 s puis 1 par seconde (552 images), vidéo à 12 images/s
(phase active en accéléré x2, fin en x12) : `render\brouillon\brouillon_360.mp4`. Priorité basse et 2 cœurs laissés libres.
Reprise automatique : relancer la même commande après une coupure.

**B2 (PC)** : regarder les images test et la vidéo dans la visionneuse 360 puis sur téléphone (YouTube non répertorié).
Choisir la vue de départ (la petite maison) : dans la visionneuse, placer le rond dessus et lancer la commande affichée (`python blatten.py cap N`).

**B3 (Claude + Ilyas)** : décider où couper le film (D1) et classer les corrections : c'est la liste de l'étape C.

### Étape C : corrections et finitions (25 octobre - 7 novembre)

Tout ce que B2 relève, par ordre d'importance. Chantiers déjà connus :
1. **Lisibilité de la matière** (aujourd'hui un lit de graviers) : couleur, taille des roches, teinte sombre humide, ombrage ; surface continue si nécessaire.
2. **Poussière** : nuage en volume (densité tirée des particules rapides + bruit), plume qui monte et dérive, d'après les vidéos de Blatten.
3. **Dépôt** : fond de vallée enseveli sans trou (surface `zfin` si les particules au repos laissent voir le terrain).
4. **Arbres proches réalistes** (D4).
5. **Mémoire et temps de rendu** : tenir dans 6 Go et dans le budget du §5.

Chaque correction se valide par **une image test** (A5) puis, si elle change tout le film, par un `test-clip` de 3 s. Pas de nouveau brouillon complet avant la fin de l'étape C.
**C-fin (PC, une nuit)** : 2e brouillon complet, regardé sur téléphone.

### Étape D : gel et rendu final (8 - 21 novembre)

**D1 (Claude, 8-9 nov)** : choisir les échantillons (48 + débruitage OptiX probable), écrire les valeurs dans `config.json`, journal.
**D2 (PC, 30 min)** : `python blatten.py bench` sur la scène finale. Calcul : images x secondes par image ; si > 40 h, réduire (Claude).
**D3 (PC, ~25-40 h réparties sur plusieurs nuits, 12-21 nov)** : menu `7` « RENDU FINAL ». Reprise automatique : lancer chaque soir, arrêter le matin (fermer la fenêtre), relancer le soir suivant.
Pendant D3, ne pas modifier ce qui change l'image (sinon les images déjà rendues ne raccordent plus).

### Étape E : livraison (22 - 25 novembre)

**E1 (Claude)** : 5 s de crédits de fin (Johan Gaume, SLF/ETH, swisstopo, OpenStreetMap, Paris 1) en image 360, ajoutés au montage.
**E2 (PC)** : `python blatten.py montage render/final`, envoi YouTube (non répertorié puis public), QR code, test sur 2 téléphones.

## 5. Budget de rendu (ordre de grandeur, à remesurer en D2)

| Réglage | Par image (mesuré sans matière, 234 000 particules) | 1 350 images |
|---|---|---|
| 96 échantillons | 77 s (+30 à 50 % avec matière, non mesuré) | 29 à 43 h |
| 48 échantillons + débruitage | 58 s (+30 à 50 %) | 22 à 33 h |
| Brouillon 1920x960, 16 éch., 1 sur 2 | ~45-55 s (coût fixe dominant) | 675 images, 8-10 h |

Le coût fixe (~40 s par image : reconstruction de la scène) domine. Leviers dans l'ordre : moins d'objets à reconstruire, persistance des données, échantillons.

## 6. Où en est chaque morceau

| Morceau | État | Pour la V1 |
|---|---|---|
| Relief, images, bâtiments | fait | retouches si B2 en relève |
| Arbres (placement, essences, taille réelle, vent, limite sous la neige) | fait, modèles simples | modèles réalistes proches (D4, étape C) |
| Eau (masque tiré de l'ortho, brillance, ondulations) | fait, à vérifier (A6) | retouches si B2 en relève |
| Ciel couvert, brume | fait | réglage final en C si besoin |
| Particules (202 fichiers) | converties (stride 5) | fait |
| Matière A (roches instanciées) | écrite, jamais vue en vraie scène | A5, puis C |
| Interpolation Hermite | confirmée et branchée | fait |
| Fenêtre de temps, cap | cap fait ; fenêtre selon D1 | D1 |
| Poussière | rien | C |
| Dépôt (fond de vallée recouvert) | les particules au repos forment le dépôt ; trous possibles à stride 5 | à juger sur B2 |
| Rendu, montage, 360, reprise | fait (C1) | B1, D3 |
| Crédits | rien | E1 |

## 7. Hors du dépôt

Son ambisonique (chantier d'Ilyas, Reaper + IEM). Stéréo 3D : non prévue (rendu mono).

## 8. Début et fin de chaque séance Claude

- Début : lire ce plan et `docs/journal/*.md` (dernières entrées). Demander à Ilyas les résultats des tâches PC en cours.
- Fin : cocher l'avancement dans §6, une entrée de journal (`docs/journal/env.md` ou `alea.md`), commit ciblé sur `main`, dire à Ilyas **exactement** quoi lancer ensuite.
- Git : la suppression est autorisée dans `C:\Dev\blatten-vr` pour la session, donc git marche depuis le shell de l'appareil, sauf `push` (pas d'identifiants) :
  Claude pousse depuis le cloud (patchs `git format-patch` récupérés, puis `git fetch` et `git reset --hard origin/main` sur le PC une fois le contenu identique vérifié).

## 9. Faits vérifiés

- Simulation de Johan Gaume : selon swissinfo, quelques jours avant l'effondrement, l'équipe a modélisé un départ de 10 millions de m3 de roche et de glace, et ses projections de l'étendue ont « étroitement correspondu » à la catastrophe réelle. **Non vérifié** : que les 202 fichiers reçus soient bien ce calcul d'avant l'événement (à confirmer par Johan avant de l'affirmer au colloque).
