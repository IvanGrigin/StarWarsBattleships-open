#!/usr/bin/env python3
"""Конвейер из мастер-плана (§11): Minecraft-постройка -> модель для игры.

Читает Sponge-схематики (.schem: legacy Blocks/Data и v2/v3 Palette/BlockData),
режет на воксели, при необходимости уменьшает (mode-пул), отбрасывает скрытые
грани, жадно сливает копланарные (greedy meshing) и выдаёт компактный JSON
сэмплирования для Three.js (demo/schem_models.js).

Использование:
  python3 tools/schem_to_mesh.py --src a.schem --out ../demo/assets/models/meshes/star_destroyer.json \
      --axis x --flip-x --max 72
Формат выхода: {"n":[nx,ny,nz], "faces":[[x,y,z,dir,w,h,r,g,b], ...]} — по грани.
"""
import argparse, gzip, json, struct, sys, os

# ---------- NBT ----------

class R:
    def __init__(s, b): s.b = b; s.i = 0
    def u1(s): v = s.b[s.i]; s.i += 1; return v
    def i2(s): v = struct.unpack_from('>h', s.b, s.i)[0]; s.i += 2; return v
    def i4(s): v = struct.unpack_from('>i', s.b, s.i)[0]; s.i += 4; return v
    def i8(s): v = struct.unpack_from('>q', s.b, s.i)[0]; s.i += 8; return v
    def str_(s):
        n = struct.unpack_from('>H', s.b, s.i)[0]; s.i += 2
        v = s.b[s.i:s.i+n].decode('utf-8', 'replace'); s.i += n; return v

SKIP = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8, 11: 4, 12: 8}

def read_payload(r, t, keep_names=None, path=''):
    if t in SKIP: 
        v = None
        if t == 1: v = r.u1()
        elif t == 2: v = r.i2()
        elif t == 3: v = r.i4()
        elif t == 4: v = r.i8()
        elif t == 5: r.i += 4; v = 0
        elif t == 6: r.i += 8; v = 0
        elif t == 11:
            n = r.i4(); v = list(struct.unpack_from('>%di' % n, r.b, r.i)); r.i += 4 * n; return v
        elif t == 12:
            n = r.i4(); v = list(struct.unpack_from('>%dq' % n, r.b, r.i)); r.i += 8 * n; return v
        return v
    if t == 7:
        n = r.i4(); v = r.b[r.i:r.i+n]; r.i += n; return v
    if t == 8: return r.str_()
    if t == 9:
        it = r.u1(); n = r.i4()
        out = []
        for _ in range(n):
            if it in SKIP:
                v = None
                if it == 1: v = r.u1()
                elif it == 2: v = r.i2()
                elif it == 3: v = r.i4()
                elif it == 4: v = r.i8()
                elif it == 5: r.i += 4
                elif it == 6: r.i += 8
                elif it == 7: n2 = r.i4(); v = r.b[r.i:r.i+n2]; r.i += n2
                elif it == 11: n2 = r.i4(); r.i += 4 * n2
                elif it == 12: n2 = r.i4(); r.i += 8 * n2
                out.append(v)
            else:
                out.append(read_payload(r, it, keep_names, path + '[]'))
        return out
    if t == 10:
        d = {}
        while True:
            et = r.u1()
            if et == 0: break
            name = r.str_()
            sub = path + '/' + name
            if keep_names is None or sub in keep_names or depth_kept(sub):
                d[name] = read_payload(r, et, keep_names, sub)
            else:
                read_payload(r, et, keep_names, sub)
        return d
    raise ValueError('tag %d at %s' % (t, path))

def depth_kept(sub):
    # тяжёлые массивы читаем только по прямому пути
    return True

def parse_nbt(raw):
    r = R(raw)
    t = r.u1()
    if t != 10: raise ValueError('root не compound')
    r.str_()
    return read_payload(r, 10, keep_names=set())

# ---------- варианты схематиков ----------

def entry_name(e):
    if isinstance(e, str): return e.replace('minecraft:', '')
    if isinstance(e, dict): return e.get('Name', 'air').replace('minecraft:', '')
    return 'air'

def load_schem(path):
    data = open(path, 'rb').read()
    if data[:2] == b'PK':
        raise SystemExit('это zip — распакуй и укажи .schem внутри')
    raw = gzip.decompress(data)
    root = parse_nbt(raw)
    if 'Schematic' in root and 'Width' not in root:
        root = root['Schematic']  # Sponge v3: данные во вложенном compound
    if 'Width' not in root and 'Regions' not in root:
        raise SystemExit('похоже на .litematic/мир — формат не поддержан этим скриптом')
    if 'Regions' in root:
        return load_litematic(path)
    w, h, l = root['Width'], root['Height'], root['Length']

    def varints(bd):
        if isinstance(bd, str): bd = bd.encode('latin-1')
        out = []; val = 0; shift = 0
        for b in bd:
            val |= (b & 0x7F) << shift
            shift += 7
            if b & 0x80: continue
            out.append(val); val = 0; shift = 0
        return out

    def clean(name): return name.split('[')[0].replace('minecraft:', '')

    # (а) корневая палитра: v2 (BlockData) и v3-nested (Blocks = {Palette, Data})
    pal_root = root.get('Palette') or (root.get('Blocks') or {}).get('Palette') if isinstance(root.get('Blocks'), dict) else root.get('Palette')
    if isinstance(pal_root, dict):
        pal = {int(idx): clean(name) for name, idx in pal_root.items()}
        vox = [0] * (w * h * l)
        bd = root.get('BlockData') or (root.get('Blocks') or {}).get('Data')
        vals = varints(bd)
        for i, sid in enumerate(vals):
            if i < len(vox): vox[i] = sid
        def get(x, y, z): return vox[(y * l + z) * w + x]
        return w, h, l, get, pal
    elif isinstance(root.get('Blocks'), (bytes, bytearray)):  # legacy Alpha/WE
        blocks = root['Blocks']; data_b = root.get('Data', b'')
        def get(x, y, z):
            i = (y * l + z) * w + x
            return (blocks[i], data_b[i] if i < len(data_b) else 0)
        pal = None
    return w, h, l, get, pal

def load_litematic(path):
    raw = gzip.decompress(open(path, 'rb').read())
    root = parse_nbt(raw)
    regions = root.get('Regions') or {}
    boxes = []
    for rname, reg in regions.items():
        size = reg.get('Size') or {}
        pos = reg.get('Position') or {}
        sx, sy, sz = int(size.get('x', 0)), int(size.get('y', 0)), int(size.get('z', 0))
        px, py, pz = int(pos.get('x', 0)), int(pos.get('y', 0)), int(pos.get('z', 0))
        boxes.append((abs(sx), abs(sy), abs(sz),
                      px if sx >= 0 else px + sx,
                      py if sy >= 0 else py + sy,
                      pz if sz >= 0 else pz + sz,
                      [entry_name(e) for e in (reg.get('BlockStatePalette') or reg.get('Palette') or [])],
                      reg.get('BlockStates') or []))
    if not boxes: raise SystemExit('litematic без регионов')
    minx = min(b[3] for b in boxes); miny = min(b[4] for b in boxes); minz = min(b[5] for b in boxes)
    nx = max(b[3] + b[0] for b in boxes) - minx
    ny = max(b[4] + b[1] for b in boxes) - miny
    nz = max(b[5] + b[2] for b in boxes) - minz
    vox = [0] * (nx * ny * nz)
    global_pal = {}      # gid -> name
    next_gid = 1
    for (rw, rh, rl, x0, y0, z0, pal, longs) in boxes:
        if not pal or (len(pal) == 1 and pal[0] == 'air'): continue
        local = {}
        for sid, name in enumerate(pal):
            if name == 'air': local[sid] = 0; continue
            gid = next((g for g, nm in global_pal.items() if nm == name), 0)
            if gid == 0:
                gid = next_gid; global_pal[gid] = name; next_gid += 1
            local[sid] = gid
        bits = max(2, (len(pal) - 1).bit_length())
        per = 64 // bits
        mask = (1 << bits) - 1
        i = 0
        for lv in longs:
            lv &= (1 << 64) - 1
            for k in range(per):
                if i >= rw * rh * rl: break
                sid = (lv >> (k * bits)) & mask
                if sid in local and local[sid]:
                    ly = i // (rw * rl); rem = i % (rw * rl); lz = rem // rw; lx = rem % rw
                    vox[((y0 - miny + ly) * nz + (z0 - minz + lz)) * nx + (x0 - minx + lx)] = local[sid]
                i += 1
    g = {}
    for j, gid in enumerate(vox):
        if not gid: continue
        y, rem = divmod(j, nx * nz); z, x = divmod(rem, nx)
        c = block_color(global_pal[gid])
        if c: g[(x, y, z)] = c
    # обрезаем пустоту
    xs = [p[0] for p in g]; ys = [p[1] for p in g]; zs = [p[2] for p in g]
    if not xs: raise SystemExit('litematic пуста')
    out = {}
    for (x, y, z), c in g.items():
        out[(x - min(xs), y - min(ys), z - min(zs))] = c
    dim = [max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, max(zs) - min(zs) + 1]
    return out, dim

# ---------- палитра цветов Minecraft ----------

WOOL = {'white': 0xE9ECEC, 'orange': 0xF07613, 'magenta': 0xBD44B3, 'light_blue': 0x3AAFD9,
        'yellow': 0xF8C627, 'lime': 0x70B919, 'pink': 0xED8DAC, 'gray': 0x3E4447,
        'light_gray': 0x8E8E86, 'cyan': 0x158991, 'purple': 0x792AAC, 'blue': 0x35399D,
        'brown': 0x724728, 'green': 0x546D1B, 'red': 0xA12722, 'black': 0x141519}

def block_color(name):
    """Базовый цвет блока по имени (упрощённая палитра Minecraft)."""
    if name in ('air', 'cave_air', 'void_air', 'structure_void'): return None
    base = name.split('[')[0]
    for pref in ('stairs', 'slab', 'wall', 'fence', 'fence_gate', 'pressure_plate', 'button',
                 'trapdoor', 'door', 'sign', 'carpet', 'pane', 'bars', 'chain', 'torch',
                 'lantern', 'rail', 'campfire', 'candle'):
        if pref in base:
            base = base.replace('_' + pref, '') if ('_' + pref) in base else base
    n = base.replace('minecraft:', '')
    # цветные семейства
    for cname, rgb in WOOL.items():
        for fam in ('wool', 'concrete', 'terracotta', 'concrete_powder', 'glazed_terracotta'):
            if n == cname + '_' + fam:
                k = 1.0 if fam == 'wool' else (0.82 if fam == 'terracotta' else 0.95)
                return (((rgb >> 16) & 255) * k, ((rgb >> 8) & 255) * k, (rgb & 255) * k)
        if n == cname + '_stained_glass' or n == cname + '_glass':
            rgb = WOOL[cname]
            return ((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255)
    simple = {
        'stone': (125, 125, 125), 'cobblestone': (110, 110, 110), 'stone_bricks': (122, 122, 122),
        'stone_brick': (122, 122, 122), 'mossy_stone_bricks': (110, 120, 100),
        'cracked_stone_bricks': (110, 110, 110), 'chiseled_stone_bricks': (118, 118, 118),
        'smooth_stone': (156, 156, 156), 'granite': (149, 103, 85), 'diorite': (188, 188, 191),
        'andesite': (136, 136, 137), 'deepslate': (80, 80, 84), 'cobbled_deepslate': (86, 86, 90),
        'deepslate_bricks': (84, 84, 88), 'deepslate_tiles': (74, 74, 78), 'polished_deepslate': (82, 82, 86),
        'blackstone': (45, 40, 48), 'polished_blackstone': (51, 46, 54),
        'polished_blackstone_bricks': (43, 38, 46), 'gilded_blackstone': (52, 44, 48),
        'bedrock': (85, 85, 85), 'dirt': (134, 96, 67), 'grass_block': (127, 178, 56),
        'sand': (219, 207, 163), 'red_sand': (190, 102, 33), 'gravel': (127, 124, 123),
        'clay': (160, 166, 179), 'snow_block': (249, 254, 254), 'ice': (145, 183, 253),
        'packed_ice': (141, 180, 250), 'obsidian': (15, 10, 24), 'crying_obsidian': (20, 18, 29),
        'netherrack': (97, 38, 38), 'nether_bricks': (44, 22, 26), 'soul_sand': (81, 62, 50),
        'end_stone': (219, 222, 158), 'purpur': (167, 125, 167), 'quartz_block': (236, 229, 222),
        'smooth_quartz': (236, 229, 222), 'iron_block': (220, 220, 220), 'iron_ore': (136, 136, 130),
        'gold_block': (246, 208, 61), 'diamond_block': (98, 237, 228), 'emerald_block': (42, 203, 87),
        'redstone_block': (212, 21, 16), 'lapis_block': (31, 64, 182), 'coal_block': (10, 10, 10),
        'netherite_block': (68, 64, 66), 'copper_block': (192, 108, 75),
        'oak_planks': (162, 130, 78), 'spruce_planks': (114, 84, 48), 'birch_planks': (192, 175, 121),
        'jungle_planks': (160, 115, 80), 'acacia_planks': (168, 90, 50), 'dark_oak_planks': (66, 43, 20),
        'crimson_planks': (101, 48, 66), 'warped_planks': (43, 88, 79),
        'oak_log': (109, 84, 50), 'spruce_log': (58, 37, 16), 'dark_oak_log': (51, 39, 21),
        'glass': (200, 220, 225), 'white_concrete': (207, 213, 214), 'gray_concrete': (54, 57, 61),
        'light_gray_concrete': (125, 125, 115), 'black_concrete': (8, 10, 15),
        'blue_ice': (116, 167, 253), 'sea_lantern': (172, 199, 190), 'glowstone': (249, 212, 140),
        'shroomlight': (240, 146, 70), 'prismarine': (99, 156, 151), 'prismarine_bricks': (99, 171, 166),
        'dark_prismarine': (51, 93, 80), 'bricks': (151, 97, 83), 'coarse_dirt': (119, 85, 59),
        'polished_andesite': (140, 140, 141), 'smooth_sandstone': (223, 214, 177),
        'cut_sandstone': (215, 205, 158), 'smooth_red_sandstone': (190, 105, 36),
        'red_nether_bricks': (69, 7, 9), 'mossy_cobblestone': (100, 110, 90),
        'calcite': (223, 224, 220), 'tuff': (108, 109, 102), 'dripstone_block': (134, 107, 92),
        'amethyst_block': (133, 97, 191), 'warped_wart_block': (22, 126, 121),
        'nether_wart_block': (94, 8, 8), 'bone_block': (203, 199, 170),
        'packed_mud': (143, 102, 79), 'mud_bricks': (137, 100, 78),
        'chiseled_quartz_block': (231, 224, 216), 'quartz_pillar': (235, 228, 221),
        'quartz_bricks': (233, 226, 219), 'redstone_lamp': (166, 199, 130),
    }
    if n in simple: return simple[n]
    # производные: плиты/ступени/стены известного камня
    for key, rgb in simple.items():
        if n.startswith(key) or key.startswith(n):
            return rgb
    if 'planks' in n: return (150, 120, 75)
    if 'log' in n or 'wood' in n: return (105, 80, 50)
    if 'glass' in n: return (200, 220, 225)
    if 'anvil' in n: return (70, 70, 70)
    if 'candle' in n: return (210, 200, 180)
    if 'skull' in n or 'head' in n: return (30, 30, 30)
    return (140, 140, 140)  # неизвестное — средне-серый

def color_of(pal, get, x, y, z):
    v = get(x, y, z)
    if pal is not None:
        name = pal.get(v)
        return block_color(name) if name else None
    # legacy: id+data — покрываем основные id
    bid, meta = v
    legacy = {1: (125, 125, 125), 4: (110, 110, 110), 5: (162, 130, 78), 17: (109, 84, 50),
              20: (200, 220, 225), 24: (215, 205, 158), 35: (220, 220, 220), 42: (220, 220, 220),
              45: (151, 97, 83), 49: (15, 10, 24), 98: (122, 122, 122), 121: (219, 222, 158),
              155: (236, 229, 222), 159: (207, 213, 214), 173: (10, 10, 10), 174: (249, 254, 254)}
    if bid == 35 or bid == 159 or bid == 251:  # шерсть/бетон: 16 цветов по meta
        keys = list(WOOL.items())
        rgb = keys[meta % 16][1]
        return (rgb >> 16, (rgb >> 8) & 255, rgb & 255)
    return legacy.get(bid, (140, 140, 140))

# ---------- крупнейшая связная компонента ----------
# В схематиках часто лежат копии постройки/голограммы/подставки рядом.
# Оставляем только самый большой связный кусок — это и есть корабль.

def recrop(g):
    xs = [p[0] for p in g]; ys = [p[1] for p in g]; zs = [p[2] for p in g]
    x0, y0, z0 = min(xs), min(ys), min(zs)
    nx, ny, nz = max(xs) - x0 + 1, max(ys) - y0 + 1, max(zs) - z0 + 1
    return { (x - x0, y - y0, z - z0): c for (x, y, z), c in g.items() }, (nx, ny, nz)

def largest_component(g):
    seen = set()
    best = None
    for start in list(g.keys()):
        if start in seen: continue
        comp = {start}; queue = [start]; seen.add(start)
        while queue:
            x, y, z = queue.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        p = (x + dx, y + dy, z + dz)
                        if p in g and p not in seen:
                            seen.add(p); comp.add(p); queue.append(p)
        if best is None or len(comp) > len(best): best = comp
    dropped = len(g) - len(best)
    return {p: g[p] for p in best}, dropped

# ---------- воксели + downsample ----------

def collect(w, h, l, get, pal):
    g = {}
    for y in range(h):
        for z in range(l):
            for x in range(w):
                c = color_of(pal, get, x, y, z)
                if c: g[(x, y, z)] = c
    return g

def crop(g):
    xs = [p[0] for p in g]; ys = [p[1] for p in g]; zs = [p[2] for p in g]
    return min(xs), min(ys), min(zs), max(xs) + 1, max(ys) + 1, max(zs) + 1

def pool(g, x0, y0, z0, x1, y1, z1, k):
    if k <= 1: return g, x1 - x0, y1 - y0, z1 - z0
    g2 = {}
    nx = (x1 - x0 + k - 1) // k; ny = (y1 - y0 + k - 1) // k; nz = (z1 - z0 + k - 1) // k
    for cx in range(nx):
        for cy in range(ny):
            for cz in range(nz):
                # самый частый непустой цвет в ячейке (детерминированно)
                cnt = {}
                for x in range(x0 + cx * k, min(x0 + (cx + 1) * k, x1)):
                    for y in range(y0 + cy * k, min(y0 + (cy + 1) * k, y1)):
                        for z in range(z0 + cz * k, min(z0 + (cz + 1) * k, z1)):
                            c = g.get((x, y, z))
                            if c: cnt[c] = cnt.get(c, 0) + 1
                if cnt:
                    g2[(cx, cy, cz)] = max(cnt.items(), key=lambda kv: (kv[1], str(kv[0])))[0]
    return g2, nx, ny, nz

# ---------- greedy meshing ----------

DIRS = [((1, 0, 0), 0.78), ((-1, 0, 0), 0.78), ((0, 1, 0), 1.0), ((0, -1, 0), 0.5), ((0, 0, 1), 0.9), ((0, 0, -1), 0.86)]

def greedy(g, nx, ny, nz):
    faces = []
    def at(x, y, z):
        return g.get((x, y, z)) if 0 <= x < nx and 0 <= y < ny and 0 <= z < nz else None
    for d, (nrm, _shade) in enumerate(DIRS):
        dx, dy, dz = nrm
        # срезы вдоль оси нормали
        axis = (0, 1, 2) if dx else ((1, 0, 2) if dy else (2, 0, 1))
        # генерируем маску видимости и жадно сливаем прямоугольники
        size = [nx, ny, nz]
        a1, a2 = axis[1], axis[2]
        n_main = size[axis[0]]
        for s in range(n_main + 1):
            mask = {}
            # заполнить маску: координаты (a1, a2) -> цвет, если voxel существует на одной стороне
            cur = [0, 0, 0]; cur[axis[0]] = s
            for i in range(size[a1]):
                for j in range(size[a2]):
                    p = list(cur); p[a1] = i; p[a2] = j
                    c1 = g.get(tuple(p))
                    q = list(p); q[axis[0]] -= 1
                    c0 = g.get(tuple(q))
                    if c1 and not c0: mask[(i, j)] = (c1, 1)
                    elif c0 and not c1: mask[(i, j)] = (c0, 0)
            # жадное слияние
            used = set()
            for (i, j) in sorted(mask.keys()):
                if (i, j) in used: continue
                c, sign = mask[(i, j)]
                w = 1
                while (i + w, j) in mask and (i + w, j) not in used and mask[(i + w, j)] == (c, sign): w += 1
                hgt = 1
                while all((i + ww, j + hgt) in mask and (i + ww, j + hgt) not in used and mask[(i + ww, j + hgt)] == (c, sign) for ww in range(w)):
                    hgt += 1
                for ww in range(w):
                    for hh in range(hgt):
                        used.add((i + ww, j + hgt))
                faces.append((s, d, sign, a1, a2, i, j, w, hgt, c))
    return faces

def emit(faces, nx, ny, nz, ax, flip_x, flip_z):
    """Каждая грань -> [px,py,pz, ux,uy,uz,ul, vx,vy,vz,vl, r,g,b].
    Базовая точка и два ребра квада; нормаль = cross(u, v)."""
    out = []
    for (s, d, sign, a1, a2, i, j, w, h, c) in faces:
        shade = DIRS[d][1]
        axis = (0, 1, 2) if d in (0, 1) else ((1, 0, 2) if d in (2, 3) else (2, 0, 1))
        p = [0.0, 0.0, 0.0]
        p[axis[0]] = s
        p[a1] = i; p[a2] = j
        u = [0.0, 0.0, 0.0]; v = [0.0, 0.0, 0.0]
        u[a1] = w; v[a2] = h
        if ax == 'z':
            if flip_z:
                p[2] = nz - p[2]; u[2] = -u[2]; v[2] = -v[2]
        else:
            # поворот: X игры <- Z постройки, Z игры <- X постройки
            for pt in (p, u, v):
                pt[0], pt[2] = pt[2], pt[0]
            if flip_x:
                p[2] = nx - p[2]; u[2] = -u[2]; v[2] = -v[2]
        out.append([round(p[0], 2), round(p[1], 2), round(p[2], 2),
                    u[0], u[1], u[2],
                    v[0], v[1], v[2],
                    int(c[0] * shade), int(c[1] * shade), int(c[2] * shade), d])
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--axis', default='x', choices=['x', 'z'], help='ось длины постройки')
    ap.add_argument('--flip-x', action='store_true')
    ap.add_argument('--flip-z', action='store_true')
    ap.add_argument('--max', type=int, default=72, help='максимум вокселей по длинной оси')
    ap.add_argument('--strip-bottom', type=int, default=0, help='срезать N нижних слоёв (платформа-подложка)')
    args = ap.parse_args()

    if args.src.endswith('.litematic'):
        g, dim = load_litematic(args.src)
        k = max(1, -(-max(dim) // args.max))
        g, nx, ny, nz = pool(g, 0, 0, 0, dim[0], dim[1], dim[2], k)
        g, dropped = largest_component(g)
        g, (nx, ny, nz) = recrop(g)
        print('largest component: отброшено', dropped, 'вокселей чужих копий')
        print('после pool k=%d: %dx%dx%d, вокселей %d' % (k, nx, ny, nz, len(g)))
        if args.strip_bottom > 0:
            g = { (x, y - args.strip_bottom, z): c for (x, y, z), c in g.items() if y >= args.strip_bottom }
            ny = max(1, ny - args.strip_bottom)
            g = { pp: c for pp, c in g.items() if pp[1] < ny }
            print('strip-bottom', args.strip_bottom, '->', len(g), 'вокселей')
        faces = greedy(g, nx, ny, nz)
        out = emit(faces, nx, ny, nz, args.axis, args.flip_x, args.flip_z)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        json.dump({'n': [nx, ny, nz], 'k': k, 'axis': args.axis, 'faces': out}, open(args.out, 'w'))
        print('граней:', len(out), '->', args.out)
        return

    w, h, l, get, pal = load_schem(args.src)
    print('размер', w, h, l)
    g = collect(w, h, l, get, pal)
    print('вокселей:', len(g))
    x0, y0, z0, x1, y1, z1 = crop(g)
    g = { (x - x0, y - y0, z - z0): c for (x, y, z), c in g.items() if (x0, y0, z0) <= (x, y, z) < (x1, y1, z1) }
    dim = [x1 - x0, y1 - y0, z1 - z0]
    long_axis = max(dim)
    k = max(1, -(-long_axis // args.max))
    g, nx, ny, nz = pool(g, 0, 0, 0, dim[0], dim[1], dim[2], k)
    print('после pool k=%d: %dx%dx%d, вокселей %d' % (k, nx, ny, nz, len(g)))
    g, dropped = largest_component(g)
    g, (nx, ny, nz) = recrop(g)
    print('largest component: отброшено', dropped, 'вокселей чужих копий')
    g, dropped = largest_component(g)
    g, (nx, ny, nz) = recrop(g)
    print('largest component: отброшено', dropped, 'вокселей чужих копий')
    if args.strip_bottom > 0:
        g = { (x, y - args.strip_bottom, z): c for (x, y, z), c in g.items() if y >= args.strip_bottom }
        ny = max(1, ny - args.strip_bottom)
        g = { pp: c for pp, c in g.items() if pp[1] < ny }
        print('strip-bottom', args.strip_bottom, '->', len(g), 'вокселей')

    faces = greedy(g, nx, ny, nz)
    out = emit(faces, nx, ny, nz, args.axis, args.flip_x, args.flip_z)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump({'n': [nx, ny, nz], 'k': k, 'axis': args.axis, 'faces': out}, open(args.out, 'w'))
    print('граней после greedy:', len(out), '->', args.out, '(%.1f КБ)' % (os.path.getsize(args.out) / 1024))

if __name__ == '__main__':
    main()
