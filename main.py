#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║      AOV Asset Tool  –  Termux Android Edition       ║
╠══════════════════════════════════════════════════════╣
║  Công cụ chỉnh sửa assetbundle Liên Quân (AOV)       ║
║  hoạt động như AssetStudio / UABE, chạy trên Termux. ║
╠══════════════════════════════════════════════════════╣
║  input/   ← đặt .assetbundle gốc vào đây             ║
║  output/  ← asset xuất ra / chỉnh sửa tại đây        ║
║  osave/   ← bundle sau khi import lưu tại đây         ║
╠══════════════════════════════════════════════════════╣
║  Hỗ trợ:  Texture2D/Sprite (PNG)  ·  Mesh (OBJ)      ║
║           TextAsset (TXT)  ·  AudioClip (WAV)        ║
║           AnimationClip + mọi loại khác (JSON)       ║
╠══════════════════════════════════════════════════════╣
║  python main.py            → menu tương tác           ║
║  python main.py list       → liệt kê asset            ║
║  python main.py export     → xuất tất cả asset        ║
║  python main.py import     → nhập lại & đóng gói      ║
╚══════════════════════════════════════════════════════╝
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from AssetbundleUtils import AssetTool as AT  # noqa: E402

DIR_INPUT = os.path.join(ROOT, "input")
DIR_OUTPUT = os.path.join(ROOT, "output")
DIR_OSAVE = os.path.join(ROOT, "osave")
for d in (DIR_INPUT, DIR_OUTPUT, DIR_OSAVE):
    os.makedirs(d, exist_ok=True)

# Cấu hình runtime
AUTO_SCALE = True       # tự normalize scale khi import mesh khác game
FORCE_RGBA32 = False    # ép texture về RGBA32 (an toàn, nhưng nặng hơn)
KNN_K = 4               # số neighbor blend bone-weight (chống "model dị")
                        # 1=nearest cũ, 4=mượt (mặc định), 8=cực mượt/chậm
OBJ_SOURCE = "aov"      # "aov" = OBJ do tool này export (đã flip X+đảo winding)
                        # "external" = OBJ Blender/3DS/Maya thuần
OBJ_ROTATE_Y = 0        # xoay quanh trục Y khi import: 0/90/180/270
OBJ_SWAP_YZ = False     # nguồn Z-up (đa số Blender Y-up nên để False)


# ── ANSI colours ─────────────────────────────────────
class C:
    R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; B = "\033[94m"
    M = "\033[95m"; C = "\033[96m"; W = "\033[97m"; D = "\033[2m"; X = "\033[0m"


def ok(m):   print(f"{C.G}  ✓{C.X}  {m}")
def err(m):  print(f"{C.R}  ✗{C.X}  {m}")
def warn(m): print(f"{C.Y}  ⚠{C.X}  {m}")
def info(m): print(f"{C.B}  →{C.X}  {m}")


def head(m):
    print(f"\n{C.M}{'─' * 56}{C.X}\n  {C.W}{m}{C.X}\n{C.M}{'─' * 56}{C.X}")


def ask(prompt):
    try:
        return input(f"  {C.Y}{prompt}{C.X} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


# ═══════════════════════════════════════════════════════
#  LIST
# ═══════════════════════════════════════════════════════
def do_list():
    head("LIỆT KÊ ASSET trong input/")
    up = AT.get_up()
    bundles = AT.scan_bundles(DIR_INPUT)
    if not bundles:
        warn("Không có bundle nào trong input/")
        return

    for bundle_path in bundles:
        bname = os.path.basename(bundle_path)
        print(f"\n{C.C}[{bname}]{C.X}")
        try:
            env = up.load(bundle_path)
        except Exception as e:
            err(f"  Load lỗi: {e}")
            continue

        items = AT.list_objects(env)
        if not items:
            info("  (không có object)")
            continue

        # gom nhóm theo loại
        by_type = {}
        for it in items:
            by_type.setdefault(it["type"], []).append(it)

        for type_name in sorted(by_type):
            group = by_type[type_name]
            print(f"  {C.W}{type_name}{C.X} {C.D}({len(group)}){C.X}")
            for it in group:
                name = it["name"] or "(no name)"
                print(f"    {name:<38}  {C.D}id={it['path_id']}{C.X}")


# ═══════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════
def do_export(type_filter=None, mode="auto"):
    head("EXPORT ASSET  (bundle → output/)")
    up = AT.get_up()
    bundles = AT.scan_bundles(DIR_INPUT)
    if not bundles:
        warn("Không có bundle nào trong input/")
        return

    info(f"Chế độ: {mode}" + (f"  ·  lọc loại: {type_filter}" if type_filter else ""))
    total_ok = total_err = total_skip = 0

    for bundle_path in bundles:
        bname = os.path.basename(bundle_path)
        print(f"\n{C.C}[{bname}]{C.X}")
        try:
            env = up.load(bundle_path)
        except Exception as e:
            err(f"  Load lỗi: {e}")
            continue

        for obj in env.objects:
            type_name = obj.type.name
            if type_filter and type_name not in type_filter:
                total_skip += 1
                continue
            success, result = AT.export_object(obj, bname, DIR_OUTPUT, mode=mode)
            if success:
                ok(f"  {type_name:<16} → {os.path.basename(result)}")
                total_ok += 1
            else:
                warn(f"  {result}")
                total_err += 1

    print()
    print(f"{C.G}Export xong:{C.X} {total_ok}  |  "
          f"{C.R}Lỗi/skip:{C.X} {total_err}  |  {C.D}bỏ qua: {total_skip}{C.X}")
    info(f"Asset tại: {DIR_OUTPUT}")


def export_menu():
    head("EXPORT – chọn tuỳ chọn")
    print(f"  {C.G}1{C.X}  Export tất cả (tự động theo loại)")
    print(f"  {C.G}2{C.X}  Chỉ Texture2D/Sprite (PNG)")
    print(f"  {C.G}3{C.X}  Chỉ Mesh (OBJ)")
    print(f"  {C.G}4{C.X}  Chỉ AnimationClip (JSON)")
    print(f"  {C.G}5{C.X}  Chỉ TextAsset / AudioClip")
    print(f"  {C.G}6{C.X}  Export TẤT CẢ dạng JSON typetree (kiểu UABE dump)")
    print(f"  {C.G}7{C.X}  Export TẤT CẢ dạng RAW (.dat)")
    print(f"  {C.R}0{C.X}  Quay lại\n")
    ch = ask("Chọn:")
    if ch == "1":
        do_export()
    elif ch == "2":
        do_export(type_filter=AT.TEXTURE_TYPES)
    elif ch == "3":
        do_export(type_filter=AT.MESH_TYPES)
    elif ch == "4":
        do_export(type_filter={"AnimationClip"}, mode="json")
    elif ch == "5":
        do_export(type_filter=AT.TEXT_TYPES | AT.AUDIO_TYPES)
    elif ch == "6":
        do_export(mode="json")
    elif ch == "7":
        do_export(mode="raw")
    elif ch == "0":
        return
    else:
        warn("Lựa chọn không hợp lệ.")


# ═══════════════════════════════════════════════════════
#  IMPORT
# ═══════════════════════════════════════════════════════
def _find_bundle(raw_key, bundles_dict):
    """Tìm bundle gốc khớp với tên đã sanitize trong filename."""
    if raw_key in bundles_dict:
        return bundles_dict[raw_key]
    for bname, bpath in bundles_dict.items():
        if AT.sanitize(bname) == raw_key:
            return bpath
    for bname, bpath in bundles_dict.items():
        n = AT.sanitize(bname)
        if raw_key.startswith(n) or n.startswith(raw_key):
            return bpath
    return None


def do_import():
    head("IMPORT ASSET  (output/ → osave/)")

    files = [f for f in sorted(os.listdir(DIR_OUTPUT))
             if os.path.isfile(os.path.join(DIR_OUTPUT, f))]
    if not files:
        warn("output/ trống – không có gì để import.")
        return

    # gom file theo bundle
    jobs = {}        # bundle_key -> list[(path_id, filepath, ext, name)]
    unparsed = []
    for fname in files:
        meta = AT.parse_filename(fname)
        if not meta:
            unparsed.append(fname)
            continue
        jobs.setdefault(meta["bundle"], []).append(
            (meta["path_id"], os.path.join(DIR_OUTPUT, fname),
             meta["ext"], meta["name"])
        )

    if unparsed:
        warn(f"Bỏ qua {len(unparsed)} file không đúng quy ước tên:")
        for f in unparsed:
            print(f"      {C.D}{f}{C.X}")
    if not jobs:
        err("Không có file hợp lệ để import.")
        return

    up = AT.get_up()
    bundles_in_input = {os.path.basename(p): p
                        for p in AT.scan_bundles(DIR_INPUT)}
    total_ok = total_err = 0

    for bundle_key, file_jobs in jobs.items():
        bundle_path = _find_bundle(bundle_key, bundles_in_input)
        if bundle_path is None:
            err(f"Không tìm thấy bundle '{bundle_key}' trong input/")
            err(f"  Có sẵn: {', '.join(bundles_in_input.keys()) or '(trống)'}")
            total_err += len(file_jobs)
            continue

        bname = os.path.basename(bundle_path)
        print(f"\n{C.C}[{bname}]{C.X}  ({len(file_jobs)} file)")
        try:
            env = up.load(bundle_path)
        except Exception as e:
            err(f"  Load lỗi: {e}")
            total_err += len(file_jobs)
            continue

        obj_map = {str(o.path_id): o for o in env.objects}
        modified = False

        for (path_id, filepath, ext, name) in file_jobs:
            obj = obj_map.get(path_id)
            if obj is None:
                err(f"  id={path_id} ({name}) không có trong bundle")
                total_err += 1
                continue
            t0 = time.time()
            success, msg = AT.import_file(
                obj, filepath, ext,
                auto_scale=AUTO_SCALE, force_rgba32=FORCE_RGBA32,
                knn_k=KNN_K,
                obj_source=OBJ_SOURCE,
                rotate_y_deg=OBJ_ROTATE_Y,
                swap_yz=OBJ_SWAP_YZ,
            )
            if success:
                ok(f"  {name}  ({msg})  {time.time() - t0:.1f}s")
                modified = True
                total_ok += 1
            else:
                err(f"  {name}: {msg.splitlines()[0]}")
                total_err += 1

        if not modified:
            info("  Không có thay đổi, bỏ qua lưu bundle.")
            continue

        out_bundle = os.path.join(DIR_OSAVE, bname)
        try:
            _, packer = AT.save_bundle(env, out_bundle)
            ok(f"  Đã lưu → osave/{bname}  ({packer})")
        except Exception as e:
            err(f"  Lưu bundle lỗi: {e}")
            total_err += 1

    print()
    print(f"{C.G}Import xong:{C.X} {total_ok}  |  {C.R}Lỗi:{C.X} {total_err}")
    info(f"Bundle đã mod tại: {DIR_OSAVE}")
    info("Chép bundle trong osave/ đè vào game để áp dụng mod.")


# ═══════════════════════════════════════════════════════
#  SETTINGS
# ═══════════════════════════════════════════════════════
def settings_menu():
    global AUTO_SCALE, FORCE_RGBA32, KNN_K
    global OBJ_SOURCE, OBJ_ROTATE_Y, OBJ_SWAP_YZ
    head("CÀI ĐẶT")
    print(f"  {C.G}1{C.X}  Auto-scale mesh khi import : "
          f"{C.G if AUTO_SCALE else C.R}{'BẬT' if AUTO_SCALE else 'TẮT'}{C.X}")
    print(f"  {C.G}2{C.X}  Ép texture về RGBA32       : "
          f"{C.G if FORCE_RGBA32 else C.R}{'BẬT' if FORCE_RGBA32 else 'TẮT'}{C.X}")
    print(f"  {C.G}3{C.X}  Weight blend k (chống dị)  : "
          f"{C.G}k={KNN_K}{C.X}")
    print(f"  {C.G}4{C.X}  Nguồn OBJ (mode)           : "
          f"{C.G}{OBJ_SOURCE}{C.X}")
    print(f"  {C.G}5{C.X}  Xoay quanh trục Y          : "
          f"{C.G}{OBJ_ROTATE_Y}°{C.X}")
    print(f"  {C.G}6{C.X}  Hoán đổi Y↔Z (Z-up source) : "
          f"{C.G if OBJ_SWAP_YZ else C.R}{'BẬT' if OBJ_SWAP_YZ else 'TẮT'}{C.X}")
    print(f"  {C.R}0{C.X}  Quay lại\n")
    print(f"  {C.D}Auto-scale: chuẩn hoá kích thước khi thay model khác game.{C.X}")
    print(f"  {C.D}RGBA32: không mất chất lượng nhưng bundle nặng hơn.{C.X}")
    print(f"  {C.D}k weight: 1=cứng (nhanh, dễ dị), 4=mượt, 8=cực mượt.{C.X}")
    print(f"  {C.D}Nguồn OBJ: 'aov' cho OBJ export bằng tool này;{C.X}")
    print(f"  {C.D}           'external' cho OBJ từ Blender/3DS/Maya thuần.{C.X}")
    print(f"  {C.D}Xoay Y: dùng 180° nếu nhân vật quay mặt ngược chiều.{C.X}")
    print(f"  {C.D}Y↔Z: bật nếu OBJ ngoài là Z-up (vd Maya/3DS export gốc).{C.X}\n")
    ch = ask("Chọn để chỉnh:")
    if ch == "1":
        AUTO_SCALE = not AUTO_SCALE
        info(f"Auto-scale = {AUTO_SCALE}")
    elif ch == "2":
        FORCE_RGBA32 = not FORCE_RGBA32
        info(f"Force RGBA32 = {FORCE_RGBA32}")
    elif ch == "3":
        val = ask("Nhập k (1-16, mặc định 4):")
        try:
            KNN_K = max(1, min(16, int(val)))
            info(f"Weight blend k = {KNN_K}")
        except ValueError:
            warn("Giá trị không hợp lệ.")
    elif ch == "4":
        OBJ_SOURCE = "external" if OBJ_SOURCE == "aov" else "aov"
        info(f"Nguồn OBJ = {OBJ_SOURCE}")
    elif ch == "5":
        val = ask("Góc xoay quanh Y (0/90/180/270):")
        try:
            v = int(val) % 360
            if v in (0, 90, 180, 270):
                OBJ_ROTATE_Y = v
                info(f"Xoay Y = {OBJ_ROTATE_Y}°")
            else:
                warn("Chỉ nhận 0/90/180/270.")
        except ValueError:
            warn("Giá trị không hợp lệ.")
    elif ch == "6":
        OBJ_SWAP_YZ = not OBJ_SWAP_YZ
        info(f"Y↔Z swap = {OBJ_SWAP_YZ}")


# ═══════════════════════════════════════════════════════
#  MENU
# ═══════════════════════════════════════════════════════
def print_banner():
    print(f"""
{C.M}╔══════════════════════════════════════════════════════╗
║      {C.W}AOV Asset Tool  –  Termux Edition{C.M}               ║
╠══════════════════════════════════════════════════════╣
║  {C.C}input/{C.M}   ← .assetbundle gốc                          ║
║  {C.C}output/{C.M}  ← asset xuất / chỉnh sửa                    ║
║  {C.C}osave/{C.M}   ← bundle sau khi import                      ║
╚══════════════════════════════════════════════════════╝{C.X}""")


def print_status():
    nb = len(AT.scan_bundles(DIR_INPUT))
    no = len([f for f in os.listdir(DIR_OUTPUT)
              if os.path.isfile(os.path.join(DIR_OUTPUT, f))])
    ns = len(os.listdir(DIR_OSAVE))
    print(f"  {C.D}input:{nb} bundle   output:{no} file   "
          f"osave:{ns} file{C.X}\n")


def interactive_menu():
    print_banner()
    while True:
        print_status()
        print(f"  {C.G}1{C.X}  Liệt kê asset  (List)")
        print(f"  {C.G}2{C.X}  Export asset   (bundle → output/)")
        print(f"  {C.G}3{C.X}  Import asset   (output/ → osave/)")
        print(f"  {C.G}4{C.X}  Cài đặt")
        print(f"  {C.R}0{C.X}  Thoát\n")
        ch = ask("Chọn:")
        if ch == "1":
            do_list()
        elif ch == "2":
            export_menu()
        elif ch == "3":
            do_import()
        elif ch == "4":
            settings_menu()
        elif ch in ("0", ""):
            print("Thoát.")
            break
        else:
            warn("Lựa chọn không hợp lệ.")


def main():
    args = sys.argv[1:]
    if not args:
        interactive_menu()
        return
    cmd = args[0].lower()
    if cmd in ("list", "l", "-l"):
        do_list()
    elif cmd in ("export", "e", "-e"):
        do_export()
    elif cmd in ("import", "i", "-i"):
        do_import()
    elif cmd in ("--no-scale", "-ns"):
        global AUTO_SCALE
        AUTO_SCALE = False
        print("  Auto-scale OFF")
        if len(args) > 1 and args[1].lower() in ("import", "i"):
            do_import()
    else:
        print("Usage: python main.py [list|export|import]")
        sys.exit(1)


if __name__ == "__main__":
    main()
