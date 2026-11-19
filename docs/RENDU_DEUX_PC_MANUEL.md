# Rendu final sur deux PC, sans le protocole duo (19 nov. 2026)

Situation : le rendu final_v1 a démarré sur le PC de Samy (RTX 3060 12 Go) du début vers la fin. Décision d'Ilyas (19 nov., soir) : Samy finit le paquet 1 à 40, puis rend DE LA FIN VERS LE DÉBUT (`--inverse`, 1525 vers le bas). Le PC d'Ilyas (RTX 2060 6 Go, environ 1,6 fois plus lent) rend du début vers la fin à partir de l'image 41. Pas de limite de plage : chaque PC peut tout générer (roue de secours), sauf le PC d'Ilyas au-delà de ~950 (mémoire de carte).

- Les images sont indépendantes : `--origine 1` fixe le temps de simulation de chaque paquet, donc l'ordre de rendu ne change pas l'image.
- Conditions pour des images identiques : même code (empreinte_code), mêmes données (cache), même Blender 5.2.2 LTS. Contrôle : `python tools/verifier_donnees.py`.
- Jonction vers l'image ~800 (estimation 61 h au total) : ARRET.txt sur les deux PC dès qu'ils sont à moins de ~40 images, puis envoi des images d'un PC à l'autre (zip, Google Drive).
- Montage final (`finir` : outro, AmbiX, assemblage, métadonnées 360) : sur ordre d'Ilyas seulement, quand 1525 images sont présentes.
- Poids : environ 1,6 Mo par image, film complet environ 2,4 Go, part du PC d'Ilyas environ 1 Go.
- Prompt de la conversation du PC d'Ilyas : docs/PROMPT_PC_ILYAS.md.
