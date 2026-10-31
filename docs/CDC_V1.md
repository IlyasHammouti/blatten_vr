# Cahier des charges V1 (31 octobre 2026)

Remplace la partie pilotage de `docs/PLAN_V1.md`. Marqué (défaut) : choisi par Claude, à corriger par Ilyas si besoin.

## 1. Livrables et calendrier

- **Brouillon HD plat** : lancé quand Ilyas dit « go ». Sert à voir les détails et à corriger.
- **V1** : vidéo 360° YouTube, 3840x1920 mono, 30 i/s, son spatial ambisonique (AmbiX, 4 canaux). Livrée le **25 novembre** au plus tard.
  Rendu V1 lancé par Claude quand le brouillon plaît à Ilyas (au plus tard vers le 12 novembre).
- Méthode : Pareto. Réaliste, pas parfait. Les retours d'Ilyas sur les vidéos de l'événement servent à la version suivante.

## 2. Déroulé du film (environ 69 s, 2 070 images)

| Partie | Durée | Contenu |
|---|---|---|
| Intro | 8 s (5 s + 3 s de calme ajoutées) | Paysage calme, eau et arbres qui bougent. Texte « Blatten, Switzerland / 28 May 2025, 15:24 » dans le ciel, vers la vue de départ (cap ~200°), légèrement caché par le sommet du versant d'en face. Visible 5 s puis s'efface. Aspect : blanc lumineux, atténué par la brume (défaut). |
| Événement | t = 0 à 53 s simulées | Simulation de Johan. Fondu au noir rapide de 52 à 53 s, la vue est obstruée par la matière et la poussière. |
| Outro | 8 s (défaut) | Écran noir, texte blanc simple, posé à l'horizon dans la direction de l'événement (cap ~128°). Texte avec balises, remplacées par Ilyas. Rendu dans Blender en 360. |

L'heure 15:24 (13:24 UTC) vient de l'étude sismique de l'effondrement principal.

## 3. Scène

- **Caméra** : inchangée (`camera.json`).
- **Disparition des arbres et maisons** : désactivée.
- **Matière** : peau « mixte » actuelle. Couleur de base #BEAB98, blocs plus clairs et plus sombres.
- **Poussière** : nouveau modèle en 3 étapes, plusieurs foyers simultanés.
  1. Fusées : jets de poussière qui partent de la masse, trajectoire surtout horizontale, légère montée puis retombée (courbe convexe).
  2. Champignons : à l'impact au sol, bouffées qui gonflent et montent.
  3. Nuage : les champignons grossissent dans la vallée, deviennent moins définis et se fondent en un plus grand nuage.
  Couleurs : base #B9AB98, ombre #635B4E. Réglages dans `reglages/`, ajustés plus tard avec les commentaires d'Ilyas.
- **Bug du nuage coupé net** (vers 26 s du brouillon 360) : corrigé, plus une détection automatique des images suspectes avec nouveau rendu.
- **Arbres** :
  - Modèles proches (< 120 m) : épicéa réaliste (modèle gratuit, simplifié), mélèze et feuillus générés dans Blender. Les trois couvrent 93 % des arbres proches.
  - Vent : balancement léger mais visible, plus fort en hauteur, et frémissement des branches. Fini l'effet de paysage figé.
  - Arbres couchés vers l'aval à l'arrivée du front (souffle et débris, observés dans les vidéos et l'étude de 2026).
- **Eau** : polygones numérisés par Ilyas, reflets d'écoulement (inchangé).

## 4. Brouillon HD plat

- 1920x1080, champ de vision horizontal **75° constant**, visée fixe sur le centre de l'événement (cap ~128°, ~+8°). Trop serré à la fin : voulu.
- Événement et outro à 30 i/s (défaut). Intro : quelques images fixes visées sur le texte (cap ~200°), car le cadre de l'événement ne le montre pas.
- Échantillons choisis après la mesure d'une image (cible ~1 min par image).

## 5. V1 360 HD

- Préréglage final actuel, rendu partageable entre plusieurs PC (`--de` / `--a`).
- Vérification automatique des images, nouveau rendu des images suspectes, puis montage.

## 6. Son (script Python)

- Entrée : 4 à 6 sons mono en WAV, libres de droits (liste et liens fournis par Claude, téléchargés par Ilyas) : vent, rivière, grondement, impacts, souffle.
- Mixage par script : ambiance fixe autour de la caméra. Le grondement suit le centre de la matière vu de la caméra (direction, volume selon la distance, aigus étouffés au loin, retard du son à 343 m/s (défaut)). Impacts et souffle à l'arrivée du front. Coupure avec le fondu au noir. Outro silencieuse (défaut).
- Sortie : WAV 4 canaux AmbiX 48 kHz. Réglages des volumes dans `reglages/son.json`.
- Test : YouTube en non répertorié, sur téléphone avec casque audio.

## 7. Montage (script Python)

Images -> fondu -> outro -> son AmbiX -> métadonnées 360 et audio spatial -> MP4 prêt pour YouTube. DaVinci optionnel.

## 8. Organisation du code

- Un script par brique, lançable seul : installation et vérification (`setup.py` : Blender, GPU, Python, téléchargement des données, préparation, mesure d'une image et estimation du temps total), rendu, poussière, titres (intro et outro), son, montage, vérification des images.
- `blatten.py` : lanceur avec menus organisés, permet tout depuis un seul script.
- Fonctionne sous Windows et Linux (PC de Johan probable). Données de particules en paquet zip à héberger.

## 9. Hors V1

Mesure de la hauteur du nuage sur les vidéos, MATTER (préparation du stage), PC de Johan, pin du premier plan.

## 10. Reste à fournir

- Texte final de l'intro et de l'outro (balises en attendant).
- Sons à télécharger (liste à venir).
- Modèle de GPU du PC de Johan.
- Hébergement du paquet de particules (Google Drive, OneDrive ou autre).
