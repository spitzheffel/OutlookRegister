import time
import json
import random
import threading
from faker import Faker
from abc import ABC, abstractmethod

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
            page.get_by_text('同意并继续').wait_for(timeout=60000)
            start_time = time.time()
            page.wait_for_timeout(0.1 * self.wait_time)
            page.get_by_text('同意并继续').click(timeout=30000)

        except: 

            print("[Error: IP] - IP质量不佳，无法进入注册界面。 ")
            return False
        
        try:

            page.locator('[aria-label="新建电子邮件"]').type(email,delay=0.006 * self.wait_time,timeout=10000)
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('[type="password"]').type(password,delay=0.004 * self.wait_time, timeout=10000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            
            page.wait_for_timeout(0.03 * self.wait_time)
            page.locator('[name="BirthYear"]').fill(year,timeout=10000)

            try:

                page.wait_for_timeout(0.02 * self.wait_time)
                page.locator('[name="BirthMonth"]').select_option(value=month,timeout=1000)
                page.wait_for_timeout(0.05 * self.wait_time)
                page.locator('[name="BirthDay"]').select_option(value=day)
            
            except:

                page.locator('[name="BirthMonth"]').click()
                page.wait_for_timeout(0.02 * self.wait_time)
                page.locator(f'[role="option"]:text-is("{month}月")').click()
                page.wait_for_timeout(0.04 * self.wait_time)
                page.locator('[name="BirthDay"]').click()
                page.wait_for_timeout(0.03 * self.wait_time)
                page.locator(f'[role="option"]:text-is("{day}日")').click()
                page.locator('[data-testid="primaryButton"]').click(timeout=5000)

            page.locator('#lastNameInput').type(lastname,delay=0.002 * self.wait_time,timeout=10000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('#firstNameInput').fill(firstname,timeout=10000)

            if time.time() - start_time < self.wait_time / 1000:
                page.wait_for_timeout(self.wait_time - (time.time() - start_time) * 1000)
            
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            page.locator('span > [href="https://go.microsoft.com/fwlink/?LinkID=521839"]').wait_for(state='detached',timeout=22000)

            page.wait_for_timeout(400)

            if page.get_by_text('一些异常活动').count() or page.get_by_text('此站点正在维护，暂时无法使用，请稍后重试。').count() > 0:
                print("[Error: IP or browser] - 当前IP注册频率过快。检查IP与是否为指纹浏览器并关闭了无头模式。")
                return False

            if page.locator('iframe#enforcementFrame').count() > 0:
                if self.yescaptcha_enabled and self.yescaptcha_api_key:
                    print("[Info] 检测到图片验证码，使用 YesCaptcha 识别...")
                    captcha_result = self.handle_image_captcha(page)
                else:
                    print("[Error: FunCaptcha] - 验证码类型错误，非按压验证码。启用 yescaptcha 可自动识别。")
                    return False
            else:
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
            page.get_by_text('取消').click(timeout=20000)

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
                page.locator('[aria-label="新邮件"]').wait_for(timeout=20000)
                print("[Info] 跳过取消步骤，直接进入邮箱。")
                return True
            except:
                pass

            print(f"[Error: Timeout] - 无法找到按钮。")
            return False   

        try:

            try:
                # 这个不确定是不是一定出现
                page.get_by_text('无法创建通行密钥').wait_for(timeout=25000)
                page.get_by_text('取消').click(timeout=7000)

            except:
                pass

            page.locator('[aria-label="新邮件"]').wait_for(timeout=26000)
            return True

        except:

            print(f'[Error: Timeout] - 邮箱未初始化，无法正常收件。')
            return False