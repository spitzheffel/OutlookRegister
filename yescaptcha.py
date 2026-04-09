import requests
import base64


def classify_funcaptcha(api_key, image_base64, question=None, api_url="https://api.yescaptcha.com/createTask"):
    """
    通过 YesCaptcha FunCaptchaClassification 识别 FunCaptcha 图片验证码
    
    参数:
        api_key: YesCaptcha clientKey
        image_base64: 六宫格图片的 base64 编码（纯图片部分）
        question: 验证码问题文本（可选，直接传网页上的原文）
        api_url: API 端点
    
    返回:
        识别结果 dict: {"objects": [N], "labels": [...]} 或 None
        objects[0] 为应点击的位置索引（从0开始）
    """
    if not image_base64.startswith("data:image"):
        image_base64 = f"data:image/png;base64,{image_base64}"

    task = {
        "type": "FunCaptchaClassification",
        "image": image_base64,
    }
    if question:
        task["question"] = question

    payload = {
        "clientKey": api_key,
        "task": task,
    }

    try:
        res = requests.post(api_url, json=payload, timeout=30)
        resp = res.json()

        if resp.get("errorId", 0) != 0:
            print(f"[YesCaptcha] 识别失败: {resp.get('errorDescription', resp.get('errorCode', res.text))}")
            return None

        solution = resp.get("solution")
        if solution and "objects" in solution:
            print(f"[YesCaptcha] 识别成功: 位置 {solution['objects']}")
            return solution

        print(f"[YesCaptcha] 返回格式异常: {resp}")
        return None

    except Exception as e:
        print(f"[YesCaptcha] 请求失败: {e}")
        return None
