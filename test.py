import os
import googletrans
from googletrans import Translator


def set_proxy(proxy_str):
    if proxy_str:
        # 设置环境变量
        os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'  # 设置 HTTP 代理
        os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'  # 设置 HTTPS 代理
        os.environ['ALL_PROXY'] = 'http://127.0.0.1:7890'
        print(f"Proxy set to: {proxy_str}")
    else:
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("ALL_PROXY", None)
        print("Proxy cleared.")


langs = googletrans.LANGUAGES

translater = Translator()
out = translater.translate("你好", dest='en', src='auto')
print(out)
