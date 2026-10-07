# Architecture de la chaîne

```
swisstopo (CSV d'URL)          Johan Gaume (PLY, VDB)
        |                              |
  [download]                     [terrain]  [prep-particules]
        |                              |            |
   dalles .tif ---[prep-env]--->  cache/env      cache/*.npy + meta.json
                                     \              /
                                      [scene] blatten_blender.py
                                      terrain, ciel couvert, brume, caméra 360, matière
                                              |
                                  [bench] / [views] / [test360] / [render]
                                              |
                                   images -> vidéo -> YouTube 360 (+ audio spatial)
```

## Étapes et responsabilités

| Étape | Commande | Code | Entrée | Sortie |
|---|---|---|---|---|
| Données swisstopo | `download` | `blatten.py`, `data_sources/` | CSV d'URL | `swisstopo/*/*.tif` |
| Terrain de Johan | `terrain` | `src/scene` (`--terrain-only`) | VDB | `cache/Terrain_mesh_*m.blend` |
| Particules | `prep-particules` | `src/matiere/prep_particules.py` | PLY | `cache/*.npy`, `meta.json` |
| Environnement | `prep-env` | `src/environnement/prep_env.py` | dalles + terrain + `meta.json` | `cache/env/` (relief, image, calage LV95) |
| Scène et rendu | `views`, `test360`, `open`, `render` | `src/scene/blatten_blender.py` | tout ce qui précède | images dans `render/` |
| Benchmark | `bench` | `src/bench/bench.py` | scène complète | `bench_results/*.json` |

## Principes

1. **Un seul point d'entrée** (`blatten.py`) et **un seul fichier de réglages** (`config.json`, plus `config.local.json` par machine).
   Les scripts Blender reçoivent leurs chemins par la ligne de commande et la variable `BLATTEN_ROOT`, rien n'est en dur.
2. **Ce qui se régénère ne se partage pas.** Les dalles, maillages et caches se refabriquent par une commande.
3. **Les garde-fous sont dans le code**, pas dans la mémoire des gens : le rendu final refuse de partir sans caméra confirmée
   ni données à la résolution voulue.
4. **Chaque étape est indépendante** : on peut relancer `prep-env` sans refaire `terrain`, `bench` sans rendre une image.

## Points ouverts

- **Contrat « matière »** : format d'entrée des particules et forme de la sortie (maillage par image ?) attendue par la scène.
  A figer avant de fusionner les deux approches de modélisation.
- Pas de temps de la simulation (`dt_per_step`) et instant de départ par rapport à 15 h 24 : à confirmer avec Johan.
- Relief et image d'avant événement sur la zone qui sera ensevelie.
- Bâtiments et arbres (`src/scene`, assets dans un `assets.blend` à créer), son spatialisé (`src/audio`).
