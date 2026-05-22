#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║         AOV Mesh CLI  –  Termux Android Tool         ║
╠══════════════════════════════════════════════════════╣
║  input/   ← đặt .assetbundle vào đây                 ║
║  output/  ← OBJ xuất ra / sửa tại đây                ║
║  osave/   ← bundle đã import lưu tại đây              ║
╠══════════════════════════════════════════════════════╣
║  python mesh_cli.py          → menu tương tác         ║
║  python mesh_cli.py export   → xuất tất cả mesh       ║
║  python mesh_cli.py import   → nhập lại mesh          ║
╚══════════════════════════════════════════════════════╝
"""

import os, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# auto_scale=True: tự động normalize scale khi thay model khác game
# Đặt False nếu model đã đúng scale rồi
AUTO_SCALE = True

DIR_INPUT  = os.path.join(ROOT, "input")
DIR_OUTPUT = os.path.join(ROOT, "output")
DIR_OSAVE  = os.path.join(ROOT, "osave")

for d in (DIR_INPUT, DIR_OUTPUT, DIR_OSAVE):
    os.makedirs(d, exist_ok=True)

# ── ANSI colours ─────────────────────────────────────
class C:
    R="\033[91m"; G="\033[92m"; Y="\033[93m"; B="\033[94m"
    M="\033[95m"; C="\033[96m"; W="\033[97m"; D="\033[2m"; X="\033[0m"

def ok(m):   print(f"{C.G}  ✓{C.X}  {m}")
def err(m):  print(f"{C.R}  ✗{C.X}  {m}")
def warn(m): print(f"{C.Y}  ⚠{C.X}  {m}")
def info(m): print(f"{C.B}  →{C.X}  {m}")
def head(m): print(f"\n{C.M}{'─'*54}{C.X}\n  {C.W}{m}{C.X}\n{C.M}{'─'*54}{C.X}")

# ── UnityPy loader ───────────────────────────────────
def _up():
    try:
        import AssetbundleUtils.UnityPy_AOV as up
        return up
    except ImportError as e:
        err(f"Không load được UnityPy_AOV: {e}"); sys.exit(1)

# ── Bundle scan ──────────────────────────────────────
BUNDLE_EXTS = {".assetbundle", ".bundle", ".ab", ".unity3d"}

def scan_bundles(folder):
    res = []
    for f in sorted(os.listdir(folder)):
        fp = os.path.join(folder, f)
        if os.path.isfile(fp):
            _, ext = os.path.splitext(f.lower())
            if ext in BUNDLE_EXTS or ext == "":
                res.append(fp)
    return res

# ── Progress bar ─────────────────────────────────────
def _make_progress(label):
    _t = [time.time()]
    def cb(cur, total):
        pct = int(cur / total * 100)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        elapsed = time.time() - _t[0]
        print(f"\r    {label} [{bar}] {pct:3d}%  {elapsed:.1f}s", end="", flush=True)
    return cb

# ═══════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════

def do_export():
    head("EXPORT MESH  (bundle → OBJ)")
    up = _up()
    bundles = scan_bundles(DIR_INPUT)
    if not bundles:
        warn(f"Không có bundle nào trong input/"); return

    info(f"Tìm thấy {len(bundles)} bundle(s)")
    total_ok = total_err = 0

    for bundle_path in bundles:
        bname = os.path.basename(bundle_path)
        print(f"\n{C.C}[{bname}]{C.X}")
        try:
            env = up.load(bundle_path)
        except Exception as e:
            err(f"Load bundle lỗi: {e}"); total_err += 1; continue

        for obj in env.objects:
            if obj.type.name != "Mesh":
                continue
            try:
                data = obj.read()

                # Fix: skip nếu parse thất bại và trả về NodeHelper
                if not hasattr(data, "export"):
                    warn(f"  id={obj.path_id} → parse thất bại (NodeHelper), bỏ qua")
                    total_err += 1
                    continue

                mesh_name = getattr(data, "m_Name", None) or f"mesh_{obj.path_id}"
                safe_b = bname.replace(".", "_").replace(" ", "_")
                safe_m = mesh_name.replace("/","_").replace("\\","_").replace(" ","_")
                out_name = f"{safe_b}__{safe_m}__{obj.path_id}.obj"
                out_path = os.path.join(DIR_OUTPUT, out_name)

                obj_str = data.export()
                if not obj_str:
                    warn(f"  {mesh_name} → export rỗng, bỏ qua"); continue

                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(obj_str)

                vc = getattr(data, "m_VertexCount", "?")
                ok(f"  {mesh_name}  [{vc} verts]  →  output/{out_name}")
                total_ok += 1

            except AttributeError as e:
                # NodeHelper không có export – skip bình thường
                warn(f"  id={obj.path_id} → bỏ qua ({e})")
                total_err += 1
            except Exception as e:
                err(f"  id={obj.path_id} lỗi: {e}")
                total_err += 1

    print()
    print(f"{C.G}Export xong:{C.X} {total_ok} mesh  |  {C.R}Lỗi/skip:{C.X} {total_err}")
    info(f"File OBJ tại: {DIR_OUTPUT}")

# ═══════════════════════════════════════════════════════
#  IMPORT
# ═══════════════════════════════════════════════════════

def do_import():
    head("IMPORT MESH  (OBJ → bundle)")
    up = _up()
    from AssetbundleUtils.UnityPy_AOV.export.MeshImporter import import_obj_to_mesh

    try:
        import numpy
        print(f"  {C.G}numpy detected{C.X} – weight transfer sẽ nhanh")
    except ImportError:
        print(f"  {C.Y}numpy không có{C.X} – dùng bisect fallback (chậm hơn ~5x)")

    obj_files = [f for f in sorted(os.listdir(DIR_OUTPUT)) if f.lower().endswith(".obj")]
    if not obj_files:
        warn("Không có .obj trong output/"); return

    # Nhóm OBJ theo bundle
    bundle_jobs = {}
    unparsed = []
    for fname in obj_files:
        parts = fname[:-4].split("__")
        if len(parts) >= 3:
            rb   = parts[0]
            mname= "__".join(parts[1:-1])
            pid  = parts[-1]
            bundle_jobs.setdefault(rb, []).append((pid, os.path.join(DIR_OUTPUT, fname), mname))
        else:
            unparsed.append(fname)

    if unparsed:
        warn(f"Không parse được bundle từ {len(unparsed)} file:")
        for f in unparsed: warn(f"  {f}")
    if not bundle_jobs:
        err("Không có OBJ hợp lệ."); return

    bundles_in_input = {os.path.basename(p): p for p in scan_bundles(DIR_INPUT)}
    total_ok = total_err = 0

    for raw_key, jobs in bundle_jobs.items():
        bundle_file = _find_bundle(raw_key, bundles_in_input)
        if bundle_file is None:
            err(f"Không tìm thấy bundle '{raw_key}' trong input/")
            err("  Có: " + ", ".join(bundles_in_input.keys()))
            total_err += len(jobs); continue

        bname = os.path.basename(bundle_file)
        print(f"\n{C.C}[{bname}]{C.X}  ({len(jobs)} mesh)")
        try:
            env = up.load(bundle_file)
        except Exception as e:
            err(f"  Load lỗi: {e}"); total_err += len(jobs); continue

        obj_map  = {str(o.path_id): o for o in env.objects if o.type.name == "Mesh"}
        modified = False

        for (pid, obj_path, mname) in jobs:
            if pid not in obj_map:
                err(f"  id={pid} ({mname}) không có trong bundle"); total_err += 1; continue
            try:
                t0 = time.time()
                pcb = _make_progress(mname[:20])
                import_obj_to_mesh(obj_map[pid], obj_path, progress_cb=pcb, auto_scale=AUTO_SCALE)
                print()  # newline sau progress bar
                elapsed = time.time() - t0
                ok(f"  {mname}  (id={pid})  {elapsed:.1f}s")
                modified = True; total_ok += 1
            except ValueError as e:
                print()
                err(f"  {mname}: {e}"); total_err += 1
            except Exception as e:
                print()
                import traceback
                err(f"  {mname}: {e}"); traceback.print_exc(); total_err += 1

        if not modified:
            info("  Không có mesh nào thay đổi, bỏ qua save."); continue

        out_bundle = os.path.join(DIR_OSAVE, bname)
        try:
            data = _save_env(env)
            with open(out_bundle, "wb") as f: f.write(data)
            ok(f"  Đã lưu → osave/{bname}")
        except Exception as e:
            err(f"  Lưu bundle lỗi: {e}"); total_err += 1

    print()
    print(f"{C.G}Import xong:{C.X} {total_ok} mesh  |  {C.R}Lỗi:{C.X} {total_err}")
    info(f"Bundle tại: {DIR_OSAVE}")


def _find_bundle(raw_key, bundles_dict):
    if raw_key in bundles_dict: return bundles_dict[raw_key]
    for bname, bpath in bundles_dict.items():
        if bname.replace(".", "_").replace(" ", "_") == raw_key: return bpath
    for bname, bpath in bundles_dict.items():
        n = bname.replace(".", "_").replace(" ", "_")
        if raw_key.startswith(n) or n.startswith(raw_key): return bpath
    return None


def _save_env(env):
    try:
        return env.file.save("lz4") if hasattr(env, "file") else list(env.files.values())[0].save("lz4")
    except Exception:
        return env.file.save("lzma") if hasattr(env, "file") else list(env.files.values())[0].save("lzma")

# ═══════════════════════════════════════════════════════
#  LIST
# ═══════════════════════════════════════════════════════

def do_list():
    head("LIST MESH trong input/")
    up = _up()
    for bundle_path in scan_bundles(DIR_INPUT):
        bname = os.path.basename(bundle_path)
        print(f"\n{C.C}[{bname}]{C.X}")
        try:
            env = up.load(bundle_path)
        except Exception as e:
            err(f"  Load lỗi: {e}"); continue
        found = False
        for obj in env.objects:
            if obj.type.name != "Mesh": continue
            try:
                data  = obj.read()
                if not hasattr(data, "m_Name"):
                    warn(f"  id={obj.path_id} → parse thất bại, bỏ qua"); continue
                name  = getattr(data, "m_Name", f"[{obj.path_id}]")
                vc    = getattr(data, "m_VertexCount", "?")
                subs  = len(getattr(data, "m_SubMeshes", []))
                bones = len(getattr(data, "m_BindPose", []))
                print(f"  {C.W}{name:<40}{C.X}"
                      f"  verts={C.Y}{str(vc):<6}{C.X}"
                      f"  sub={subs}  bones={bones}"
                      f"  {C.D}id={obj.path_id}{C.X}")
                found = True
            except Exception as e:
                err(f"  id={obj.path_id} lỗi: {e}")
        if not found:
            info("  (không có Mesh)")

# ═══════════════════════════════════════════════════════
#  MENU
# ═══════════════════════════════════════════════════════

def print_banner():
    print(f"""
{C.M}╔══════════════════════════════════════════════════════╗
║      {C.W}AOV Mesh CLI  –  Termux Edition{C.M}                 ║
╠══════════════════════════════════════════════════════╣
║  {C.C}input/{C.M}   ← .assetbundle gốc                          ║
║  {C.C}output/{C.M}  ← OBJ xuất/chỉnh sửa tại đây               ║
║  {C.C}osave/{C.M}   ← bundle sau import                         ║
╚══════════════════════════════════════════════════════╝{C.X}""")

def print_status():
    nb = len(scan_bundles(DIR_INPUT))
    no = len([f for f in os.listdir(DIR_OUTPUT) if f.endswith(".obj")])
    ns = len(os.listdir(DIR_OSAVE))
    print(f"  {C.D}input:{nb} bundle  output:{no} obj  osave:{ns} file{C.X}\n")

def interactive_menu():
    print_banner()
    while True:
        print_status()
        print(f"  {C.G}1{C.X}  Export Mesh  (bundle → OBJ)")
        print(f"  {C.G}2{C.X}  Import Mesh  (OBJ → bundle)")
        print(f"  {C.G}3{C.X}  List Mesh")
        print(f"  {C.R}0{C.X}  Thoát\n")
        try:
            ch = input(f"  {C.Y}Chọn:{C.X} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nThoát."); break
        if   ch == "1": do_export()
        elif ch == "2": do_import()
        elif ch == "3": do_list()
        elif ch == "0": print("Thoát."); break
        else: warn("Lựa chọn không hợp lệ.")

def main():
    args = sys.argv[1:]
    if not args: interactive_menu()
    elif args[0].lower() in ("export","e","-e"): do_export()
    elif args[0].lower() in ("import","i","-i"): do_import()
    elif args[0].lower() in ("list","l","-l"):   do_list()
    elif args[0].lower() in ("--no-scale","-ns"):
        global AUTO_SCALE; AUTO_SCALE=False
        print("  Auto-scale OFF")
        if len(args)>1:
            if args[1].lower() in ("import","i"): do_import()
    else: print("Usage: python mesh_cli.py [export|import|list]"); sys.exit(1)

if __name__ == "__main__":
    main()
