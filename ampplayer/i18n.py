"""نظام الترجمة (عربي / إنجليزي) مع دعم اتجاه النص RTL/LTR."""

from __future__ import annotations

from typing import Dict

AR = "ar"
EN = "en"

# كل النصوص: المفتاح -> (العربي, English)
_STRINGS: Dict[str, tuple[str, str]] = {
    # ---- عام ----
    "app.title": ("Amp Player - مشغل وسائط للمكفوفين", "Amp Player - Accessible Media Player"),
    "app.short_title": ("Amp Player", "Amp Player"),
    "ok": ("موافق", "OK"),
    "cancel": ("إلغاء", "Cancel"),
    "close": ("إغلاق", "Close"),
    "save": ("حفظ", "Save"),
    "apply": ("تطبيق", "Apply"),
    "open": ("فتح", "Open"),
    "browse": ("استعراض...", "Browse..."),
    "yes": ("نعم", "Yes"),
    "no": ("لا", "No"),
    "none": ("لا يوجد", "None"),
    "unknown": ("غير معروف", "Unknown"),
    "search": ("بحث", "Search"),
    "refresh": ("تحديث", "Refresh"),
    "download": ("تحميل", "Download"),
    "retry": ("إعادة المحاولة", "Retry"),
    "help": ("مساعدة", "Help"),
    "about": ("حول البرنامج", "About"),

    # ---- القوائم ----
    "menu.file": ("ملف", "File"),
    "menu.edit": ("تحرير", "Edit"),
    "menu.view": ("عرض", "View"),
    "menu.subtitles": ("الترجمة", "Subtitles"),
    "menu.tools": ("أدوات", "Tools"),
    "menu.help": ("مساعدة", "Help"),
    "menu.open_file": ("فتح ملف وسائط...", "Open media file..."),
    "menu.open_folder": ("فتح مجلد...", "Open folder..."),
    "menu.open_url": ("فتح رابط إنترنت...", "Open network stream..."),
    "menu.open_with": ("فتح...", "Open with..."),
    "menu.recent": ("الملفات الأخيرة", "Recent files"),
    "menu.clear_recent": ("مسح قائمة الملفات الأخيرة", "Clear recent files"),
    "menu.exit": ("خروج", "Exit"),
    "menu.preferences": ("التفضيلات...", "Preferences..."),
    "menu.manage_subtitle_sites": ("إدارة مواقع الترجمة...", "Manage subtitle sites..."),
    "menu.voice_tts": ("قارئ الصوت (TTS)", "Text-to-speech"),
    "menu.voice_off": ("إيقاف قارئ الصوت", "Disable speech"),
    "menu.toggle_lang": ("تبديل اللغة (عربي / English)", "Switch language (Arabic / English)"),
    "menu.about": ("حول Amp Player", "About Amp Player"),
    "menu.dependencies": ("فحص المتطلبات...", "Check requirements..."),
    "menu.open_logs": ("فتح ملف السجل", "Open log file"),
    "menu.tips": ("اختصارات لوحة المفاتيح", "Keyboard shortcuts"),

    # ---- أزرار التشغيل ----
    "play": ("تشغيل", "Play"),
    "pause": ("إيقاف مؤقت", "Pause"),
    "stop": ("إيقاف", "Stop"),
    "next": ("التالي", "Next"),
    "prev": ("السابق", "Previous"),
    "fullscreen": ("ملء الشاشة", "Fullscreen"),
    "exit_fullscreen": ("الخروج من ملء الشاشة", "Exit fullscreen"),
    "mute": ("كتم الصوت", "Mute"),
    "volume_up": ("رفع الصوت", "Volume up"),
    "volume_down": ("خفض الصوت", "Volume down"),
    "mute_toggle": ("كتم أو استعادة الصوت", "Toggle mute"),
    "seek_forward": ("تقديم 10 ثوان", "Forward 10 seconds"),
    "seek_backward": ("تراجع 10 ثوان", "Back 10 seconds"),
    "seek_forward_long": ("تقديم دقيقة", "Forward 1 minute"),
    "seek_backward_long": ("تراجع دقيقة", "Back 1 minute"),
    "speed_up": ("تسريع", "Speed up"),
    "speed_down": ("إبطاء", "Slow down"),
    "speed_reset": ("إعادة السرعة الطبيعية", "Reset speed"),
    "frame_by_frame": ("إطار بإطار", "Frame by frame"),
    "jump_to_time": ("انتقال إلى وقت...", "Jump to time..."),
    "increase_subtitle": ("تكبير الترجمة", "Enlarge subtitle"),
    "decrease_subtitle": ("تصغير الترجمة", "Shrink subtitle"),
    "subtitle_size_increase": ("تكبير خط الترجمة المعروضة", "Enlarge subtitle text"),
    "subtitle_size_decrease": ("تصغير خط الترجمة المعروضة", "Shrink subtitle text"),
    "subtitle_delay_more": ("تأخير الترجمة 0.5 ثانية", "Delay subtitles 0.5s"),
    "subtitle_delay_less": ("تقدّم الترجمة 0.5 ثانية", "Advance subtitles 0.5s"),
    "sub.reset_offset": ("إعادة ضبط توقيت الترجمة", "Reset subtitle timing"),
    "next_subtitle": ("الترجمة التالية", "Next subtitle"),
    "prev_subtitle": ("الترجمة السابقة", "Previous subtitle"),
    "read_aloud_current": ("قراءة الترجمة الحالية صوتياً", "Read current subtitle aloud"),
    "read_aloud_stop": ("إيقاف القراءة الصوتية", "Stop reading aloud"),
    "show_subtitle_panel": ("إظهار لوحة الترجمة", "Show subtitle panel"),
    "hide_subtitle_panel": ("إخفاء لوحة الترجمة", "Hide subtitle panel"),
    "auto_read_subtitle": ("القراءة التلقائية للترجمة", "Automatic subtitle reading"),

    # ---- لوحة التشغيل ----
    "playback.time_elapsed": ("الوقت المنقضي", "Elapsed time"),
    "playback.time_total": ("المدة الكلية", "Total duration"),
    "playback.seek_slider": ("شريط التقدم", "Progress bar"),
    "playback.volume_slider": ("مستوى الصوت", "Volume"),
    "playback.now_playing": ("قيد التشغيل الآن", "Now playing"),
    "playback.nothing": ("لا يوجد ملف قيد التشغيل", "No media loaded"),
    "playback.speed_label": ("سرعة التشغيل", "Playback speed"),
    "playback.position": ("الموضع", "Position"),
    "playback.state.playing": ("قيد التشغيل", "Playing"),
    "playback.state.paused": ("متوقف مؤقتاً", "Paused"),
    "playback.state.stopped": ("متوقف", "Stopped"),
    "playback.state.loading": ("جاري التحميل", "Loading"),
    "playback.state.buffering": ("جاري التخزين المؤقت", "Buffering"),
    "playback.state.ended": ("انتهى", "Ended"),
    "playback.state.error": ("خطأ", "Error"),

    # ---- قائمة التشغيل ----
    "playlist.title": ("قائمة التشغيل", "Playlist"),
    "playlist.add_file": ("إضافة ملف...", "Add file..."),
    "playlist.add_folder": ("إضافة مجلد...", "Add folder"),
    "playlist.add_url": ("إضافة رابط...", "Add URL..."),
    "playlist.remove": ("إزالة المحدد", "Remove selected"),
    "playlist.remove_all": ("إزالة الكل", "Remove all"),
    "playlist.move_up": ("تحريك لأعلى", "Move up"),
    "playlist.move_down": ("تحريك لأسفل", "Move down"),
    "playlist.clear": ("تفريغ القائمة", "Clear playlist"),
    "playlist.count": ("عدد الملفات", "Item count"),
    "playlist.dup_item": ("العنصر موجود بالفعل في القائمة", "Item already in playlist"),
    "playlist.empty": ("قائمة التشغيل فارغة. أضف ملفاً للبدء.",
                       "Playlist is empty. Add a file to start."),
    "playlist.added_folder": ("تمت إضافة ملفات من المجلد", "Files added from folder"),
    "folder.no_media": ("لا يوجد ملفات وسائط في هذا المجلد", "No media files in this folder"),

    # ---- الترجمة ----
    "sub.title": ("الترجمة", "Subtitles"),
    "sub.language": ("لغة الترجمة", "Subtitle language"),
    "sub.load_external": ("تحميل ملف ترجمة خارجي...", "Load external subtitle file..."),
    "sub.auto_load": ("تحميل تلقائي لملف الترجمة المرافق", "Auto-load sidecar subtitle file"),
    "sub.search_online": ("البحث عن ترجمة عبر الإنترنت...", "Search subtitles online..."),
    "sub.external_loaded": ("تم تحميل الترجمة الخارجية", "External subtitle loaded"),
    "sub.no_external": ("لم يتم العثور على ملف ترجمة مرافق", "No sidecar subtitle file found"),
    "sub.no_subtitles": ("لا توجد ترجمة متاحة", "No subtitles available"),
    "sub.unsupported_format": ("صيغة الترجمة غير مدعومة", "Unsupported subtitle format"),
    "sub.read_aloud_unavailable": ("قارئ الصوت غير متوفر (pyttsx3 غير مثبت)", "TTS unavailable (pyttsx3 not installed)"),
    "sub.speak_now": ("الآن", "now"),
    "sub.pause_on_line": ("إيقاف مؤقت عند كل سطر ترجمة", "Pause on each subtitle line"),
    "sub.delay_offset": ("إزاحة توقيت الترجمة", "Subtitle timing offset"),
    "sub.size": ("حجم خط الترجمة", "Subtitle font size"),
    "sub.font": ("خط الترجمة", "Subtitle font"),
    "sub.color": ("لون الترجمة", "Subtitle color"),
    "sub.background_opacity": ("شفافية خلفية الترجمة", "Subtitle background opacity"),
    "sub.force_position": ("موضع الترجمة", "Subtitle position"),
    "sub.on_screen": ("عرض الترجمة على الشاشة", "Show subtitles on screen"),
    "sub.sync_to_audio": ("مزامنة الترجمة مع الصوت", "Sync subtitles with audio"),
    "sub.panel_title": ("لوحة قراءة الترجمة", "Subtitle reading panel"),
    "sub.next_line": ("السطر التالي", "Next line"),
    "sub.prev_line": ("السطر السابق", "Previous line"),
    "sub.copy_line": ("نسخ السطر الحالي", "Copy current line"),
    "sub.copy_all": ("نسخ الترجمة كاملة", "Copy whole subtitle"),
    "sub.clear_log": ("مسح سجل الترجمة", "Clear subtitle log"),
    "sub.export_log": ("حفظ سجل الترجمة", "Save subtitle log"),
    "sub.lines_count": ("عدد الأسطر", "Line count"),
    "sub.line": ("السطر", "Line"),
    "sub.time": ("الزمن", "Time"),
    "sub.external_none": ("لا يوجد ملف ترجمة خارجي", "No external subtitle file"),

    # ---- البحث عن ترجمة ----
    "search.title": ("البحث عن ترجمة", "Search Subtitles"),
    "search.query": ("اسم الفيلم أو المسلسل", "Movie or series name"),
    "search.language": ("اللغة", "Language"),
    "search.season": ("الموسم", "Season"),
    "search.episode": ("الحلقة", "Episode"),
    "search.release": ("إصدار الفيديو (اختياري)", "Video release (optional)"),
    "search.imdb": ("رقم IMDb (اختياري)", "IMDb ID (optional)"),
    "search.site": ("الموقع", "Site"),
    "search.start": ("ابدأ البحث", "Start search"),
    "search.searching": ("جاري البحث...", "Searching..."),
    "search.results": ("نتائج البحث", "Search results"),
    "search.no_results": ("لا توجد نتائج", "No results found"),
    "search.check_query": ("اكتب اسم الفيلم أولاً", "Enter movie name first"),
    "search.site_disabled": ("هذا الموقع معطّل", "This site is disabled"),
    "search.all_sites": ("كل المواقع", "All sites"),
    "search.sort": ("ترتيب", "Sort"),
    "search.sort.rating": ("الأعلى تقييماً", "Highest rating"),
    "search.sort.downloads": ("الأكثر تحميلاً", "Most downloaded"),
    "search.sort.recent": ("الأحدث", "Recently added"),
    "search.downloading": ("جاري التحميل...", "Downloading..."),
    "search.download_ok": ("تم تحميل الترجمة بنجاح", "Subtitle downloaded successfully"),
    "search.download_fail": ("فشل تحميل الترجمة", "Subtitle download failed"),
    "search.no_files": ("لم يتم العثور على ملفات ترجمة", "No subtitle files found"),
    "search.opening_site": ("جاري فتح المتصفح...", "Opening browser..."),
    "search.manual_hint": ("لا توجد نتائج؟ افتح الموقع بنفسك وحمّل الترجمة يدوياً ثم استورد الملف.",
                           "No results? Open the site manually, download the subtitle and import the file."),
    "search.open_site": ("فتح موقع الترجمة في المتصفح", "Open subtitle site in browser"),
    "search.expand_files": ("عرض ملفات الترجمة", "Show subtitle files"),
    "search.filter_lang": ("تصفية حسب اللغة", "Filter by language"),
    "search.results_count": ("عدد النتائج: {n}", "Results: {n}"),
    "search.site_summary": ("{site}: {n}", "{site}: {n}"),
    "search.network_error": ("خطأ في الاتصال بالشبكة", "Network error"),
    "search.added_to_app": ("تمت إضافة الترجمة إلى التطبيق", "Subtitle added to the app"),
    "search.auto_searching": ("جاري البحث التلقائي عن الترجمة...", "Automatically searching for subtitles..."),
    "search.auto_found": ("تم العثور على ترجمة تلقائياً", "Subtitle found automatically"),
    "search.auto_none": ("لم يُعثر على ترجمة تلقائية؛ افتح قائمة الترجمة ثم ابحث يدوياً أو ضع ملف SRT بجانب الفيلم",
                         "No automatic subtitle found; use the Subtitles menu to search manually or place an SRT file next to the movie"),

    # ---- دمج الترجمة ----
    "merge.title": ("دمج الترجمة في الفيديو", "Merge Subtitles into Video"),
    "merge.subtitle_file": ("ملف الترجمة", "Subtitle file"),
    "merge.video_file": ("ملف الفيديو", "Video file"),
    "merge.output": ("ملف الإخراج", "Output file"),
    "merge.select_sub": ("اختر ملف الترجمة", "Select subtitle file"),
    "merge.select_video": ("اختر ملف الفيديو", "Select video file"),
    "merge.select_output": ("اختر مسار الإخراج", "Select output path"),
    "merge.start": ("ابدأ الدمج", "Start merge"),
    "merge.merging": ("جاري الدمج...", "Merging..."),
    "merge.done": ("تم الدمج بنجاح: {path}", "Merged successfully: {path}"),
    "merge.failed": ("فشل الدمج", "Merge failed"),
    "merge.needs_ffmpeg": ("دمج الترجمة يتطلب FFmpeg. ثبّته من قائمة الأدوات.",
                           "Merging requires FFmpeg. Install it from the Tools menu."),
    "merge.need_both": ("اختر ملف الفيديو وملف الترجمة", "Choose both video and subtitle files"),
    "merge.same_file": ("لا يمكن الكتابة فوق الملف الأصلي", "Cannot overwrite the original file"),
    "merge.audio_codec": ("ترميز الصوت", "Audio codec"),
    "merge.subtitle_codec": ("ترميز الترجمة", "Subtitle codec"),
    "merge.copy_audio": ("نسخ الصوت دون إعادة ترميز (أسرع)", "Copy audio without re-encoding (faster)"),
    "merge.keep_original": ("إبقاء الملف الأصلي", "Keep original file"),

    # ---- التفضيلات ----
    "prefs.title": ("التفضيلات", "Preferences"),
    "prefs.tabs.general": ("عام", "General"),
    "prefs.tabs.language": ("اللغة", "Language"),
    "prefs.tabs.subtitles": ("الترجمة", "Subtitles"),
    "prefs.tabs.speech": ("الصوت", "Speech"),
    "prefs.tabs.advanced": ("متقدم", "Advanced"),
    "prefs.language": ("لغة الواجهة", "Interface language"),
    "prefs.rtl": ("اتجاه النص من اليمين لليسار", "Right-to-left text direction"),
    "prefs.autoplay_next": ("تشغيل الملف التالي تلقائياً", "Auto-play next file"),
    "prefs.remember_pos": ("تذكر موضع التشغيل لكل ملف", "Remember playback position"),
    "prefs.decode_threads": ("خيوط فك الترميز", "Decoder threads"),
    "prefs.decode_auto": ("تلقائي", "Automatic"),
    "prefs.decode_threads_hint": (
        "عدد الخيوط التي يوزّع عليها FFmpeg فك ترميز الفيديو. اتركه تلقائياً "
        "إن لم يكن لديك سبب لتغييره.",
        "How many threads FFmpeg spreads video decoding across. Leave on "
        "automatic unless you have a reason to change it.",
    ),
    "prefs.auto_sub_search": ("البحث التلقائي عند فشل الترجمة", "Auto-search when subtitles missing"),
    "prefs.audio_device": ("جهاز الإخراج الصوتي", "Audio output device"),
    "prefs.audio_default": ("افتراضي (حسب ويندوز)", "Default (system)"),
    "prefs.audio_device_hint": (
        "اختر جهاز الصوت الذي سيخرج منه الفيديو. إذا كان الصوت يقطّع، "
        "جرّب جهازاً آخر أو «افتراضي» إن كانت سماعاتك بلوتوث.",
        "Choose the device video audio goes to. If sound keeps cutting out, "
        "try another device or Default if your headphones are Bluetooth.",
    ),
    "diag.title": ("تشخيص الصوت", "Audio diagnostics"),
    "diag.device": ("جهاز الصوت", "Audio device"),
    "diag.rate": ("معدل العيّنات", "Sample rate"),
    "diag.callbacks": ("استدعاءات الجهاز", "Device callbacks"),
    "diag.underruns": ("مرّات تقطيع الصوت", "Audio underruns"),
    "diag.late": ("استدعاءات متأخرة", "Late callbacks"),
    "diag.queue": ("امتلاء المخزن", "Buffer fill"),
    "prefs.speech_rate": ("سرعة القراءة", "Speech rate"),
    "prefs.speech_volume": ("مستوى صوت القراءة", "Speech volume"),
    "prefs.speech_voice": ("صوت القارئ", "Speech voice"),
    "prefs.speech_engine": ("محرك النطق", "Speech engine"),
    "engine.auto": ("تلقائي (NVDA إن كان يعمل)", "Auto (NVDA if running)"),
    "engine.nvda": ("NVDA (قارئ الشاشة)", "NVDA (screen reader)"),
    "engine.system": ("صوت النظام (SAPI)", "System voice (SAPI)"),
    "engine.voice_note": ("صوت NVDA يُضبط من إعدادات NVDA نفسها", "NVDA voice follows NVDA's own settings"),
    "engine.mpv": ("محرّك mpv", "mpv engine"),
    "engine.pyav": ("محرّك FFmpeg (PyAV)", "FFmpeg engine (PyAV)"),
    "prefs.announce_state": ("إعلان تغييرات حالة التشغيل", "Announce playback state changes"),
    "prefs.announce_subtitle": ("قراءة الترجمة عند ظهورها", "Read subtitle when it appears"),
    "prefs.duck_while_speaking": ("خفض صوت الفيديو أثناء النطق", "Lower video volume while speaking"),
    "prefs.duck_hold": ("مدة بقاء الصوت منخفضاً بعد النطق", "Duration volume stays lowered after speech"),
    "prefs.announce_volume": ("إعلان تغيير الصوت", "Announce volume changes"),
    "prefs.show_logs": ("عرض سجل الترجمات", "Show subtitle log"),
    "prefs.save_on_exit": ("حفظ الإعدادات عند الخروج", "Save settings on exit"),
    "prefs.ffmpeg_lib_path": ("مجلد مكتبات FFmpeg", "FFmpeg libraries folder"),
    "prefs.ffmpeg_path": ("مسار FFmpeg", "FFmpeg path"),
    "prefs.browse_ffmpeg_lib": ("اختر مجلد مكتبات FFmpeg", "Select FFmpeg libraries folder"),
    "prefs.browse_ffmpeg": ("اختر ffmpeg.exe", "Select ffmpeg.exe"),
    "prefs.sites": ("مواقع الترجمة المفعّلة", "Enabled subtitle sites"),
    "prefs.test_sites": ("اختبار المواقع", "Test sites"),
    "prefs.site_test_ok": ("الموقع يعمل", "Site works"),
    "prefs.site_test_fail": ("الموقع لا يعمل", "Site unreachable"),
    "prefs.cache_folder": ("مجلد التخزين المؤقت", "Cache folder"),
    "prefs.open_cache": ("فتح مجلد التخزين المؤقت", "Open cache folder"),
    "prefs.clear_cache": ("مسح التخزين المؤقت", "Clear cache"),
    "prefs.restart_required": ("أعد تشغيل البرنامج لتطبيق التغييرات", "Restart the app to apply changes"),
    "prefs.reset": ("استعادة الإعدادات الافتراضية", "Reset to defaults"),

    # ---- المتطلبات ----
    "deps.title": ("فحص المتطلبات", "Requirements Check"),
    "deps.engine_ok": ("محرّك FFmpeg جاهز", "FFmpeg engine ready"),
    "deps.engine_missing": ("محرّك FFmpeg غير متاح - مطلوب لتشغيل الفيديو والصوت",
                         "FFmpeg engine unavailable - required for playback"),
    "deps.engine_hint": ("ثبّت حزمة av من: https://pypi.org/project/av/",
                       "Install the av package from https://pypi.org/project/av/"),
    "deps.mpv_ok": ("محرّك mpv جاهز (صوت WASAPI، بلا تقطيع)", "mpv engine ready (native WASAPI)"),
    "deps.mpv_missing": ("محرّك mpv غير متاح - سيُستخدم محرّك FFmpeg تلقائياً",
                       "mpv engine unavailable - FFmpeg engine used automatically"),
    "deps.audio_device": ("جهاز الصوت", "Audio device"),
    "deps.audio_device_ok": ("جهاز الصوت جاهز", "Audio output ready"),
    "deps.audio_device_missing": (
        "لا يوجد جهاز صوت - سيعمل الفيديو بلا صوت",
        "No audio device - video will play without sound",
    ),
    "deps.ffmpeg_ok": ("FFmpeg متوفر", "FFmpeg found"),
    "deps.ffmpeg_missing": ("FFmpeg غير مثبت - مطلوب لدمج الترجمة داخل الفيديو",
                            "FFmpeg not installed - required to merge subtitles into the video"),
    "deps.ffmpeg_hint": ("ثبّت FFmpeg من: https://www.gyan.dev/ffmpeg/builds/",
                          "Install FFmpeg from https://www.gyan.dev/ffmpeg/builds/"),
    "deps.tts_ok": ("قارئ الصوت متوفر", "Text-to-speech available"),
    "deps.tts_missing": ("قارئ الصوت غير متوفر (اختياري)", "Text-to-speech unavailable (optional)"),
    "deps.download_ffmpeg": ("تحميل FFmpeg", "Download FFmpeg"),
    "deps.downloading": ("جاري التحميل...", "Downloading..."),
    "deps.download_done": ("تم تحميل FFmpeg", "FFmpeg downloaded"),
    "deps.copy_hint": ("انسخ ملف ffmpeg.exe إلى مجلد الأدوات", "Copy ffmpeg.exe into the tools folder"),
    "deps.close": ("إغلاق", "Close"),
    "deps.all_ok": ("كل المتطلبات متوفرة", "All requirements satisfied"),
    "deps.path": ("المسار", "Path"),
    "deps.version": ("الإصدار", "Version"),
    "deps.browse": ("تحديد المسار يدوياً", "Locate manually"),
    "deps.browse_ffmpeg": ("اختر ffmpeg.exe", "Select ffmpeg.exe"),
    "deps.browse_engine": ("اختر ملفات FFmpeg", "Select FFmpeg libraries"),

    # ---- مساعد ----
    "onboarding.title": ("مرحباً بك في Amp Player", "Welcome to Amp Player"),
    "onboarding.text": (
        "هذا البرنامج مصمم خصيصاً للمكفوفين.\n\n"
        "• استخدم Tab للتنقل بين الأزرار و Enter للاختيار.\n"
        "• اضغط S لقراءة الترجمة الحالية صوتياً.\n"
        "• اضمس Ctrl+O لفتح ملف وسائط.\n"
        "• الترجمة تُقرأ تلقائياً عند ظهورها إن فُعّل ذلك.\n\n"
        "اضغط زر «ابدأ» للبدء.",
        "This player is designed for blind users.\n\n"
        "- Use Tab to move between buttons and Enter to activate.\n"
        "- Press S to read the current subtitle aloud.\n"
        "- Press Ctrl+O to open a media file.\n"
        "- Subtitles are read automatically when enabled.\n\n"
        "Press Start to begin.",
    ),
    "onboarding.start": ("ابدأ", "Start"),
    "onboarding.skip": ("تخطي", "Skip"),
    "onboarding.dont_show": ("عدم إظهار هذا مجدداً", "Do not show this again"),

    # ---- الأخطاء ----
    "error.title": ("خطأ", "Error"),
    "error.cannot_open": ("لا يمكن فتح الملف", "Cannot open file"),
    "error.file_not_found": ("الملف غير موجود", "File not found"),
    "error.unsupported": ("صيغة غير مدعومة", "Unsupported format"),
    "error.permission": ("لا يوجد صلاحية للوصول", "Permission denied"),
    "error.generic": ("حدث خطأ غير متوقع: {msg}", "Unexpected error: {msg}"),
    "error.save_failed": ("فشل حفظ الملف", "Failed to save file"),
    "error.load_failed": ("فشل تحميل الملف", "Failed to load file"),

    # ---- سجل ----
    "log.title": ("سجل البرنامج", "Application log"),
    "log.copied": ("تم نسخ السجل", "Log copied"),
    "log.clear": ("مسح السجل", "Clear log"),

    # ---- اختصارات ----
    "shortcuts.title": ("اختصارات لوحة المفاتيح", "Keyboard shortcuts"),
    "shortcuts.general": ("عام", "General"),
    "shortcuts.playback": ("التشغيل", "Playback"),
    "shortcuts.subtitles": ("الترجمة", "Subtitles"),
    "shortcuts.movement": ("التنقل بين الملفات", "Navigation"),

    # ---- مصادر الترجمة الموحّدة ----
    "src.external": ("ملف ترجمة خارجي", "External subtitle file"),
    "src.remote": ("ترجمة المصدر (يوتيوب)", "Source subtitles (YouTube)"),
    "src.mode_auto": ("تلقائي", "Auto"),
    "src.mode_manual": ("يدوي", "Manual"),
    "src.embedded": ("ترجمة مدمجة داخل الفيديو", "Embedded subtitles (in video)"),
    "sub.embedded_tracks": ("مسار الترجمة المدمجة", "Embedded subtitle track"),
    "sub.embedded_track_auto": ("تلقائي (حسب اللغة المفضلة)", "Automatic (preferred language)"),
    "sub.embedded_found": ("تم اكتشاف ترجمة مدمجة", "Embedded subtitles detected"),
    "sub.embedded_none": ("لا توجد ترجمة مدمجة", "No embedded subtitles"),
    "sub.embedded_unsupported_image": ("ترجمة صورية غير مدعومة للقراءة", "Image-based subtitles (not readable)"),
    "sub.embedded_extract_failed": ("تعذّر استخراج الترجمة المدمجة", "Could not extract embedded subtitles"),
    "sub.embedded_extracting": ("جاري استخراج الترجمة المدمجة...", "Extracting embedded subtitles..."),
    "sub.track_default": ("(افتراضي)", "(default)"),
    "lang.ara": ("العربية", "Arabic"),
    "lang.eng": ("الإنجليزية", "English"),
    "lang.fra": ("الفرنسية", "French"),
    "lang.deu": ("الألمانية", "German"),
    "lang.spa": ("الإسبانية", "Spanish"),
    "lang.tur": ("التركية", "Turkish"),
    "lang.fas": ("الفارسية", "Persian"),
    "lang.urd": ("الأردية", "Urdu"),
    "lang.hin": ("الهندية", "Hindi"),
    "lang.und": ("لغة غير محددة", "Unknown language"),
    "src.none": ("لا يوجد مصدر ترجمة فعّال", "No active subtitle source"),
    "src.current": ("مصدر الترجمة الحالي", "Current subtitle source"),
    "sub.source": ("مصدر الترجمة", "Subtitle source"),
    "sub.read_last": ("إعادة نطق آخر ترجمة", "Repeat last subtitle"),
    "sub.read_last_none": ("لا توجد ترجمة مسموعة بعد", "No subtitle read yet"),
    "sub.current_text": ("الترجمة الحالية", "Current subtitle text"),

    "prefs.src_mode": ("وضع اختيار مصدر الترجمة", "Subtitle source mode"),

    # ---- يوتيوب ----
    "ytdlp.missing": (
        "yt-dlp غير مثبت: لا يمكن جلب ترجمة يوتيوب",
        "yt-dlp is not installed: cannot fetch YouTube subtitles",
    ),
    "ytdlp.fetching": ("جاري جلب ترجمة يوتيوب...", "Fetching YouTube subtitles..."),
    "ytdlp.ok": ("تم جلب ترجمة يوتيوب", "YouTube subtitles fetched"),
    "ytdlp.none": ("لا توجد ترجمة متاحة لهذا الفيديو", "No subtitles available for this video"),
    "ytdlp.error": ("فشل جلب ترجمة يوتيوب", "Failed to fetch YouTube subtitles"),
    "ytdlp.url": ("رابط فيديو يوتيوب", "YouTube video URL"),
    "ytdlp.action": ("جلب ترجمة يوتيوب...", "Fetch YouTube subtitles..."),

    # ---- حول البرنامج والتواصل ----
    "about.developer": ("المطوّر", "Developer"),
    "about.contact": ("للتواصل والدعم", "Contact and support"),
    "about.email": ("البريد الإلكتروني", "Email"),
    "about.twitter": ("حساب إكس/تويتر", "X/Twitter"),
    "about.copy_contact": ("نسخ بيانات التواصل", "Copy contact details"),
    "about.copied": ("تم نسخ بيانات التواصل", "Contact details copied"),
    "about.open_email": ("إرسال بريد", "Send email"),
    "about.open_twitter": ("فتح الحساب", "Open profile"),
    "about.about_text": (
        "مشغّل وسائط متوافق مع المكفوفين، يقرأ ملفات الترجمة الخارجية والترجمة المدمجة داخل الفيديو عبر NVDA.",
        "An accessible media player that reads external subtitle files and embedded subtitles through NVDA.",
    ),
}


class Translator:
    """مترجم نصوص بسيط يدعم العربية والإنجليزية."""

    def __init__(self, lang: str = AR):
        self._lang = AR if lang not in (AR, EN) else lang

    @property
    def language(self) -> str:
        return self._lang

    def set_language(self, lang: str) -> None:
        self._lang = AR if lang not in (AR, EN) else lang

    def is_rtl(self) -> bool:
        return self._lang == AR

    def __call__(self, key: str, **kwargs) -> str:
        pair = _STRINGS.get(key)
        if pair is None:
            return key
        text = pair[0] if self._lang == AR else pair[1]
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    # اختصار للقراءة داخل القوالب
    def t(self, key: str, **kwargs) -> str:
        return self(key, **kwargs)


# نسخة افتراضية عامة تُستخدم عند الحاجة خارج الـ widgets
tr = Translator()