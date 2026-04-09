import random
import string
import secrets
import requests

# 常见英文名
FIRST_NAMES = [
    'james', 'john', 'robert', 'michael', 'david', 'william', 'richard', 'joseph', 'thomas', 'charles',
    'mary', 'patricia', 'jennifer', 'linda', 'elizabeth', 'barbara', 'susan', 'jessica', 'sarah', 'karen',
    'daniel', 'matthew', 'anthony', 'mark', 'donald', 'steven', 'paul', 'andrew', 'joshua', 'kenneth',
    'emily', 'emma', 'olivia', 'sophia', 'isabella', 'mia', 'charlotte', 'amelia', 'harper', 'evelyn',
    'alex', 'ryan', 'kevin', 'brian', 'george', 'edward', 'henry', 'jason', 'adam', 'nathan',
    'grace', 'lily', 'chloe', 'hannah', 'ella', 'madison', 'aria', 'luna', 'victoria', 'stella'
]

LAST_NAMES = [
    'smith', 'johnson', 'williams', 'brown', 'jones', 'garcia', 'miller', 'davis', 'rodriguez', 'martinez',
    'wilson', 'anderson', 'taylor', 'thomas', 'moore', 'jackson', 'martin', 'lee', 'thompson', 'white',
    'harris', 'clark', 'lewis', 'walker', 'hall', 'allen', 'young', 'king', 'wright', 'hill',
    'scott', 'green', 'baker', 'adams', 'nelson', 'carter', 'mitchell', 'roberts', 'turner', 'phillips'
]

def random_email():
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    digits = ''.join(random.choices(string.digits, k=6))
    email = f"{first}{last}{digits}"
    return email, first.capitalize(), last.capitalize()

def generate_strong_password(length=random.randint(11, 15)):

    chars = string.ascii_letters + string.digits + "!@#$%^&*"

    while True:
        password = ''.join(secrets.choice(chars) for _ in range(length))

        if (any(c.islower() for c in password) 
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)
                and any(c in "!@#$%^&*" for c in password)):
            return password


# 国家代码 -> (浏览器语言, locale) 映射
COUNTRY_LOCALE_MAP = {
    "US": ("en-US", "en-US"), "GB": ("en-GB", "en-GB"), "CA": ("en-CA", "en-CA"),
    "AU": ("en-AU", "en-AU"), "CN": ("zh-CN", "zh-CN"), "TW": ("zh-TW", "zh-TW"),
    "HK": ("zh-HK", "zh-HK"), "JP": ("ja-JP", "ja-JP"), "KR": ("ko-KR", "ko-KR"),
    "DE": ("de-DE", "de-DE"), "FR": ("fr-FR", "fr-FR"), "ES": ("es-ES", "es-ES"),
    "IT": ("it-IT", "it-IT"), "PT": ("pt-PT", "pt-PT"), "BR": ("pt-BR", "pt-BR"),
    "RU": ("ru-RU", "ru-RU"), "IN": ("en-IN", "en-IN"), "SG": ("en-SG", "en-SG"),
    "NL": ("nl-NL", "nl-NL"), "SE": ("sv-SE", "sv-SE"), "NO": ("nb-NO", "nb-NO"),
    "DK": ("da-DK", "da-DK"), "FI": ("fi-FI", "fi-FI"), "PL": ("pl-PL", "pl-PL"),
    "TR": ("tr-TR", "tr-TR"), "TH": ("th-TH", "th-TH"), "VN": ("vi-VN", "vi-VN"),
    "ID": ("id-ID", "id-ID"), "MY": ("ms-MY", "ms-MY"), "PH": ("en-PH", "en-PH"),
    "MX": ("es-MX", "es-MX"), "AR": ("es-AR", "es-AR"), "CL": ("es-CL", "es-CL"),
    "CO": ("es-CO", "es-CO"), "IE": ("en-IE", "en-IE"), "NZ": ("en-NZ", "en-NZ"),
    "ZA": ("en-ZA", "en-ZA"), "IL": ("he-IL", "he-IL"), "AE": ("ar-AE", "ar-AE"),
    "SA": ("ar-SA", "ar-SA"), "EG": ("ar-EG", "ar-EG"), "UA": ("uk-UA", "uk-UA"),
    "CZ": ("cs-CZ", "cs-CZ"), "RO": ("ro-RO", "ro-RO"), "HU": ("hu-HU", "hu-HU"),
    "AT": ("de-AT", "de-AT"), "CH": ("de-CH", "de-CH"), "BE": ("nl-BE", "nl-BE"),
}


def detect_proxy_geo(proxy_url=None):
    """通过代理检测出口 IP 的地理位置信息，用于浏览器指纹一致性"""
    try:
        proxies = None
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}
        resp = requests.get(
            "http://ip-api.com/json/?fields=status,country,countryCode,timezone,lat,lon,query",
            proxies=proxies, timeout=10
        )
        data = resp.json()
        if data.get("status") == "success":
            cc = data.get("countryCode", "US")
            lang, locale = COUNTRY_LOCALE_MAP.get(cc, ("en-US", "en-US"))
            geo = {
                "ip": data.get("query"),
                "country_code": cc,
                "timezone": data.get("timezone", "America/New_York"),
                "latitude": data.get("lat", 0),
                "longitude": data.get("lon", 0),
                "lang": lang,
                "locale": locale,
            }
            print(f"[GeoDetect] 出口IP: {geo['ip']} | 国家: {cc} | 时区: {geo['timezone']} | 语言: {lang}")
            return geo
    except Exception as e:
        print(f"[GeoDetect] 代理地理位置检测失败: {e}")
    return None
