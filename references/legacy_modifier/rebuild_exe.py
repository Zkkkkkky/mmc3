import struct, sys

# ================= 输入 =================
stream = open(r'd:\LLM\项目\修改器\unpacked_unf.bin','rb').read()
packed = open(r'd:\LLM\项目\修改器\SRW2修改器(扩容版专用).exe','rb').read()
packed_rsrc = packed[0xf2e00:0xf2e00+0x2e00]

def u32(b,o): return struct.unpack_from('<I', b, o)[0]
def u16(b,o): return struct.unpack_from('<H', b, o)[0]
def p32(v): return struct.pack('<I', v)
def p16(v): return struct.pack('<H', v)

OUT = open(r'd:\LLM\项目\修改器\_rebuild.txt','w', encoding='utf-8')
def P(*a):
    print(*a)
    print(*a, file=OUT)

# ================= 1. b_info (原始 PE 头) =================
pe_off = stream.rfind(b'PE\x00\x00')
assert pe_off == 0x5f6f28, hex(pe_off)
b_info = stream[pe_off:pe_off+0x198]   # PE 签名 + COFF(0x14) + 可选头(0xE0) + 节表(0xA0)
coff = b_info[4:24]
opt  = b_info[24:24+0xE0]
secs = b_info[24+0xE0:24+0xE0+0xA0]     # 4 节
P('b_info PE@0x%x' % pe_off)

# ================= 2. 解析 CIM 导入数据 =================
groups = []   # (iat_rva, [(typ,val),...])
pos = 0x5f5000
for g in range(19):
    nxt = u32(stream, pos)
    iat_rel = u32(stream, pos+4)
    iat_rva = iat_rel + 0x1000
    p = pos + 8
    entries = []
    while True:
        b0 = stream[p]
        if b0 == 0x00:
            p += 1
            break
        elif b0 == 0x01:
            e = stream.find(b'\x00', p+1)
            entries.append(('name', stream[p+1:e].decode('latin1')))
            p = e + 1
        elif b0 == 0xff:
            entries.append(('ord', u16(stream, p+1)))
            p += 3
        elif b0 == 0xfe:
            entries.append(('ord', u32(stream, p+1)))
            p += 5
        else:
            raise Exception('bad entry byte 0x%x at 0x%x' % (b0, p))
    groups.append((iat_rva, entries))
    pos = p

total = sum(len(e) for _,e in groups)
P('CIM groups=%d total entries=%d (期望 524)' % (len(groups), total))

# ================= 3. DLL 名 (来自打包 exe 导入表) =================
PACKED_RSRC_RAW = 0xf2e00
PACKED_RSRC_VA  = 0x5fa000
imp_raw = PACKED_RSRC_RAW + (0x5fc8d0 - PACKED_RSRC_VA)
dll_names = []
for i in range(19):
    o = imp_raw + i*20
    name_rva = u32(packed, o+12)
    nr = PACKED_RSRC_RAW + (name_rva - PACKED_RSRC_VA)
    dll = packed[nr:nr+64].split(b'\x00')[0].decode('latin1')
    dll_names.append(dll)

P('\n=== 组 -> DLL 映射 ===')
for gi,(iat_rva,entries) in enumerate(groups):
    first = entries[0][1] if entries else '?'
    last = entries[-1][1] if entries else '?'
    P('  %2d %-14s IAT=0x%x n=%d  [%s .. %s]' % (gi, dll_names[gi], iat_rva, len(entries), first, last))

# ================= 4. 构建导入数据 (.idata) =================
IDATA_VA = 0x5fd000
ilt_slots = sum(len(e)+1 for _,e in groups)          # 每 DLL 条目 + null
ilt_size  = ilt_slots*4
hn_size = 0
for _,entries in groups:
    for typ,val in entries:
        if typ=='name':
            hn_size += 2 + len(val) + 1
dll_size = sum(len(n)+1 for n in dll_names)

desc_off = 0
ilt_off  = 0x200
hn_off   = ilt_off + ilt_size
dll_off  = hn_off + hn_size
idata_size = (dll_off + dll_size + 0xfff) & ~0xfff

desc_rva = IDATA_VA + desc_off
ilt_rva  = IDATA_VA + ilt_off
hn_rva   = IDATA_VA + hn_off
dll_rva  = IDATA_VA + dll_off

ilt_buf = bytearray(); hn_buf = bytearray(); dll_buf = bytearray()
descs = []
dll_offs = []
for n in dll_names:
    dll_offs.append(len(dll_buf))
    dll_buf += n.encode('latin1') + b'\x00'

IAT_RVA  = 0x335000
IAT_SIZE = 0x87c
iat_buf = bytearray([0x01]) * IAT_SIZE   # 预填非零 (覆盖散落的 gap 槽位)

ilt_cursor = 0; hn_cursor = 0
for gi,(iat_rva,entries) in enumerate(groups):
    start_slot = ilt_cursor
    for k,(typ,val) in enumerate(entries):
        if typ=='name':
            hn_buf += p16(0) + val.encode('latin1') + b'\x00'
            slot = hn_rva + hn_cursor
            hn_cursor += 2 + len(val) + 1
        else:
            slot = 0x80000000 | val
        ilt_buf += p32(slot); ilt_cursor += 1
        # IAT 槽位预填与 ILT 相同的值 (标准 PE 语义), 否则系统加载器不解析导入
        iat_off = (iat_rva - IAT_RVA) + k*4
        iat_buf[iat_off:iat_off+4] = p32(slot)
    ilt_buf += p32(0); ilt_cursor += 1
    descs.append((ilt_rva + start_slot*4, dll_rva + dll_offs[gi], iat_rva))

desc_buf = bytearray()
for oft,name,ft in descs:
    desc_buf += p32(oft) + p32(0) + p32(0) + p32(name) + p32(ft)
desc_buf += b'\x00'*20   # 结尾 null 描述符

idata = bytearray(idata_size)
idata[desc_off:desc_off+len(desc_buf)] = desc_buf
idata[ilt_off:ilt_off+len(ilt_buf)] = ilt_buf
idata[hn_off:hn_off+len(hn_buf)] = hn_buf
idata[dll_off:dll_off+len(dll_buf)] = dll_buf

import_dir_rva  = desc_rva
import_dir_size = len(desc_buf)
P('\nidata: desc_rva=0x%x size=0x%x ilt_rva=0x%x hn_rva=0x%x dll_rva=0x%x idata_size=0x%x' %
  (desc_rva, import_dir_size, ilt_rva, hn_rva, dll_rva, idata_size))

# ================= 5. 重建 .rsrc =================
RSRC_VA = 0x5ea000
rsrc_size = 0x13000
rsrc = bytearray(rsrc_size)

# 5a. 资源树 (打包 .rsrc 开头)
tree_extent = 0x17aa
rsrc[0:tree_extent] = packed_rsrc[0:tree_extent]

# 5b. 遍历树收集数据项
data_entries = []
def parse_tree(buf, off):
    nnamed = u16(buf, off+12); nid = u16(buf, off+14)
    entries = off + 16
    for i in range(nnamed+nid):
        e = entries + i*8
        name = u32(buf, e); offs = u32(buf, e+4)
        is_dir = (offs & 0x80000000)!=0
        off_real = offs & 0x7fffffff
        if is_dir:
            parse_tree(buf, off_real)
        else:
            rva = u32(buf, off_real); sz = u32(buf, off_real+4); cp = u32(buf, off_real+8)
            data_entries.append((rva, sz, cp))
parse_tree(rsrc, 0)

n_stream = n_packed = 0
for rva,sz,cp in data_entries:
    off = rva - RSRC_VA
    so = rva - 0x1000
    if 0 <= so and so+sz <= len(stream):
        rsrc[off:off+sz] = stream[so:so+sz]
        n_stream += 1
    else:
        po = rva - PACKED_RSRC_VA
        rsrc[off:off+sz] = packed_rsrc[po:po+sz]
        n_packed += 1
P('\nrsrc: data entries=%d (stream=%d packed=%d) size=0x%x' % (len(data_entries), n_stream, n_packed, rsrc_size))

# ================= 6. 打补丁 =================
text = bytearray(stream[0x0000:0x334000])

def patch_va(va, newhex, desc):
    off = va - 0x401000
    n = len(bytes.fromhex(newhex))
    old = bytes(text[off:off+n]).hex()
    text[off:off+n] = bytes.fromhex(newhex)
    P('patch %-24s VA 0x%x off 0x%x: %s -> %s' % (desc, va, off, old, newhex))

P('\n=== 补丁 ===')
# 1. verify @ 0x61e450 (授权类方法): 直接返回 1 (通过)
patch_va(0x61e450, 'B8 01 00 00 00 C2 0C 00', 'verify->ret 1')
# 2. 主入口 0x401632 硬件指纹校验 (网卡型号/MAC/卷序列号):
#    a. 0x401757: jne 0x401a93 ("请检查网络") -> nop
patch_va(0x401757, '90 90 90 90 90 90', 'net check jne->nop')
#    b. 0x4017b6: je 0x401a3d ("进入修改器失败") -> nop
patch_va(0x4017b6, '90 90 90 90 90 90', 'hw cmp je->nop')
#    c. 0x4018fd: je 0x4019ab (注册码比较) -> jmp 0x4019ab (jmp 5字节, 偏移 0x4019ab-0x401902=0xa9)
patch_va(0x4018fd, 'E9 A9 00 00 00 90', 'reg je->jmp')

# ================= 7. 组装 PE 头 =================
# 修改 COFF: NumberOfSections 4->5
coff = bytearray(coff)
coff[2:4] = p16(5)

# 修改可选头: SizeOfImage, Import 目录, Resource 目录
opt = bytearray(opt)
opt[56:60]   = p32(0x600000)        # SizeOfImage
opt[104:108] = p32(import_dir_rva)  # Import RVA
opt[108:112] = p32(import_dir_size) # Import size
opt[112:116] = p32(RSRC_VA)         # Resource RVA (不变)
opt[116:120] = p32(rsrc_size)       # Resource size

# 节表: 4 原始节 (改 .rsrc) + 新增 .idata
secs = bytearray(secs)
# .rdata 改为可写 (IAT 在 RVA 0x335000, 需要加载器写入函数地址)
rdata_hdr = bytearray(secs[1*40:2*40])
rdata_hdr[36:40] = p32(0xC0000040)   # READ|WRITE|INITIALIZED_DATA
secs[1*40:2*40] = rdata_hdr
# .rdata 改为可写 (IAT 在 RVA 0x335000, 需要加载器写入函数地址)
rdata_hdr = bytearray(secs[1*40:2*40])
rdata_hdr[36:40] = p32(0xC0000040)   # READ|WRITE|INITIALIZED_DATA
secs[1*40:2*40] = rdata_hdr
# .rsrc 是第 4 节 (索引 3): vsize@8, rawsz@16
rsrc_hdr = secs[3*40:4*40]
rsrc_hdr = bytearray(rsrc_hdr)
rsrc_hdr[8:12]  = p32(rsrc_size)   # VirtualSize
rsrc_hdr[16:20] = p32(rsrc_size)   # SizeOfRawData
secs[3*40:4*40] = rsrc_hdr

# 新 .idata 节
idata_hdr = bytearray(40)
idata_hdr[0:8]   = b'.idata\x00\x00'
idata_hdr[8:12]  = p32(idata_size)       # VirtualSize
idata_hdr[12:16] = p32(IDATA_VA)         # VirtualAddress
idata_hdr[16:20] = p32(idata_size)       # SizeOfRawData
idata_hdr[20:24] = p32(0x56d000)         # PointerToRawData
idata_hdr[36:40] = p32(0x40000040)       # Characteristics
secs += idata_hdr

# DOS 头
dos = bytearray(0x80)
dos[0:2] = b'MZ'
dos[0x3C:0x40] = p32(0x80)
stub = b'This program cannot be run in DOS mode.\r\r\n$'
dos[0x40:0x40+len(stub)] = stub

pe_hdr = b'PE\x00\x00' + bytes(coff) + bytes(opt) + bytes(secs)

# ================= 8. 输出文件 =================
headers = bytearray(0x1000)
headers[0:0x80] = dos
headers[0x80:0x80+len(pe_hdr)] = pe_hdr

rdata = bytearray(stream[0x334000:0x52f000])
rdata[0:IAT_SIZE] = iat_buf        # IAT 区预填 hint/name RVA (非零), 让系统加载器解析导入

data_sec = stream[0x52f000:0x559000]

out = bytearray()
out += headers
out += text
out += rdata
out += data_sec
out += rsrc
out += idata

OUTNAME = r'd:\LLM\项目\修改器\SRW2_patched.exe'
open(OUTNAME,'wb').write(out)
P('\n输出: %s  大小 0x%x (%d 字节)' % (OUTNAME, len(out), len(out)))
P('理论文件大小 0x570000')
OUT.close()
print('DONE')
