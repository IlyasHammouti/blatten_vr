# Journal ENV (environnement, caméra, relief, bâtiments, arbres, ciel, brume, bench)

Écrit par la conversation ENV. La conversation ALEA le lit au début de chaque séance (après `git pull`). Les plus récents en haut.

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
