# Jeux de réglages

Chaque fichier `<nom>.json` est un essai de rendu, sans toucher au code. Format et règles: `src/reglages.py`.
Valeurs par défaut et explication de chaque clé: en tête de `src/matiere/matiere_roches.py` (matière), `src/matiere/poussiere.py`
(poussière), `src/matiere/depot.py` (dépôt) et `CFG` dans `src/scene/blatten_blender.py` (scène).

- Comparer plusieurs jeux au même instant: `python blatten.py variantes --temps 43 --jeux actuel mixte "mixte poussiere_v2"`
  (ou double-clic sur `Lancer_variantes.bat`). Images dans `render/variantes/`.
- Essai ponctuel: `--set poussiere.densite=0.02` (répétable), après les jeux.
- Le film utilise `film.json` (via `config.json`, clé `scene.reglages`). Quand un essai est validé, le recopier dans `film.json`.
