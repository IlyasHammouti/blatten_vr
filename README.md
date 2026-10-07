# Blatten VR 360

Vidéo immersive à 360° de l'avalanche de roche et de glace de Blatten (28 mai 2025, effondrement à 15 h 24 CEST).
Colloque « Mouvements de terrain : aléas et réponses des sociétés », CNRS Thiais, 3 et 4 décembre 2026.
Simulation : Johan Gaume (Kang et al. 2026). Diffusion : YouTube 360 par QR code, visionnage individuel sur smartphone.
Premier rendu à remettre le 25 novembre 2026.

Ce dépôt contient **le code et les réglages**. Les données lourdes (relief, images, simulation) n'y sont pas : elles
se retéléchargent ou se partagent à part (voir plus bas).

## Démarrage

**Nouvelle machine : suivre `TUTO.md`**, pas à pas (installation, configuration, données, benchmark). Il peut aussi être collé à ChatGPT
pour être guidé. La suite de ce fichier est la référence.

Un double-clic sur `blatten.py` (ou `lancer_blatten.bat`) ouvre un menu ; la fenêtre attend Entrée avant de se fermer. Commandes principales :

```
python blatten.py status          # ce qui est prêt, ce qui manque
python blatten.py setup           # Blender trouvé, bibliothèques installées, dossiers créés
python blatten.py bench           # temps de rendu de VOTRE machine
python blatten.py bench-compare   # tableau des benchmarks, signale ceux qui ne sont pas comparables
```

Préparation des données (`download`, `terrain`, `prep-particules`, `prep-env`) : voir `TUTO.md` et `docs/ARCHITECTURE.md`.

## Structure

```
blatten.py                point d'entrée unique (python blatten.py menu)
config.json               réglages communs (versionnés)
config.local.json         réglages de VOTRE machine (ignoré par git)
camera.json               position de la caméra, "confirmed": false tant que le groupe n'a pas validé
data_sources/swisstopo/   listes d'URL des dalles (CSV) : c'est ce qui rend l'environnement reproductible
src/environnement/        prépa du relief et de l'image aérienne, calage, installation des bibliothèques
src/matiere/              particules de Johan -> .npy, puis (à venir) surface de la matière et poussière
src/scene/                scène Blender : terrain, ciel, brume, caméra 360, rendu
src/bench/                benchmark de rendu
src/audio/                son spatialisé (plan seulement)
bench_results/            résultats de benchmark (JSON versionnés, pour comparer les machines)
docs/                     prérequis de la version finale, architecture
```

## Où sont les données

| Quoi | Taille | Dans git ? | Comment l'avoir |
|---|---|---|---|
| Code, config, `camera.json`, CSV swisstopo | quelques Mo | oui | `git clone` |
| Dalles swisstopo (relief, image) | ~1,3 Go (2 m) | non | `python blatten.py download` |
| VDB et PLY de Johan | ~11 Go | non | dossier partagé, une seule copie |
| `data/cache/` (maillages, `.npy`, environnement) | ~0,6 à plusieurs Go | non | régénéré par `terrain`, `prep-particules`, `prep-env` |
| Rendus | variable | non | locaux |

Règle : tout ce qui se régénère par une commande ne se partage pas. Le partage ne sert que pour ce qui vient de Johan.

## Travailler à plusieurs

- Une branche par personne (`ilyas/...`, `collegue/...`), fusion dans `main` par pull request quand ça marche.
- Chacun son dossier : l'environnement et la scène (`src/environnement`, `src/scene`) d'un côté, la matière (`src/matiere`) de l'autre.
  Ce qui est partagé (`config.json`, `camera.json`) se modifie après discussion.
- `camera.json` : ne passer `confirmed` à `true` qu'après décision du groupe. Le rendu final refuse de démarrer sinon.
- Comparer les machines : chacun lance `python blatten.py bench` et pousse son JSON de `bench_results/`. `bench-compare` les met en tableau. Deux résultats sont comparables si leur clé est identique (mêmes réglages de `config.json`, même caméra de référence, mêmes données `meta.json` et `env_meta.json`, même version de Blender).

## Rendu final

`python blatten.py render --frames 1 1200` lance le rendu final. Des garde-fous le bloquent tant que la caméra n'est pas
confirmée et que les données ne sont pas à la résolution voulue (relief 0,5 m, image 10 cm à la bonne date).
Liste complète : `docs/PREREQUIS_VERSION_FINALE.md`.

## Conventions

- Repère de la simulation : Y vertical (Houdini). Blender : Z vertical. Conversion `(x, y, z) -> (x, -z, y)`, tout est recentré
  sur l'origine stockée dans `meta.json`. L'altitude réelle est conservée (Z Blender = altitude en m).
- Coordonnées suisses LV95 : `E = scene_E0 + X`, `N = scene_N0 + Y` (valeurs dans `cache/env/env_meta.json`).
