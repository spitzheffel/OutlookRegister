import time
import json
import random
import threading
import os
import shutil
import tempfile
from urllib.parse import urlparse
from faker import Faker
from abc import ABC, abstractmethod
from utils import detect_proxy_geo

class BaseBrowserController(ABC):
    """
    所有浏览器通用的接口和共享逻辑
    """

    def __init__(self):
        with open('config.json', 'r', encoding='utf-8') as f:
            data = json.load(f) 
        self.wait_time = data['bot_protection_wait'] * 1000
        self.max_captcha_retries = data['max_captcha_retries']
        self.enable_oauth2 = data["oauth2"]['enable_oauth2']
        proxy_cfg = data['proxy']
        if isinstance(proxy_cfg, list):
            self.proxy_pool = proxy_cfg
            self.proxy = None  # 每次 launch_browser 时从 pool 选取
        else:
            self.proxy_pool = [proxy_cfg] if proxy_cfg else []
            self.proxy = proxy_cfg

        capsolver_cfg = data.get('capsolver', {})
        self.capsolver_enabled = capsolver_cfg.get('enabled', False)
        self.capsolver_api_key = capsolver_cfg.get('api_key', '')

        yescaptcha_cfg = data.get('yescaptcha', {})
        self.yescaptcha_enabled = yescaptcha_cfg.get('enabled', False)
        self.yescaptcha_api_key = yescaptcha_cfg.get('api_key', '')

        self.thread_local = threading.local()
        self.cleanup_lock = threading.Lock()
        self.active_resources = []  # 记录资源以便关闭
        self.context_profile_dirs = {}
        self.configured_contexts = set()

        # 检测代理出口 IP 地理位置，用于浏览器指纹一致性
        sample_proxy = self.proxy_pool[0] if self.proxy_pool else self.proxy
        self.default_geo_info = detect_proxy_geo(sample_proxy)

        fingerprint_cfg = data.get("fingerprint", {})
        self.persistent_context = fingerprint_cfg.get("persistent_context", True)
        self.cleanup_profile = fingerprint_cfg.get("cleanup_profile", True)
        self.disable_webrtc = fingerprint_cfg.get("disable_webrtc", True)
        self.grant_geolocation = fingerprint_cfg.get("grant_geolocation", False)
        self.force_remote_dns = fingerprint_cfg.get("force_remote_dns", True)
        self.host_resolver_excludes = fingerprint_cfg.get(
            "host_resolver_excludes",
            ["localhost", "127.0.0.1", "::1"]
        )
        self.profile_root = fingerprint_cfg.get("profile_root", os.path.join("Results", "browser_profiles"))
        viewport_cfg = fingerprint_cfg.get("viewport", {})
        screen_cfg = fingerprint_cfg.get("screen", {})
        self.viewport = {
            "width": int(viewport_cfg.get("width", 1280)),
            "height": int(viewport_cfg.get("height", 720)),
        }
        self.screen = {
            "width": int(screen_cfg.get("width", self.viewport["width"])),
            "height": int(screen_cfg.get("height", self.viewport["height"])),
        }
        self.default_fingerprint_state = self._build_fingerprint_state(self.default_geo_info)
        self.geo_info = self.default_fingerprint_state["geo_info"]
        self.language_list = self.default_fingerprint_state["language_list"]
        self.accept_language = self.default_fingerprint_state["accept_language"]

    def _is_blocked(self, page):
        """检测页面是否显示 IP 被封/异常活动/维护中等拦截信息"""
        if page.locator('#error_desc, [data-testid="errorDescription"]').count() > 0:
            return True

        try:
            title = page.title()
            blocked_titles = (
                "已封鎖建立帳戶",
                "已封锁建立帐户",
                "已封锁创建帐户",
                "Blocked from creating an account",
            )
            if any(marker in title for marker in blocked_titles):
                return True
        except:
            pass

        try:
            body_text = page.locator("body").inner_text(timeout=1000)
            blocked_markers = (
                "一些异常活动",
                "一些異常活動",
                "已封鎖建立帳戶",
                "已封锁建立帐户",
                "已封锁创建帐户",
                "此站点正在维护",
                "此網站正在維護",
                "Blocked from creating an account",
                "temporarily unavailable",
            )
            if any(marker in body_text for marker in blocked_markers):
                return True
        except:
            pass

        return False

    def _build_language_list(self, locale):
        values = [locale]
        if locale == "zh-HK":
            values.extend(["zh-TW", "zh", "en-US", "en"])
        elif locale == "zh-TW":
            values.extend(["zh-HK", "zh", "en-US", "en"])
        elif locale == "zh-CN":
            values.extend(["zh", "en-US", "en"])
        else:
            base_lang = locale.split("-")[0]
            values.extend([base_lang, "en-US", "en"])

        seen = set()
        result = []
        for item in values:
            if item and item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _build_accept_language(self, languages):
        parts = []
        for idx, language in enumerate(languages):
            if idx == 0:
                parts.append(language)
            else:
                quality = max(0.1, 1 - idx * 0.1)
                parts.append(f"{language};q={quality:.1f}")
        return ",".join(parts)

    def _build_fingerprint_state(self, geo_info):
        locale = geo_info["locale"] if geo_info else "en-US"
        language_list = self._build_language_list(locale)
        return {
            "geo_info": geo_info,
            "language_list": language_list,
            "accept_language": self._build_accept_language(language_list),
        }

    def _get_fingerprint_state(self):
        return getattr(self.thread_local, "fingerprint_state", None) or self.default_fingerprint_state

    def _activate_proxy_fingerprint(self, proxy_url=None):
        geo_info = detect_proxy_geo(proxy_url)
        if not geo_info:
            geo_info = self.default_fingerprint_state["geo_info"]

        state = self._build_fingerprint_state(geo_info)
        self.thread_local.proxy_url = proxy_url
        self.thread_local.fingerprint_state = state
        return state

    def _build_browser_proxy_settings(self, proxy_url):
        if not proxy_url:
            self.thread_local.proxy_server_host = None
            self.thread_local.proxy_server_scheme = None
            return None

        parsed = urlparse(proxy_url)
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"代理格式错误: {proxy_url}")

        raw_scheme = (parsed.scheme or "").lower()
        browser_scheme = "socks5" if raw_scheme == "socks5h" else raw_scheme
        proxy_settings = {
            "server": f"{browser_scheme}://{parsed.hostname}:{parsed.port}",
            "bypass": "localhost",
        }
        if parsed.username:
            proxy_settings["username"] = parsed.username
        if parsed.password:
            proxy_settings["password"] = parsed.password

        self.thread_local.proxy_server_host = parsed.hostname
        self.thread_local.proxy_server_scheme = raw_scheme
        return proxy_settings

    def _build_host_resolver_rules(self):
        if not self.force_remote_dns:
            return None

        proxy_url = getattr(self.thread_local, "proxy_url", None)
        proxy_host = getattr(self.thread_local, "proxy_server_host", None)
        if not proxy_url or not proxy_host:
            return None

        excluded_hosts = []
        for host in [*self.host_resolver_excludes, proxy_host]:
            if host and host not in excluded_hosts:
                excluded_hosts.append(host)

        rules = ["MAP * ~NOTFOUND"]
        rules.extend(f"EXCLUDE {host}" for host in excluded_hosts)
        return " , ".join(rules)

    def _build_context_kwargs(self):
        state = self._get_fingerprint_state()
        geo_info = state["geo_info"]
        ctx_kwargs = {
            "viewport": self.viewport,
            "screen": self.screen,
            "locale": geo_info["locale"] if geo_info else "en-US",
        }
        if geo_info:
            ctx_kwargs["timezone_id"] = geo_info["timezone"]
            ctx_kwargs["geolocation"] = {
                "latitude": geo_info["latitude"],
                "longitude": geo_info["longitude"],
            }
        return ctx_kwargs

    def _build_launch_args(self):
        state = self._get_fingerprint_state()
        geo_info = state["geo_info"]
        lang = geo_info["lang"] if geo_info else "en-US"
        args = [f"--lang={lang}"]
        if self.disable_webrtc:
            args.extend([
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--enforce-webrtc-ip-permission-check",
            ])
        host_resolver_rules = self._build_host_resolver_rules()
        if host_resolver_rules:
            args.append(f"--host-resolver-rules={host_resolver_rules}")
        return args

    def _create_profile_dir(self):
        if not self.persistent_context:
            return None
        os.makedirs(self.profile_root, exist_ok=True)
        return tempfile.mkdtemp(prefix="profile-", dir=self.profile_root)

    def _remember_context_profile(self, context, profile_dir):
        if profile_dir:
            self.context_profile_dirs[id(context)] = profile_dir

    def _cleanup_context_profile(self, context):
        self.configured_contexts.discard(id(context))
        profile_dir = self.context_profile_dirs.pop(id(context), None)
        if profile_dir and self.cleanup_profile:
            shutil.rmtree(profile_dir, ignore_errors=True)

    def _clear_thread_runtime(self):
        for attr in (
            "browser",
            "playwright",
            "fingerprint_state",
            "proxy_url",
            "proxy_server_host",
            "proxy_server_scheme",
        ):
            if hasattr(self.thread_local, attr):
                delattr(self.thread_local, attr)

    def _release_thread_browser(self, page=None):
        browser = getattr(self.thread_local, "browser", None)
        playwright = getattr(self.thread_local, "playwright", None)
        context = page.context if page else None

        if context and context is not browser:
            try:
                context.close()
            except Exception:
                pass
            self._cleanup_context_profile(context)

        if browser:
            try:
                browser.close()
            except Exception:
                pass
            self._cleanup_context_profile(browser)

        if playwright:
            try:
                playwright.stop()
            except Exception:
                pass

        if browser:
            with self.cleanup_lock:
                self.active_resources = [
                    (p, b) for p, b in self.active_resources
                    if b is not browser
                ]

        self._clear_thread_runtime()

    def _configure_context(self, context):
        context_id = id(context)
        if context_id in self.configured_contexts:
            return

        state = self._get_fingerprint_state()
        geo_info = state["geo_info"]
        language_list = state["language_list"]
        accept_language = state["accept_language"]

        context.set_extra_http_headers({
            "Accept-Language": accept_language,
        })

        languages_json = json.dumps(language_list, ensure_ascii=False)
        primary_language = json.dumps(language_list[0], ensure_ascii=False)
        context.add_init_script(f"""
            (() => {{
                const languages = {languages_json};
                const primaryLanguage = {primary_language};
                const define = (proto, key, getter) => {{
                    try {{
                        Object.defineProperty(proto, key, {{
                            get: getter,
                            configurable: true
                        }});
                    }} catch (e) {{
                    }}
                }};

                define(Navigator.prototype, 'language', () => primaryLanguage);
                define(Navigator.prototype, 'languages', () => languages.slice());
            }})();
        """)

        if self.grant_geolocation and geo_info:
            context.grant_permissions(["geolocation"])

        self.configured_contexts.add(context_id)

    def _select_fluent_dropdown(self, page, trigger_selector, option_index):
        """
        选择 Fluent UI combobox 中的第 N 个选项。
        微软注册页会把多个隐藏 dropdown 同时挂在 DOM 上，所以这里显式取可见 listbox。
        """
        trigger = page.locator(trigger_selector).first
        trigger.wait_for(state="attached", timeout=10000)

        try:
            tag_name = trigger.evaluate("el => el.tagName.toLowerCase()")
        except:
            tag_name = ""

        if tag_name == "select":
            try:
                trigger.select_option(value=str(option_index), timeout=5000)
                return
            except:
                trigger.select_option(index=option_index - 1, timeout=5000)
                return

        visible_listbox = page.locator('[role="listbox"]:visible').last

        def try_click_option():
            visible_listbox.wait_for(state="visible", timeout=1200)
            visible_listbox.locator('[role="option"]').nth(option_index - 1).click(timeout=5000)

        try:
            trigger.click(timeout=5000)
            try_click_option()
            return
        except:
            pass

        try:
            trigger.focus(timeout=3000)
        except:
            pass

        for open_key in ("Alt+ArrowDown", "Space", "Enter"):
            try:
                page.keyboard.press(open_key)
                page.wait_for_timeout(150)
                try:
                    try_click_option()
                    return
                except:
                    pass
            except:
                continue

        # 最后的兜底：直接通过键盘移动到目标选项并确认。
        try:
            trigger.focus(timeout=3000)
        except:
            pass

        try:
            page.keyboard.press("Home")
            page.wait_for_timeout(100)
        except:
            pass

        for _ in range(max(option_index - 1, 0)):
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(40)
        page.keyboard.press("Enter")
        page.wait_for_timeout(250)

        current_text = ""
        try:
            current_text = (trigger.text_content(timeout=1000) or "").strip()
        except:
            pass

        if not current_text:
            raise TimeoutError(f"下拉框未成功选择选项: {trigger_selector} -> {option_index}")


    @abstractmethod
    def launch_browser(self):
        """
        获取浏览器实例,返回playwright_instance, browser_instance
        """
        pass

    @abstractmethod
    def handle_captcha(self, page):
        """
        验证码处理流程（按压型）
        """
        pass

    def handle_image_captcha(self, page):
        """
        图片验证码处理流程（YesCaptcha FunCaptchaClassification）
        子类可覆盖
        """
        return False

    @abstractmethod 
    def clean_up(self, page=None, type = "all_browser"):
        """
        清理自己创建的内容
        一个是单进程结束后关闭进程，另一个是程序结束后清除所有内容
        """
        pass

    @abstractmethod
    def get_thread_page(self):
        """
        返回页面
        """


    def get_thread_browser(self):
        """
        通用逻辑:获取不同进程的浏览器
        """

        if not hasattr(self.thread_local,"browser"):

            p, b  = self.launch_browser()
            if not p:
                return False

            self.thread_local.playwright = p
            self.thread_local.browser = b

            with self.cleanup_lock:
                self.active_resources.append((p, b))

        return self.thread_local.browser

    def outlook_register(self, page, email, password, firstname='', lastname=''):

        """
        通用逻辑:注册邮箱
        """
        if not firstname:
            from faker import Faker
            fake = Faker()
            firstname = fake.first_name()
        if not lastname:
            from faker import Faker
            fake = Faker()
            lastname = fake.last_name()
        year = str(random.randint(1960, 2005))
        month = str(random.randint(1, 12))
        day = str(random.randint(1, 28))

        try:

            page.goto("https://outlook.live.com/mail/0/?prompt=create_account", timeout=60000, wait_until="domcontentloaded")
            page.locator('[data-testid="primaryButton"]').first.wait_for(timeout=60000)
            start_time = time.time()
            page.wait_for_timeout(0.1 * self.wait_time)
            page.locator('[data-testid="primaryButton"]').first.click(timeout=30000)

        except: 

            print("[Error: IP] - IP质量不佳，无法进入注册界面。 ")
            return False
        
        try:

            page.locator('input[name="email"]').first.type(email,delay=0.006 * self.wait_time,timeout=10000)
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('[type="password"]').type(password,delay=0.004 * self.wait_time, timeout=10000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            
            page.wait_for_timeout(0.03 * self.wait_time)
            page.locator('[name="BirthYear"]').fill(year,timeout=10000)

            # 月份和日期现在是 combobox（Fluent UI Dropdown），不再是原生 <select>
            self._select_fluent_dropdown(page, '#BirthMonthDropdown, [name="BirthMonth"]', int(month))
            page.wait_for_timeout(0.04 * self.wait_time)
            self._select_fluent_dropdown(page, '#BirthDayDropdown, [name="BirthDay"]', int(day))

            page.locator('[data-testid="primaryButton"]').click(timeout=5000)

            page.locator('#lastNameInput').type(lastname,delay=0.002 * self.wait_time,timeout=10000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('#firstNameInput').fill(firstname,timeout=10000)

            if time.time() - start_time < self.wait_time / 1000:
                page.wait_for_timeout(self.wait_time - (time.time() - start_time) * 1000)
            
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            page.locator('span > [href="https://go.microsoft.com/fwlink/?LinkID=521839"]').wait_for(state='detached',timeout=22000)

            page.wait_for_timeout(400)

            if self._is_blocked(page):
                print("[Error: IP or browser] - 当前IP注册频率过快。检查IP与是否为指纹浏览器并关闭了无头模式。")
                return False

            captcha_result = self.handle_captcha(page)

            if not captcha_result:
                raise TimeoutError

        except Exception as e:
            print(e)
            print(f"[Error: IP] - 加载超时或因触发机器人检测导致按压次数达到最大仍未通过。")
            return False 
        
        filename = 'Results\\logged_email.txt' if self.enable_oauth2 else 'Results\\unlogged_email.txt'
        with open(filename, 'a', encoding='utf-8') as f:
            f.write(f"{email}@outlook.com: {password}\n")
        print(f'[Success: Email Registration] - {email}@outlook.com: {password}')

        if not self.enable_oauth2:
            return True
        
        try:
            page.locator('[data-testid="secondaryButton"], [data-testid="cancelButton"], #declineButton').first.click(timeout=20000)

        except:
            # 截图诊断：看看注册后页面到底是什么
            try:
                page.screenshot(path='Results\\debug_after_captcha.png')
                print(f"[Debug] 截图已保存到 Results/debug_after_captcha.png")
                print(f"[Debug] 当前URL: {page.url}")
                print(f"[Debug] 页面标题: {page.title()}")
            except:
                pass

            # 尝试直接等待邮箱收件箱（跳过取消步骤）
            try:
                page.locator('[data-testid="ComposeMail"], [data-testid="newMessageButton"], button[class*="compose"]').first.wait_for(timeout=20000)
                print("[Info] 跳过取消步骤，直接进入邮箱。")
                return True
            except:
                pass

            print(f"[Error: Timeout] - 无法找到按钮。")
            return False   

        try:

            try:
                # passkey 弹窗，不一定出现
                page.locator('[data-testid="passkey-error"], [data-testid="errorDescription"]').first.wait_for(timeout=25000)
                page.locator('[data-testid="secondaryButton"], [data-testid="cancelButton"], #declineButton').first.click(timeout=7000)

            except:
                pass

            page.locator('[data-testid="ComposeMail"], [data-testid="newMessageButton"], button[class*="compose"]').first.wait_for(timeout=26000)
            return True

        except:

            print(f'[Error: Timeout] - 邮箱未初始化，无法正常收件。')
            return False
