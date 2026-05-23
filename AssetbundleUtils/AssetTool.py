# -*- coding: utf-8 -*-
"""
AssetTool – engine xuất/nhập asset đa năng cho bundle Liên Quân (AOV).

Hỗ trợ:
  - Texture2D / Sprite   <->  PNG
  - Mesh                 <->  OBJ
  - TextAsset            <->  TXT / BIN
  - AudioClip            -->  WAV / OGG  (chỉ export)
  - AnimationClip + mọi loại còn lại  <->  JSON (typetree dump, kiểu UABE)
  - Mọi loại             <->  RAW (.dat)

Mọi thao tác đều đi qua typetree nên không phụ thuộc class parser –
nhờ đó AnimationClip (vốn không có hàm save) vẫn mod được.
"""

import os
import io
import sys
import json
import base64
import traceback
import contextlib


@contextlib.contextmanager
def _quiet():
    """Chặn stdout/stderr ồn ào từ parser khi class parse thất bại."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BUNDLE_EXTS = {".assetbundle", ".bundle", ".ab", ".unity3d"}

# Loại asset -> định dạng file xuất ra
TEXTURE_TYPES = {"Texture2D", "Sprite"}
TEXT_TYPES = {"TextAsset"}
MESH_TYPES = {"Mesh"}
AUDIO_TYPES = {"AudioClip"}


# ──────────────────────────────────────────────────────────
#  UnityPy loader
# ──────────────────────────────────────────────────────────
def get_up():
    """Load fork UnityPy_AOV."""
    import AssetbundleUtils.UnityPy_AOV as up
    return up


def scan_bundles(folder):
    """Trả về danh sách path bundle trong folder (kể cả file không đuôi)."""
    res = []
    if not os.path.isdir(folder):
        return res
    for f in sorted(os.listdir(folder)):
        fp = os.path.join(folder, f)
        if not os.path.isfile(fp):
            continue
        ext = os.path.splitext(f.lower())[1]
        if ext in BUNDLE_EXTS or ext == "":
            res.append(fp)
    return res


def sanitize(s):
    """Chuẩn hoá chuỗi để dùng làm tên file (không chứa '__')."""
    out = []
    for c in str(s):
        if c.isalnum() or c in "-.":
            out.append(c)
        else:
            out.append("_")
    s = "".join(out)
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_") or "unnamed"


# ──────────────────────────────────────────────────────────
#  JSON typetree (hỗ trợ bytes qua base64)
# ──────────────────────────────────────────────────────────
class _B64Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (bytes, bytearray)):
            return {"__bytes_b64__": base64.b64encode(bytes(o)).decode("ascii")}
        return json.JSONEncoder.default(self, o)


def _b64_hook(d):
    if len(d) == 1 and "__bytes_b64__" in d:
        return base64.b64decode(d["__bytes_b64__"])
    return d


def tree_to_json(tree):
    return json.dumps(tree, cls=_B64Encoder, ensure_ascii=False, indent=1)


def json_to_tree(text):
    return json.loads(text, object_hook=_b64_hook)


# ──────────────────────────────────────────────────────────
#  Quy ước tên file:  {bundle}__{type}__{name}__{pathid}.{ext}
# ──────────────────────────────────────────────────────────
def make_filename(bundle_name, type_name, asset_name, path_id, ext):
    b = sanitize(bundle_name)
    t = sanitize(type_name)
    n = sanitize(asset_name)
    return f"{b}__{t}__{n}__{path_id}.{ext}"


def parse_filename(fname):
    """Tách metadata từ tên file. Trả về dict hoặc None."""
    base, ext = os.path.splitext(fname)
    ext = ext.lower().lstrip(".")
    parts = base.split("__")
    if len(parts) >= 4:
        return {
            "bundle": parts[0],
            "type": parts[1],
            "name": "__".join(parts[2:-1]),
            "path_id": parts[-1],
            "ext": ext,
        }
    # Tương thích định dạng cũ của mesh: {bundle}__{name}__{pathid}.obj
    if len(parts) == 3 and ext == "obj":
        return {
            "bundle": parts[0],
            "type": "Mesh",
            "name": parts[1],
            "path_id": parts[-1],
            "ext": ext,
        }
    return None


# ──────────────────────────────────────────────────────────
#  Liệt kê asset
# ──────────────────────────────────────────────────────────
def list_objects(env):
    """Trả về list dict mô tả mọi object trong env."""
    items = []
    for obj in env.objects:
        info = {
            "obj": obj,
            "type": obj.type.name,
            "path_id": obj.path_id,
            "name": "",
            "size": getattr(obj, "byte_size", 0),
        }
        try:
            with _quiet():
                data = obj.read()
            info["name"] = (
                getattr(data, "m_Name", None)
                or getattr(data, "name", None)
                or ""
            )
        except Exception:
            pass
        items.append(info)
    return items


# ──────────────────────────────────────────────────────────
#  EXPORT
# ──────────────────────────────────────────────────────────
def export_object(obj, bundle_name, out_dir, mode="auto"):
    """
    Xuất 1 object ra file.
    mode: "auto" (theo loại), "json" (typetree), "raw" (.dat).
    Trả về (ok: bool, path_hoặc_thông_báo: str).
    """
    type_name = obj.type.name
    path_id = obj.path_id

    # tên asset
    asset_name = ""
    data = None
    try:
        with _quiet():
            data = obj.read()
        asset_name = (
            getattr(data, "m_Name", None) or getattr(data, "name", None) or ""
        )
    except Exception:
        pass
    if not asset_name:
        asset_name = f"{type_name}_{path_id}"

    try:
        if mode == "raw":
            return _safe_call(_export_raw, obj, bundle_name, type_name,
                              asset_name, out_dir)
        if mode == "json":
            ok, fp = _safe_call(_export_json, obj, bundle_name, type_name,
                                asset_name, out_dir)
            if ok:
                return True, fp
            # JSON typetree thất bại -> rớt xuống RAW
            return _safe_call(_export_raw, obj, bundle_name, type_name,
                              asset_name, out_dir)

        # ── mode "auto": cascade native -> JSON typetree -> RAW ─────
        ok, result = False, ""
        if type_name in MESH_TYPES:
            ok, result = _safe_call(_export_mesh, obj, data, bundle_name,
                                    asset_name, out_dir)
        elif type_name in TEXTURE_TYPES:
            ok, result = _safe_call(_export_texture, obj, data, bundle_name,
                                    type_name, asset_name, out_dir)
        elif type_name in TEXT_TYPES:
            ok, result = _safe_call(_export_text, obj, data, bundle_name,
                                    asset_name, out_dir)
        elif type_name in AUDIO_TYPES:
            ok, result = _safe_call(_export_audio, obj, data, bundle_name,
                                    asset_name, out_dir)
        if ok:
            return True, result

        # Fallback 1: JSON typetree (chạy cho hầu hết mọi class hợp lệ)
        ok2, fp2 = _safe_call(_export_json, obj, bundle_name, type_name,
                              asset_name, out_dir)
        if ok2:
            return True, fp2

        # Fallback cuối: RAW (.dat) – luôn thành công, bảo toàn nguyên byte
        ok3, fp3 = _safe_call(_export_raw, obj, bundle_name, type_name,
                              asset_name, out_dir)
        if ok3:
            return True, fp3

        # Cả 3 lớp đều fail -> trả lý do lớp đầu tiên
        return False, result or fp2 or fp3 or f"{type_name} id={path_id}: lỗi không xác định"
    except Exception as e:
        # Bắt sót — vẫn cố bảo toàn bằng RAW
        try:
            return _safe_call(_export_raw, obj, bundle_name, type_name,
                              asset_name, out_dir)
        except Exception:
            return False, f"{type_name} id={path_id}: {e}"


def _safe_call(fn, *args, **kwargs):
    """Gọi exporter trong môi trường im lặng, không bao giờ ném exception."""
    try:
        with _quiet():
            return fn(*args, **kwargs)
    except Exception as e:
        return False, f"{fn.__name__}: {e}"


def _write(out_dir, fname, data, binary=True):
    fp = os.path.join(out_dir, fname)
    mode = "wb" if binary else "w"
    if binary:
        with open(fp, mode) as f:
            f.write(data)
    else:
        with open(fp, mode, encoding="utf-8") as f:
            f.write(data)
    return fp


def _export_raw(obj, bundle, type_name, name, out_dir):
    fname = make_filename(bundle, type_name, name, obj.path_id, "dat")
    fp = _write(out_dir, fname, obj.get_raw_data())
    return True, fp


def _export_json(obj, bundle, type_name, name, out_dir):
    tree = obj.read_typetree()
    fname = make_filename(bundle, type_name, name, obj.path_id, "json")
    fp = _write(out_dir, fname, tree_to_json(tree), binary=False)
    return True, fp


def _export_mesh(obj, data, bundle, name, out_dir):
    if data is None or not hasattr(data, "export"):
        return False, f"Mesh id={obj.path_id}: parse thất bại"
    obj_str = data.export()
    if not obj_str:
        return False, f"Mesh {name}: export rỗng"
    fname = make_filename(bundle, "Mesh", name, obj.path_id, "obj")
    fp = _write(out_dir, fname, obj_str, binary=False)
    return True, fp


def _export_texture(obj, data, bundle, type_name, name, out_dir):
    if data is None or not hasattr(data, "image"):
        return False, f"{type_name} id={obj.path_id}: không có ảnh"
    img = data.image
    if img is None:
        return False, f"{type_name} {name}: ảnh rỗng"
    fname = make_filename(bundle, type_name, name, obj.path_id, "png")
    fp = os.path.join(out_dir, fname)
    img.save(fp)
    return True, fp


def _export_text(obj, data, bundle, name, out_dir):
    if data is None or not hasattr(data, "m_Script"):
        return False, f"TextAsset id={obj.path_id}: không đọc được"
    raw = bytes(data.m_Script)
    # text thuần -> .txt, nhị phân -> .bin
    is_text = True
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        is_text = False
    ext = "txt" if is_text else "bin"
    fname = make_filename(bundle, "TextAsset", name, obj.path_id, ext)
    fp = _write(out_dir, fname, raw)
    return True, fp


def _export_audio(obj, data, bundle, name, out_dir):
    from AssetbundleUtils.UnityPy_AOV.export.AudioClipConverter import (
        extract_audioclip_samples,
    )
    samples = extract_audioclip_samples(data)
    if not samples:
        return False, f"AudioClip {name}: không có dữ liệu (streamed?)"
    last = None
    for sample_name, sample_data in samples.items():
        ext = os.path.splitext(sample_name)[1].lstrip(".") or "wav"
        fname = make_filename(bundle, "AudioClip", name, obj.path_id, ext)
        last = _write(out_dir, fname, sample_data)
    return True, last


# ──────────────────────────────────────────────────────────
#  IMPORT
# ──────────────────────────────────────────────────────────
def import_file(obj, filepath, ext, auto_scale=True, force_rgba32=False):
    """
    Nhập 1 file vào object. Trả về (ok: bool, thông_báo: str).
    Định dạng được suy ra từ ext.

    Cơ chế fallback: nếu import theo class (texture/mesh/text) thất bại,
    thử tự động JSON typetree hoặc RAW (.dat) cùng tên (nếu user đã xuất
    sẵn bằng các fallback đó), để asset vẫn được mod thay vì bỏ qua.
    """
    ext = ext.lower()
    try:
        with _quiet():
            if ext in ("png", "jpg", "jpeg", "bmp", "tga"):
                ok, msg = _import_texture(obj, filepath, force_rgba32)
            elif ext == "obj":
                ok, msg = _import_mesh(obj, filepath, auto_scale)
            elif ext == "json":
                ok, msg = _import_json(obj, filepath)
            elif ext in ("txt", "bin"):
                ok, msg = _import_text(obj, filepath)
            elif ext == "dat":
                ok, msg = _import_raw(obj, filepath)
            else:
                ok, msg = False, f"Không hỗ trợ import định dạng .{ext}"
        if ok:
            return True, msg
    except Exception as e:
        msg = str(e).splitlines()[0]

    # Import gốc lỗi -> thử file fallback cùng pathid trong cùng thư mục
    folder = os.path.dirname(filepath)
    pid = str(obj.path_id)
    for cand_ext in ("json", "dat"):
        if cand_ext == ext:
            continue
        for f in os.listdir(folder):
            if not f.endswith(f"__{pid}.{cand_ext}"):
                continue
            try:
                with _quiet():
                    if cand_ext == "json":
                        return _import_json(obj, os.path.join(folder, f))
                    return _import_raw(obj, os.path.join(folder, f))
            except Exception:
                pass
    return False, msg


def _import_texture(obj, filepath, force_rgba32):
    from PIL import Image
    from AssetbundleUtils.UnityPy_AOV.enums import TextureFormat

    if obj.type.name not in TEXTURE_TYPES:
        return False, f"id={obj.path_id} không phải Texture2D/Sprite"
    data = obj.read()
    if not hasattr(data, "image") or not hasattr(data, "save"):
        return False, "Asset không hỗ trợ import texture"
    img = Image.open(filepath).convert("RGBA")

    if force_rgba32:
        data.m_TextureFormat = TextureFormat.RGBA32
    try:
        data.image = img
    except Exception:
        # encoder cho định dạng gốc không có -> fallback RGBA32
        data.m_TextureFormat = TextureFormat.RGBA32
        data.image = img
    data.save()
    return True, f"texture {data.m_Width}x{data.m_Height} -> id={obj.path_id}"


def _import_mesh(obj, filepath, auto_scale):
    from AssetbundleUtils.UnityPy_AOV.export.MeshImporter import import_obj_to_mesh

    if obj.type.name != "Mesh":
        return False, f"id={obj.path_id} không phải Mesh"
    import_obj_to_mesh(obj, filepath, auto_scale=auto_scale)
    return True, f"mesh -> id={obj.path_id}"


def _import_json(obj, filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        tree = json_to_tree(f.read())
    obj.save_typetree(tree)
    return True, f"typetree -> id={obj.path_id}"


def _import_text(obj, filepath):
    if obj.type.name not in TEXT_TYPES:
        return False, f"id={obj.path_id} không phải TextAsset"
    data = obj.read()
    with open(filepath, "rb") as f:
        raw = f.read()
    data.m_Script = raw
    data.save()
    return True, f"text {len(raw)} bytes -> id={obj.path_id}"


def _import_raw(obj, filepath):
    with open(filepath, "rb") as f:
        raw = f.read()
    obj.set_raw_data(raw)
    return True, f"raw {len(raw)} bytes -> id={obj.path_id}"


# ──────────────────────────────────────────────────────────
#  Lưu bundle
# ──────────────────────────────────────────────────────────
def save_bundle(env, out_path):
    """Đóng gói lại bundle đã chỉnh sửa, ghi ra out_path."""
    last_err = None
    for packer in ("lz4", "lzma", "none"):
        try:
            if hasattr(env, "file"):
                data = env.file.save(packer=packer)
            else:
                data = list(env.files.values())[0].save(packer=packer)
            with open(out_path, "wb") as f:
                f.write(data)
            return True, packer
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Không lưu được bundle: {last_err}")
