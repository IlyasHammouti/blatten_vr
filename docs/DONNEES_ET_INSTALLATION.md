# Installation et données, pas à pas

Pour Maxime (et toute nouvelle machine). Objectif : arriver au même point qu'Ilyas (environnement prêt, benchmark lancé)
puis pouvoir travailler sur la matière.

Si une étape échoue : copier le message d'erreur complet (la fenêtre reste ouverte, appuyer sur Entrée seulement après l'avoir copié)
et l'envoyer à Ilyas, ou le donner à ChatGPT avec ce fichier et `README.md`.

## 0. Ce qu'on te fournit et ce que tu n'as pas à télécharger

| Quoi | Taille | D'où | Pour quoi |
|---|---|---|---|
| Code, config, CSV swisstopo (`data_sources/swisstopo/`) | quelques Mo | `git clone` | tout |
| Les 202 PLY de Johan (fichier wetransfer) | 6,2 Go | ton wetransfer | la matière |
| `cache_ilyas.zip` (dossier `pipeline\cache` d'Ilyas) | ~0,6 Go | Ilyas | terrain + relief + image aérienne déjà calés |
| `Nesthorn_release_klein.vdb` | 6 Mo | Ilyas | zone de départ (facultatif au début) |
| `Nesthorn_terrain_klein.vdb` | 3,6 Go | Ilyas | **pas nécessaire** : le terrain est déjà dans `cache_ilyas.zip` |
| Dalles swisstopo (relief, image) | ~1,3 Go | `python blatten.py download` | **pas nécessaire au début** : l'environnement est déjà dans le cache. Utile plus tard (0,5 m, 10 cm) |

Le plus rapide pour démarrer : le git, les PLY, et le zip du cache. Le reste se télécharge ou se régénère plus tard.

## 1. Installer les logiciels

1. **Blender 5.2 LTS** (blender.org, installateur Windows). Noter le chemin de `blender.exe`.
2. **Python 3.8 ou plus** (python.org). Cocher « Add python.exe to PATH » à l'installation.
3. **Git** (git-scm.com), et être connecté à GitHub (tu es collaborateur du dépôt `IlyasHammouti/blatten_vr`).
4. Une carte graphique NVIDIA récente améliore beaucoup le rendu, mais n'est pas obligatoire pour le benchmark.

## 2. Cloner le dépôt

**Hors d'un dossier synchronisé** (pas OneDrive, pas Dropbox), par exemple `C:\Dev`.

```
cd C:\Dev
git clone https://github.com/IlyasHammouti/blatten_vr.git blatten-vr
cd blatten-vr
```

## 3. Configurer ta machine

Copier `config.local.example.json` en `config.local.json` et le remplir (ce fichier n'est jamais envoyé sur GitHub) :

```
{
  "blender": "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe",
  "data_root": "D:/Blatten",
  "cache_dir": "D:/Blatten/pipeline/cache",
  "swisstopo_dir": "D:/Blatten/swisstopo",
  "johan_dir": "D:/Blatten/Data_Johan"
}
```

Adapter les chemins (barres `/`, pas `\`). Choisir un disque avec au moins 20 Go libres. Les dossiers inexistants sont créés par `setup`.

## 4. Vérifier l'installation

```
python blatten.py setup
python blatten.py status
```

`setup` trouve Blender, installe les petites bibliothèques (`.pylibs/`) et crée les dossiers. `status` liste ce qui est prêt et ce qui manque.
À ce stade, il doit manquer seulement les données (étapes 5 et 6).

## 5. Mettre les données en place

1. **Cache d'Ilyas** : dézipper `cache_ilyas.zip` **dans** le dossier `cache_dir` de ta config. On doit y trouver directement
   `env/`, `Terrain_mesh_8m.blend`, `meta.json`, etc. (pas un sous-dossier de plus).
2. **PLY de Johan** : dézipper le wetransfer où tu veux (par exemple `D:/Blatten/Data_Johan/ply_202/`). Il doit contenir 202 fichiers `.ply`.
3. **VDB de départ** (facultatif) : copier `Nesthorn_release_klein.vdb` dans `johan_dir`.

Relancer `python blatten.py status` : l'environnement doit apparaître comme prêt.

## 6. Convertir les PLY de Johan (attention au `meta.json`)

Le cache d'Ilyas contient un `meta.json` issu d'**un ancien fichier unique** (stride 10, un seul fichier). Si on convertit les 202 nouveaux PLY dedans
sans précaution, le script refuse (stride différent) ou mélange les anciennes et nouvelles données. Deux règles :

- Le **repère de la scène** (origine) est fixé par ce `meta.json` et par le calage de l'environnement. Ne pas le changer.
  Origine : `1117.4016956592827 0.0 -1121.1231332002285` (repère de Johan, Y vertical).
- Convertir les nouveaux fichiers **dans un dossier de sortie séparé** pour ne rien écraser :

```
python blatten.py prep-particules D:/Blatten/Data_Johan/ply_202 --out D:/Blatten/pipeline/cache_ply202 --stride 10 --reset --origin 1117.4016956592827 0 -1121.1231332002285
```

Pour un premier essai rapide, ne convertir que quelques fichiers, par exemple un sur dix : ajouter `--every 10`.
Chaque PLY contient 1 168 808 particules, `--stride 10` en garde une sur dix (environ 117 000). Le choix définitif du stride se fera avec les tests de rendu.

Ne pas mettre les `.npy` convertis dans git.

## 7. Le benchmark

```
python blatten.py bench
```

Durée : de 20 à 40 minutes, l'ordinateur ne doit rien faire d'autre. Il produit un JSON et une image dans `bench_results/`.
Pour l'envoyer au groupe :

```
git checkout -b maxime/bench
git add bench_results/*.json
git commit -m "Benchmark machine de Maxime"
git push -u origin maxime/bench
```

Puis ouvrir une pull request sur GitHub (ou prévenir Ilyas). `python blatten.py bench-compare` affiche le tableau des machines.
Deux résultats ne sont comparables que si leur clé est identique ; l'outil le signale.

## 8. Ce dont tu n'as pas besoin

- Le terrain VDB de 3,6 Go, les dalles swisstopo, `python blatten.py download` : déjà couverts par le cache d'Ilyas.
- `terrain`, `prep-env` : à relancer seulement si la résolution de l'environnement change (0,5 m et 10 cm pour la version finale).
- OneDrive : à éviter pour le dépôt et le cache.

## 9. Ensuite

Lire `docs/CONTRAT_MATIERE.md` (décisions déjà prises pour la matière) et `docs/HANDOVER_IA_MATIERE.md` (à donner à ton IA).
