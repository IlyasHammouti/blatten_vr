# Journal ENV (environnement, caméra, relief, bâtiments, arbres, ciel, brume, bench)

Écrit par la conversation ENV. La conversation ALEA le lit au début de chaque séance (après `git pull`). Les plus récents en haut.

## 2026-10-13 : environnement complet (pour l'ALEA)
- **Caméra** validée par Ilyas: `camera.json` (X -643,73, Y 769,57, Z 1685,6, rotation 90 / 0 / -69). `confirmed: true`. Ne pas la changer sans prévenir ENV (le masque de visibilité en dépend).
- **Relief** : anneaux 0,5 m / 1 m / 2 m / 8 m / 32 m / 128 m, images 2 m, 50 cm et 10 cm. Les bâtiments (swissBUILDINGS3D, 1 841 sur 7 km) et les arbres (essences d'après l'OFEV, jusqu'à 4,6 km, arbustes en avant-plan) sont dans la scène.
- **Couloir protégé** : `python blatten.py empreinte-alea` (menu 25) écrit `cache/env/alea_empreinte.npz` (grille 4 m, LV95): `occ` (où passe la matière), `tarr` (instant de première arrivée, s depuis le fichier 1),
  `zfin` (surface du dépôt, altitude de la plus haute particule du dernier fichier), `zmax` (altitude maximale atteinte). `visible` s'en sert: 250 m autour de l'empreinte jamais coupés, et jusqu'à 1,5 km tout ce qui serait visible avec un nuage de 100 m.
  Relancer `visible` (menu 8, ou le menu 23) après `empreinte-alea`.
- **Bâtiments et arbres balayés** : ceux qui sont dans l'empreinte sont regroupés par instant d'arrivée (pas de 3 s, objets `Batiments_t<s>` et `Arbres_t<s>`) et masqués (rendu et vue) à partir de cet instant, dans `on_frame` (`maj_ensevelis`). `--no-ensevelis` n'existe pas encore comme option: pour l'éviter, supprimer `alea_empreinte.npz`.
- **Fond de vallée / dépôt** : le relief est celui d'avant l'événement. Pour le recouvrir, utiliser `zfin` (surface du dépôt) à ta façon (maillage, mélange avec le relief). Je n'ai rien fait là-dessus: à toi de décider (voir aussi la question à Johan: son terrain est-il d'avant ou d'après?).
- **À savoir** : la scène sans `empreinte-alea` marche comme avant (rien n'est masqué, aucun couloir).

## 2026-10-10
- **Interface matière** : la scène charge `src/matiere/<nom>.py` avec `--matiere <nom>` (fonctions `build` et `update`). Gabarit: `src/matiere/rendu_matiere.py`.
  Sans l'option, la matière par défaut de la scène est utilisée.
- **`dt_per_step` = 1,0** ajouté à `config.json` (`scene`): avant, la valeur par défaut de la scène (0,01) faisait jouer les 202 fichiers 100 fois trop vite.
- **Caméra** (position annoncée par Ilyas): X -731,88, Y 720,95, Z 1693,1, rotation 94,4 / 0 / -129,38. Le Z est à environ 1 m du sol: il sera remonté à hauteur d'homme (`python blatten.py visible --eye 1.7 --ecrire-camera`).
- **Relief 0,5 m** et **images 50 cm / 10 cm** autour de la caméra: `python blatten.py download` puis `python blatten.py prep-env --hires`.
  La scène ajoute deux anneaux de relief (0,5 m et 1 m) autour de la caméra et des images locales dans le matériau du terrain.
- **Zone visible** : `python blatten.py visible` calcule ce que la caméra voit (fichiers dans `cache/env/visible/`, rien n'est écrasé).
  `--cull` dans la scène ne construit que le relief visible. Sur la caméra actuelle, environ 85 % du relief est caché.
- Demande à ALEA: la matière cachée derrière une crête peut aussi être retirée (le masque `visible_2m.npy` est utilisable pour les particules), à ton initiative.

## 2026-10-10 (suite) : zone visible validée sans haute résolution
- `visible` calcule le masque sur chaque niveau (0,5 / 2 / 8 m), depuis une caméra relevée de 4 m (`--leve`), avec tolérance verticale 5 m (`--tol`) et marge 12 m.
- Test cloud: `--no-hires --cull` donne la même image que sans coupe (0 pixel de différence). Le masque doit être calculé avec les mêmes niveaux que la scène (`visible --no-hires` si la scène est lancée avec `--no-hires`).
- Non validé: cas haute résolution (le test cloud dépasse 8 Go de mémoire). À vérifier sur le PC d'Ilyas: image `--cull` identique à l'image sans `--cull`.
