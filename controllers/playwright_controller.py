import json
import random
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from .base_controller import BaseBrowserController



class PlaywrightController(BaseBrowserController):

    def __init__(self):
        super().__init__()
        with open('config.json', 'r', encoding='utf-8') as f:
            data = json.load(f)  
        self.browser_path = data["playwright"]["browser_path"]

    def launch_browser(self):
        try:
            p = sync_playwright().start()

            proxy_url = random.choice(self.proxy_pool) if self.proxy_pool else self.proxy
            self._activate_proxy_fingerprint(proxy_url)
            proxy_settings = self._build_browser_proxy_settings(proxy_url)
            if proxy_url:
                parsed = urlparse(proxy_url)
                print(f"[Proxy] 使用代理: {parsed.hostname}:{parsed.port}")
            launch_kwargs = {
                "headless": False,
                "args": self._build_launch_args(),
                "proxy": proxy_settings,
            }
            if self.browser_path:
                launch_kwargs["executable_path"] = self.browser_path

            if self.persistent_context:
                profile_dir = self._create_profile_dir()
                b = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    **launch_kwargs,
                    **self._build_context_kwargs()
                )
                self._configure_context(b)
                self._remember_context_profile(b, profile_dir)
            else:
                b = p.chromium.launch(**launch_kwargs)

            return p, b

        except Exception as e:
            print(f"启动浏览器失败: {e}")
            return False, False

    def get_thread_page(self):
        browser = self.get_thread_browser()
        if hasattr(browser, "new_context"):
            context = browser.new_context(**self._build_context_kwargs())
            self._configure_context(context)
        else:
            context = browser
        return context.new_page()
    
    def handle_captcha(self, page):

        page.wait_for_event("request", lambda req: req.url.startswith("blob:https://iframe.hsprotect.net/"), timeout=22000)
        page.wait_for_timeout(800)

        for _ in range(0, self.max_captcha_retries + 1):

            page.keyboard.press('Enter')
            page.wait_for_timeout(11500)
            page.keyboard.press('Enter')

            try:
                page.wait_for_event("request", lambda req: req.url.startswith("https://browser.events.data.microsoft.com"), timeout=8000)
                try:
                    page.wait_for_event("request", lambda req: req.url.startswith("https://collector-pxzc5j78di.hsprotect.net/assets/js/bundle"), timeout=1700) 
                    page.wait_for_timeout(2000)
                    continue

                except:
                    if self._is_blocked(page):
                        print("[Error: Rate limit] - 正常通过验证码，但当前IP注册频率过快。")
                        return False
                    break

            except:
                # raise TimeoutError
                page.wait_for_timeout(5000)
                page.keyboard.press('Enter')
                page.wait_for_event("request", lambda req: req.url.startswith("https://browser.events.data.microsoft.com"), timeout=10000)
                
                try:
                    page.wait_for_event("request", lambda req: req.url.startswith("https://collector-pxzc5j78di.hsprotect.net/assets/js/bundle"), timeout=4000)
                except:
                    break
                page.wait_for_timeout(500)
        else: 
            return False
        
        return True


    def clean_up(self, page=None, type="all_browser"):

        if type == "done_browser" and page:
            self._release_thread_browser(page)

        elif type == "all_browser":
            for p, b in self.active_resources:
                try:
                    b.close()
                except Exception: pass
                self._cleanup_context_profile(b)
                try:
                    p.stop()
                except Exception: pass

