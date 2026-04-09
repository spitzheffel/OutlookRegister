import random
import base64
from urllib.parse import urlparse, parse_qs
from patchright.sync_api import sync_playwright
from .base_controller import BaseBrowserController
from capsolver import solve_funcaptcha
from yescaptcha import classify_funcaptcha


class PatchrightController(BaseBrowserController):

    def launch_browser(self):
        try:
            p = sync_playwright().start() 

            proxy_settings = None
            proxy_url = random.choice(self.proxy_pool) if self.proxy_pool else self.proxy
            if proxy_url:
                parsed = urlparse(proxy_url)
                proxy_settings = {
                    "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                    "bypass": "localhost",
                }
                if parsed.username:
                    proxy_settings["username"] = parsed.username
                if parsed.password:
                    proxy_settings["password"] = parsed.password
                print(f"[Proxy] 使用代理: {parsed.hostname}:{parsed.port}")

            b = p.chromium.launch(
                headless=False,            
                args=['--lang=zh-CN'],
                proxy=proxy_settings
            )

            return p, b

        except Exception as e:
            print(f"启动浏览器失败: {e}")
            return False, False
        
    def handle_captcha(self, page):

        if self.capsolver_enabled and self.capsolver_api_key:
            return self._handle_captcha_capsolver(page)
        return self._handle_captcha_click(page)

    def _extract_arkose_public_key(self, page):
        """从 enforcement iframe 的 URL 中提取 Arkose Labs 公钥"""
        try:
            enforcement_frame = page.frame_locator('iframe[title="验证质询"]')
            inner_frame = enforcement_frame.frame_locator('iframe[style*="display: block"]')
            # 尝试从 iframe src 获取 public key
            for frame in page.frames:
                if 'arkoselabs.com' in frame.url or 'funcaptcha.com' in frame.url:
                    parsed = urlparse(frame.url)
                    qs = parse_qs(parsed.query)
                    if 'pk' in qs:
                        return qs['pk'][0]
            # fallback: 微软注册页面的已知公钥
            return "B7D8911C-5CC8-A9A3-35B0-554ACEE604DA"
        except:
            return "B7D8911C-5CC8-A9A3-35B0-554ACEE604DA"

    def _extract_data_blob(self, page):
        """尝试从页面提取 data blob"""
        try:
            for frame in page.frames:
                if 'arkoselabs.com' in frame.url or 'funcaptcha.com' in frame.url:
                    parsed = urlparse(frame.url)
                    qs = parse_qs(parsed.query)
                    if 'data[blob]' in qs:
                        return qs['data[blob]'][0]
        except:
            pass
        return None

    def _handle_captcha_capsolver(self, page):
        """使用 CapSolver API 求解 FunCaptcha"""
        print("[CapSolver] 正在提取验证码参数...")
        page.wait_for_timeout(1000)

        public_key = self._extract_arkose_public_key(page)
        data_blob = self._extract_data_blob(page)

        print(f"[CapSolver] 公钥: {public_key}")
        token = solve_funcaptcha(
            api_key=self.capsolver_api_key,
            website_url="https://signup.live.com",
            website_public_key=public_key,
            subdomain="https://client-api.arkoselabs.com",
            data_blob=data_blob
        )

        if not token:
            print("[CapSolver] 求解失败，回退到点击方式")
            return self._handle_captcha_click(page)

        # 注入 token 到 Arkose enforcement
        try:
            injected = False
            for frame in page.frames:
                if 'arkoselabs.com' in frame.url or 'funcaptcha.com' in frame.url:
                    frame.evaluate(f"""
                        (function() {{
                            var token = "{token}";
                            // 尝试通过 parent 回调
                            if (window.parent && window.parent.ae) {{
                                window.parent.ae.setToken(token);
                            }}
                            // 尝试通过 postMessage
                            window.parent.postMessage(JSON.stringify({{
                                eventId: "challenge-complete",
                                payload: {{ sessionToken: token }}
                            }}), "*");
                            // 设置 fc-token
                            var fcInput = document.querySelector('input[name="fc-token"]');
                            if (fcInput) {{ fcInput.value = token; }}
                            // 尝试调用全局回调
                            if (typeof window.verifyCallback === 'function') {{ window.verifyCallback(token); }}
                        }})();
                    """)
                    injected = True
                    break

            if not injected:
                # 尝试在主页面设置
                page.evaluate(f"""
                    (function() {{
                        var token = "{token}";
                        var fcInput = document.querySelector('input[name="fc-token"]');
                        if (fcInput) {{ fcInput.value = token; }}
                        if (typeof window.fc_callback === 'function') {{ window.fc_callback(token); }}
                    }})();
                """)

            # 等待验证结果
            page.wait_for_timeout(5000)

            if page.get_by_text('一些异常活动').count() or page.get_by_text('此站点正在维护，暂时无法使用，请稍后重试。').count() > 0:
                print("[Error: Rate limit] - CapSolver 通过验证码，但 IP 频率过快。")
                return False

            if page.get_by_text('取消').count() > 0:
                return True

            # 检查验证码是否还在
            try:
                frame1 = page.frame_locator('iframe[title="验证质询"]')
                frame2 = frame1.frame_locator('iframe[style*="display: block"]')
                if frame2.locator('[aria-label="可访问性挑战"]').count() > 0:
                    print("[CapSolver] Token 注入后验证码仍在，回退到点击方式")
                    return self._handle_captcha_click(page)
            except:
                pass

            return True

        except Exception as e:
            print(f"[CapSolver] Token 注入失败: {e}，回退到点击方式")
            return self._handle_captcha_click(page)

    def _handle_captcha_click(self, page):
        """原始的按钮点击方式处理验证码"""
        frame1 = page.frame_locator('iframe[title="验证质询"]')
        frame2 = frame1.frame_locator('iframe[style*="display: block"]')


        for _ in range(0, self.max_captcha_retries + 1):

            page.wait_for_timeout(200)
            loc = frame2.locator('[aria-label="可访问性挑战"]')
            box = loc.bounding_box()
            x = box['x'] + box['width'] / 2 + random.randint(-10, 10)
            y = box['y'] + box['height'] / 2 + random.randint(-10, 10)
            page.mouse.click(x, y)

            loc2 = frame2.locator('[aria-label="再次按下"]')
            box2 = loc2.bounding_box()
            x = box2['x'] + box2['width'] / 2 + random.randint(-20, 20)
            y = box2['y'] + box2['height'] / 2 + random.randint(-13, 13)
            page.mouse.click(x, y)

            try:

                page.locator('.draw').wait_for(state="detached")
                try:

                    # 简单的认为加载8秒后成功，暂不考虑请求.
                    page.locator('[role="status"][aria-label="正在加载..."]').wait_for(timeout=5000)
                    page.wait_for_timeout(8000)
                    if page.get_by_text('一些异常活动').count() or page.get_by_text('此站点正在维护，暂时无法使用，请稍后重试。').count() > 0:
                        print("[Error: Rate limit] - 正常通过验证码，但当前IP注册频率过快。")
                        return False
                    elif frame2.locator('[aria-label="可访问性挑战"]').count() > 0:
                        continue
                    break

                except:

                    if page.get_by_text('取消').count() > 0:
                        break
                    frame1.get_by_text("请再试一次").wait_for(timeout=15000)
                    continue

            except:
                if page.get_by_text('取消').count() > 0:
                     break
                return False
        else: 
            return False

        return True

    def handle_image_captcha(self, page):
        """使用 YesCaptcha FunCaptchaClassification 处理图片型验证码"""
        max_rounds = 5  # 最多尝试轮数（每轮一道题）

        try:
            page.wait_for_timeout(2000)
            enforcement = page.frame_locator('iframe#enforcementFrame')

            # 找到 arkoselabs 的 challenge iframe
            challenge_frame = None
            for frame in page.frames:
                if 'arkoselabs.com' in frame.url or 'funcaptcha.com' in frame.url:
                    challenge_frame = frame
                    break

            if not challenge_frame:
                print("[YesCaptcha] 未找到验证码 iframe")
                return False

            for round_idx in range(max_rounds):
                page.wait_for_timeout(1500)

                # 提取问题文本
                question = self._extract_funcaptcha_question(challenge_frame)
                if not question:
                    print(f"[YesCaptcha] 第{round_idx+1}轮：未找到问题文本")
                    return False
                print(f"[YesCaptcha] 第{round_idx+1}轮问题: {question}")

                # 截取验证码图片区域
                image_b64 = self._capture_funcaptcha_image(challenge_frame, page)
                if not image_b64:
                    print(f"[YesCaptcha] 第{round_idx+1}轮：未能截取验证码图片")
                    return False

                # 调用 YesCaptcha 识别
                result = classify_funcaptcha(self.yescaptcha_api_key, image_b64, question)
                if not result or "objects" not in result:
                    print(f"[YesCaptcha] 第{round_idx+1}轮：识别失败")
                    return False

                target_index = result["objects"][0]
                print(f"[YesCaptcha] 点击位置: {target_index}")

                # 点击对应位置
                self._click_funcaptcha_option(challenge_frame, page, target_index)

                page.wait_for_timeout(3000)

                # 检查是否通过
                if page.get_by_text('一些异常活动').count() or page.get_by_text('此站点正在维护，暂时无法使用，请稍后重试。').count() > 0:
                    print("[Error: Rate limit] - 通过验证码，但当前IP注册频率过快。")
                    return False

                if page.get_by_text('取消').count() > 0:
                    print(f"[YesCaptcha] 验证码已通过（{round_idx+1}轮）")
                    return True

                # 检查验证码是否仍然存在（可能需要多轮）
                if page.locator('iframe#enforcementFrame').count() == 0:
                    print(f"[YesCaptcha] 验证码已通过（{round_idx+1}轮）")
                    return True

            print(f"[YesCaptcha] 达到最大轮数 {max_rounds}，仍未通过")
            return False

        except Exception as e:
            print(f"[YesCaptcha] 图片验证码处理异常: {e}")
            return False

    def _extract_funcaptcha_question(self, challenge_frame):
        """从 FunCaptcha challenge frame 提取问题文本"""
        selectors = [
            'h2',
            '[class*="title"]',
            '[class*="question"]',
            '[class*="instruction"]',
            '[role="heading"]',
        ]
        for sel in selectors:
            try:
                el = challenge_frame.locator(sel).first
                if el.count() > 0:
                    text = el.text_content(timeout=2000)
                    if text and len(text.strip()) > 3:
                        return text.strip()
            except:
                continue
        return None

    def _capture_funcaptcha_image(self, challenge_frame, page):
        """截取 FunCaptcha 的图片区域并转为 base64"""
        # 尝试从 canvas 获取
        try:
            canvas = challenge_frame.locator('canvas').first
            if canvas.count() > 0:
                b64 = challenge_frame.evaluate("""() => {
                    const canvas = document.querySelector('canvas');
                    if (canvas) return canvas.toDataURL('image/png');
                    return null;
                }""")
                if b64:
                    return b64
        except:
            pass

        # 尝试截取图片区域元素
        image_selectors = [
            '[class*="game-image"]',
            '[class*="challenge-image"]',
            'img[class*="challenge"]',
            '.fc-image-grid',
            '[class*="image-container"]',
        ]
        for sel in image_selectors:
            try:
                el = challenge_frame.locator(sel).first
                if el.count() > 0:
                    screenshot = el.screenshot(timeout=5000)
                    return base64.b64encode(screenshot).decode('utf-8')
            except:
                continue

        # 最后兜底：截取整个 challenge frame 区域
        try:
            for sel in ['[class*="challenge"]', '[class*="game"]', 'body']:
                el = challenge_frame.locator(sel).first
                if el.count() > 0:
                    screenshot = el.screenshot(timeout=5000)
                    return base64.b64encode(screenshot).decode('utf-8')
        except:
            pass

        return None

    def _click_funcaptcha_option(self, challenge_frame, page, index):
        """点击 FunCaptcha 六宫格中的指定位置（从0开始）"""
        # 尝试直接点击对应的图片/按钮元素
        option_selectors = [
            f'[class*="option"]:nth-child({index + 1})',
            f'[class*="tile"]:nth-child({index + 1})',
            f'li:nth-child({index + 1})',
            f'[role="button"]:nth-child({index + 1})',
        ]
        for sel in option_selectors:
            try:
                el = challenge_frame.locator(sel).first
                if el.count() > 0:
                    el.click(timeout=3000)
                    return
            except:
                continue

        # 如果找不到单独的元素，根据六宫格布局坐标点击
        # 标准六宫格：2行3列，根据 index 计算行列
        try:
            container_selectors = [
                '[class*="game-image"]',
                '[class*="challenge-image"]',
                'canvas',
                '[class*="image-container"]',
                '[class*="challenge"]',
            ]
            for sel in container_selectors:
                el = challenge_frame.locator(sel).first
                if el.count() > 0:
                    box = el.bounding_box()
                    if box:
                        col = index % 3
                        row = index // 3
                        cell_w = box['width'] / 3
                        cell_h = box['height'] / 2
                        x = box['x'] + cell_w * col + cell_w / 2
                        y = box['y'] + cell_h * row + cell_h / 2
                        page.mouse.click(x + random.randint(-5, 5), y + random.randint(-5, 5))
                        return
        except:
            pass

    def get_thread_page(self):
        browser = self.get_thread_browser()
        context = browser.new_context()
        return context.new_page()

    def clean_up(self, page=None, type="all_browser"):
        if type == "done_browser" and page:
            context = page.context
            context.close()

        elif type == "all_browser":
            for p, b in self.active_resources:
                try:
                    b.close()
                except Exception: pass
                try:
                    p.stop()
                except Exception: pass

    