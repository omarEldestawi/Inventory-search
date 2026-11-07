"""Font-aware PDF character decoding, page assessment, and coordinate reading-order reconstruction."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import re
import struct
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import pymupdf

# Compact embedded fallback GID -> Unicode table for standard Windows Arial (ASCII + Arabic presentation forms)
# Used when system font files are unavailable (e.g. restricted container/CI environments).
FALLBACK_ARIAL_GID_TO_UNI: Dict[int, str] = {
    3: " ", 4: "!", 5: '"', 6: "#", 7: "$", 8: "%", 9: "&", 10: "'", 11: "(", 12: ")",
    13: "*", 14: "+", 15: ",", 16: "-", 17: ".", 18: "/", 19: "0", 20: "1", 21: "2",
    22: "3", 23: "4", 24: "5", 25: "6", 26: "7", 27: "8", 28: "9", 29: ":", 30: ";",
    31: "<", 32: "=", 33: ">", 34: "?", 35: "@", 36: "A", 37: "B", 38: "C", 39: "D",
    40: "E", 41: "F", 42: "G", 43: "H", 44: "I", 45: "J", 46: "K", 47: "L", 48: "M",
    49: "N", 50: "O", 51: "P", 52: "Q", 53: "R", 54: "S", 55: "T", 56: "U", 57: "V",
    58: "W", 59: "X", 60: "Y", 61: "Z", 62: "[", 63: "\\", 64: "]", 65: "^", 66: "_",
    67: "`", 68: "a", 69: "b", 70: "c", 71: "d", 72: "e", 73: "f", 74: "g", 75: "h",
    76: "i", 77: "j", 78: "k", 79: "l", 80: "m", 81: "n", 82: "o", 83: "p", 84: "q",
    85: "r", 86: "s", 87: "t", 88: "u", 89: "v", 90: "w", 91: "x", 92: "y", 93: "z",
    94: "{", 95: "|", 96: "}", 97: "~",
    892: "﴾", 893: "﴿", 896: "ﺀ", 897: "آ", 898: "ﺂ", 899: "أ", 900: "ﺄ", 901: "ؤ",
    902: "ﺆ", 903: "إ", 904: "ﺈ", 905: "ئ", 906: "ﺊ", 907: "ﺋ", 908: "ﺌ", 909: "ا",
    910: "ﺎ", 911: "ب", 912: "ﺐ", 913: "ﺑ", 914: "ﺒ", 915: "ة", 916: "ﺔ", 917: "ت",
    918: "ﺖ", 919: "ﺗ", 920: "ﺘ", 921: "ث", 922: "ﺚ", 923: "ﺛ", 924: "ﺜ", 925: "ج",
    926: "ﺞ", 927: "ﺟ", 928: "ﺠ", 929: "ح", 930: "ﺢ", 931: "ﺣ", 932: "ﺤ", 933: "خ",
    934: "ﺦ", 935: "ﺧ", 936: "ﺨ", 937: "د", 938: "ﺪ", 939: "ذ", 940: "ﺬ", 941: "ر",
    942: "ﺮ", 943: "ز", 944: "ﺰ", 945: "س", 946: "ﺲ", 947: "ﺳ", 948: "ﺴ", 949: "ش",
    950: "ﺶ", 951: "ﺷ", 952: "ﺸ", 953: "ص", 954: "ﺺ", 955: "ﺻ", 956: "ﺼ", 957: "ض",
    958: "ﺾ", 959: "ﺿ", 960: "ﻀ", 961: "ط", 962: "ﻂ", 963: "ﻃ", 964: "ﻄ", 965: "ظ",
    966: "ﻆ", 967: "ﻇ", 968: "ﻈ", 969: "ع", 970: "ﻊ", 971: "ﻋ", 972: "ﻌ", 973: "غ",
    974: "ﻎ", 975: "ﻏ", 976: "ﻐ", 977: "ف", 978: "ﻒ", 979: "ﻓ", 980: "ﻔ", 981: "ق",
    982: "ﻖ", 983: "ﻗ", 984: "ﻘ", 985: "ك", 986: "ﻚ", 987: "ﻛ", 988: "ﻜ", 989: "ل",
    990: "ﻞ", 991: "ﻟ", 992: "ﻠ", 993: "م", 994: "ﻢ", 995: "ﻣ", 996: "ﻤ", 997: "ن",
    998: "ﻦ", 999: "ﻧ", 1000: "ﻨ", 1001: "ه", 1002: "ﮫ", 1003: "ھ", 1004: "ﮭ",
    1005: "و", 1006: "ﻮ", 1007: "ى", 1008: "ﻰ", 1009: "ي", 1010: "ﻲ", 1011: "ﯾ",
    1012: "ﯿ", 1013: "ﻵ", 1014: "ﻶ", 1015: "ﻷ", 1016: "ﻸ", 1017: "ﻹ", 1018: "ﻺ",
    1019: "ﻻ", 1020: "ﻼ",
}

FALLBACK_GLYF_HASH_TO_UNI: Dict[str, str] = {
    "b0010780a4ee0a61edc173df2c5248f60f99d06ae7e9bb36abfd60a62f78257f": ":",
    "73cc3d108ad7dbb0f0ec950f824e1beeeddc3e2e35f729decf87eb95b81024d2": "ﮐ",
    "1e39263b384b6a0d3c2adec801c1cc6722b2f1302c4827f9b22c35817cf2c430": "أ",
    "b57609e21a6a7923860b54a41b18b8c2489924df3f22440a920427ef3b6b4199": "إ",
    "34043da8b0abe84899224f4784d9059bda78dc3bcd1f7ec1027b8c7c55821333": "ا",
    "a4e6e11ffade7a90211a9ce872f2b2bda5ca138cb70a765759c82ca8d946b92b": "ﺎ",
    "9be1c2d5a9f804abbf6c7d9443a31e742aaeb66c57c943de06e74a77d6cd8cd8": "ة",
    "66d52c9fa08bbef45996af13fe137bdcde6e7ab9e3d7c6ce763776871e2f25ee": "ﺔ",
    "2419a90255f49b7fdac1f8ce3c05845f412e2dcdf787d5557f7965abab9205f3": "ﺣ",
    "2d4c4f53a5c449cb508bc3d94ccf810e3508ddf14a9235ff6e6a1e98b918c6a5": "د",
    "662c44014d15d3afa5be75f0a2dca0571e95bd3a257ae48d2b8f9775b4d8529a": "ر",
    "343b02f0cb98db6f57e33e65ec410ac5f556d19ca4d4be0d67eb3fef07df33e7": "ﺳ",
    "81455ab3151e56728242f12998990d9861a17cfba1fd16620f1b85577b9e15ef": "ﺻ",
    "5c86862fe5a484cb72212bb3090f52d5322b687f13084cf757092e0c9ed23456": "ط",
    "a2f881579cd82071d04f8cb255f003814ff4c2fb101465e3183ffcd3a0e9f4f2": "ﻌ",
    "6f271e000543b735b3cf9c84d48ef3f6959b9ecf916e5cc8dc9268b0e4e994eb": "ﻟ",
    "47a621c2c28eb70352ab5691227008897ad3fc658ef9da15c3155ff26b7980c4": "م",
    "16f73797ddf7331175feff9a9f1eff5d2b9ea4a727ceab1428db1c9a31de85b3": "ﻣ",
    "1637330639153a17e4b3c13618a078281685400e25403ff530dee67db69cf8b8": "ﮭ",
    "c23d88e5168f7d4610a57f7fbe587dfc45d06a644cd8b14cc250fac854349e88": "و",
    "77bab18c8165560f26fbd4ec2c7483e4e93d2f58a768df54a0aaf48a09d3dab3": "ى",
    "eb1dc19536a5d2670580cc0241a00eacb7bdd8b9b7fcf13c3ae45a05014d49f6": "ء",
    "61bf7511edb4b011362ed91b567e4c38158f2223bf8d6cc5b4993c936e081796": "ـ",
    "f253b2423327d13390eedd8b593a95dcc21fc6f8fa1f99f88bf92d2b5b0bab2a": "ە",
    "60564a77a349513ac8be2f99b1eab91db85cb56bd2ca90bae817fd8b865ba115": "ﮐ",
    "523fd4beeadf449a5d8cfdfd609fd7835f8d317e8f8d86a753392191d395841d": "ی",
    "55817e5bf5172146f56a96efbdf29ed01c366941b6182372b0c1c8b993583f85": "ﯽ",
    "8533b3e2394591ef4289255c96b5813e0b70195f1895e7135dd82d749df1e58f": "ﺎ",
    "98a4eb736687bb4b4bb8bd7bd46b3c846fe3ef4a76a310610156abe6aafcc838": "ﺢ",
    "7b359cdb7158148097943cc1660065720437697e78a69cf972a66c9058c9f68b": "ﺣ",
    "812c44019d5e8758c1055461441e4fd84f9f7c88333261723be15adedf5fc0fa": "د",
    "e4f43e5da95f1d58840a1197b87a81264a3bcba91dbb730eada840c3b247fd98": "ر",
    "140bf2b3c94a949382deda8aacb6cfbc76140b151808a1f4d00552d1785a9607": "س",
    "a1bda1dcf54a69eeb4b634026882531c08bbee52e208fdb00d7f1dd053c43272": "ﺳ",
    "c1948a24a89a46ff3298723ddf41e557473f3d94758d36556a719b0b9f50de6a": "ص",
    "c83add444e011335d4f4a4406c6f83f86a29470e25a3a912a448821eaea5797c": "ﺻ",
    "fa6c808a0fb9abd14d7035d7ba1b454d9db29cf0569f8247c9c97b207cd09d0c": "ط",
    "b753cefa501a5c3c33f83102682fc06f8a830f4e8cf1cb4c677305b59ee196e1": "ع",
    "3bc4264397f65c5b611bf1705ed24f06281fcbf77f1d5f76069217ad6bd6b15c": "ﻊ",
    "7faeb689ece24431cb743b0744c8df44f98ef6b22330a6812dcd005bbe6c107d": "ﻋ",
    "1eb459a290f737d5ce40f38efec1e3f727d10fae5edf6c99374c7bf7ffb80b0a": "ﻌ",
    "a58608c59cd72be7a40650c108bc1563964a5190bcc66b02f89f1b4585e7e604": "ﻘ",
    "7491079baa4f684692b27b65cc37a971f7a753de71c9941f4af5afe0b1b20697": "ك",
    "1ec0342dc70cca9a7eef9e0bee7966a250872370e0e934dd18d68cd35b7ef6ac": "ل",
    "45f0cf78ac03801b3a0f72601555b6e9735f43d3ac9e2296bd1e599fda5df4ac": "ﻟ",
    "fb767f6face96a035211104c11df2d4b3a6f09b43302d343da16bf3fd9c0c08c": "م",
    "9e93bf0146ef6b2580f76b4aa9821919a8c65c59d5fd83bce037aba7600c1972": "ﻣ",
    "6d6ea2566c17f659ff10cac3591f5309c22a95b54775df731df884422aa1d4dc": "ھ",
    "e1f123a1da9706915d271a72e69abb261f5341beae44e3e143afeb4c7b8bde5c": "ﮭ",
    "4d6c2274e40046cfac101612234b39bca6391018f23210c6c0514da2df5b7fb8": "و",
    "79f2ff6bb44c94a9d2e735bfdb7b46357eac4f96e82c0221d654a294c04f1a67": "ﻲ",
    "7bd52ed9f4d9aee3969a7631ffce1183c475c9cd681510d6146e6834cc1b25dd": "ﻻ",
    "24c2c85f9a7718d87bd693fc28ae57c8f7e838d9e3336aa201a627e861ffbda9": "ﻼ",
}


def parse_ttf_tables(data: bytes) -> Dict[str, bytes]:
    """Parses SFNT TrueType table directory and returns raw table slices."""
    if not data or len(data) < 12:
        return {}
    try:
        _, num_tables = struct.unpack(">IH", data[:6])
    except struct.error:
        return {}
    tables: Dict[str, bytes] = {}
    for i in range(num_tables):
        offset = 12 + i * 16
        if offset + 16 > len(data):
            break
        try:
            tag, _, tbl_offset, length = struct.unpack(">4sIII", data[offset : offset + 16])
            tag_str = tag.decode("latin1", errors="replace")
            if tbl_offset + length <= len(data):
                tables[tag_str] = data[tbl_offset : tbl_offset + length]
        except struct.error:
            continue
    return tables


def _parse_cmap_format4(subtable: bytes) -> Dict[int, int]:
    if len(subtable) < 16:
        return {}
    try:
        _, _, segCountX2 = struct.unpack(">HHH", subtable[2:8])
        segCount = segCountX2 // 2
        if 16 + segCountX2 * 4 > len(subtable):
            return {}
        endCode = struct.unpack(f">{segCount}H", subtable[14 : 14 + segCountX2])
        start_pos = 16 + segCountX2
        startCode = struct.unpack(f">{segCount}H", subtable[start_pos : start_pos + segCountX2])
        delta_pos = start_pos + segCountX2
        idDelta = struct.unpack(f">{segCount}h", subtable[delta_pos : delta_pos + segCountX2])
        ro_pos = delta_pos + segCountX2
        idRangeOffset = struct.unpack(f">{segCount}H", subtable[ro_pos : ro_pos + segCountX2])
    except struct.error:
        return {}

    char_to_gid: Dict[int, int] = {}
    for i in range(segCount):
        sc, ec, delta, ro = startCode[i], endCode[i], idDelta[i], idRangeOffset[i]
        if sc == 0xFFFF and ec == 0xFFFF:
            break
        if ec < sc or (ec - sc) > 0x10000:
            continue
        for code in range(sc, ec + 1):
            if ro == 0:
                gid = (code + delta) & 0xFFFF
            else:
                idx = ro_pos + i * 2 + ro + (code - sc) * 2
                if idx + 2 <= len(subtable):
                    gid = struct.unpack(">H", subtable[idx : idx + 2])[0]
                    if gid != 0:
                        gid = (gid + delta) & 0xFFFF
                else:
                    gid = 0
            if gid != 0:
                char_to_gid[code] = gid
    return char_to_gid


def parse_cmap(cmap_bytes: bytes) -> Dict[Tuple[int, int, int], Dict[int, int]]:
    """Parses TrueType cmap subtables (formats 4 and 6)."""
    if not cmap_bytes or len(cmap_bytes) < 4:
        return {}
    try:
        _, num_tables = struct.unpack(">HH", cmap_bytes[:4])
    except struct.error:
        return {}
    subtables: Dict[Tuple[int, int, int], Dict[int, int]] = {}
    for i in range(num_tables):
        rec_off = 4 + i * 8
        if rec_off + 8 > len(cmap_bytes):
            break
        try:
            plat_id, enc_id, offset = struct.unpack(">HHI", cmap_bytes[rec_off : rec_off + 8])
            if offset + 4 > len(cmap_bytes):
                continue
            fmt = struct.unpack(">H", cmap_bytes[offset : offset + 2])[0]
            if fmt == 4:
                sub_len = struct.unpack(">H", cmap_bytes[offset + 2 : offset + 4])[0]
                if offset + sub_len <= len(cmap_bytes):
                    subtables[(plat_id, enc_id, fmt)] = _parse_cmap_format4(cmap_bytes[offset : offset + sub_len])
            elif fmt == 6:
                if offset + 10 <= len(cmap_bytes):
                    first_code, entry_count = struct.unpack(">HH", cmap_bytes[offset + 6 : offset + 10])
                    end_off = offset + 10 + entry_count * 2
                    if end_off <= len(cmap_bytes):
                        gids = struct.unpack(f">{entry_count}H", cmap_bytes[offset + 10 : end_off])
                        subtables[(plat_id, enc_id, fmt)] = {
                            first_code + idx: g for idx, g in enumerate(gids) if g != 0
                        }
        except struct.error:
            continue
    return subtables


def get_glyf_hashes(ttf_bytes: bytes) -> Dict[int, str]:
    """Computes SHA-256 hashes of raw TrueType glyph outlines for each GID."""
    tables = parse_ttf_tables(ttf_bytes)
    if not all(k in tables for k in ("head", "loca", "glyf", "maxp")):
        return {}
    head = tables["head"]
    maxp = tables["maxp"]
    loca = tables["loca"]
    glyf = tables["glyf"]
    if len(head) < 52 or len(maxp) < 6:
        return {}
    try:
        index_to_loc_format = struct.unpack(">h", head[50:52])[0]
        num_glyphs = struct.unpack(">H", maxp[4:6])[0]
    except struct.error:
        return {}

    offsets: List[int] = []
    if index_to_loc_format == 0:
        for i in range(num_glyphs + 1):
            if i * 2 + 2 <= len(loca):
                offsets.append(struct.unpack(">H", loca[i * 2 : i * 2 + 2])[0] * 2)
    else:
        for i in range(num_glyphs + 1):
            if i * 4 + 4 <= len(loca):
                offsets.append(struct.unpack(">I", loca[i * 4 : i * 4 + 4])[0])

    hashes: Dict[int, str] = {}
    for gid in range(num_glyphs):
        if gid + 1 < len(offsets):
            start, end = offsets[gid], offsets[gid + 1]
            if 0 <= start < end <= len(glyf):
                g_bytes = glyf[start:end]
                if g_bytes:
                    hashes[gid] = hashlib.sha256(g_bytes).hexdigest()
    return hashes


_REF_TABLES_LOADED = False
_REF_HASH_TO_UNI: Dict[str, str] = dict(FALLBACK_GLYF_HASH_TO_UNI)
_REF_GID_TO_UNI: Dict[int, str] = dict(FALLBACK_ARIAL_GID_TO_UNI)


def _ensure_reference_font_tables() -> Tuple[Dict[str, str], Dict[int, str]]:
    """Lazily loads system Arial/Calibri glyph hashes and GID maps when available."""
    global _REF_TABLES_LOADED
    if _REF_TABLES_LOADED:
        return _REF_HASH_TO_UNI, _REF_GID_TO_UNI
    _REF_TABLES_LOADED = True

    windir = os.environ.get("WINDIR", r"C:\Windows")
    font_dir = os.path.join(windir, "Fonts")
    for fname in ("arial.ttf", "arialbd.ttf", "calibri.ttf", "calibrib.ttf"):
        fpath = os.path.join(font_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "rb") as stream:
                buf = stream.read()
            tables = parse_ttf_tables(buf)
            if "cmap" not in tables:
                continue
            subs = parse_cmap(tables["cmap"])
            gh = get_glyf_hashes(buf)
            is_arial = fname.startswith("arial")
            for (plat_id, enc_id, _), mapping in subs.items():
                if (plat_id, enc_id) in ((3, 1), (0, 3)):
                    for code, gid in sorted(mapping.items()):
                        if 0x0020 <= code <= 0xFFFD and not (0xF000 <= code <= 0xF8FF):
                            ch = chr(code)
                            if is_arial:
                                _REF_GID_TO_UNI.setdefault(gid, ch)
                            if gid in gh:
                                _REF_HASH_TO_UNI.setdefault(gh[gid], ch)
        except Exception:
            continue
    return _REF_HASH_TO_UNI, _REF_GID_TO_UNI


@dataclass
class FontDiagnostic:
    xref: int
    name: str
    subtype: str
    has_broken_tounicode: bool = False
    repaired: bool = False
    repair_summary: str = ""
    unresolved_count: int = 0


def inspect_and_repair_pdf_fonts(doc: pymupdf.Document) -> Tuple[pymupdf.Document, Dict[int, FontDiagnostic]]:
    """
    Inspects embedded TrueType/Type0 fonts across the document for broken or incomplete
    `/ToUnicode` CMaps and repairs them in-memory using verified embedded `cmap` tables,
    glyph outline SHA-256 hashes, and Arial GID tables.

    Returns:
        (repaired_doc, font_diagnostics_by_xref)
        Note: Never modifies the source PDF on disk. If repairs are applied, re-opens the
        repaired PDF stream in memory so MuPDF refreshes cached font CMap structures.
    """
    ref_hash_to_uni, ref_gid_to_uni = _ensure_reference_font_tables()
    diagnostics: Dict[int, FontDiagnostic] = {}
    any_repaired = False

    for page_idx in range(len(doc)):
        try:
            page_fonts = doc[page_idx].get_fonts(full=True)
        except Exception:
            continue
        for f_info in page_fonts:
            xref = f_info[0]
            if xref in diagnostics:
                continue
            try:
                fname, fext, fsub, fbuf = doc.extract_font(xref)
            except Exception:
                continue
            f_diag = FontDiagnostic(xref=xref, name=fname or "", subtype=fsub or "")
            diagnostics[xref] = f_diag

            if fext != "ttf" or not fbuf:
                continue

            try:
                obj_str = doc.xref_object(xref)
            except Exception:
                continue
            m_tu = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", obj_str)
            if not m_tu:
                continue
            tu_xref = int(m_tu.group(1))
            try:
                tu_bytes = doc.xref_stream(tu_xref)
                tu_stream = tu_bytes.decode("latin1", errors="replace") if tu_bytes else ""
            except Exception:
                continue
            if not tu_stream:
                continue

            tables = parse_ttf_tables(fbuf)
            if "cmap" not in tables:
                continue
            subs = parse_cmap(tables["cmap"])
            gh = get_glyf_hashes(fbuf)

            local_gid_to_uni: Dict[int, str] = {3: " "}
            for (plat_id, enc_id, _), mapping in subs.items():
                if (plat_id, enc_id) in ((3, 1), (0, 3)):
                    for code, gid in sorted(mapping.items()):
                        if 0x0020 <= code <= 0xFFFD and not (0xF000 <= code <= 0xF8FF):
                            local_gid_to_uni.setdefault(gid, chr(code))

            # Case 1: Type0 Identity-H font with <001F> control characters in /ToUnicode
            # (e.g. العابد نقدي الخميس.pdf where <001F> and several mismatched Arabic presentation
            # forms appear in /ToUnicode while the embedded FontFile2 has a complete Unicode cmap).
            if fsub == "Type0" and "<001F>" in tu_stream.upper():
                f_diag.has_broken_tounicode = True
                has_full_cmap = len(local_gid_to_uni) > 500
                fixed_count = 0
                unresolved = 0

                def _repl_type0(match: re.Match) -> str:
                    nonlocal fixed_count, unresolved
                    cid_hex, uni_hex = match.group(1), match.group(2)
                    cid = int(cid_hex, 16)
                    uni = int(uni_hex, 16)
                    if has_full_cmap and cid in local_gid_to_uni:
                        true_ch = local_gid_to_uni[cid]
                        if ord(true_ch) != uni:
                            fixed_count += 1
                        return f"<{cid_hex}> <{ord(true_ch):04X}>"
                    if uni == 0x001F or uni < 0x0020:
                        true_ch = (
                            local_gid_to_uni.get(cid)
                            or (ref_hash_to_uni.get(gh[cid]) if cid in gh else None)
                            or ref_gid_to_uni.get(cid)
                        )
                        if true_ch:
                            fixed_count += 1
                            return f"<{cid_hex}> <{ord(true_ch):04X}>"
                        unresolved += 1
                    return match.group(0)

                new_tu = re.sub(r"<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>", _repl_type0, tu_stream)
                f_diag.unresolved_count = unresolved
                if fixed_count > 0 and new_tu != tu_stream:
                    doc.update_stream(tu_xref, new_tu.encode("latin1"))
                    f_diag.repaired = True
                    f_diag.repair_summary = f"Type0 ToUnicode repaired ({fixed_count} entries)"
                    any_repaired = True

            # Case 2: Simple 1-byte TrueType subset font with incomplete /ToUnicode CMap
            # (e.g. 2طباعه مزدوجه.pdf where 59 of 117 glyph codes are omitted from /ToUnicode).
            elif fsub == "TrueType":
                code_to_gid: Dict[int, int] = {}
                if (1, 0, 6) in subs:
                    code_to_gid = subs[(1, 0, 6)]
                elif (3, 0, 4) in subs:
                    code_to_gid = {code & 0xFF: gid for code, gid in subs[(3, 0, 4)].items()}

                if code_to_gid:
                    existing_tu: Dict[int, str] = {}
                    for m in re.finditer(
                        r"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4})>", tu_stream
                    ):
                        c1, c2, u = int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)
                        for idx, c in enumerate(range(c1, c2 + 1)):
                            existing_tu[c] = chr(u + idx)
                    for m in re.finditer(r"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4})>", tu_stream):
                        c, u = int(m.group(1), 16), int(m.group(2), 16)
                        existing_tu[c] = chr(u)

                    missing_codes = [c for c in code_to_gid if c not in existing_tu]
                    if missing_codes:
                        f_diag.has_broken_tounicode = True
                        full_map = dict(existing_tu)
                        resolved_count = 0
                        unresolved = 0
                        for c in missing_codes:
                            gid = code_to_gid[c]
                            true_ch = (
                                local_gid_to_uni.get(gid)
                                or (ref_hash_to_uni.get(gh[gid]) if gid in gh else None)
                                or ref_gid_to_uni.get(gid)
                            )
                            if true_ch:
                                full_map[c] = true_ch
                                resolved_count += 1
                            else:
                                unresolved += 1
                        f_diag.unresolved_count = unresolved
                        if resolved_count > 0:
                            lines = [
                                "/CIDInit /ProcSet findresource begin",
                                "12 dict begin",
                                "begincmap",
                                "/CMapType 2 def",
                                f"/CMapName/R{tu_xref} def",
                                "1 begincodespacerange",
                                "<00><ff>",
                                "endcodespacerange",
                                f"{len(full_map)} beginbfchar",
                            ]
                            for c, ch in sorted(full_map.items()):
                                lines.append(f"<{c:02x}><{ord(ch):04x}>")
                            lines.extend(
                                [
                                    "endbfchar",
                                    "endcmap",
                                    "CMapName currentdict /CMap defineresource pop",
                                    "end end",
                                ]
                            )
                            doc.update_stream(tu_xref, "\n".join(lines).encode("latin1"))
                            f_diag.repaired = True
                            f_diag.repair_summary = (
                                f"TrueType ToUnicode completed ({resolved_count}/{len(missing_codes)} codes)"
                            )
                            any_repaired = True

    if any_repaired:
        pdf_bytes = doc.tobytes()
        doc.close()
        repaired_doc = pymupdf.open("pdf", pdf_bytes)
        return repaired_doc, diagnostics

    return doc, diagnostics


# Suspicious character detector used for page assessment and row quality checks
SUSPICIOUS_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd\u0370-\u03ff\u1400-\u167f\u16a0-\u16ff\u1800-\u18af]"
)


def has_suspicious_characters(text: str) -> Tuple[bool, List[str]]:
    """
    Checks whether extracted or normalized text still contains unmapped control bytes,
    replacement characters (U+FFFD), or legacy custom-font scripts (Greek, Canadian Aboriginal,
    Runic, Mongolian).
    """
    if not text:
        return False, []
    reasons: List[str] = []
    if "\ufffd" in text:
        reasons.append("replacement_char_ufffd")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
        reasons.append("control_char_in_text")
    if re.search(r"[\u0370-\u03ff]", text):
        reasons.append("unmapped_greek_glyphs")
    if re.search(r"[\u1400-\u167f\u16a0-\u16ff\u1800-\u18af]", text):
        reasons.append("unmapped_custom_script_glyphs")
    return bool(reasons), reasons


@dataclass
class PageAssessment:
    page: int
    classification: str  # usable_digital, suspicious_encoding, image_only, mixed_content, pure_raster, pure_vector, mixed_vector
    selected_method: str
    reasons: List[str] = field(default_factory=list)
    font_repaired: bool = False
    mode: str = "pure_vector"  # pure_vector, mixed_vector, pure_raster


def assess_pdf_page(
    page: pymupdf.Page,
    page_idx: int,
    font_diagnostics: Optional[Dict[int, FontDiagnostic]] = None,
) -> PageAssessment:
    """
    Classifies a single PDF page independently across 3 operational modes:
      - pure_vector: Clean digital vector text or font CMap repaired text stream.
      - mixed_vector: Digital vector text with unmapped image regions or damaged bounding boxes.
      - pure_raster: Image-only or scanned raster pages requiring CV table slicing and OCR.
    """
    reasons: List[str] = []
    font_repaired = False
    has_broken_font = False
    has_unresolved_font = False

    if font_diagnostics:
        try:
            for f_info in page.get_fonts(full=True):
                xref = f_info[0]
                fd = font_diagnostics.get(xref)
                if fd:
                    if fd.has_broken_tounicode:
                        has_broken_font = True
                    if fd.repaired:
                        font_repaired = True
                        if fd.repair_summary and fd.repair_summary not in reasons:
                            reasons.append(fd.repair_summary)
                    if fd.unresolved_count > 0:
                        has_unresolved_font = True
                        reasons.append(f"unresolved_font_glyphs_{fd.unresolved_count}")
        except Exception:
            pass

    raw_text = page.get_text("text") or ""
    stripped_text = raw_text.strip()
    char_count = len(stripped_text)

    try:
        images = page.get_images(full=True)
    except Exception:
        images = []
    has_images = len(images) > 0

    has_susp, susp_reasons = has_suspicious_characters(stripped_text)
    if has_susp:
        reasons.extend(susp_reasons)

    if char_count < 15:
        if has_images:
            reasons.append("image_only_no_digital_text")
            return PageAssessment(
                page=page_idx + 1,
                classification="image_only",
                selected_method="raster_table_ocr",
                reasons=reasons,
                font_repaired=font_repaired,
                mode="pure_raster",
            )
        reasons.append("empty_or_minimal_digital_text")
        return PageAssessment(
            page=page_idx + 1,
            classification="usable_digital",
            selected_method="digital_empty",
            reasons=reasons,
            font_repaired=font_repaired,
            mode="pure_vector",
        )

    if has_susp or has_unresolved_font:
        reasons.append("suspicious_character_encoding_detected")
        return PageAssessment(
            page=page_idx + 1,
            classification="suspicious_encoding",
            selected_method="digital_with_font_recovery",
            reasons=reasons,
            font_repaired=font_repaired,
            mode="pure_vector",
        )

    if has_broken_font and font_repaired:
        reasons.append("repaired_broken_tounicode_cmap")
        return PageAssessment(
            page=page_idx + 1,
            classification="suspicious_encoding",
            selected_method="digital_font_cmap_repaired",
            reasons=reasons,
            font_repaired=True,
            mode="pure_vector",
        )

    if has_images and char_count < 120:
        reasons.append("mixed_images_and_sparse_digital_text")
        return PageAssessment(
            page=page_idx + 1,
            classification="mixed_content",
            selected_method="digital_and_region_review",
            reasons=reasons,
            font_repaired=font_repaired,
            mode="mixed_vector",
        )

    reasons.append("clean_digital_text")
    return PageAssessment(
        page=page_idx + 1,
        classification="usable_digital",
        selected_method="digital_table_and_coordinate",
        reasons=reasons,
        font_repaired=font_repaired,
        mode="pure_vector",
    )


def _is_ltr_char(ch: str) -> bool:
    return ("0" <= ch <= "9") or ("A" <= ch <= "Z") or ("a" <= ch <= "z")


def reconstruct_rtl_line_from_chars(chars: List[Dict[str, Any]]) -> str:
    """
    Reconstructs natural RTL Arabic reading order from a list of PyMuPDF `rawdict` character
    dicts (`{'c': str, 'bbox': (x0, y0, x1, y1)}`) on a single horizontal line while keeping
    LTR runs (numbers, decimals, multi-part ratios like `1000/2.5/12.5`, Latin words) intact.
    """
    if not chars:
        return ""
    valid = [c for c in chars if c.get("c") and ord(c["c"]) >= 0x20]
    if not valid:
        return ""

    by_x_asc = sorted(valid, key=lambda c: (round((c["bbox"][0] + c["bbox"][2]) / 2.0, 2), c["bbox"][0]))

    tokens: List[Dict[str, Any]] = []
    i = 0
    n = len(by_x_asc)
    while i < n:
        c = by_x_asc[i]
        ch = c["c"]
        x0, _, x1, _ = c["bbox"]
        is_leading_dot_num = (
            ch == "."
            and i + 1 < n
            and "0" <= by_x_asc[i + 1]["c"] <= "9"
            and (by_x_asc[i + 1]["bbox"][0] - x1) <= 2.5
        )
        if _is_ltr_char(ch) or is_leading_dot_num:
            run_chars = [ch]
            run_x0, run_x1 = x0, x1
            j = i + 1
            while j < n:
                nc = by_x_asc[j]
                nch = nc["c"]
                nx0, _, nx1, _ = nc["bbox"]
                gap = nx0 - run_x1
                if gap <= 2.5 and _is_ltr_char(nch):
                    run_chars.append(nch)
                    run_x1 = max(run_x1, nx1)
                    j += 1
                elif (
                    gap <= 2.5
                    and nch in (".", "/", "-")
                    and j + 1 < n
                    and _is_ltr_char(by_x_asc[j + 1]["c"])
                    and (by_x_asc[j + 1]["bbox"][0] - nx1) <= 2.5
                ):
                    run_chars.append(nch)
                    run_x1 = max(run_x1, nx1)
                    j += 1
                elif gap <= 2.5 and nch == "%" and any("0" <= rc <= "9" for rc in run_chars):
                    run_chars.append(nch)
                    run_x1 = max(run_x1, nx1)
                    j += 1
                else:
                    break
            tokens.append({"text": "".join(run_chars), "x0": run_x0, "x1": run_x1, "kind": "ltr"})
            i = j
        else:
            tokens.append({"text": ch, "x0": x0, "x1": x1, "kind": "rtl"})
            i += 1

    rtl_tokens = list(reversed(tokens))
    out: List[str] = []
    for idx, tok in enumerate(rtl_tokens):
        if idx > 0:
            prev = rtl_tokens[idx - 1]
            gap = prev["x0"] - tok["x1"]
            if prev["text"] != " " and tok["text"] != " ":
                if gap > 1.8:
                    out.append(" ")
        out.append(tok["text"])
    res = unicodedata.normalize("NFKC", "".join(out))
    return re.sub(r"\s+", " ", res).strip()


def extract_page_chars(page: pymupdf.Page) -> List[Dict[str, Any]]:
    """Extracts all character dicts from a page's `rawdict` representation."""
    chars: List[Dict[str, Any]] = []
    try:
        rd = page.get_text("rawdict")
    except Exception:
        return chars
    for b in rd.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                for c in s.get("chars", []):
                    if c.get("c") and c.get("bbox"):
                        chars.append(c)
    return chars


def reconstruct_cell_text_from_chars(
    page_chars: List[Dict[str, Any]],
    bbox: Tuple[float, float, float, float],
    y_tolerance: float = 4.5,
) -> str:
    """
    Reconstructs multi-line or single-line cell text inside `bbox` directly from character
    coordinates, preserving top-to-bottom wrapped line order and natural RTL/LTR token order.
    """
    if not page_chars or not bbox:
        return ""
    x0, y0, x1, y1 = bbox
    cell_chars = [
        c
        for c in page_chars
        if (x0 - 1.5) <= ((c["bbox"][0] + c["bbox"][2]) / 2.0) <= (x1 + 1.5)
        and (y0 + 0.5) <= ((c["bbox"][1] + c["bbox"][3]) / 2.0) <= (y1 - 0.5)
    ]
    if not cell_chars:
        return ""

    lines: List[Dict[str, Any]] = []
    for c in sorted(cell_chars, key=lambda item: (item["bbox"][1] + item["bbox"][3]) / 2.0):
        yc = (c["bbox"][1] + c["bbox"][3]) / 2.0
        placed = False
        for ln in lines:
            if abs(ln["yc"] - yc) <= y_tolerance:
                ln["chars"].append(c)
                ln["yc"] = sum((x["bbox"][1] + x["bbox"][3]) / 2.0 for x in ln["chars"]) / len(ln["chars"])
                placed = True
                break
        if not placed:
            lines.append({"yc": yc, "chars": [c]})

    line_texts = [reconstruct_rtl_line_from_chars(ln["chars"]) for ln in sorted(lines, key=lambda l: l["yc"])]
    return " ".join(t for t in line_texts if t).strip()
