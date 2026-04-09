import json
import base64
import random
import string
import winreg
import hashlib
import secrets
import requests
from datetime import datetime
from urllib.parse import quote, parse_qs, urlsplit

def get_proxy():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
            if proxy_enable and proxy_server:
                return {"http": f"http://{proxy_server}", "https": f"http://{proxy_server}"}
    except WindowsError:
        pass
    return {"http": None, "https": None}

def generate_code_verifier(length=128):
    alphabet = string.ascii_letters + string.digits + '-._~'
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_code_challenge(code_verifier):
    sha256_hash = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(sha256_hash).decode().rstrip('=')

def handle_oauth2_form(page,email):
    try:
        # 等待登录页面加载完成
        try:
            page.locator('#loginHeader, #tilesHolder, [name="loginfmt"]').first.wait_for(timeout=15000)
        except:
            print("[OAuth2] 登录页面未加载")
            page.screenshot(path='Results\\debug_oauth2.png')
            return

        page.wait_for_timeout(1000)

        # 优先：点击底部已登录的账号磁贴
        try:
            tile = page.locator(f'[data-test-id="{email}@outlook.com"]')
            if tile.count() > 0:
                print(f"[OAuth2] 点击已登录账号磁贴")
                tile.click(timeout=5000)
            else:
                # 尝试包含邮箱地址的可点击元素
                tile_alt = page.locator(f'div:has-text("{email}@outlook.com")').last
                if tile_alt.count() > 0:
                    print(f"[OAuth2] 点击包含邮箱的磁贴")
                    tile_alt.click(timeout=5000)
                else:
                    # 回退：填写登录表单
                    login_input = page.locator('[name="loginfmt"]')
                    login_input.wait_for(timeout=5000)
                    print("[OAuth2] 填写登录表单")
                    login_input.fill(f'{email}@outlook.com', timeout=10000)
                    page.locator('#idSIButton9').click(timeout=7000)
        except Exception as e:
            print(f"[OAuth2] 登录/选择账号异常: {e}")
            page.screenshot(path='Results\\debug_oauth2_login.png')

        # 等待并点击同意按钮
        try:
            consent_btn = page.locator('[data-testid="appConsentPrimaryButton"], #idBtn_Accept, [value="Accept"]')
            consent_btn.first.wait_for(timeout=20000)
            print("[OAuth2] 点击同意按钮")
            consent_btn.first.click(timeout=7000)
        except Exception as e:
            print(f"[OAuth2] 同意按钮异常: {e}")
            page.screenshot(path='Results\\debug_oauth2_consent.png')

    except Exception as e:
        print(f"[OAuth2] handle_oauth2_form 异常: {e}")

def get_access_token(page, email):

    with open('config.json', 'r', encoding='utf-8') as f:
        data = json.load(f) 
    SCOPES = data['oauth2']['Scopes']
    client_id = data['oauth2']['client_id']
    redirect_url = data['oauth2']['redirect_url']

    code_verifier = generate_code_verifier()  
    code_challenge = generate_code_challenge(code_verifier) 
    scope = ' '.join(SCOPES)
    params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': redirect_url,
        'scope': scope,
        'response_mode': 'query',
        'prompt': 'select_account',
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256'
    }

    # 用事件监听器在请求发出时捕获 redirect URL（避免 localhost 无服务导致 chrome-error）
    captured_code = {}

    def on_request(request):
        if request.url.startswith(redirect_url) and 'code=' in request.url:
            query = parse_qs(urlsplit(request.url).query)
            if 'code' in query:
                captured_code['code'] = query['code'][0]

    page.on('request', on_request)

    max_time = 2
    current_times = 0
    while current_times < max_time:
        try:
            page.wait_for_timeout(250)
            url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{'&'.join(f'{k}={quote(v)}' for k,v in params.items())}"
            page.goto(url)
            break
        except:
            current_times = current_times + 1
            if current_times == max_time:
                page.remove_listener('request', on_request)
                return False, False, False
            continue

    handle_oauth2_form(page, email)

    # 等待 code 被捕获
    for _ in range(120):  # 最多等 60 秒
        if 'code' in captured_code:
            break
        page.wait_for_timeout(500)

    page.remove_listener('request', on_request)

    if 'code' not in captured_code:
        print(f"Authorization failed: No code captured. Current URL: {page.url}")
        return False, False, False

    auth_code = captured_code['code']

    token_data = {
        'client_id': client_id,
        'code': auth_code,
        'redirect_uri': redirect_url,
        'grant_type': 'authorization_code',
        'code_verifier': code_verifier,
        'scope': ' '.join(SCOPES)
    }

    response = requests.post('https://login.microsoftonline.com/common/oauth2/v2.0/token', data=token_data, headers={
        'Content-Type': 'application/x-www-form-urlencoded'
    }, proxies=get_proxy())

    if 'refresh_token' in response.json():

        tokens = response.json()
        token_data = {
            'refresh_token': tokens['refresh_token'],
            'access_token': tokens.get('access_token', ''),
            'expires_at': datetime.now().timestamp() + tokens['expires_in']
    }
        refresh_token = token_data['refresh_token']
        access_token = token_data['access_token']
        expire_at = token_data['expires_at']
        return refresh_token, access_token, expire_at

    else:

        return False, False, False
