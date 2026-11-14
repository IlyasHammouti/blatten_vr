# Nuit du 13 au 14 nov.: notes de Claude (état, verdicts, à faire)

Règles de la nuit (Ilyas dort): aucune demande d'autorisation, aucun contrôle à distance, pas de device_bash (la machine virtuelle
mange la RAM du PC). Seulement: push sur main (le veilleur relit nuit/file.txt), device_list_dir, device_stage_files.
Le PC ne peut pas pousser sur GitHub (pas d'identifiants): les résultats se lisent par device_stage_files dans
C:\Dev\blatten-vr\render\nuit\depot\<MMJJ_HHMM>\ (JPEG préparés par nuit-envoi), journal: render\nuit\journal.txt.
Pas de rendu long. Compte rendu complet à Ilyas le matin (verdicts francs, sans tiret cadratin, en français).

## Fait
- Veilleur lancé à 23:56 (heure du PC = UTC+1). File: oiseaux1, herbe2, final1 (360 à t = 10,8 et 30 s), perf_a / perf_b (persistant).
- Herbe v1 (D, E): faible (touffes sombres, clairsemées). Herbe v2 codée (lames translucides, plus larges): essai hors ligne net progrès.
- Premier test oiseaux invalide (fenêtre trop haute), relancé puis fermé par Ilyas avant la fin (aucun oiseau visible à t = 9,2 s, normal).

## Verdicts (passage de 00:45 UTC)
- Le PC va vite quand la RAM est libre: une image de fenêtre = 2,2 min construction comprise (12 min hier soir: c'était le swap).
- Lecture des résultats: device_list_dir ne descend qu'à 5 niveaux et device_stage_files à 7: stager directement
  C:\Dev\blatten-vr\render\tests\... (final/<date>/A_film_t30s/frame_0001.jpg, fenetre/<jeu>/<date>/<fen>__<var>/frame_0001.png)
  et D:\Blatten_render\tests_oiseaux\<date>\frame_XXXX.png. Journal: render\nuit\journal.txt.
- oiseaux1 (v1, ils s'éloignent, 90 m): points de 2-3 px, illisibles. => v2 codée: ils fuient en passant à 20-35 m de la caméra
  (envergure 10 px à t = 11 s, 25 px au passage vers t = 17-20 s), suivent le relief. Test oiseaux2 en file (16 images, t = 12 à 19,5 s).
  Si bon: lancer un clip fluide pour Ilyas (ex. --t0 14 --t1 19 --pas 3). Images v1: /mnt/user-data/outputs/nuit/ois_zoom.png.
- herbe2 (v2): bonne, se fond dans le sol (proche), un peu trop claire/paille sur la pente => teinte baissée (0.7, 0.9, 1.05). À garder, densité 35.
  Images: outputs/nuit/herbe_EF.jpg (E v1 à gauche, F v2 à droite), pente_F.jpg.
- versant19 (touffes 0.28 / 0.45): effet faible mais dans le bon sens, neutre en moyenne. Proposer 0.45. Image: outputs/nuit/versant_BGH.jpg.
- final1 (360, herbe v2 + oiseaux v1): OK, carte 4582/6144 Mo, RAM libre mini 0,7 Go. 10,1 min à t = 10,8 s, 12,8 min à t = 30 s.
  => film entier ~300 h sur la 2060 seule, ~115 h à deux. C'EST LE POINT DUR pour le 25 nov. Image: outputs/nuit/final_30.jpg.
- perf_a / perf_b: données persistantes PLUS LENTES (1096 s contre 780 s pour 6 images): abandonné.
- En file: ref30 puis vit1 (48 éch., seuil 0,02), vit2 (6 rebonds), vit3 (les deux): temps dans render\tests\final\<date>\bilan.json,
  comparer les images à ref30 (différence, zones de forêt et de poussière).

## À juger
- oiseaux1: visibles ? taille ? (groupes aux caps 189 et 229, fenêtre 165-250, x = (cap-165)/85*907)
- herbe2 (proche et pente), final1 (mémoire carte, temps), perf_a contre perf_b (chrono.json: secondes par paquet de 6 images).

## Idées restantes
- Chantier 19 (arbres du versant d'en face trop lisses): regarder versant__B_arbres_90pct (déjà dans /mnt/user-data/uploads).
- Figer reglages/film.json (arbres_luminosite 0.9, herbe, oiseaux), puis notice du partage avec le frère (dépôt blatten-transfert + jeton: Ilyas).
- Feuille de route (docs/FEUILLE_DE_ROUTE.md et doc du projet claude/blatten-vr-roadmap.md) à mettre à jour le matin.
