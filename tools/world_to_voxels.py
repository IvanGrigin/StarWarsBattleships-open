#!/usr/bin/env python3
"""Парсер миров Minecraft (anvil) -> воксели -> mesh JSON (тот же формат, что schem_to_mesh).

Поддержка: legacy 1.12 (Blocks+Data, nibble) и современные 1.13+ (sections с
palette+bit-packed data, включая 1.18+ плоскую структуру chunks).
Использование:
  python3 tools/world_to_voxels.py --world "путь/к/миру" --out demo/assets/models/meshes/xxx.json \
      [--axis x] [--flip-x] [--max 72]
"""
import argparse, gzip, io, json, os, struct, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schem_to_mesh import (R, read_payload, parse_nbt, block_color, pool, greedy, emit)

# ---------- .mca ----------

def iter_chunks(mca_path):
    data = open(mca_path, 'rb').read()
    if len(data) < 8192: return
    for i in range(1024):
        off = struct.unpack_from('>I', b'\x00' + data[i*4:i*4+3])[0]
        cnt = data[i*4+3]
        if off == 0 or cnt == 0: continue
        start = off * 4096
        ln = struct.unpack_from('>I', data, start)[0]
        comp = data[start+4]
        blob = data[start+5:start+4+ln]
        if comp == 2:
            raw = zlib.decompress(blob)
        elif comp == 1:
            raw = gzip.decompress(blob)
        else:
            raw = blob
        r = R(raw)
        t = r.u1()
        if t != 10: continue
        r.str_()
        yield read_payload(r, 10)

# ---------- palette entry -> name ----------

def entry_name(e):
    if isinstance(e, str): return e.replace('minecraft:', '')
    if isinstance(e, dict): return e.get('Name', 'air').replace('minecraft:', '')
    return 'air'

# ---------- сборка вокселей ----------

class World:
    def __init__(self):
        self.g = {}          # (x,y,z) -> name (str) для современных
        self.legacy = {}     # (x,y,z) -> (id, meta) для 1.12
        self.is_legacy = False

    def add(self, x, y, z, name):
        if name in ('air', 'cave_air', 'void_air'): return
        self.g[(x, y, z)] = name

    def add_legacy(self, x, y, z, idmeta):
        self.legacy[(x, y, z)] = idmeta

def parse_sections(secs, ox, oz, world):
    for s in secs:
        if not isinstance(s, dict): continue
        sy = s.get('Y', 0)
        pal = s.get('palette') or s.get('Palette')
        bs = s.get('block_states')
        if isinstance(bs, dict):
            pal = bs.get('palette') or pal
        pal = pal or []
        names = [entry_name(e) for e in pal]
        if not names or (len(names) == 1 and names[0] == 'air'): continue
        data = s.get('data') or s.get('Data') or s.get('BlockStates')
        if isinstance(bs, dict) and bs.get('data'):
            data = bs['data']
        y0 = sy * 16
        if data is None:
            for iy in range(16):
                for iz in range(16):
                    for ix in range(16):
                        world.add(ox+ix, y0+iy, oz+iz, names[0])
            continue
        bits = max(4, (len(names)-1).bit_length())
        per_long = 64 // bits
        mask = (1 << bits) - 1
        for iy in range(16):
            for iz in range(16):
                for ix in range(16):
                    idx = iy * 256 + iz * 16 + ix
                    li, off = divmod(idx, per_long)
                    if li >= len(data): continue
                    val = (data[li] >> (off * bits)) & mask
                    name = names[val] if val < len(names) else 'air'
                    world.add(ox+ix, y0+iy, oz+iz, name)

def parse_modern_chunk(chunk, wx, wz, world):
    parse_sections(chunk.get('sections') or [], wx*16, wz*16, world)

def parse_legacy_chunk(chunk, wx, wz, world):
    level = chunk.get('Level', chunk)
    secs = level.get('Sections') or []
    byte_secs = [s for s in secs if isinstance(s, dict) and isinstance(s.get('Blocks'), (bytes, bytearray))]
    if byte_secs:
        for s in byte_secs:
            sy = s.get('Y', 0)
            blocks = s['Blocks']
            datab = s.get('Data', b'')
            addb = s.get('Add', b'')
            y0 = sy * 16
            for iy in range(16):
                for iz in range(16):
                    for ix in range(16):
                        idx = iy * 256 + iz * 16 + ix
                        b = blocks[idx]
                        if addb:
                            hi = (addb[idx >> 1] >> ((idx & 1) * 4)) & 0xF
                            b |= hi << 8
                        meta = (datab[idx >> 1] >> ((idx & 1) * 4)) & 0xF if idx < len(datab)*2 else 0
                        if b == 0: continue
                        world.add_legacy(wx*16+ix, y0+iy, wz*16+iz, (b, meta))
    else:
        parse_sections(secs, wx*16, wz*16, world)

LEGACY_NAMES = {1:'stone',2:'grass_block',3:'dirt',4:'cobblestone',5:'oak_planks',7:'bedrock',
    8:'water',9:'water',10:'lava',11:'lava',12:'sand',13:'gravel',17:'oak_log',20:'glass',
    22:'lapis_block',23:'dispenser',24:'sandstone',25:'note_block',35:'white_wool',41:'gold_block',
    '42':'iron_block',42:'iron_block',45:'bricks',47:'bookshelf',48:'mossy_cobblestone',49:'obsidian',
    52:'spawner',54:'chest',56:'diamond_ore',57:'diamond_block',58:'crafting_table',61:'furnace',
    79:'ice',80:'snow_block',82:'clay',86:'carved_pumpkin',89:'glowstone',91:'jack_o_lantern',
    95:'white_stained_glass',98:'stone_bricks',101:'iron_bars',112:'nether_bricks',121:'end_stone',
    123:'redstone_lamp',155:'quartz_block',159:'white_terracotta',165:'slime_block',168:'purpur',
    173:'coal_block',174:'packed_ice',179:'red_sandstone',201:'purpur',206:'end_bricks'}

def legacy_color(idmeta):
    bid, meta = idmeta
    if bid == 35 or bid == 159 or bid == 251:
        WOOL16 = [0xE9ECEC,0xF07613,0xBD44B3,0x3AAFD9,0xF8C627,0x70B919,0xED8DAC,0x3E4447,
                  0x8E8E86,0x158991,0x792AAC,0x35399D,0x724728,0x546D1B,0xA12722,0x141519]
        rgb = WOOL16[meta % 16]
        return ((rgb>>16)&255, (rgb>>8)&255, rgb&255)
    name = LEGACY_NAMES.get(bid) or (LEGACY_NAMES.get(str(bid)))
    if name is None: name = 'stone'
    return block_color(name) or (125, 125, 125)

def load_world(world_dir, spawn_crop=None):
    w = World()
    ver = '?'
    spawn = None
    ld = os.path.join(world_dir, 'level.dat')
    if os.path.exists(ld):
        raw = gzip.decompress(open(ld, 'rb').read())
        root = parse_nbt(raw)
        data = root.get('Data') or {}
        ver = (data.get('Version') or {}).get('Name', '?')
        if data.get('SpawnX') is not None:
            spawn = (data.get('SpawnX'), data.get('SpawnY'), data.get('SpawnZ'))
    region_dir = None
    for cand in ('region', os.path.join('DIM-1', 'region'), os.path.join('DIM1', 'region')):
        p = os.path.join(world_dir, cand)
        if os.path.isdir(p): region_dir = p; break
    if not region_dir: raise SystemExit('region/ не найден в ' + world_dir)
    for f in sorted(os.listdir(region_dir)):
        if not f.endswith('.mca'): continue
        for chunk in iter_chunks(os.path.join(region_dir, f)):
            if 'sections' in chunk:
                parse_modern_chunk(chunk, chunk.get('xPos', 0), chunk.get('zPos', 0), w)
            elif 'Level' in chunk:
                level = chunk['Level']
                parse_legacy_chunk(chunk, level.get('xPos', 0), level.get('zPos', 0), w)
    if w.g:
        # современные: имена -> цвета
        g = {}
        for (x, y, z), name in w.g.items():
            c = block_color(name)
            if c: g[(x, y, z)] = c
        print('формат: современный, версия', ver, 'вокселей:', len(g))
    else:
        g = {}
        for (x, y, z), idmeta in w.legacy.items():
            c = legacy_color(idmeta)
            if c: g[(x, y, z)] = c
        print('формат: legacy 1.12, версия', ver, 'вокселей:', len(g))
    if spawn and spawn_crop:
        sx, sy, sz = spawn
        g = { (x, y, z): c for (x, y, z), c in g.items()
              if abs(x - sx) <= spawn_crop and abs(z - sz) <= spawn_crop }
        print('кроп вокруг спавна', spawn, 'R=', spawn_crop, '->', len(g), 'вокселей')
    return g

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--world', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--axis', default='x', choices=['x', 'z'])
    ap.add_argument('--flip-x', action='store_true')
    ap.add_argument('--flip-z', action='store_true')
    ap.add_argument('--max', type=int, default=72)
    ap.add_argument('--spawn-crop', type=int, default=None, help='обрезать мир вокруг точки спавна (радиус, блоков)')
    args = ap.parse_args()

    # мир может лежать в подпапке архива
    world_dir = args.world
    if os.path.isdir(world_dir) and not os.path.isdir(os.path.join(world_dir, 'region')):
        for e in sorted(os.listdir(world_dir)):
            sub = os.path.join(world_dir, e)
            if os.path.isdir(sub) and os.path.isdir(os.path.join(sub, 'region')):
                world_dir = sub; break
    g = load_world(world_dir, args.spawn_crop)
    xs = [p[0] for p in g]; ys = [p[1] for p in g]; zs = [p[2] for p in g]
    x0, y0, z0 = min(xs), min(ys), min(zs)
    x1, y1, z1 = max(xs)+1, max(ys)+1, max(zs)+1
    print('bounds', x1-x0, y1-y0, z1-z0)
    g = { (x-x0, y-y0, z-z0): c for (x, y, z), c in g.items() }
    dim = [x1-x0, y1-y0, z1-z0]
    k = max(1, -(-max(dim) // args.max))
    g, nx, ny, nz = pool(g, 0, 0, 0, dim[0], dim[1], dim[2], k)
    print('после pool k=%d: %dx%dx%d, вокселей %d' % (k, nx, ny, nz, len(g)))
    faces = greedy(g, nx, ny, nz)
    out = emit(faces, nx, ny, nz, args.axis, args.flip_x, args.flip_z)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump({'n': [nx, ny, nz], 'k': k, 'axis': args.axis, 'faces': out}, open(args.out, 'w'))
    print('граней:', len(out), '->', args.out, '(%.1f КБ)' % (os.path.getsize(args.out)/1024))

if __name__ == '__main__':
    main()
