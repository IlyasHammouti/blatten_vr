# Matière : ce qu'on s'est déjà dit

Ce document n'est **pas un règlement**. Il rappelle les décisions déjà prises par le groupe pour que le code de la matière
(avalanche, dépôt, poussière) s'emboîte avec le reste. On peut s'en écarter si c'est justifié, mais alors **prévenir le groupe avant**
(Ilyas, Maxime, et Johan pour ce qui touche à la simulation), pour ne pas casser le travail des autres.

Légende : **Décidé** = choix déjà fait ensemble. **Hypothèse** = pas encore mesuré ou confirmé. **Libre** = à Maxime de choisir.

## 1. But et priorités

- Vidéo 360° (3840x1920, mono, 30 images/s, environ 1 minute dont environ 40 s d'événement) vue sur smartphone via YouTube.
- **Décidé** : l'immersion et le réalisme passent avant l'exactitude scientifique. Ne pas déformer la simulation sans raison, mais un rendu crédible prime sur un rendu strictement fidèle.
- **Décidé** : caméra fixe, un seul point de vue (position à choisir par le groupe, provisoire dans `camera.json`).
- **Décidé** : ciel couvert, brume avec la hauteur.

## 2. Les données de Johan

- **Décidé** : 202 fichiers PLY, un par seconde simulée, 1 168 808 particules chacun, résolution 4 m.
- **Hypothèse à confirmer avec Johan** : le pas de temps exact entre deux fichiers (environ 1,04 s), l'instant du premier fichier par rapport à 15 h 24, le sens de `mu_b` (constant dans notre extrait), l'absence de poussière dans la simulation.
- Colonnes lues par `prep_particules.py` : `x, y, z, vx, vy, vz, mu_b` (vitesses en m/s).
- **Décidé** : particules de 4 m, donc suffisantes pour le rendu au-delà d'environ 400 m de la caméra. Plus près, il faudra un détail supplémentaire (à étudier, **Libre**).

## 3. Repère et conversion (à ne pas changer sans prévenir : tout l'environnement en dépend)

- **Décidé** : Johan est en Y vertical. Blender est en Z vertical. Conversion `(x, y, z) -> (x - Ox, -(z - Oz), y - Oy)`.
- **Décidé** : origine `O = [1117.4016956592827, 0.0, -1121.1231332002285]`, stockée dans `meta.json`. L'altitude réelle est conservée (Z Blender = altitude en m).
- **Décidé** : coordonnées suisses `E = 2629118.28 + X`, `N = 1140115.05 + Y` (valeurs dans `cache/env/env_meta.json`). Le calage médian vaut 0,69 m.
- Si tu changes l'origine ou le repère, le terrain et l'image aérienne ne seront plus alignés avec la matière.

## 4. Temps

- **Décidé** : la simulation est à 1 image par seconde, la vidéo à 30 images par seconde. Il faut donc **interpoler** entre deux fichiers, en utilisant les positions et les vitesses (déplacement le long de la vitesse, éventuellement hermite).
- **Décidé** : pas de rendu intermédiaire à 1 image/s : l'animation doit être fluide.
- **Hypothèse** : ralentir ou accélérer l'événement n'est pas prévu. Durée visée : environ 40 s pour l'événement.

## 5. Ce que Maxime peut faire librement (Libre)

- Représentation de la matière : sphères, métaballes, surface remaillée, VDB, nuages de points avec bruit, mélange selon la distance.
- Lissage, détails, textures, couleur, rugosité, ombrage de la masse (roche, glace, neige).
- Poussière et nuage : volume, particules secondaires, intensité, dérive. Pas de données de Johan là-dessus pour l'instant : tout est à inventer de façon plausible, sans prétendre à l'exactitude.
- Dépôt final : épaisseur, étalement, fusion avec le terrain.
- Nombre de particules gardées (`--stride`) et choix d'échantillonnage, en fonction du temps de rendu mesuré par `bench`.

## 6. Budget de rendu (Hypothèse, à mesurer)

- Mesure d'Ilyas (RTX 2060) : environ 69 s fixes + 0,62 s par échantillon, soit environ 130 s par image à 96 échantillons.
  1200 images, soit environ 43 h. Marge de 30 % pour la matière : **hypothèse non mesurée**.
- Plus de la moitié du temps d'une image est un coût fixe (reconstruction de la scène à chaque image). Réduire les échantillons seul gagne peu.
  Une matière légère et rapide à reconstruire vaut donc plus qu'une matière très chargée.
- Prévu : rendu sur deux PC. Le calcul exact dépendra de la matière finale. Relancer `bench` après un gros changement.

## 7. Intégration dans le code

- Ce qui est partagé et se modifie après discussion : `config.json`, `camera.json`, le repère (§3), `src/scene/`.
- Le travail de Maxime vit dans `src/matiere/`. Une branche `maxime/...`, fusion dans `main` par pull request quand ça tourne.
- Les données lourdes (`.npy`, `.ply`, `.vdb`, `.blend`) ne vont pas dans git.
- Le script de matière doit rester lançable par `python blatten.py ...` (nouvelle commande ajoutée au menu), et afficher des messages d'erreur lisibles.
- Mélange des approches d'Ilyas et de Maxime : prévu, à discuter ensemble une fois la première version de Maxime disponible.

## 8. Questions ouvertes (à trancher en groupe)

- Position de la caméra.
- Source des bâtiments et des arbres (swissBUILDINGS3D probablement indisponible sur la zone, alternative OSM ou autre).
- Relief et image avant l'événement dans la zone qui sera recouverte.
- Qui anime la poussière, et avec quelle source.
- Questions à Johan, seulement si on est bloqué.
