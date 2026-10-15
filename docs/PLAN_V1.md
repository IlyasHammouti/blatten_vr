# PLAN V1 : de l'état actuel à la vidéo finale muette

Mis à jour le 15 octobre 2026. **Document de référence unique** (remplace, pour le pilotage, `docs/HANDOVER_ALEA.md` et le handover unifié ;
leurs sections techniques restent valables comme mémoire). Une conversation Claude, une branche (`main`).

## 0. L'objectif, et la règle qui protège l'objectif

**Livrable V1 (25 novembre)** : une vidéo 360° muette, YouTube, 3840x1920, 30 images/s, ~45 s : 5 s de paysage calme, l'avalanche
(accélérée si nécessaire), le dépôt, quelques secondes de fin avec crédits. Regardée **sur smartphone** via QR code.

**Critère « assez bon »** : sur un téléphone, dans YouTube 360, un spectateur qui tourne la tête comprend ce qui arrive (une masse qui
descend, de la poussière, un fond de vallée enseveli) et rien ne le sort de l'immersion (pas de trou, pas de scintillement, pas d'objet absurde).
Rien d'autre ne compte pour la V1.

**Règles anti-détail (Pareto)** :
1. On ne juge une image **que** dans la visionneuse 360 (`voir360`) ou sur téléphone. Jamais dans la vue 3D de Blender.
2. Chaque tâche a une durée maximale. Dépassée : on garde l'état actuel et l'idée va au **Backlog V2** (§7).
3. **L'environnement est gelé le 17 octobre.** Après : seulement les bugs qui cassent le rendu (mémoire, trous, crash).
4. Une séance = une ligne du plan. Une idée nouvelle n'interrompt pas la séance : elle va au backlog.
5. On voit le **film entier en brouillon** avant de peaufiner quoi que ce soit (étape B). On corrige ensuite les 3 plus gros défauts, pas les 20.

## 1. Recul (honnête)

- Depuis début octobre, l'essentiel du temps est allé à l'**environnement** (relief, bâtiments, arbres, eau). C'est le décor. Le sujet,
  l'avalanche, **n'a encore jamais été vue dans la vraie scène**. C'est le risque n° 1.
- Les 202 fichiers PLY sont sur le PC (`Data_Johan\wetransfer_blatten-data_2026-10-07_1149`, 6,2 Go) mais **le cache n'en contient qu'un**
  (`all_particles_1500`). Toute la partie aléa attend cette conversion de 20 minutes.
- La caméra 360 voit dans toutes les directions : **tourner le cap ne change rien à la zone visible** (`visible.py` n'utilise que la position).
  On peut donc mettre l'événement face au spectateur sans rien recalculer.
- Mémoire GPU (6 Go) : la version lite a déjà saturé avec 628 000 arbres. Avec la matière en plus, c'est le 2e risque.
- Temps de rendu final estimé 25 à 40 h sur un seul PC : le rendu final doit **commencer au plus tard le 12 novembre**.

## 2. Chemin critique

```
A. Remise à plat (15-17 oct) -> B. Brouillon du film entier (18-24 oct) -> C. Les 3 plus gros défauts (25 oct-7 nov)
   -> D. Gel, réglages, rendu final (8-21 nov) -> E. Montage, crédits, YouTube (22-25 nov)
```

## 3. Décisions à prendre maintenant (avec recommandation)

| # | Décision | Recommandation | Statut |
|---|---|---|---|
| D1 | Fenêtre de temps | Accéléré constant (x2 provisoire : `time_scale` 0.5) du départ jusqu'à ~90 % de la distance parcourue, puis le dépôt. À 1x, 40 s ne montrent pas le dépôt et 150 s coûteraient 4 500 images. Chiffres exacts après `analyse_temps` (A3). | provisoire dans `config.json` |
| D2 | Cap de la caméra | Mettre le départ et le dépôt face au spectateur (rotation Z seulement, gratuit). Claude calcule l'angle (C2), Ilyas valide sur une image. | à faire |
| D3 | Maxime et la matière | Une seule matière, la nôtre (`matiere_roches`). Si Maxime veut aider : poussière de référence (vidéos de Blatten) ou son. Message à lui envoyer aujourd'hui. | à demander |
| D4 | Modèles d'arbres réalistes | **Hors V1** (backlog). Les arbres actuels passent à distance ; seuls ~240 sont à moins de 120 m. | décidé |
| D5 | 2e PC pour le rendu final | Seulement si Maxime a un GPU NVIDIA avec plus de 6 Go. Sinon tout sur le PC d'Ilyas. | à demander |

## 4. Les tâches

Format : **qui** (PC = Ilyas lance, Claude = code dans le cloud), **comment**, **durée**, **ce qu'on renvoie**, **fini quand**.
Toutes les commandes se lancent dans PowerShell depuis `C:\Dev\blatten-vr`.

### Étape A : remise à plat (15-17 octobre)

**A1 (PC, 5 min) : tout mettre sur `main` et pousser.**
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

**A2 (PC, 20-40 min, sans surveillance) : convertir les 202 fichiers de Johan.**
Déplacer d'abord `pipeline\cache\all_particles_1500.npy` dans un sous-dossier `pipeline\cache\_ancien\` (sinon il se mélange à la série). Puis :
```
python blatten.py prep-particules "D:\OneDrive\Université\Master Dynarisk\M2\Blatten\Data_Johan\wetransfer_blatten-data_2026-10-07_1149" --stride 5 --reset --origin 1117.4016956592827 0.0 -1121.1231332002285
```
(`--origin` garde exactement le calage actuel avec le terrain ; ne pas l'enlever.)
Renvoyer : la dernière ligne (`meta.json écrit (202 fichier(s)), vmax=...`).

**A3 (PC, 10 min) : analyses.**
```
python src/matiere/analyse_temps.py
python src/matiere/test_interpolation.py
```
Renvoyer : les deux résumés collés tels quels.

**A4 (PC, 30-60 min, sans surveillance) : empreinte et zone visible sur la vraie série.**
Menu `6` puis « Empreinte de l'aléa », puis menu `4` « Zone visible ». Renvoyer : le bilan.

**A5 (PC, 15 min) : première image de l'avalanche dans la vraie scène.**
```
python blatten.py test360 --mono --render-frame 900
```
(image 900 = 30 s de film = 50 s de simulation avec les réglages provisoires). Renvoyer : l'image (et le message d'erreur s'il y en a un).

**A6 (PC, 5 min) : préparer l'eau** (menu 4, « Préparer l'eau ») et envoyer `pipeline\cache\env\eau_apercu_2m.png`. Accepter tel quel sauf faux positif flagrant.

**C1 (Claude, fait le 15 oct)** : préréglage `brouillon`, commandes `brouillon` et `montage`, rendu final avec reprise automatique, `t0`/`intro` dans la scène.
**C2 (Claude, après A2)** : calcul du cap (D2) et proposition de `rot_deg` ; vérifier les positions départ/dépôt par rapport à la caméra.
**C3 (Claude, après A3)** : si l'interpolation Hermite est confirmée, la brancher dans la scène. Fixer `t0`, `time_scale`, nombre d'images (D1).

### Étape B : le film entier en brouillon (18-24 octobre)

**B1 (PC, une nuit, sans surveillance)** : menu `7` « BROUILLON du film complet », ou `python blatten.py brouillon`.
1920x960, 16 échantillons, une image sur deux (675 images, ~8-10 h). En cas de coupure : relancer la même commande, les images faites sont gardées.
Produit `render\brouillon\brouillon_360.mp4`.
Si « Out of memory » : coller la ligne `arbres:` et l'erreur, Claude coupe le budget (C4) et on relance.

**B2 (PC, 15 min)** : envoyer `brouillon_360.mp4` sur YouTube en **non répertorié**, le regarder **sur le téléphone**, noter en 5 lignes max
ce qui gêne le plus (ordre d'importance). Ça valide aussi toute la chaîne YouTube 360 dès maintenant.

**B3 (Claude + Ilyas, 30 min)** : classer les défauts, garder les 3 premiers pour l'étape C. Le reste va au backlog.

### Étape C : les 3 plus gros défauts (25 octobre - 7 novembre)

Probables (à confirmer par B2), avec la piste prévue :
1. **La matière se lit mal** (lit de graviers, contraste) : couleur, taille des roches, teinte sombre humide, ombrage. Durée max : 2 séances.
2. **Pas de poussière** : nuage de poussière en volume (densité tirée des particules rapides + bruit), plume qui monte et dérive. Durée max : 3 séances.
3. **Mémoire ou temps de rendu** : moins d'arbres lointains, persistance des données, échantillons. Durée max : 1 séance.

Chaque correction se valide par **une image test** (A5) puis, si elle change tout le film, par un `test-clip` de 3 s. Pas de nouveau brouillon complet avant la fin de l'étape C.
**C-fin (PC, une nuit)** : 2e brouillon complet, regardé sur téléphone. Fini quand : rien ne sort de l'immersion.

### Étape D : gel et rendu final (8 - 21 novembre)

**D1 (Claude, 8-9 nov)** : choisir les échantillons (48 + débruitage OptiX probable), écrire les valeurs dans `config.json`, journal.
**D2 (PC, 30 min)** : `python blatten.py bench` sur la scène gelée. Calcul : images x secondes par image ; si > 40 h, réduire (Claude).
**D3 (PC, ~25-40 h réparties sur plusieurs nuits, 12-21 nov)** : menu `7` « RENDU FINAL ». Reprise automatique : lancer chaque soir, arrêter le matin (fermer la fenêtre), relancer le soir suivant.
**Ne plus toucher au code pendant D3.**

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
| Relief, images, bâtiments | fait | gelé |
| Arbres (placement, essences, taille réelle, vent, limite sous la neige) | fait, modèles simples | gelé (modèles réalistes : backlog) |
| Eau (masque tiré de l'ortho, brillance, ondulations) | fait, à vérifier (A6) | gelé après A6 |
| Ciel couvert, brume | fait | réglage final en C si besoin |
| Particules (202 fichiers) | **pas converties** | A2 |
| Matière A (roches instanciées) | écrite, jamais vue en vraie scène | A5, puis C |
| Interpolation Hermite | écrite, à confirmer | C3 |
| Fenêtre de temps, cap | provisoire | D1, D2 de §3 |
| Poussière | rien | C |
| Dépôt (fond de vallée recouvert) | les particules au repos forment le dépôt ; trous possibles à stride 5 | à juger sur B2 |
| Rendu, montage, 360, reprise | fait (C1) | B1, D3 |
| Crédits | rien | E1 |

## 7. Backlog V2 (ne pas faire avant la V1)

Modèles d'arbres réalistes (import par essence), surface continue de la matière (B'), dépôt maillé depuis `zfin`, stéréo 3D,
son ambisonique (chantier d'Ilyas hors dépôt), torrents fins dans le masque d'eau, faux positifs d'eau (toits, parkings), ombres des arbres lointains.

## 8. Début et fin de chaque séance Claude

- Début : lire ce plan et `docs/journal/*.md` (dernières entrées). Demander à Ilyas les résultats des tâches PC en cours. Une seule ligne du plan.
- Fin : cocher l'avancement dans §6, une entrée de journal (`docs/journal/env.md` ou `alea.md`), commit ciblé sur `main`, dire à Ilyas **exactement** quoi lancer ensuite.
- Pièges techniques (git dans la VM, CRLF, verrous) : voir `HANDOVER_ALEA.md` §4. Règle simple : **Claude ne lance pas de git sur le PC** ; Ilyas fait `git pull` lui-même.
