"""
interpolation.py : état des particules (positions, vitesses) à un instant quelconque, par Hermite cubique.

Pourquoi remplacer Sequence.state (src/scene/blatten_blender.py) : celle-ci fait un fondu linéaire entre l'extrapolation avant
(p0 + v0 tau) et arrière (p1 - v1 (dt - tau)). À mi-chemin, cela revient à 0,5 (p0 + p1) + (dt / 4)(v0 - v1), alors que la
bonne correction est (dt / 8)(v0 - v1): pour une accélération constante a, l'erreur vaut a dt^2 / 8, la même (de signe opposé)
qu'un simple fondu linéaire des positions. Hermite est exact pour une accélération constante (erreur d'ordre dt^4 sinon).
Mesure sur les vraies données: python src/matiere/test_interpolation.py

Utilisation:  P, V = etat(seq, t)     (même contrat que seq.state(t): repère simulation, Y vertical)
Retombe sur seq.state(t) quand Hermite n'est pas applicable (hors de la plage des fichiers, nombre de particules différent,
séquence sans .times/.arr).
"""
import numpy as np


def etat(seq, t):
    times = getattr(seq, "times", None)
    arr = getattr(seq, "arr", None)
    if times is None or arr is None or len(times) < 2 or t <= times[0] or t >= times[-1]:
        return seq.state(t)
    i = int(np.searchsorted(times, t, side="right") - 1)
    a0, a1 = arr(i), arr(i + 1)
    if len(a0) != len(a1):
        return seq.state(t)
    dt = float(times[i + 1] - times[i])
    f = (t - float(times[i])) / dt
    p0, v0 = np.asarray(a0[:, :3], np.float64), np.asarray(a0[:, 3:6], np.float64)
    p1, v1 = np.asarray(a1[:, :3], np.float64), np.asarray(a1[:, 3:6], np.float64)
    f2, f3 = f * f, f * f * f
    P = (2 * f3 - 3 * f2 + 1) * p0 + (f3 - 2 * f2 + f) * dt * v0 + (-2 * f3 + 3 * f2) * p1 + (f3 - f2) * dt * v1
    V = ((6 * f2 - 6 * f) * p0 + (3 * f2 - 4 * f + 1) * dt * v0 + (-6 * f2 + 6 * f) * p1 + (3 * f2 - 2 * f) * dt * v1) / dt
    return P, V.astype(np.float32)
