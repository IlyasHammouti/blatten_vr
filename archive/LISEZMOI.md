# Archive (30 octobre 2026)

Fichiers qui ne servent plus à la chaîne de rendu, gardés pour mémoire. Rien ici n'est appelé par `blatten.py` ni par la scène.

| Fichier | Pourquoi archivé |
|---|---|
| `Lancer_test_persistent.bat` | Test conclu le 19 octobre: le mode `--persistent` est 18 % plus lent sur la RTX 2060, abandonné. |
| `src/matiere/rendu_matiere.py` | Gabarit de module de matière pour la piste de Maxime; décision D3: une seule matière (`matiere_roches`, modes roches / surface / mixte). |
| `src/matiere/analyse_temps.py` | Chronologie de l'événement (tâche A3 du plan, faite le 16 octobre). |
| `src/matiere/test_interpolation.py` | Mesure de l'interpolation Hermite (A3, faite: erreur médiane 0,02 m). Se relance si besoin: `python archive/src/matiere/test_interpolation.py`. |

Documents archivés: `docs/archive/` (handovers des conversations ENV/ALEA et unifié, contrat et handover de la matière pour Maxime; l'interface des modules de matière reste décrite dans `HANDOVER_ALEA.md`), remplacés par `docs/PLAN_V1.md`.
Sur le PC, les sorties de tests devenues inutiles sont rangées dans `render/_archive/` et `_archive/` (non versionnés).
