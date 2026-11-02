"""Ajoute les métadonnées "vidéo sphérique" (Google, version 1) à un MP4 équirectangulaire, et, si la piste audio a 4 canaux,
les métadonnées d'audio spatial (boîte SA3D: ambisonique d'ordre 1, canaux ACN, normalisation SN3D = format AmbiX), que YouTube
exige pour faire tourner le son avec la tête. Sans elles, YouTube lit les 4 canaux comme un son ordinaire.

Sans elles, YouTube et VLC voient une vidéo plate déformée. Avec elles, ils proposent la vue à 360°.
Bibliothèque standard seulement. Usage :  python inject_360.py entree.mp4 [sortie.mp4]
(ou : python blatten.py meta360 entree.mp4). Le fichier d'entrée n'est pas modifié.
"""
import struct
import sys

UUID = bytes.fromhex("ffcc8263f8554a938814587a02521fdd")
XML = (b'<?xml version="1.0"?><rdf:SphericalVideo xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
       b'xmlns:GSpherical="http://ns.google.com/videos/1.0/spherical/"><GSpherical:Spherical>true</GSpherical:Spherical>'
       b'<GSpherical:Stitched>true</GSpherical:Stitched><GSpherical:StitchingSoftware>Blatten VR</GSpherical:StitchingSoftware>'
       b'<GSpherical:ProjectionType>equirectangular</GSpherical:ProjectionType></rdf:SphericalVideo>')
CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


def _boxes(buf, start, end):
    i = start
    while i + 8 <= end:
        size, typ = struct.unpack(">I4s", buf[i:i + 8])
        hdr = 8
        if size == 1:
            size = struct.unpack(">Q", buf[i + 8:i + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - i
        if size < hdr or i + size > end:
            raise ValueError("fichier MP4 invalide ou tronqué")
        yield i, size, hdr, typ
        i += size


def _find(buf, start, end, path):
    for i, size, hdr, typ in _boxes(buf, start, end):
        if typ == path[0]:
            return (i, size, hdr) if len(path) == 1 else _find(buf, i + hdr, i + size, path[1:])
    return None


def _is_video(buf, trak):
    h = _find(buf, trak[0] + trak[2], trak[0] + trak[1], [b"mdia", b"hdlr"])
    return bool(h) and buf[h[0] + h[2] + 8:h[0] + h[2] + 12] == b"vide"


# boîte SA3D: version, type (0 = périphonique), ordre 1, ordre des canaux (0 = ACN), normalisation (0 = SN3D), 4 canaux, carte 0..3
SA3D = struct.pack(">I4s", 36, b"SA3D") + struct.pack(">BBIBBI", 0, 0, 1, 0, 0, 4) + struct.pack(">4I", 0, 1, 2, 3)


def _decaler_offsets(buf, moov_pos, n):
    """moov avant mdat: les positions des données (stco/co64) se décalent de n octets."""
    moov = next((i, s, h) for i, s, h, t in _boxes(buf, 0, len(buf)) if t == b"moov" and i == moov_pos)
    for i, s, h, t in _boxes(buf, moov[0] + moov[2], moov[0] + moov[1]):
        if t != b"trak":
            continue
        stbl = _find(buf, i + h, i + s, [b"mdia", b"minf", b"stbl"])
        if not stbl:
            continue
        for j, s2, h2, t2 in _boxes(buf, stbl[0] + stbl[2], stbl[0] + stbl[1]):
            if t2 in (b"stco", b"co64"):
                cnt = struct.unpack_from(">I", buf, j + h2 + 4)[0]
                fmt, w = (">I", 4) if t2 == b"stco" else (">Q", 8)
                for k in range(cnt):
                    o = j + h2 + 8 + k * w
                    struct.pack_into(fmt, buf, o, struct.unpack_from(fmt, buf, o)[0] + n)


def inject_audio(buf):
    """Ajoute SA3D à la piste audio de 4 canaux (modifie buf). Rend True si ajouté, False si rien à faire."""
    top = list(_boxes(buf, 0, len(buf)))
    moov = next(((i, s, h) for i, s, h, t in top if t == b"moov"), None)
    if not moov:
        raise ValueError("pas de boîte 'moov'")
    mdat_pos = next((i for i, s, h, t in top if t == b"mdat"), None)
    for trak in [(i, s, h) for i, s, h, t in _boxes(buf, moov[0] + moov[2], moov[0] + moov[1]) if t == b"trak"]:
        a, b_ = trak[0] + trak[2], trak[0] + trak[1]
        hd = _find(buf, a, b_, [b"mdia", b"hdlr"])
        if not hd or buf[hd[0] + hd[2] + 8:hd[0] + hd[2] + 12] != b"soun":
            continue
        chaine = [moov, trak]
        for chemin in ([b"mdia"], [b"mdia", b"minf"], [b"mdia", b"minf", b"stbl"], [b"mdia", b"minf", b"stbl", b"stsd"]):
            chaine.append(_find(buf, a, b_, chemin))
        stsd = chaine[-1]
        e = stsd[0] + stsd[2] + 8                        # première entrée d'échantillon (après version/flags et nombre d'entrées)
        esize = struct.unpack_from(">I", buf, e)[0]
        if struct.unpack_from(">H", buf, e + 24)[0] != 4:
            return False                                  # pas 4 canaux: pas ambisonique
        if b"SA3D" in bytes(buf[e:e + esize]):
            return False
        n = len(SA3D)
        for pos, size, hdr in chaine + [(e, esize, 8)]:
            if hdr != 8:
                raise ValueError("boîtes 64 bits non gérées")
            struct.pack_into(">I", buf, pos, size + n)
        buf[e + esize:e + esize] = SA3D
        if mdat_pos is not None and mdat_pos > moov[0]:
            _decaler_offsets(buf, moov[0], n)
        return True
    return False


def inject(src, dst):
    buf = bytearray(open(src, "rb").read())
    top = list(_boxes(buf, 0, len(buf)))
    moov = next(((i, s, h) for i, s, h, t in top if t == b"moov"), None)
    if not moov:
        raise ValueError("pas de boîte 'moov' : ce n'est pas un MP4 classique")
    mdat_pos = next((i for i, s, h, t in top if t == b"mdat"), None)
    traks = [(i, s, h) for i, s, h, t in _boxes(buf, moov[0] + moov[2], moov[0] + moov[1]) if t == b"trak"]
    trak = next((t for t in traks if _is_video(buf, t)), None)
    if not trak:
        raise ValueError("aucune piste vidéo")
    if _find(buf, trak[0] + trak[2], trak[0] + trak[1], [b"uuid"]) and UUID in buf[trak[0]:trak[0] + trak[1]]:
        raise ValueError("les métadonnées 360 sont déjà présentes")
    box = struct.pack(">I4s", 8 + 16 + len(XML), b"uuid") + UUID + XML
    n = len(box)
    # taille de trak et de moov
    for pos, size, hdr in (trak, moov):
        if hdr != 8:
            raise ValueError("boîtes 64 bits non gérées")
        struct.pack_into(">I", buf, pos, size + n)
    shift = mdat_pos is not None and mdat_pos > moov[0]   # moov avant mdat: les positions des données se décalent
    buf[trak[0] + trak[1]:trak[0] + trak[1]] = box        # insertion à la fin de trak
    if shift:
        moov_end = moov[0] + moov[1] + n
        for i, s, h, t in _boxes(buf, moov[0] + moov[2], moov_end):
            if t != b"trak":
                continue
            stbl = _find(buf, i + h, i + s, [b"mdia", b"minf", b"stbl"])
            if not stbl:
                continue
            for j, s2, h2, t2 in _boxes(buf, stbl[0] + stbl[2], stbl[0] + stbl[1]):
                if t2 in (b"stco", b"co64"):
                    cnt = struct.unpack_from(">I", buf, j + h2 + 4)[0]
                    fmt, w = (">I", 4) if t2 == b"stco" else (">Q", 8)
                    for k in range(cnt):
                        o = j + h2 + 8 + k * w
                        struct.pack_into(fmt, buf, o, struct.unpack_from(fmt, buf, o)[0] + n)
    if inject_audio(buf):
        print("audio spatial (SA3D, AmbiX ordre 1) ajouté")
    open(dst, "wb").write(buf)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage : python inject_360.py entree.mp4 [sortie.mp4]")
    a = sys.argv[1]
    b = sys.argv[2] if len(sys.argv) > 2 else a[:-4] + "_360.mp4" if a.lower().endswith(".mp4") else a + "_360.mp4"
    inject(a, b)
    print("écrit :", b)
