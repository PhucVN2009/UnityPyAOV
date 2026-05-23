"""
MeshImporter v9
Tổng hợp tất cả fixes:
  1. parse_obj: pre-populate (unified[vi]=vi) + reverse indices
     - Pre-populate: skin_weight[vi] đúng với position[vi] cho same_vc
     - Reverse indices: bù đắp MeshExporter viết f(idx2,idx1,idx0) ngược chiều
       → không bị wall hack khi import→export lại
  2. Không có axis swap Y↔Z (gây mesh deformation)
  3. _normalize_to_bbox: chỉ dùng cho weight lookup, KHÔNG áp dụng cho vertex data
  4. CompressedMesh luôn zeroed sau import
  5. Bone indices clamped, weights normalized
"""

import struct, math, bisect

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from ..streams import EndianBinaryWriter


# ═══════════════════════════════════════════════
#  OBJ PARSER
# ═══════════════════════════════════════════════

def parse_obj(filepath):
    raw_v, raw_vt, raw_vn = [], [], []
    groups, cur_name, cur_faces = [], "default", []

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            p = line.split(); t = p[0]
            if t == "v":
                raw_v.append((float(p[1]), float(p[2]), float(p[3])))
            elif t == "vt":
                raw_vt.append((float(p[1]), float(p[2]) if len(p) > 2 else 0.0))
            elif t == "vn":
                raw_vn.append((float(p[1]), float(p[2]), float(p[3])))
            elif t in ("g", "o"):
                if cur_faces: groups.append((cur_name, cur_faces)); cur_faces = []
                cur_name = p[1] if len(p) > 1 else "group"
            elif t == "f":
                face = []
                for tok in p[1:]:
                    s = tok.split("/")
                    vi = int(s[0]) - 1
                    ti = int(s[1]) - 1 if len(s) > 1 and s[1] else -1
                    ni = int(s[2]) - 1 if len(s) > 2 and s[2] else -1
                    face.append((vi, ti, ni))
                for i in range(1, len(face) - 1):
                    cur_faces.append((face[0], face[i], face[i + 1]))

    if cur_faces: groups.append((cur_name, cur_faces))
    if not groups: return [], [], [], [], [], []

    vmap = {}; out_v, out_vt, out_vn = [], [], []

    def get_idx(key):
        if key not in vmap:
            new_i = len(out_v) // 3; vmap[key] = new_i
            vi, ti, ni = key
            vx, vy, vz = raw_v[vi]
            out_v.extend([-vx, vy, vz])   # restore Unity X (MeshExporter flips X)
            out_vt.extend(raw_vt[ti] if ti >= 0 and raw_vt else [0.0, 0.0])
            if ni >= 0 and raw_vn:
                nx, ny, nz = raw_vn[ni]; out_vn.extend([-nx, ny, nz])
            else:
                out_vn.extend([0.0, 1.0, 0.0])
        return vmap[key]

    # Pre-populate: unified[vi] = vi → skin_weight[v] maps to position[v] correctly
    # Unity OBJ always uses f a/a/a format (vi=ti=ni)
    for vi in range(len(raw_v)):
        get_idx((vi, vi, vi))

    out_idx = []; submeshes = []
    for name, faces in groups:
        first = len(out_idx)
        for tri in faces:
            ia = get_idx(tri[0])
            ib = get_idx(tri[1])
            ic = get_idx(tri[2])
            # REVERSED: MeshExporter writes f(idx2,idx1,idx0) → reverse here to compensate
            # Without this: import→export doubles the reversal → inside-out faces → wall hack
            out_idx.extend([ic, ib, ia])
        submeshes.append({"first": first, "count": len(out_idx) - first, "name": name})

    vc = len(out_v) // 3
    tang = _compute_tangents(out_v, out_vt, out_vn, out_idx, vc)
    return out_v, out_vn, out_vt, tang, out_idx, submeshes


def _compute_tangents(verts, uvs, normals, indices, vc):
    tan1 = [[0.0, 0.0, 0.0] for _ in range(vc)]
    tan2 = [[0.0, 0.0, 0.0] for _ in range(vc)]
    has_uv = len(uvs) >= vc * 2
    for i in range(0, len(indices), 3):
        i1, i2, i3 = indices[i], indices[i+1], indices[i+2]
        v1=verts[i1*3:i1*3+3]; v2=verts[i2*3:i2*3+3]; v3=verts[i3*3:i3*3+3]
        w1=uvs[i1*2:i1*2+2] if has_uv else [0,0]
        w2=uvs[i2*2:i2*2+2] if has_uv else [0,0]
        w3=uvs[i3*2:i3*2+2] if has_uv else [0,0]
        x1,y1,z1=v2[0]-v1[0],v2[1]-v1[1],v2[2]-v1[2]
        x2,y2,z2=v3[0]-v1[0],v3[1]-v1[1],v3[2]-v1[2]
        s1,t1=w2[0]-w1[0],w2[1]-w1[1]; s2,t2=w3[0]-w1[0],w3[1]-w1[1]
        d=s1*t2-s2*t1; r=1.0/d if abs(d)>1e-8 else 0.0
        sd=[(t2*x1-t1*x2)*r,(t2*y1-t1*y2)*r,(t2*z1-t1*z2)*r]
        td=[(s1*x2-s2*x1)*r,(s1*y2-s2*y1)*r,(s1*z2-s2*z1)*r]
        for ii in (i1,i2,i3):
            for d2 in range(3): tan1[ii][d2]+=sd[d2]; tan2[ii][d2]+=td[d2]
    result = []
    for i in range(vc):
        n=normals[i*3:i*3+3] if len(normals)>=(i+1)*3 else [0,1,0]
        t=tan1[i]; dot=sum(n[k]*t[k] for k in range(3))
        tx,ty,tz=t[0]-n[0]*dot,t[1]-n[1]*dot,t[2]-n[2]*dot
        ln=math.sqrt(tx*tx+ty*ty+tz*tz)
        if ln>1e-8: tx,ty,tz=tx/ln,ty/ln,tz/ln
        cn=[n[1]*t[2]-n[2]*t[1],n[2]*t[0]-n[0]*t[2],n[0]*t[1]-n[1]*t[0]]
        t2i=tan2[i]; w=-1.0 if sum(cn[k]*t2i[k] for k in range(3))<0.0 else 1.0
        result.extend([tx,ty,tz,w])
    return result


# ═══════════════════════════════════════════════
#  BOUNDING BOX + NORMALIZE  (chỉ cho weight lookup)
# ═══════════════════════════════════════════════

def _bbox(verts):
    if not verts: return (0,0,0),(0,0,0),(0,0,0),(1,1,1)
    xs=verts[0::3]; ys=verts[1::3]; zs=verts[2::3]
    mn=(min(xs),min(ys),min(zs)); mx=(max(xs),max(ys),max(zs))
    cx=(mn[0]+mx[0])/2; cy=(mn[1]+mx[1])/2; cz=(mn[2]+mx[2])/2
    sx=max(mx[0]-mn[0],1e-6); sy=max(mx[1]-mn[1],1e-6); sz=max(mx[2]-mn[2],1e-6)
    return mn,mx,(cx,cy,cz),(sx,sy,sz)


def _normalize_to_bbox(src_verts, ref_verts):
    """
    Scale đồng đều + translate center về ref.
    KHÔNG swap trục (không detect Y-up/Z-up) — gây mesh deformation.
    Chỉ dùng để tìm nearest vertex cho weight transfer, KHÔNG dùng cho VertexData.
    """
    if not ref_verts or not src_verts: return src_verts[:]
    _,_,src_c,src_s = _bbox(src_verts)
    _,_,ref_c,ref_s = _bbox(ref_verts)
    src_max = max(src_s[0], src_s[1], src_s[2], 1e-6)
    ref_max = max(ref_s[0], ref_s[1], ref_s[2], 1e-6)
    scale = ref_max / src_max
    result = []
    for i in range(0, len(src_verts), 3):
        result.extend([(src_verts[i]-src_c[0])*scale+ref_c[0],
                        (src_verts[i+1]-src_c[1])*scale+ref_c[1],
                        (src_verts[i+2]-src_c[2])*scale+ref_c[2]])
    return result


# ═══════════════════════════════════════════════
#  WEIGHT TRANSFER
# ═══════════════════════════════════════════════

def _transfer_weights(orig_verts, orig_skin, lookup_verts, new_vc,
                      max_bone_idx, progress_cb=None, knn_k=4):
    """k-NN inverse-distance weight blending – chống "model dị" khi mod
    mesh từ game khác.

    Mỗi vertex mới lấy `knn_k` vertex gốc gần nhất, blend bone weights
    theo trọng số tỉ lệ nghịch khoảng cách:
        - k=1: nearest-vertex copy (cũ; nhanh nhưng dễ snap cứng)
        - k=4 (mặc định): blend mượt, khớp anim tốt hơn
        - k=8: cực mượt, chậm hơn nhưng tốt cho mesh chênh lệch topology
    """
    from ..classes.Mesh import BoneWeights4
    orig_vc = len(orig_skin)
    if orig_vc == 0:
        return [BoneWeights4() for _ in range(new_vc)]
    knn_k = max(1, min(knn_k, orig_vc))

    # Pack weight/index gốc thành flat array để truy cập nhanh
    flat_w = [0.0] * (orig_vc * 4)
    flat_b = [0] * (orig_vc * 4)
    for i, s in enumerate(orig_skin):
        for slot in range(4):
            flat_w[i * 4 + slot] = float(s.weight[slot])
            flat_b[i * 4 + slot] = min(max(int(s.boneIndex[slot]), 0),
                                       max_bone_idx)

    if _HAS_NUMPY:
        knn = _knn_numpy(orig_verts, lookup_verts, orig_vc, new_vc,
                         knn_k, progress_cb)
    else:
        knn = _knn_bisect(orig_verts, lookup_verts, orig_vc, new_vc,
                          knn_k, progress_cb)

    result = []
    for nbrs in knn:
        # Gộp weight từ k neighbor theo inverse distance
        agg = {}
        for src_i, d2 in nbrs:
            iw = 1.0 / (d2 + 1e-10)
            base = src_i * 4
            for slot in range(4):
                w = flat_w[base + slot]
                if w <= 0.0:
                    continue
                b = flat_b[base + slot]
                agg[b] = agg.get(b, 0.0) + w * iw

        # Top-4 bone theo trọng số tổng hợp
        top = sorted(agg.items(), key=lambda x: -x[1])[:4]
        ws = [w for _, w in top]
        bs = [b for b, _ in top]
        while len(ws) < 4:
            ws.append(0.0); bs.append(0)
        tot = sum(ws)
        if tot > 1e-6:
            ws = [w / tot for w in ws]
        else:
            ws = [1.0, 0.0, 0.0, 0.0]

        bw = BoneWeights4()
        bw.weight = ws
        bw.boneIndex = bs
        result.append(bw)
    return result


def _knn_numpy(orig_verts, new_verts, orig_vc, new_vc, k, progress_cb):
    """Vector hoá: với mỗi vertex mới, lấy k orig vertex có d² nhỏ nhất."""
    ov = np.array(orig_verts, dtype=np.float32).reshape(orig_vc, 3)
    nv = np.array(new_verts, dtype=np.float32).reshape(new_vc, 3)
    BATCH = 256
    out = []
    for start in range(0, new_vc, BATCH):
        b = nv[start:start + BATCH]
        # (B, ovc) ma trận khoảng cách bình phương
        d2 = ((b[:, None, :] - ov[None, :, :]) ** 2).sum(axis=2)
        k_eff = min(k, d2.shape[1])
        k_idx = np.argpartition(d2, k_eff - 1, axis=1)[:, :k_eff]
        for qi in range(b.shape[0]):
            idxs = k_idx[qi]
            dists = d2[qi, idxs]
            ord_q = np.argsort(dists)
            out.append([(int(idxs[j]), float(dists[j])) for j in ord_q])
        if progress_cb:
            progress_cb(min(start + BATCH, new_vc), new_vc)
    return out


def _knn_bisect(orig_verts, new_verts, orig_vc, new_vc, k, progress_cb):
    """Pure-Python: bisect tìm anchor x, mở rộng 2 phía + prune theo dx²."""
    import heapq
    order = sorted(range(orig_vc), key=lambda i: orig_verts[i * 3])
    xs = [orig_verts[order[i] * 3] for i in range(orig_vc)]
    REPORT = max(1, new_vc // 20)
    out = []
    for qi in range(new_vc):
        nx = new_verts[qi * 3]
        ny = new_verts[qi * 3 + 1]
        nz = new_verts[qi * 3 + 2]
        anchor = bisect.bisect_left(xs, nx)
        heap = []  # max-heap: (-d2, src_i); top = lớn nhất trong k tốt nhất
        l = anchor - 1
        r = anchor
        while l >= 0 or r < orig_vc:
            worst = -heap[0][0] if len(heap) >= k else float("inf")
            adv = False
            if r < orig_vc:
                dx = xs[r] - nx
                if dx * dx < worst:
                    j = order[r]
                    dy = orig_verts[j * 3 + 1] - ny
                    dz = orig_verts[j * 3 + 2] - nz
                    d2 = dx * dx + dy * dy + dz * dz
                    if len(heap) < k:
                        heapq.heappush(heap, (-d2, j))
                    elif d2 < -heap[0][0]:
                        heapq.heapreplace(heap, (-d2, j))
                    r += 1
                    adv = True
                else:
                    r = orig_vc  # prune bên phải
            if l >= 0:
                worst = -heap[0][0] if len(heap) >= k else float("inf")
                dx = nx - xs[l]
                if dx * dx < worst:
                    j = order[l]
                    dy = orig_verts[j * 3 + 1] - ny
                    dz = orig_verts[j * 3 + 2] - nz
                    d2 = dx * dx + dy * dy + dz * dz
                    if len(heap) < k:
                        heapq.heappush(heap, (-d2, j))
                    elif d2 < -heap[0][0]:
                        heapq.heapreplace(heap, (-d2, j))
                    l -= 1
                    adv = True
                else:
                    l = -1  # prune bên trái
            if not adv:
                break
        nbrs = sorted([(i, -nd2) for nd2, i in heap], key=lambda x: x[1])
        out.append(nbrs)
        if progress_cb and qi % REPORT == 0:
            progress_cb(qi, new_vc)
    return out


# ═══════════════════════════════════════════════
#  VERTEX DATA PATCH  (same vc, in-place)
# ═══════════════════════════════════════════════

def _patch_vertex_data(mesh, new_verts, new_normals, new_uvs, new_tangents):
    vd=mesh.m_VertexData; version=mesh.version; endian=mesh.reader.endian
    vc=vd.m_VertexCount; buf=bytearray(vd.m_DataSize)
    channels=vd.m_Channels; streams=vd.m_Streams
    chn_data={0:(new_verts,3),1:(new_normals,3),2:(new_tangents,4),4:(new_uvs,2)}
    from ..classes.Mesh import MeshHelper
    for ci,(new_data,_) in chn_data.items():
        if ci>=len(channels): continue
        ch=channels[ci]
        if ch.dimension==0 or not new_data: continue
        stream=streams.get(ch.stream)
        if stream is None: continue
        stride=stream.stride; s_off=stream.offset; ch_off=ch.offset
        fmt=MeshHelper.ToVertexFormat(ch.format,version)
        bsz=MeshHelper.GetFormatSize(fmt); pc=_fmt_char(fmt)
        for v in range(vc):
            base=s_off+stride*v+ch_off
            for d in range(ch.dimension):
                si=v*ch.dimension+d
                val=float(new_data[si]) if si<len(new_data) else 0.0
                packed=struct.pack(endian+pc,_clamp(val,fmt))
                buf[base+d*bsz:base+d*bsz+bsz]=packed
    return bytes(buf)


def _fmt_char(vfmt):
    from ..classes.Mesh import VertexFormat as VF
    M={VF.kVertexFormatFloat:"f",VF.kVertexFormatFloat16:"e",
       VF.kVertexFormatUNorm8:"B",VF.kVertexFormatSNorm8:"b",
       VF.kVertexFormatUNorm16:"H",VF.kVertexFormatSNorm16:"h",
       VF.kVertexFormatUInt8:"B",VF.kVertexFormatSInt8:"b",
       VF.kVertexFormatUInt16:"H",VF.kVertexFormatSInt16:"h",
       VF.kVertexFormatUInt32:"I",VF.kVertexFormatSInt32:"i"}
    return M.get(vfmt,"f")


def _clamp(val,vfmt):
    from ..classes.Mesh import VertexFormat as VF
    if vfmt==VF.kVertexFormatUNorm8:  return int(max(0,min(255,round(val*255))))
    if vfmt==VF.kVertexFormatSNorm8:  return int(max(-128,min(127,round(val*127))))
    if vfmt==VF.kVertexFormatUNorm16: return int(max(0,min(65535,round(val*65535))))
    if vfmt==VF.kVertexFormatSNorm16: return int(max(-32768,min(32767,round(val*32767))))
    return float(val)


# ═══════════════════════════════════════════════
#  BUILD FULL VERTEX DATA
# ═══════════════════════════════════════════════

def _build_full_vertex_data(endian, vc, vertices, normals, uvs, tangents, skin):
    has_norm=len(normals)>=vc*3; has_tang=len(tangents)>=vc*4
    has_uv=len(uvs)>=vc*2;       has_skin=bool(skin) and len(skin)>=vc

    ch_defs=[None]*14; stride=0
    def add_ch(idx,dim,fmt=0):
        nonlocal stride
        off=stride; stride+=dim*4; ch_defs[idx]={"dim":dim,"fmt":fmt,"off":off}

    add_ch(0,3)
    if has_norm: add_ch(1,3)
    if has_tang: add_ch(2,4)
    if has_uv:   add_ch(4,2)
    if has_skin: add_ch(12,4,0); add_ch(13,4,10)

    pf=endian+"f"; pI=endian+"I"
    buf=bytearray(vc*stride)
    for v in range(vc):
        base=v*stride
        def wf(off,val): struct.pack_into(pf,buf,base+off,float(val))
        def wi(off,val): struct.pack_into(pI,buf,base+off,int(val)&0xFFFFFFFF)
        c=ch_defs[0]
        wf(c["off"],vertices[v*3]); wf(c["off"]+4,vertices[v*3+1]); wf(c["off"]+8,vertices[v*3+2])
        if has_norm:
            c=ch_defs[1]
            wf(c["off"],normals[v*3]); wf(c["off"]+4,normals[v*3+1]); wf(c["off"]+8,normals[v*3+2])
        if has_tang:
            c=ch_defs[2]
            wf(c["off"],tangents[v*4]); wf(c["off"]+4,tangents[v*4+1])
            wf(c["off"]+8,tangents[v*4+2]); wf(c["off"]+12,tangents[v*4+3])
        if has_uv:
            c=ch_defs[4]; wf(c["off"],uvs[v*2]); wf(c["off"]+4,uvs[v*2+1])
        if has_skin:
            sk=skin[v]; c12=ch_defs[12]; c13=ch_defs[13]
            for d in range(4):
                wf(c12["off"]+d*4,sk.weight[d]); wi(c13["off"]+d*4,sk.boneIndex[d])

    w=EndianBinaryWriter(endian=endian)
    w.write_u_int(vc); w.write_int(14)
    for i in range(14):
        ch=ch_defs[i]
        if ch is None:
            w.write(b'\x00\x00\x00\x00')
        else:
            w.write(bytes([0, ch["off"]&0xFF, ch["fmt"]&0xFF, ch["dim"]&0xFF]))
    w.write_int(len(buf)); w.write(bytes(buf)); w.align_stream()
    return w.bytes


# ═══════════════════════════════════════════════
#  AABB
# ═══════════════════════════════════════════════

def _aabb(vertices):
    if not vertices: return (0,0,0),(0,0,0)
    xs=vertices[0::3]; ys=vertices[1::3]; zs=vertices[2::3]
    return (((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2),
            ((max(xs)-min(xs))/2,(max(ys)-min(ys))/2,(max(zs)-min(zs))/2))


# ═══════════════════════════════════════════════
#  EMPTY COMPRESSED MESH
# ═══════════════════════════════════════════════

def _write_empty_compressed_mesh(w, version):
    def pf():
        w.write_u_int(0); w.write_float(0.0); w.write_float(0.0)
        w.write_int(0); w.align_stream(); w.write_byte(0); w.align_stream()
    def pi():
        w.write_u_int(0); w.write_int(0)
        w.align_stream(); w.write_byte(0); w.align_stream()
    pf(); pf()
    if version < (5,): pf()
    pf(); pf(); pi(); pi(); pi()
    if version >= (5,): pf()
    pi(); pi()
    if version >= (3, 5):
        if version < (5,): pi()
        else: w.write_u_int(0)


# ═══════════════════════════════════════════════
#  BLEND SHAPE DATA
# ═══════════════════════════════════════════════

def _write_blend_shape_data(w, shapes, version):
    if version >= (4, 3):
        verts=getattr(shapes,"vertices",[]); sh=getattr(shapes,"shapes",[])
        chs=getattr(shapes,"channels",[]); wts=getattr(shapes,"fullWeights",[])
        w.write_int(len(verts))
        for v in verts:
            w.write_float(v.vertex.X); w.write_float(v.vertex.Y); w.write_float(v.vertex.Z)
            w.write_float(v.normal.X); w.write_float(v.normal.Y); w.write_float(v.normal.Z)
            w.write_float(v.tangent.X); w.write_float(v.tangent.Y); w.write_float(v.tangent.Z)
            w.write_u_int(v.index)
        w.write_int(len(sh))
        for s in sh:
            w.write_u_int(s.firstVertex); w.write_u_int(s.vertexCount)
            w.write_boolean(s.hasNormals); w.write_boolean(s.hasTangents); w.align_stream()
        w.write_int(len(chs))
        for c in chs:
            w.write_aligned_string(c.name); w.write_u_int(c.nameHash)
            w.write_int(c.frameIndex); w.write_int(c.frameCount)
        w.write_int(len(wts)); w.write_float_array(list(wts))
    else:
        sl=getattr(shapes,"m_Shapes",[]); w.write_int(len(sl))
        for s in sl:
            w.write_aligned_string(s.name); w.write_u_int(s.firstVertex); w.write_u_int(s.vertexCount)
            w.write_float(s.aabbMinDelta.X); w.write_float(s.aabbMinDelta.Y); w.write_float(s.aabbMinDelta.Z)
            w.write_float(s.aabbMaxDelta.X); w.write_float(s.aabbMaxDelta.Y); w.write_float(s.aabbMaxDelta.Z)
            w.write_boolean(s.hasNormals); w.write_boolean(s.hasTangents)
        w.align_stream()
        sv=getattr(shapes,"m_ShapeVertices",[]); w.write_int(len(sv))
        for v in sv:
            w.write_float(v.vertex.X); w.write_float(v.vertex.Y); w.write_float(v.vertex.Z)
            w.write_float(v.normal.X); w.write_float(v.normal.Y); w.write_float(v.normal.Z)
            w.write_float(v.tangent.X); w.write_float(v.tangent.Y); w.write_float(v.tangent.Z)
            w.write_u_int(v.index)


# ═══════════════════════════════════════════════
#  MESH SERIALIZER
# ═══════════════════════════════════════════════

def _serialize_mesh(mesh):
    from ..streams import EndianBinaryWriter
    from ..enums import BuildTarget
    from ..classes.PPtr import save_ptr
    version=mesh.version; endian=mesh.reader.endian
    w=EndianBinaryWriter(endian=endian)

    if mesh.platform==BuildTarget.NoTarget:
        w.write_u_int(getattr(mesh,"_object_hide_flags",0))
        save_ptr(mesh.m_PrefabParentObject,w); save_ptr(mesh.m_PrefabInternal,w)

    w.write_aligned_string(mesh.m_Name)

    if version<(3,5): w.write_int(1 if mesh.m_Use16BitIndices else 0)
    if version[:2]<=(2,5):
        if mesh.m_Use16BitIndices:
            w.write_int(len(mesh.m_IndexBuffer)*2)
            for i in mesh.m_IndexBuffer: w.write_u_short(i)
            w.align_stream()
        else:
            w.write_int(len(mesh.m_IndexBuffer)*4); w.write_u_int_array(mesh.m_IndexBuffer)

    w.write_int(len(mesh.m_SubMeshes))
    for sm in mesh.m_SubMeshes: sm.save(w,version)

    if version>=(4,1): _write_blend_shape_data(w,mesh.m_Shapes,version)

    if version>=(4,3):
        w.write_matrix_array(mesh.m_BindPose)
        w.write_u_int_array(mesh.m_BoneNameHashes,write_length=True)
        w.write_u_int(mesh.m_RootBoneNameHash)

    if version>=(2,6):
        if version>=(2019,):
            w.write_int(len(mesh.m_BonesAABB))
            for aabb in mesh.m_BonesAABB: aabb.save(w)
            w.write_u_int_array(mesh.m_VariableBoneCountWeights,write_length=True)
        w.write_u_int(len(mesh.m_BindPose))  # m_IsInUse = bone count
        w.write_byte(mesh.m_MeshCompression)
        if version>=(4,):
            if version<(5,): w.write_byte(mesh.m_StreamCompression)
            w.write_boolean(mesh.m_IsReadable)
            w.write_boolean(mesh.m_KeepVertices)
            w.write_boolean(mesh.m_KeepIndices)
        w.align_stream()
        if (version>=(2017,4)
                or version[:3]==(2017,3,1) and mesh.build_type.IsPatch
                or version[:2]==(2017,3) and mesh.m_MeshCompression==0):
            w.write_int(mesh.m_IndexFormat)
        if mesh.m_Use16BitIndices:
            w.write_int(len(mesh.m_IndexBuffer)*2)
            for i in mesh.m_IndexBuffer: w.write_u_short(i)
            w.align_stream()
        else:
            w.write_int(len(mesh.m_IndexBuffer)*4); w.write_u_int_array(mesh.m_IndexBuffer)

    if version<(3,5):
        w.write_int(mesh.m_VertexCount); w.write_float_array(mesh.m_Vertices)
        w.write_int(len(mesh.m_Skin))
        for sk in mesh.m_Skin: sk.save(w)
        w.write_matrix_array(mesh.m_BindPose)
        w.write_int(len(mesh.m_UV0)//2); w.write_float_array(mesh.m_UV0)
        w.write_int(len(mesh.m_UV1)//2); w.write_float_array(mesh.m_UV1)
        if version[:2]<=(2,5):
            n=len(mesh.m_Normals)//3; w.write_int(n)
            for i in range(n):
                w.write_float(mesh.m_Normals[i*3]); w.write_float(mesh.m_Normals[i*3+1]); w.write_float(mesh.m_Normals[i*3+2])
                w.write_float(mesh.m_Tangents[i*4]); w.write_float(mesh.m_Tangents[i*4+1]); w.write_float(mesh.m_Tangents[i*4+2]); w.write_float(mesh.m_Tangents[i*4+3])
        else:
            w.write_int(len(mesh.m_Tangents)//4); w.write_float_array(mesh.m_Tangents)
            w.write_int(len(mesh.m_Normals)//3); w.write_float_array(mesh.m_Normals)
    else:
        if version[:2]<(2018,2):
            w.write_int(len(mesh.m_Skin))
            for sk in mesh.m_Skin: sk.save(w)
        if version[:2]<=(4,2): w.write_matrix_array(mesh.m_BindPose)
        _vd = getattr(mesh,"_new_vd_bytes",None)
        if _vd:
            w.write(_vd)
        else:
            mesh.m_VertexData.save(w,version)

    if version>=(2,6):
        _write_empty_compressed_mesh(w,version)

    mesh.m_LocalAABB.save(w)

    if version[:2]<=(3,4):
        mc=getattr(mesh,"mColors",[])
        w.write_int(len(mc)//4)
        for c in mc: w.write_byte(int(c*255))
        w.write_int(0); w.write_int(0)

    w.write_int(mesh.m_MeshUsageFlags)

    if version>=(5,):
        conv=getattr(mesh,"m_BakedConvexCollisionMesh",b"")
        w.write_int(len(conv)); w.write(bytes(conv)); w.align_stream()
        tri=getattr(mesh,"m_BakedTriangleCollisionMesh",b"")
        w.write_int(len(tri)); w.write(bytes(tri)); w.align_stream()

    if version>=(2018,2):
        m=getattr(mesh,"m_MeshMetrics",[0.0,0.0])
        w.write_float(m[0]); w.write_float(m[1])

    if version>=(2018,3):
        w.align_stream()
        if version>=(2020,): w.write_u_long(0)
        else: w.write_u_int(0)
        w.write_u_int(0); w.write_aligned_string("")

    return w.bytes


# ═══════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════

def import_obj_to_mesh(obj_reader, filepath, progress_cb=None,
                       auto_scale=True, knn_k=4):
    """
    Import .obj → Unity Mesh.

    Same vertex count:
      • Rebuild VertexData với geometry mới + giữ nguyên skin weights gốc

    Different vertex count:
      • lookup_verts = normalize(vertices, orig) → chỉ để tìm nearest vertex
      • Vertex data = `vertices` gốc (không bị scale/shift)
      • Weight transfer nearest-vertex với bone clamp + normalize
    """
    vertices, normals, uvs, tangents, indices, submeshes = parse_obj(filepath)
    if not vertices or not indices:
        raise ValueError("OBJ file không có geometry hợp lệ.")
    new_vc = len(vertices) // 3

    mesh    = obj_reader.read()
    version = mesh.version
    endian  = mesh.reader.endian

    orig_vc    = getattr(mesh,"m_VertexCount",0)
    if orig_vc == 0 and hasattr(mesh,"m_VertexData"):
        orig_vc = mesh.m_VertexData.m_VertexCount
    orig_skin  = getattr(mesh,"m_Skin",[])
    orig_verts = getattr(mesh,"m_Vertices",[])
    bone_count = len(getattr(mesh,"m_BindPose",[]))
    max_bone_idx = max(bone_count-1, 0)

    use_16bit = new_vc <= 65535
    mesh.m_Use16BitIndices = use_16bit
    mesh.m_IndexFormat = 0 if use_16bit else 1
    mesh.m_IndexBuffer = indices

    from ..classes.AnimationClip import AABB
    from ..math import Vector3
    center, extent = _aabb(vertices)
    new_aabb = AABB.__new__(AABB)
    new_aabb.m_Center = Vector3(center[0],center[1],center[2])
    new_aabb.m_Extent = Vector3(extent[0],extent[1],extent[2])

    if submeshes and len(submeshes) == len(mesh.m_SubMeshes):
        for i,sm_info in enumerate(submeshes):
            sm = mesh.m_SubMeshes[i]
            sm.firstByte  = sm_info["first"] * (2 if use_16bit else 4)
            sm.indexCount = sm_info["count"]; sm.firstVertex = 0
            sm.vertexCount = new_vc; sm.localAABB = new_aabb
    else:
        from ..classes.Mesh import SubMesh
        from ..enums import GfxPrimitiveType
        new_sms = []
        for sm_info in (submeshes or [{"first":0,"count":len(indices),"name":""}]):
            sm = SubMesh.__new__(SubMesh)
            sm.firstByte  = sm_info["first"] * (2 if use_16bit else 4)
            sm.indexCount = sm_info["count"]; sm.topology = GfxPrimitiveType.kPrimitiveTriangles
            sm.baseVertex = 0; sm.firstVertex = 0; sm.vertexCount = new_vc
            sm.localAABB  = new_aabb
            if version < (4,): sm.triangleCount = sm_info["count"] // 3
            new_sms.append(sm)
        mesh.m_SubMeshes = new_sms

    mesh.m_LocalAABB   = new_aabb
    mesh.m_VertexCount = new_vc
    mesh.m_MeshCompression = 0
    if hasattr(mesh,"m_StreamData"):
        mesh.m_StreamData.path=""; mesh.m_StreamData.offset=0; mesh.m_StreamData.size=0

    if new_vc == orig_vc:
        # Same count: rebuild VertexData với geometry mới, giữ skin weights gốc
        skin_to_use = orig_skin if orig_skin else []
        mesh._new_vd_bytes = _build_full_vertex_data(
            endian, new_vc, vertices, normals, uvs, tangents, skin_to_use)
        if hasattr(mesh,"m_VertexData"):
            mesh.m_VertexData.m_VertexCount = new_vc
            mesh.m_VertexData.m_DataSize    = b""
        mesh.m_Skin = skin_to_use
    else:
        # Different count: weight transfer
        algo = "numpy" if _HAS_NUMPY else "bisect"
        print(f"    [weight transfer {orig_vc}→{new_vc}, algo={algo}, "
              f"k={knn_k}, bones={bone_count}]")

        # Normalize CHỈ để tìm nearest vertex (weight lookup)
        # KHÔNG áp dụng lên vertex data
        lookup_verts = vertices
        if auto_scale and orig_verts:
            lookup_verts = _normalize_to_bbox(vertices, orig_verts)

        new_skin = _transfer_weights(
            orig_verts, orig_skin, lookup_verts, new_vc,
            max_bone_idx, progress_cb, knn_k=knn_k)

        # Dùng vertices gốc (không scale) cho VertexData
        mesh._new_vd_bytes = _build_full_vertex_data(
            endian, new_vc, vertices, normals, uvs, tangents, new_skin)
        if hasattr(mesh,"m_VertexData"):
            mesh.m_VertexData.m_VertexCount = new_vc
            mesh.m_VertexData.m_DataSize    = b""
        mesh.m_Skin = new_skin

    raw = _serialize_mesh(mesh)
    obj_reader.set_raw_data(raw)
    return True
