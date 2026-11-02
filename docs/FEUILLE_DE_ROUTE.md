# Feuille de route Blatten VR

Mise à jour: 2 novembre 2026. **À relire avant chaque grande étape** (lancer un rendu, ajouter une fonction, envoyer quelque chose à Johan). Claude la relit et la met à jour à chaque étape; Ilyas peut dire "feuille de route" pour la faire afficher.

## Dates

| Date | Jalon |
|---|---|
| 12 nov. au plus tard | Lancement du rendu 360 de la V1 (le rendu seul demande environ 200 h sur le PC d'Ilyas, moins avec le PC du frère) |
| 25 nov. | V1 à remettre |
| 3 et 4 déc. | Colloque CNRS Thiais |
| ~10 nov. | Gel du réalisme du nuage (Pareto: ce qui n'est pas prêt est abandonné) |

## Avant tout rendu (brouillon, test ou 360)

1. Le PC est libre: pas d'autre application lourde (16 Go de RAM; sous 7 Go libres le rendu attend, sous ~5 Go il produit des images noires).
2. Les décisions de `reglages/film.json` sont prises (voir "Décisions en attente" ci-dessous): saturation, couronnes, police du titre, vent.
3. Le texte de l'outro est rempli (`reglages/outro.json`, sinon les balises `[...]` s'impriment).
4. Caméra figée (`camera.json`), pas de changement de cap prévu.
5. Espace disque sur D: suffisant (un rendu bande HD complet ≈ 5 Go; le 360 final est beaucoup plus lourd).
6. Les .bat se remettent à jour tout seuls (git reset sur origin/main): ne pas modifier le dossier C:\Dev\blatten-vr à la main.
7. Après le rendu: `finir` (réparation des images noires, outro, son, montage), puis regarder la vidéo.

## Avant d'ajouter une fonction ou un effet

1. Ça sert l'objectif (réalisme suffisant, Pareto), et ça ne retarde pas le 360?
2. Coût mesuré: temps par image et mémoire (`bench`), sur UNE image de test avant tout rendu long.
3. Un réglage dans `reglages/film.json` plutôt qu'un code en dur, pour pouvoir comparer A/B.
4. Décision et résultat notés ici.

## Avant le rendu 360 final

1. Son validé en spatial (voir chantier 1).
2. Mêmes décisions visuelles que le brouillon HD validé (couleurs, forêt, titre, eau, arbres).
3. Pipeline à deux PC prêt: `python blatten.py paquet` pour le PC du frère, plages `--de/--a` réparties selon la vitesse mesurée de chaque carte.
4. Licences: sons (klankbeeld CC BY à créditer dans l'outro, G43-01 et G43-02 à confirmer en CC0), modèles d'arbres, images.
5. Plan B si le temps manque: baisser la résolution ou le nombre d'échantillons plutôt que couper le contenu.

## Chantiers

| # | Chantier | État | Prochaine action | À faire avant |
|---|---|---|---|---|
| 1 | Son spatial (AmbiX) | Injection SA3D codée et testée sur fichier factice. Commande `test-son` prête | Double-clic `Lancer_test_son.bat`, mettre `test_son_360.mp4` sur YouTube en non répertorié, écouter au casque en tournant la vue (ordre des bruits: avant, gauche, arrière, droite) | Rendu 360 final |
| 2 | Brouillon HD, 10 dernières s + fondu + outro | `Lancer_brouillon_fin.bat` prêt (images 1531 à 1830, ~150 images, ~10 h) | Fournir le texte de l'outro, puis lancer quand le PC est libre | Texte outro, décisions couleurs/vent |
| 3 | Saturation de l'image satellite et densité de forêt | `test-couleurs` fait ou à refaire (4 variantes sur l'image 1) | Choisir A/B/C/D, reporter dans `film.json` (`ortho_saturation`, `tree_couronne`) | Brouillon 2 |
| 4 | Police du titre | `titre-test --polices` prêt (6 polices Windows) | Double-clic `Lancer_test_polices.bat`, choisir, reporter dans `film.json` (`titre_police`) | Brouillon 2 |
| 5 | Arbres moches | Pas d'import de modèles encore. Les liens sont donnés à Ilyas | Télécharger dans `D:\Blatten_render\assets\arbres`, puis Claude écrit l'import (low-poly, couleurs par matériau, limite RAM) | Rendu 360 |
| 6 | Balancement des arbres | `vent_force` passé de 0,05 à 0,09 dans `film.json` | Juger sur le brouillon 2 | |
| 7 | Eau: sens d'écoulement et scintillement de loin | Codé: cap constant nord-est vers sud-ouest sur le fond plat, pente sur les versants, grandes taches rapides visibles de loin, réflexions limitées au cœur du masque | `Lancer_test_eau.bat` (3 images), regarder si c'est visible et si ça descend | Rendu 360 |
| 8 | Lissage de l'image satellite | À faire: lissage classique d'abord, Gemini ensuite (consigne: ne rien inventer), comparaison | Écrire les deux tests, comparer sur une même zone | Rendu 360 |
| 9 | Nuage de poussière | Réaliste en progrès, pas de "cloches gravitaires" | Test léger (sans environnement) Mantaflow, puis autres outils, avec limite de temps | Gel ~10 nov. |
| 10 | Précurseurs qui couchent les arbres trop tôt | Corrigé (couchage à ≥ 2 m de matière) | Vérifier visuellement sur le brouillon 2 | |
| 11 | Herbe | Plus tard, seulement si peu coûteux | Test mémoire après les arbres | |
| 12 | Pipeline avec le PC du frère | Plus tard | Mesurer sa carte avec `bench`, préparer le `paquet` | 12 nov. |
| 13 | Courrier Johan | Réponse UNESCO (forfait) envoyée ou à envoyer | Voir le fil mail | |

## Décisions en attente d'Ilyas

- Saturation (A 0,8 / B 1,0 / C 1,25) et couronnes (x1,3 ou non).
- Police du titre.
- Texte principal de l'outro et noms de la réalisation.
- Modèles d'arbres retenus (après téléchargement).
- Lissage satellite: classique ou Gemini.

## Journal court

- 2 nov.: SA3D, `test-son`, brouillon fin, polices, `test-eau`, vent 0,09, eau (cap + loin), feuille de route.
