import sys
import os
import pyperclip
import json
import glob
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QTextEdit, QComboBox, QHBoxLayout, QGroupBox, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import yt_dlp
import re


def parse_string_to_dict(input_string):
    pattern = r'--(\w+)\s(\S+)|-(\w)\s(\S+)'
    matches = re.findall(pattern, input_string)
    result = {}
    for match in matches:
        if match[0]:  # 长选项
            result[match[0]] = match[1]
        elif match[2]:  # 短选项
            result[match[2]] = match[3]
    return result


class StopDownloadException(Exception):
    """Custom exception to signal download interruption."""
    pass


class DownloadThread(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, urls, path, download_type, video_format, audio_format, prefix, proxy, ffmpeg_path,
                 video_quality, audio_quality, extra_params, get_translation):
        super().__init__()
        self.urls = urls
        self.path = path
        self.download_type = download_type
        self.video_format = video_format
        self.audio_format = audio_format
        self.prefix = prefix
        self.proxy = proxy
        self.ffmpeg_path = ffmpeg_path
        self.video_quality = video_quality
        self.audio_quality = audio_quality
        self.extra_params = extra_params
        self._stop_flag = False
        self.get_translation = get_translation

    def stop(self):
        """Set the stop flag to signal the thread to stop."""
        self._stop_flag = True

    def run(self):
        for i, url in enumerate(self.urls, 1):
            if self._stop_flag:
                self.log_signal.emit(self.get_translation('download_stopped'))
                break
            self.log_signal.emit(self.get_translation('download_start_single', index=i, url=url))
            self.download_single(url)

    def download_single(self, url):
        def progress_hook(d):
            if self._stop_flag:
                raise StopDownloadException("Download interrupted by user")
            if d['status'] == 'downloading':
                percent = d.get('_percent_str', '').strip()
                speed = d.get('_speed_str', '')
                eta = d.get('_eta_str', '')
                self.log_signal.emit(self.get_translation('download_progress', percent=percent, speed=speed, eta=eta))
            elif d['status'] == 'finished':
                self.log_signal.emit(self.get_translation('download_completed', filename=d['filename']))

        ydl_opts = {
            'outtmpl': os.path.join(self.path, f'{self.prefix}%(title)s.%(ext)s'),
            'progress_hooks': [progress_hook],
        }

        if self.proxy:
            ydl_opts['proxy'] = self.proxy

        if self.ffmpeg_path:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_path

        if self.download_type == '只下载音频':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': self.audio_format,
                    'preferredquality': self.audio_quality or '192',
                }],
            })
            ydl_opts['outtmpl'] = os.path.join(self.path, f'{self.prefix}%(title)s.{self.audio_format}')
            ydl_opts.pop('merge_output_format', None)
        elif self.download_type == '只下载视频':
            video_fmt = self.video_quality if self.video_quality else 'bestvideo'
            ydl_opts['format'] = f'{video_fmt}'
            ydl_opts['outtmpl'] = os.path.join(self.path, f'{self.prefix}%(title)s.{self.video_format}')
            ydl_opts['merge_output_format'] = self.video_format
        elif self.download_type == '音视频同时下载':
            video_fmt = self.video_quality if self.video_quality else 'bestvideo'
            audio_fmt = self.audio_quality if self.audio_quality else 'bestaudio'
            ydl_opts['format'] = f'{video_fmt}+{audio_fmt}/best'
            ydl_opts['merge_output_format'] = self.video_format
        elif self.download_type == '字幕':
            ydl_opts.update({
                'skip_download': True,
                'writesubtitles': True,
                'subtitleslangs': ['all'],
            })

        # Apply extra parameters
        if self.extra_params:
            try:
                extra_args = parse_string_to_dict(self.extra_params)
                if extra_args:
                    from yt_dlp import YoutubeDL
                    temp_ydl = YoutubeDL()
                    parsed_opts = temp_ydl.parse_options(extra_args)[0]
                    for key, value in parsed_opts.items():
                        if value is not None and value != '':
                            ydl_opts[key] = value
                    self.log_signal.emit(self.get_translation('extra_params_applied', params=str(extra_args)))
            except Exception as e:
                self.log_signal.emit(self.get_translation('extra_params_error', error=str(e)))

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except StopDownloadException:
            self.log_signal.emit(self.get_translation('download_stopped'))
        except Exception as e:
            self.log_signal.emit(self.get_translation('download_error', error=str(e)))


def get_clipboard_url():
    try:
        text = pyperclip.paste().strip()
        if text.startswith(('http://', 'https://')):
            return text
        return ""
    except Exception as e:
        print(f"Error accessing clipboard: {e}")
        return ""


class YTDLPApp(QWidget):
    def __init__(self):
        super().__init__()
        self.stop_btn = None
        self.worker = None
        self.translations = {}
        self.lang_files = {}
        self.current_lang = 'en'
        self.load_translations()

        self.exit_btn = None
        self.file_format_label = None
        self.ffmpeg_input = None
        self.download_btn = None
        self.log_output = None
        self.proxy_input = None
        self.audio_quality_input = None
        self.audio_quality_combo = None
        self.video_quality_input = None
        self.video_quality_combo = None
        self.prefix_input = None
        self.path_input = None
        self.url_input = None
        self.format_combo = None
        self.file_format_combo = None
        self.language_combo = None
        self.extra_params_input = None
        self.setWindowTitle(self.get_translation('window_title'))
        self.setGeometry(200, 200, 800, 700)
        self.init_ui()
        self.load_configuration()
        self.url_input.installEventFilter(self)

        # Connect clipboard change signal
        QApplication.clipboard().dataChanged.connect(self.update_url_from_clipboard)

    def update_url_from_clipboard(self):
        clipboard_text = get_clipboard_url()
        if clipboard_text:
            current_text = self.url_input.toPlainText().strip()
            if clipboard_text not in current_text:
                if current_text:
                    self.url_input.setPlainText(current_text + '\n' + clipboard_text)
                else:
                    self.url_input.setPlainText(clipboard_text)

    def closeEvent(self, event):
        self.save_configuration()
        event.accept()

    def save_configuration(self):
        config = {
            'path': self.path_input.text(),
            'prefix': self.prefix_input.text(),
            'download_type': self.format_combo.currentText(),
            'video_format': self.file_format_combo.currentText() if self.file_format_combo.isEnabled() else '',
            'audio_format': self.audio_quality_combo.currentText() if self.audio_quality_combo.isEnabled() else '',
            'video_quality': self.video_quality_combo.currentText() if self.video_quality_combo.isEnabled() else '',
            'audio_quality': self.audio_quality_combo.currentText() if self.audio_quality_combo.isEnabled() else '',
            'proxy': self.proxy_input.text(),
            'ffmpeg_path': self.ffmpeg_input.text(),
            'language': self.current_lang,
            'extra_params': self.extra_params_input.text()
        }
        try:
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except IOError as e:
            print(f"Error saving configuration: {e}")

    def load_configuration(self):
        default_config = {
            'path': os.path.expanduser("~/Downloads"),
            'prefix': self.get_translation('prefix_none'),
            'download_type': self.get_translation('download_types')[0],
            'video_format': 'mp4',
            'audio_format': 'mp3',
            'video_quality': 'Auto',
            'audio_quality': 'Auto',
            'proxy': 'http://127.0.0.1:7890',
            'ffmpeg_path': '',
            'language': 'en',
            'extra_params': ''
        }
        if os.path.exists('config.json'):
            try:
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    default_config.update(config)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading configuration: {e}. Using defaults.")

        self.path_input.setText(default_config['path'])
        self.prefix_input.setText(default_config['prefix'])
        self.format_combo.setCurrentText(default_config['download_type'])
        self.file_format_combo.setCurrentText(default_config['video_format'])
        self.audio_quality_combo.setCurrentText(default_config['audio_format'])
        self.video_quality_combo.setCurrentText(default_config['video_quality'])
        self.audio_quality_combo.setCurrentText(default_config['audio_quality'])
        self.proxy_input.setText(default_config['proxy'])
        self.ffmpeg_input.setText(default_config['ffmpeg_path'])
        self.extra_params_input.setText(default_config['extra_params'])
        lang_code = default_config['language']
        for lang_name, code in self.lang_files.items():
            if code == lang_code:
                self.language_combo.setCurrentText(lang_name)
                self.current_lang = lang_code
                self.update_ui_text()
                break

    def load_translations(self):
        translation_dir = 'lang'
        default_translations = {
            'en': {
                'language_name': 'English',
                "language_simple": "en",
                'window_title': 'YT-DLP Visual Batch Downloader',
                'url_label': 'Video URL (supports multiple lines, auto-reads clipboard):',
                'path_label': 'Save Path:',
                'browse_button': 'Browse',
                'prefix_label': 'File Prefix (optional):',
                'prefix_none': 'None',
                'prefix_date': 'Date: {date}',
                'prefix_datetime': 'DateTime: {datetime}',
                'download_type_label': 'Download Type:',
                'file_format_label': 'File Format:',
                'video_quality_label': 'Video Quality (select or custom):',
                'audio_quality_label': 'Audio Quality (select or custom):',
                'proxy_label': 'Proxy Settings (optional, e.g., http://127.0.0.1:7890):',
                'ffmpeg_label': 'FFmpeg Path (optional):',
                'ffmpeg_placeholder': 'Optional, e.g., /usr/bin/ffmpeg or ffmpeg.exe',
                'extra_params_label': 'Extra yt-dlp Parameters (optional, space-separated):',
                'extra_params_placeholder': 'e.g., --no-playlist --embed-subs',
                'download_button': 'Start Download',
                'stop_button': 'Stop Download',
                'exit_button': 'Exit',
                'log_group_title': 'Download Log',
                'error_no_url_path': '❗ Please provide URL and save path.',
                'download_start': '🚀 Starting download of {count} videos...',
                'download_stopped': '🛑 Download stopped',
                'download_start_single': '[{index}] Starting download: {url}',
                'download_progress': '⬇ Downloading: {percent} Speed: {speed} ETA: {eta}',
                'download_completed': '✅ Download completed: {filename}',
                'extra_params_applied': 'Applied extra parameters: {params}',
                'extra_params_error': '❌ Error parsing extra parameters: {error}',
                'download_error': '❌ Download error: {error}',
                'download_types': ['Video + Audio', 'Video Only', 'Audio Only', 'Subtitles Only'],
                'video_formats': ['mp4', 'webm', 'mkv', 'flv'],
                'audio_formats': ['mp3', 'wav', 'aac', 'flac', 'opus'],
                'combined_formats': ['mp4', 'mkv', 'webm'],
                'no_format': 'None',
                'video_qualities': ['Auto', '8K', '4K', '1080p', '720p', '480p', '360p', '240p'],
                'audio_qualities': ['Auto', '320 kbps', '256 kbps', '192 kbps', '128 kbps', '96 kbps'],
                'video_quality_placeholder': 'Custom format',
                'audio_quality_placeholder': 'Custom quality',
                'language_label': 'Language:'
            }
        }
        self.translations = default_translations
        self.lang_files = {'English': 'en'}
        if os.path.exists(translation_dir):
            json_files = glob.glob(os.path.join(translation_dir, '*.json'))
            for file_path in json_files:
                lang_code = os.path.splitext(os.path.basename(file_path))[0]
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        translation_data = json.load(f)
                        lang_code=translation_data['language_simple']
                        lang_name = translation_data.get('language_name', lang_code.capitalize())
                        # Ensure download_types is a list
                        if 'download_types' not in translation_data or not isinstance(translation_data['download_types'], list):
                            translation_data['download_types'] = default_translations['en']['download_types']
                        self.translations[lang_code] = translation_data
                        self.lang_files[lang_name] = lang_code
                except (json.JSONDecodeError, IOError) as e:
                    print(f"Error loading translation file {file_path}: {e}")
        else:
            print(f"Translation directory '{translation_dir}' not found. Using default translations.")

    def get_translation(self, key, **kwargs):
        translation = self.translations.get(self.current_lang, {}).get(key, '')
        if key == 'download_types' and not isinstance(translation, list):
            # Fallback to default if download_types is not a list
            translation = self.translations['en']['download_types']
        if isinstance(translation, str):
            return translation.format(**kwargs)
        elif isinstance(translation, list):
            return translation
        return translation

    def eventFilter(self, watched, event):
        from PyQt6.QtCore import QEvent
        if watched == self.url_input and event.type() == QEvent.Type.MouseButtonPress:
            clipboard_text = get_clipboard_url()
            if clipboard_text:
                current_text = self.url_input.toPlainText().strip()
                if clipboard_text not in current_text:
                    if current_text:
                        self.url_input.setPlainText(current_text + '\n' + clipboard_text)
                    else:
                        self.url_input.setPlainText(clipboard_text)
                    return True
        return super().eventFilter(watched, event)

    def init_ui(self):
        main_layout = QVBoxLayout()

        # Language selection
        lang_layout = QHBoxLayout()
        lang_label = QLabel(self.get_translation('language_label'))
        self.language_combo = QComboBox()
        self.language_combo.addItems(list(self.lang_files.keys()))
        self.language_combo.currentIndexChanged.connect(self.change_language)
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.language_combo)
        lang_layout.addStretch()
        main_layout.addLayout(lang_layout)

        # Input area
        input_group = QGroupBox("")
        input_layout = QVBoxLayout()
        input_layout.addWidget(QLabel(self.get_translation('url_label')))
        self.url_input = QTextEdit()
        self.url_input.setPlainText(get_clipboard_url())
        input_layout.addWidget(self.url_input)
        input_group.setLayout(input_layout)
        main_layout.addWidget(input_group)

        # Save settings area
        save_group = QGroupBox("")

        save_layout = QVBoxLayout()
        save_layout.addWidget(QLabel(self.get_translation('path_label')))
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setText(os.path.expanduser("~/Downloads"))
        path_layout.addWidget(self.path_input)
        browse_btn = QPushButton(self.get_translation('browse_button'))
        browse_btn.clicked.connect(self.browse_folder)

        path_layout.addWidget(browse_btn)
        save_layout.addLayout(path_layout)

        save_layout.addWidget(QLabel(self.get_translation('prefix_label')))
        self.prefix_input = QLineEdit()
        self.path_input.setText("")
        save_layout.addWidget(self.prefix_input)
        save_group.setLayout(save_layout)
        main_layout.addWidget(save_group)

        # Download options area
        download_options_group = QGroupBox("")
        download_options_layout = QGridLayout()
        download_choice_label = QLabel(self.get_translation('download_type_label'))
        download_options_layout.addWidget(download_choice_label, 0, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(self.get_translation('download_types'))
        self.format_combo.currentIndexChanged.connect(self.update_file_format_options)
        download_options_layout.addWidget(self.format_combo, 1, 0)
        self.file_format_label = QLabel(self.get_translation('file_format_label'))
        download_options_layout.addWidget(self.file_format_label, 0, 1)
        self.file_format_combo = QComboBox()
        self.file_format_combo.setEnabled(False)
        download_options_layout.addWidget(self.file_format_combo, 1, 1)
        video_quality_label = QLabel(self.get_translation('video_quality_label'))
        download_options_layout.addWidget(video_quality_label, 2, 0)
        video_quality_layout = QHBoxLayout()
        self.video_quality_combo = QComboBox()
        self.video_quality_combo.addItems(self.get_translation('video_qualities'))
        self.video_quality_input = QLineEdit()
        self.video_quality_input.setPlaceholderText(self.get_translation('video_quality_placeholder'))
        video_quality_layout.addWidget(self.video_quality_combo)
        video_quality_layout.addWidget(self.video_quality_input)
        download_options_layout.addLayout(video_quality_layout, 3, 0)
        audio_quality_label = QLabel(self.get_translation('audio_quality_label'))
        download_options_layout.addWidget(audio_quality_label, 2, 1)
        audio_quality_layout = QHBoxLayout()
        self.audio_quality_combo = QComboBox()
        self.audio_quality_combo.addItems(self.get_translation('audio_qualities'))
        self.audio_quality_input = QLineEdit()
        self.audio_quality_input.setPlaceholderText(self.get_translation('audio_quality_placeholder'))
        audio_quality_layout.addWidget(self.audio_quality_combo)
        audio_quality_layout.addWidget(self.audio_quality_input)
        download_options_layout.addLayout(audio_quality_layout, 3, 1)
        download_options_group.setLayout(download_options_layout)
        main_layout.addWidget(download_options_group)

        # Advanced settings area
        advanced_group = QGroupBox("")
        advanced_layout = QVBoxLayout()
        advanced_layout.addWidget(QLabel(self.get_translation('proxy_label')))
        self.proxy_input = QLineEdit()
        self.proxy_input.setText('http://127.0.0.1:7890')
        advanced_layout.addWidget(self.proxy_input)
        advanced_layout.addWidget(QLabel(self.get_translation('ffmpeg_label')))
        self.ffmpeg_input = QLineEdit()
        self.ffmpeg_input.setPlaceholderText(self.get_translation('ffmpeg_placeholder'))
        advanced_layout.addWidget(self.ffmpeg_input)
        advanced_layout.addWidget(QLabel(self.get_translation('extra_params_label')))
        self.extra_params_input = QLineEdit()
        self.extra_params_input.setPlaceholderText(self.get_translation('extra_params_placeholder'))
        advanced_layout.addWidget(self.extra_params_input)
        advanced_group.setLayout(advanced_layout)
        main_layout.addWidget(advanced_group)

        # Download control area
        control_layout = QHBoxLayout()
        control_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.download_btn = QPushButton(self.get_translation('download_button'))
        self.download_btn.clicked.connect(self.start_download)
        control_layout.addWidget(self.download_btn)
        control_layout.addSpacing(20)
        self.stop_btn = QPushButton(self.get_translation('stop_button'))
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.stop_btn)
        control_layout.addSpacing(20)
        self.exit_btn = QPushButton(self.get_translation('exit_button'))
        self.exit_btn.clicked.connect(self.close)
        control_layout.addWidget(self.exit_btn)
        main_layout.addLayout(control_layout)

        # Log output area
        log_group = QGroupBox(self.get_translation('log_group_title'))
        log_layout = QVBoxLayout()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

        self.setLayout(main_layout)

        # Connect signals for saving configuration
        self.format_combo.currentIndexChanged.connect(self.save_configuration)
        self.file_format_combo.currentIndexChanged.connect(self.save_configuration)
        self.audio_quality_combo.currentIndexChanged.connect(self.save_configuration)
        self.video_quality_combo.currentIndexChanged.connect(self.save_configuration)
        self.prefix_input.textChanged.connect(self.save_configuration)
        self.video_quality_input.textChanged.connect(self.save_configuration)
        self.audio_quality_input.textChanged.connect(self.save_configuration)
        self.proxy_input.textChanged.connect(self.save_configuration)
        self.ffmpeg_input.textChanged.connect(self.save_configuration)
        self.path_input.textChanged.connect(self.save_configuration)
        self.language_combo.currentIndexChanged.connect(self.save_configuration)
        self.extra_params_input.textChanged.connect(self.save_configuration)

    def change_language(self):
        self.current_lang = self.lang_files[self.language_combo.currentText()]
        self.update_ui_text()

    def update_ui_text(self):
        self.setWindowTitle(self.get_translation('window_title'))

        self.format_combo.clear()
        self.format_combo.addItems(self.get_translation('download_types'))
        self.video_quality_combo.clear()
        self.video_quality_combo.addItems(self.get_translation('video_qualities'))
        self.audio_quality_combo.clear()
        self.audio_quality_combo.addItems(self.get_translation('audio_qualities'))
        self.video_quality_input.setPlaceholderText(self.get_translation('video_quality_placeholder'))
        self.audio_quality_input.setPlaceholderText(self.get_translation('audio_quality_placeholder'))
        self.prefix_input.setPlaceholderText(self.get_translation('prefix_text'))
        self.download_btn.setText(self.get_translation('download_button'))
        self.stop_btn.setText(self.get_translation('stop_button'))
        self.exit_btn.setText(self.get_translation('exit_button'))
        self.update_file_format_options(self.format_combo.currentIndex())

        main_layout = self.layout()
        main_layout.itemAt(0).layout().itemAt(0).widget().setText(self.get_translation('language_label'))
        main_layout.itemAt(1).widget().layout().itemAt(0).widget().setText(self.get_translation('url_label'))
        main_layout.itemAt(2).widget().layout().itemAt(0).widget().setText(self.get_translation('path_label'))
        main_layout.itemAt(2).widget().layout().itemAt(1).layout().itemAt(1).widget().setText(
            self.get_translation('browse_button'))
        main_layout.itemAt(2).widget().layout().itemAt(2).widget().setText(self.get_translation('prefix_label'))
        main_layout.itemAt(3).widget().layout().itemAt(0).widget().setText(self.get_translation('download_type_label'))
        main_layout.itemAt(3).widget().layout().itemAt(2).widget().setText(self.get_translation('file_format_label'))
        main_layout.itemAt(3).widget().layout().itemAt(4).widget().setText(self.get_translation('video_quality_label'))
        main_layout.itemAt(3).widget().layout().itemAt(6).widget().setText(self.get_translation('audio_quality_label'))
        main_layout.itemAt(4).widget().layout().itemAt(0).widget().setText(self.get_translation('proxy_label'))
        main_layout.itemAt(4).widget().layout().itemAt(2).widget().setText(self.get_translation('ffmpeg_label'))
        main_layout.itemAt(4).widget().layout().itemAt(4).widget().setText(self.get_translation('extra_params_label'))
        main_layout.itemAt(6).widget().setTitle(self.get_translation('log_group_title'))

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.get_translation('browse_button'))
        if folder:
            self.path_input.setText(folder)

    def update_file_format_options(self, index):
        selected_format = self.format_combo.itemText(index)
        self.file_format_combo.clear()
        self.file_format_combo.setEnabled(True)
        download_types = self.get_translation('download_types')
        if selected_format == download_types[1]:
            self.file_format_combo.addItems(self.get_translation('video_formats'))
            self.file_format_combo.setCurrentText("mp4")
        elif selected_format == download_types[2]:
            self.file_format_combo.addItems(self.get_translation('audio_formats'))
            self.file_format_combo.setCurrentText("mp3")
        elif selected_format == download_types[0]:
            self.file_format_combo.addItems(self.get_translation('combined_formats'))
            self.file_format_combo.setCurrentText("mp4")
        elif selected_format == download_types[3]:
            self.file_format_combo.setEnabled(False)
            self.file_format_combo.addItem(self.get_translation('no_format'))
            self.file_format_combo.setCurrentText(self.get_translation('no_format'))

    def stop_download(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None
            self.download_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.log_output.append(self.get_translation('download_stopped'))

    def start_download(self):
        self.log_output.clear()
        urls = self.url_input.toPlainText().strip().splitlines()
        path = self.path_input.text().strip()
        download_types = self.get_translation('download_types')
        download_type = self.format_combo.currentText()
        video_format = ""
        audio_format = ""

        if download_type == download_types[1] or download_type == download_types[0]:
            video_format = self.file_format_combo.currentText()
        elif download_type == download_types[2]:
            audio_format = self.file_format_combo.currentText()

        prefix_text = self.prefix_input.text()
        proxy = self.proxy_input.text().strip()
        ffmpeg_path = self.ffmpeg_input.text().strip()
        video_quality = self.video_quality_input.text().strip() or self.video_quality_combo.currentText().strip()
        audio_quality = self.audio_quality_input.text().strip() or self.audio_quality_combo.currentText().strip()
        extra_params = self.extra_params_input.text().strip()

        if not urls or not path:
            self.log_output.append(self.get_translation('error_no_url_path'))
            return

        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_output.append(self.get_translation('download_start', count=len(urls)))

        self.worker = DownloadThread(
            urls, path, download_type, video_format, audio_format, prefix_text, proxy, ffmpeg_path,
            video_quality, audio_quality, extra_params, self.get_translation
        )
        self.worker.log_signal.connect(self.log_output.append)
        self.worker.finished.connect(lambda: self.download_btn.setEnabled(True))
        self.worker.finished.connect(lambda: self.stop_btn.setEnabled(False))
        self.worker.start()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YTDLPApp()
    window.show()
    sys.exit(app.exec())