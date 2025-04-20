import json
import asyncio

import googletrans
from googletrans import Translator
import os


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


def read_language_file(file_path):
    """Read a JSON language file and return its content."""
    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            language_file = json.load(json_file)
        return language_file
    except Exception as e:
        print(f"Error reading '{file_path}': {e}")
        raise


async def translate_text(text, src_lang, dest_lang, translator):
    """Translate a single text string asynchronously using a thread pool."""
    if not text:
        return text
    try:
        # Run synchronous translate in a thread
        result = await asyncio.to_thread(translator.translate, text, src=src_lang, dest=dest_lang)
        return result.text if hasattr(result, 'text') else result
    except Exception as e:
        print(f"Error translating '{text}' to '{dest_lang}': {e}")
        return text


async def translate_language_file(language_file, src_lang, target_langs, translater, all_languages):
    """Translate the language file content into multiple target languages."""
    translated_files_temp = {}
    if isinstance(target_langs, dict):
        target_langs_temp = target_langs.keys()
    else:
        target_langs_temp = target_langs
    for lang in target_langs_temp:
        if src_lang == lang:
            continue
        translated_content = {}
        if isinstance(target_langs, dict):
            print(f"Translating from '{target_langs[src_lang]}' to '{target_langs[lang]}'...")
        else:
            print(f"Translating from '{src_lang}' to '{lang}'...")
        for key, value in language_file.items():
            if key == 'language_simple':
                translated_content[key] = lang
                continue
            if key == "language_name":
                translated_content[key] = str.capitalize(all_languages[lang])
                continue
            if isinstance(value, str):
                translated_content[key] = await translate_text(value, src_lang, lang, translater)
                print(f"Translated '{key}' to '{lang}': {translated_content[key]}")
            elif isinstance(value, list):
                translated_content[key] = [
                    await translate_text(item, src_lang, lang, translater) for item in value
                ]
                print(f"Translated '{key}' to '{lang}': {translated_content[key]}")
            else:
                translated_content[key] = value
                # print(f"Warning: Key '{key}' has non-string/list value '{value}', copied as-is.")
        translated_files_temp[lang] = translated_content
    return translated_files_temp


def save_to_json_files(translated_files_temp):
    """Save translated content to JSON files."""
    for lang, content in translated_files_temp.items():
        file_name = f"lang/language_{lang}.json"
        os.makedirs(os.path.dirname(file_name), exist_ok=True)
        try:
            with open(file_name, "w", encoding="utf-8") as json_file:
                json.dump(content, json_file, ensure_ascii=False, indent=4)
            print(f"Saved file: {file_name}")
        except Exception as e:
            print(f"Error saving '{file_name}': {e}")


async def main(target_langs_t=None, src_lang_content=None):
    all_languages = googletrans.LANGUAGES
    try:
        # Test proxy connectivity
        if target_langs_t is None:
            target_langs_t = all_languages
        translater = Translator()
        # test_translation = translater.translate("你好", dest='en', src='auto')
        src_lang = src_lang_content.get("language_simple")
    except FileNotFoundError:
        print("Error: 'lang/lang_fr.json' not found.")

    # Translate the file
    translated_files = await translate_language_file(src_lang_content, src_lang, target_langs_t, translater,
                                                     all_languages)

    # Save translated content to files
    save_to_json_files(translated_files)
    print("Translation completed!")


if __name__ == "__main__":
    set_proxy("http://127.0.0.1:7890")
    # 列出常见语言名称,英语，日语，汉语，法语，德语，俄语，葡萄牙语，西班牙语，阿拉伯语，保加利亚语，冰岛语，丹麦语，
    target_langs = ["en", "ja", "fr", "de", "ru", "pt", "es", "ar", "bg", "is", "da", "nl", "it", "pl", "ro",]
    srclang_file = read_language_file("lang/lang_zh-CN.json")
    asyncio.run(main(target_langs, srclang_file))
