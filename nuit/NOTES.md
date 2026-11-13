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

## À juger
- oiseaux1: visibles ? taille ? (groupes aux caps 189 et 229, fenêtre 165-250, x = (cap-165)/85*907)
- herbe2 (proche et pente), final1 (mémoire carte, temps), perf_a contre perf_b (chrono.json: secondes par paquet de 6 images).

## Idées restantes
- Chantier 19 (arbres du versant d'en face trop lisses): regarder versant__B_arbres_90pct (déjà dans /mnt/user-data/uploads).
- Figer reglages/film.json (arbres_luminosite 0.9, herbe, oiseaux), puis notice du partage avec le frère (dépôt blatten-transfert + jeton: Ilyas).
- Feuille de route (docs/FEUILLE_DE_ROUTE.md et doc du projet claude/blatten-vr-roadmap.md) à mettre à jour le matin.
