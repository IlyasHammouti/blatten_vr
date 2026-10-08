"""Ajoute les métadonnées "vidéo sphérique" (Google, version 1) à un MP4 équirectangulaire.

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
    open(dst, "wb").write(buf)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage : python inject_360.py entree.mp4 [sortie.mp4]")
    a = sys.argv[1]
    b = sys.argv[2] if len(sys.argv) > 2 else a[:-4] + "_360.mp4" if a.lower().endswith(".mp4") else a + "_360.mp4"
    inject(a, b)
    print("écrit :", b)
