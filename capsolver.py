import time
import requests


def solve_funcaptcha(api_key, website_url, website_public_key, subdomain=None, data_blob=None, timeout=120):
    """
    通过 CapSolver API 求解 FunCaptcha (Arkose Labs)
    返回 token 字符串，失败返回 None
    """
    task = {
        "type": "FunCaptchaTaskProxyLess",
        "websiteURL": website_url,
        "websitePublicKey": website_public_key,
    }
    if subdomain:
        task["funcaptchaApiJSSubdomain"] = subdomain
    if data_blob:
        task["data"] = '{"blob":"' + data_blob + '"}'

    payload = {
        "clientKey": api_key,
        "task": task
    }

    try:
        res = requests.post("https://api.capsolver.com/createTask", json=payload, timeout=30)
        resp = res.json()
        task_id = resp.get("taskId")
        if not task_id:
            print(f"[CapSolver] 创建任务失败: {resp.get('errorDescription', res.text)}")
            return None
        print(f"[CapSolver] 任务已创建: {task_id}")
    except Exception as e:
        print(f"[CapSolver] 请求失败: {e}")
        return None

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(3)
        try:
            res = requests.post("https://api.capsolver.com/getTaskResult",
                                json={"clientKey": api_key, "taskId": task_id}, timeout=30)
            resp = res.json()
            status = resp.get("status")
            if status == "ready":
                token = resp.get("solution", {}).get("token")
                print(f"[CapSolver] 验证码已解决")
                return token
            if status == "failed" or resp.get("errorId"):
                print(f"[CapSolver] 求解失败: {resp.get('errorDescription', res.text)}")
                return None
        except Exception as e:
            print(f"[CapSolver] 轮询失败: {e}")
            return None

    print("[CapSolver] 求解超时")
    return None
