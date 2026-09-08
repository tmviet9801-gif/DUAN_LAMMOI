"""Khoi SAN SANG -> BAT DAU cua mot van.

Tach khoi matching.py: ~285 dong, chi phu thuoc mot Page va co `is_anchor`,
khong dung toi vong lap gom ban.
"""
import logging
import os
from pathlib import Path

from core.page_world import eval_page

log = logging.getLogger("auto_flow_controller")


async def check_and_click_ready_or_start(ctx, p, is_anchor=False, name="Profile"):
        """Kiểm tra và bấm nút [ SẴN SÀNG ] (cho nick phụ) hoặc [ BẮT ĐẦU ] (cho Anchor).
        Hỗ trợ 4 cơ chế:
        1. Cocos Scene & DOM Inspector trong JS: tìm btn_begin / Label SẴN SÀNG/BẮT ĐẦU và lấy tọa độ thực.
        2. OpenCV Multi-Scale Template Matching nếu có nút trên màn hình.
        3. Physical Mouse Click Playwright tại tọa độ phát hiện (hoặc center fallback).
        4. Bắn song song WebSocket packet tương ứng.
        """
        btn_type = "BẮT ĐẦU" if is_anchor else "SẴN SÀNG"

        # 0. ĐƯỜNG ƯU TIÊN: gọi thẳng API component của game.
        # Dò trên scene thật cho thấy HitClub có lộ phương thức, tên KHÔNG
        # bị obfuscate (chỉ tên lớp bị rút thành 'e'):
        #   TLDLScene/.../CardGameTableNoDealer -> sendReady()
        #   TLDLScene/.../TLMNScene            -> btn_begin (chủ bàn)
        # Gọi hàm thì chắc chắn hơn hẳn việc dò nhãn "SẴN SÀNG"/"BẮT ĐẦU"
        # rồi so ảnh OpenCV rồi click toạ độ: không phụ thuộc ngôn ngữ
        # hiển thị, không phụ thuộc độ phân giải, không click nhầm UI khác.
        # Nếu không tìm thấy thì rơi xuống đường cũ bên dưới.
        try:
            api_ok = await eval_page(p, """(wantStart) => {
                const scene = (typeof cc !== "undefined" && cc.director) ? cc.director.getScene() : null;
                if (!scene) return false;
                let done = false;
                function comps(node) {
                    try { return node.getComponents(cc.Component) || []; } catch (e) { return []; }
                }
                function walk(node, depth) {
                    if (!node || depth > 30 || done) return;
                    for (const c of comps(node)) {
                        if (!c) continue;
                        if (wantStart) {
                            // Chủ bàn: kích nút Bắt đầu qua chính component của game
                            if (c.btn_begin && c.btn_begin.node && c.btn_begin.node.activeInHierarchy) {
                                try {
                                    if (cc.Component && cc.Component.EventHandler && c.btn_begin.clickEvents) {
                                        cc.Component.EventHandler.emitEvents(c.btn_begin.clickEvents, c.btn_begin);
                                        done = true; return;
                                    }
                                } catch (_) {}
                            }
                        } else if (typeof c.sendReady === "function") {
                            try { c.sendReady(); done = true; return; } catch (_) {}
                        }
                    }
                    const ch = node.children || [];
                    for (let i = 0; i < ch.length && !done; i++) walk(ch[i], depth + 1);
                }
                walk(scene, 0);
                return done;
            }""", bool(is_anchor))
        except Exception:
            api_ok = False
        if api_ok:
            log.info("find-and-match: [%s] >>> Gọi thẳng API game cho '%s' (không cần click) <<<", name, btn_type)
            return True

        sw, sh = await ctx.screen_size(p)
        default_x = int(sw * 0.500)
        default_y = int(sh * 0.525)

        # 1. Quét qua JS Cocos Scene
        js_res = {}
        try:
            js_res = await eval_page(p, """(wantStart) => {
                try {
                    const canvas = document.querySelector("canvas");
                    const rect = canvas ? canvas.getBoundingClientRect() : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
                    let targetX = rect.left + rect.width * 0.500;
                    let targetY = rect.top + rect.height * 0.525;
                    let found = false;
                    let btnName = "";
                    let btnText = "";

                    if (typeof cc !== "undefined" && cc.director) {
                        const scene = cc.director.getScene();
                        if (scene) {
                            function searchNode(node, depth) {
                                if (!node || depth > 40 || found) return;
                                const comps = (typeof node.getComponents === "function") ? node.getComponents(cc.Component) : (node._components || []);
                                for (let i = 0; i < comps.length; i++) {
                                    const c = comps[i];
                                    if (!c) continue;

                                    // btn_begin chỉ thuộc quyền chủ bàn. Nick phụ không
                                    // được kích nó vì có thể là nút Start của Account 1.
                                    if (wantStart && c.btn_begin && c.btn_begin.node && c.btn_begin.node.active) {
                                        found = true;
                                        btnName = "btn_begin";
                                        if (typeof cc.Component !== "undefined" && cc.Component.EventHandler && c.btn_begin.clickEvents) {
                                            try { cc.Component.EventHandler.emitEvents(c.btn_begin.clickEvents, c.btn_begin); } catch (_) {}
                                        }
                                        try { c.btn_begin.node.emit(cc.Node.EventType.TOUCH_END); } catch (_) {}

                                        try {
                                            if (typeof c.btn_begin.node.getBoundingBoxToWorld === "function" && cc.view) {
                                                const b = c.btn_begin.node.getBoundingBoxToWorld();
                                                const vs = cc.view.getVisibleSize();
                                                if (b && vs && vs.width > 0 && vs.height > 0) {
                                                    targetX = rect.left + (b.x + b.width / 2) * (rect.width / vs.width);
                                                    targetY = rect.top + (vs.height - (b.y + b.height / 2)) * (rect.height / vs.height);
                                                }
                                            }
                                        } catch (_) {}
                                        return;
                                    }

                                    const labelStr = (c.string || c._string || (c.label && c.label.string) || "").toUpperCase();
                                    const labelMatchesRole = wantStart
                                        ? (labelStr.includes("BẮT ĐẦU") || labelStr.includes("BAT DAU"))
                                        : (labelStr.includes("SẴN SÀNG") || labelStr.includes("SAN SANG"));
                                    if (labelMatchesRole) {
                                        if (node.active) {
                                            found = true;
                                            btnText = labelStr;
                                            btnName = node.name || "label_btn";
                                            let parent = node;
                                            while (parent && !parent.getComponent(cc.Button) && parent.parent) parent = parent.parent;
                                            const btnComp = parent ? (parent.getComponent(cc.Button) || parent.getComponent("cc.Button")) : null;
                                            if (btnComp && btnComp.clickEvents) {
                                                try { cc.Component.EventHandler.emitEvents(btnComp.clickEvents, btnComp); } catch (_) {}
                                            }
                                            try { (parent || node).emit(cc.Node.EventType.TOUCH_END); } catch (_) {}
                                            return;
                                        }
                                    }
                                }
                                const children = node.children || [];
                                for (let j = 0; j < children.length; j++) {
                                    searchNode(children[j], depth + 1);
                                    if (found) return;
                                }
                            }
                            searchNode(scene, 0);
                        }
                    }

                    // Gọi DUY NHẤT helper đúng vai trò, không bắn Ready/Start
                    // lẫn nhau trên cả hai account.
                    if (wantStart && typeof window.__autotool_exec_start === "function") {
                        try { window.__autotool_exec_start(); } catch (_) {}
                    } else if (!wantStart && typeof window.__autotool_exec_ready === "function") {
                        try { window.__autotool_exec_ready(); } catch (_) {}
                    }

                    return {
                        found: found,
                        name: btnName,
                        text: btnText,
                        x: Math.round(targetX),
                        y: Math.round(targetY)
                    };
                } catch (e) {
                    return { error: String(e) };
                }
            }""", bool(is_anchor))
        except Exception:
            pass

        click_x = (js_res or {}).get("x") or default_x
        click_y = (js_res or {}).get("y") or default_y
        has_found = bool((js_res or {}).get("found"))

        # 2. Template Matching qua OpenCV nếu chưa tìm thấy qua Cocos
        if not has_found:
            try:
                import cv2
                import numpy as np
                tmpl_dir = Path(__file__).resolve().parent.parent / "data" / "templates"
                tmpl_file = tmpl_dir / "btn_ready.png"
                if os.path.exists(tmpl_file):
                    tmpl_img = cv2.imread(tmpl_file)
                    if tmpl_img is not None:
                        shot_bytes = await p.screenshot()
                        arr = np.frombuffer(shot_bytes, np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if frame is not None:
                            h_t, w_t = tmpl_img.shape[:2]
                            best_val = -1
                            best_pt = None
                            for sc in [0.5, 0.7, 0.85, 1.0, 1.15]:
                                rw, rh = int(w_t * sc), int(h_t * sc)
                                if rh < frame.shape[0] and rw < frame.shape[1]:
                                    r_tmpl = cv2.resize(tmpl_img, (rw, rh))
                                    res = cv2.matchTemplate(frame, r_tmpl, cv2.TM_CCOEFF_NORMED)
                                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                                    if max_val > best_val:
                                        best_val = max_val
                                        best_pt = (max_loc[0] + rw // 2, max_loc[1] + rh // 2)
                            if best_val >= 0.65 and best_pt:
                                click_x, click_y = best_pt
                                has_found = True
                                log.info("find-and-match: [%s] OpenCV phát hiện nút '%s' (độ tin cậy: %.2f) tại (%d, %d)", 
                                         name, btn_type, best_val, click_x, click_y)
            except Exception:
                pass

        # 3. Chỉ click khi Cocos/OpenCV xác định đúng nút. Không click tâm
        # màn hình khi không thấy nút vì dễ click vào UI bàn/cược khác.
        if has_found:
            try:
                await p.mouse.click(click_x, click_y)
                log.info("find-and-match: [%s] >>> Đã CLICK nút '%s' đã xác minh tại (%d, %d) <<<",
                         name, btn_type, click_x, click_y)
            except Exception:
                pass
        else:
            log.warning("find-and-match: [%s] Không thấy nút '%s'; chỉ dùng WS helper đúng vai trò, không click mù.", name, btn_type)

        return has_found
