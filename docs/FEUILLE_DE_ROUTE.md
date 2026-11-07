# Feuille de route Blatten VR

Mise à jour: 7 novembre 2026 (soir, après les tests). **À relire avant chaque grande étape** (lancer un rendu, ajouter une fonction, envoyer quelque chose à Johan). Claude la relit et la met à jour à chaque étape; Ilyas peut dire "feuille de route" pour la faire afficher.

## Dates

| Date | Jalon |
|---|---|
| dès que possible, 12 nov. au plus tard | Lancement du rendu 360 de la V1. Mesuré le 7 nov. (`test-final`): environ 160 h sur le PC d'Ilyas seul, environ 62 h à deux PC (si la 3060 va 1,6 fois plus vite). Plus rien ne bloque le lancement: l'outro et le son ne servent qu'au montage, refaisable après (`finir`) |
| 25 nov. | V1 à remettre |
| 3 et 4 déc. | Colloque CNRS Thiais |
| ~10 nov. | Gel du réalisme du nuage (Pareto: ce qui n'est pas prêt est abandonné) |

## Avant tout rendu (brouillon, test ou 360)

1. Le PC est libre: pas d'autre application lourde (16 Go de RAM; Blender en prend 9,5 en rendu final, il restait 2 Go libres le 7 nov.; sous 7 Go libres le rendu attend avant de démarrer, et la mémoire qui manque donne des images noires).
2. Les décisions de `reglages/film.json` sont prises (voir "Décisions en attente" ci-dessous).
3. Le texte de l'outro est rempli (`reglages/outro.json`, sinon les balises `[...]` s'impriment). Montage seulement: modifiable après le rendu (`finir`).
4. Caméra figée (`camera.json`), pas de changement de cap prévu.
5. Espace disque sur D: suffisant (un rendu bande HD complet ≈ 5 Go; le 360 final: environ 1 Mo par image, 2 Go).
6. Les .bat se remettent à jour tout seuls quand on les lance (git reset sur origin/main): ne pas modifier le dossier C:\Dev\blatten-vr à la main. Un nouveau .bat n'apparaît qu'après le lancement d'un autre .bat (ou si Claude le dépose).
7. Après le rendu: `finir` (réparation des images noires, outro, son, montage), puis regarder la vidéo.

## Avant d'ajouter une fonction ou un effet

1. Ça sert l'objectif (réalisme suffisant, Pareto), et ça ne retarde pas le 360?
2. Coût mesuré: temps par image et mémoire (`bench`), sur UNE image de test avant tout rendu long.
3. Un réglage dans `reglages/film.json` plutôt qu'un code en dur, pour pouvoir comparer A/B.
4. Décision et résultat notés ici.

## Avant le rendu 360 final

1. Son validé en spatial (voir chantier 1). Montage seulement: peut se faire pendant le rendu.
2. Décisions visuelles prises le 7 nov. (voir journal) et vérifiées ensemble sur `Lancer_test_bande.bat` (3 images, environ 8 min): raccord du sol nettoyé près de la caméra, couleurs, arbres.
2 bis. `test-final` fait le 7 nov.: carte 5 491 Mo sur 6 144 au pire (ça tient, pas de tuiles), qualité pleine gardée (96 échantillons). À deux PC, la fin du film (après t = 32 à 38 s) va à la 3060 de 12 Go; si la carte d'Ilyas est pleine sur une image, son PC laisse les suivantes au frère tout seul.
2 ter. Sol nettoyé: `prep-sol` fait le 7 nov. (fichiers `*_sol.jpg` dans cache/env). Ne pas relancer `prep-...` après le paquet.
3. Rendu à deux PC (docs/RENDU_A_DEUX.md): envoi des images du frère choisi (GitHub recommandé: dépôt privé `blatten-transfert` + jeton, 3 min), puis `Lancer_preparer_duo.bat` (le paquet se teste tout seul), zip donné au frère, `Lancer_rendu_duo.bat`. Le partage entre les PC se règle tout seul.
4. Licences: sons (klankbeeld CC BY à créditer dans l'outro, G43-01 et G43-02 à confirmer en CC0), images; arbres détaillés: EZ-Tree (Daniel Greenheck, licence MIT, copie dans assets/arbres), écorces Poly Haven et texturecan (CC0). Crédit conseillé dans l'outro.
5. Plan B si le temps manque: baisser le nombre d'échantillons (64 au lieu de 96: environ 17 % plus rapide) plutôt que couper le contenu.

## Chantiers

| # | Chantier | État | Prochaine action | À faire avant |
|---|---|---|---|---|
| 1 | Son spatial (AmbiX) | Injection SA3D codée. `test_son_360.mp4` fait le 7 nov. (D:\Blatten_render\tests_son\20261107_1948) | Le mettre sur YouTube en non répertorié, écouter au casque en tournant la vue (ordre des bruits: avant, gauche, arrière, droite) | Montage final |
| 2 | Brouillon HD, 10 dernières s + fondu + outro | `Lancer_brouillon_fin.bat` prêt | Facultatif maintenant que le rendu final peut partir | |
| 3 | Saturation de l'image satellite et densité de forêt | Décidé le 7 nov.: saturation 1,25 (C), couronnes inchangées | Rien | |
| 4 | Police du titre | Décidé le 7 nov.: Palatino (`C:/Windows/Fonts/pala.ttf`, présente sur tout Windows) | Rien | |
| 5 | Arbres et couleur des arbres | Décidé par Ilyas (7 nov.): arbres détaillés EZ-Tree jusqu'à 1000 m au moins (la limite à 500 m se voyait sur le versant d'en face), fondu entre 850 et 1150 m (proportion d'arbres détaillés de 1 à 0, pas de ligne); au-delà, arbres simples avec le même calage de couleur. Coût mesuré à t = 15 s: +48 % de rendu (moins avec la poussière). Vent seulement à moins de 300 m. Couleur: calage sur la forêt de l'image en cours (2 mesures faites) | `Lancer_test_arbres.bat` (sans arbres, simples, détaillés 1000 m: ~6 min), corrections restantes proches de 1 ? | Paquet |
| 6 | Balancement des arbres | `vent_force` 0,09 dans `film.json` | Juger sur le film | |
| 7 | Eau: sens d'écoulement et scintillement de loin | Codé. `test-eau` du 7 nov.: le scintillement ne change que 465 pixels sur 3,3 millions (invisible sur une image fixe), sans coût | Gardé tel quel, rien à faire | |
| 8 | Sol: image aérienne | Décidé le 7 nov.: sol nettoyé (`prep-sol`) seulement près de la caméra, image 10 cm (`ortho_sol: ["ortho_10cm.jpg"]`): plus de taches noires ni de quadrillage sous les pieds; au loin, image d'origine (forêts plus denses et plus sombres, comme avant) | Vérifier le raccord sur `Lancer_test_bande.bat` | Paquet |
| 9 | Nuage de poussière | Réaliste en progrès. Vu le 7 nov.: vers t = 39-43 s, bord droit du nuage en rideau vertical strié; entre 49 et 53 s la coulée et le nuage arrivent sur la caméra, image presque noire à 53 s (`test-final`, luminosité 5 sur 255). Décidé: fin gardée jusqu'à 53 s (fondu au noir de 52 à 53 s); couper plus tôt reste possible au montage sans rien refaire | Hors V1 (Pareto): pas de nouvelle simulation avant le rendu final | Gel ~10 nov. |
| 10 | Précurseurs qui couchent les arbres trop tôt | Corrigé (couchage à ≥ 2 m de matière) | Vérifier sur le film | |
| 11 | Herbe | Plus tard, seulement si peu coûteux | | |
| 12 | Rendu à deux PC | Codé et testé le 7 nov. (simulation sur le vrai film, essai complet avec un faux Blender): partage en direct, suivi sur le téléphone (ntfy), montage automatique. Carte pleine: le PC se limite tout seul, l'autre fait la fin | Choisir l'envoi (GitHub: dépôt de transfert + jeton), puis `Lancer_preparer_duo.bat`, zip au frère, `Lancer_rendu_duo.bat` | 12 nov. |
| 13 | Courrier Johan | Réponse UNESCO (forfait) envoyée ou à envoyer | Voir le fil mail | |

## Décisions en attente d'Ilyas

- Envoi des images du frère: GitHub (recommandé), dossier partagé ou à la main.
- Texte principal de l'outro et noms de la réalisation (montage seulement).

## Journal court

- 8 nov. (0 h 30, 3e test arbres): mesure par zones de forêt entières (le gain pixel par pixel est biaisé pour les arbres vus de côté: derrière eux, la photo montre le pré ou la pente). Arbres simples sans ombres projetées (la photo les a déjà), bas des couronnes moins assombri, couleurs bornées sans écrêtage; arbres détaillés moins verts, plus sombres au loin.
- 7 nov. (minuit): arbres détaillés jusqu'à 1000 m avec fondu, mesure des couleurs par type d'arbre tel qu'il reste dans le film.
- 7 nov. (23 h 27, 2e test arbres): calage incomplet (arbres x 1,2 seulement: les couleurs bornées avaient divisé la couleur moyenne par 2; dominante bleue des arbres détaillés). Gains refaits d'après cette mesure, feuillage teinté par la luminosité de la texture. 3e test à faire.
- 7 nov. (nuit, tests arbres): 500 m retenus; couleur des arbres calée sur l'image (gains mesurés, couleurs bornées).
- 7 nov. (nuit, suite): couleur des arbres alignée sur l'image du sol (`_ortho_comme_le_sol`, `tree_ortho` 0,85); gains mesurés par `test-arbres` (`Lancer_test_arbres.bat`).
- 7 nov. (nuit): `test-bande` des réglages retenus: raccord du sol nettoyé invisible, rien à corriger. Arbres détaillés EZ-Tree portés en Python (`src/scene/arbres_ez.py`, sans dépendance), branchés pour les arbres à moins de 200 m (`placer_arbres_ez`, vent et couchage par rotation de l'objet); empreinte du rendu à deux étendue à assets/.
- 7 nov. (résultats des tests): `Lancer_tous_les_tests.bat` en 1 h, sans erreur. Rendu final sur la 2060: 3,5 min par image à t = 15 s, 11,4 à 43 s, 8,9 à 53 s; carte 5 491 / 6 144 Mo; RAM libre mini 2 Go. Estimation: 160 h seul, 62 h à deux. Réglages rapides: volumes (B) sans gain, 64 échantillons (C) -17 %, mesurés sur l'image noire de 53 s donc non jugeables: qualité pleine gardée. Décisions d'Ilyas: Palatino, saturation 1,25, arbres en grappes, sol nettoyé près de la caméra seulement (nouveau réglage `ortho_sol` en liste), fin gardée jusqu'à 53 s.
- 7 nov.: rendu à deux PC (`paquet`, `duo`, `duo-etat`, `duo-envoyer`, `duo-importer`), docs/RENDU_A_DEUX.md; pas de mise en veille pendant les rendus.
- 7 nov. (soir): `test-final`, arbres en grappes, `prep-sol`, `test-aspect`, `Lancer_tests_rapides.bat` et `Lancer_tests_soir.bat`.
- 7 nov. (nuit): essai de fumée dans Blender (sol, eau, titre, réglages de rendu, forêt complète): aucune erreur. Plan B mémoire: `scene.rendu_tuile`, `duo` qui laisse les images trop lourdes à l'autre PC, `--max-image`. `Lancer_tous_les_tests.bat` (les deux lots à la suite).
- 2 nov.: SA3D, `test-son`, brouillon fin, polices, `test-eau`, vent 0,09, eau (cap + loin), feuille de route.
