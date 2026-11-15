import os
import glob
import re
import sqlite3
from functools import wraps
from flask import Flask, render_template_string, jsonify, request, session, redirect, url_for

app = Flask(__name__)
# Secret key for session signing
app.secret_key = os.environ.get("SECRET_KEY", "mofadala-secret-key-2026-auth-secure")

# Admin credentials (configurable via Render Environment Variables)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin@moazns.sy")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@2027")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "mofadala.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """تهيئة الجداول الإضافية والأعمدة الجديدة عند بدء تشغيل التطبيق"""
    conn = get_db_connection()
    c = conn.cursor()
    # جدول المجاميع العامة لكل سنة
    c.execute("""
        CREATE TABLE IF NOT EXISTS year_settings (
            year INTEGER PRIMARY KEY,
            max_score REAL DEFAULT 2400
        )
    """)
    
    # فحص عمود round_type في جدول admission_data
    cols = [r[1] for r in c.execute("PRAGMA table_info(admission_data)").fetchall()]
    if "round_type" not in cols:
        c.execute("ALTER TABLE admission_data ADD COLUMN round_type TEXT DEFAULT 'إعلان نتيجة'")
        c.execute("UPDATE admission_data SET round_type = 'مفاضلة أولى' WHERE is_final_result = 0")
        c.execute("UPDATE admission_data SET round_type = 'إعلان نتيجة' WHERE is_final_result = 1 OR round_type IS NULL")
        
    # ملء السنوات غير الموجودة في year_settings بقيمة افتراضية 2400
    c.execute("SELECT DISTINCT year FROM admission_data WHERE year IS NOT NULL")
    existing_years = [r[0] for r in c.fetchall()]
    for y in existing_years:
        c.execute("INSERT OR IGNORE INTO year_settings (year, max_score) VALUES (?, 2400)", (y,))
        
    conn.commit()
    conn.close()

# تنفيذ التهيئة
init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "غير مصرح، يرجى تسجيل الدخول أولاً"}), 401
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function

def get_scanned_and_empty_files():
    """
    تحديد ملفات الـ PDF التي تعذر استخراج بيانات منها آلياً أو الممسوحة ضوئياً
    لتسهيل إدخال بياناتها يدوياً على المستخدم.
    """
    pdf_files = sorted(glob.glob(os.path.join(BASE_DIR, "*.pdf")))
    conn = get_db_connection()
    c = conn.cursor()
    
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    files_info = []
    
    for f in pdf_files:
        basename = os.path.basename(f)
        norm_name = basename.translate(trans)
        year_match = re.search(r"(20\d\d)", norm_name)
        year = int(year_match.group(1)) if year_match else None
        
        adm_type = "عام"
        if "موازي" in norm_name and "عام" not in norm_name:
            adm_type = "موازي"
            
        is_final = any(ind in norm_name for ind in ["نتائج", "حدود", "معدلات", "ثانية", "الثانية", "تانية"])
        round_type = "إعلان نتيجة" if is_final else "مفاضلة أولى"
        
        if year:
            c.execute("SELECT COUNT(*) FROM admission_data WHERE year = ? AND admission_type = ?", (year, adm_type))
            count = c.fetchone()[0]
        else:
            count = 0
            
        is_known_scanned = any(s in basename for s in [
            "معدلات أولى علمي2018", 
            "مفاضلة العلمي الأولى عام 2017", 
            "موازي اولى 2017", 
            "نتائج_مفاضلة_2025_علمي_عام_موازي_بوت_مكتبتي"
        ])
        
        files_info.append({
            "filename": basename,
            "year": year,
            "admission_type": adm_type,
            "round_type": round_type,
            "is_final_result": is_final,
            "existing_records": count,
            "is_scanned": is_known_scanned
        })
        
    conn.close()
    return files_info

def get_year_audit_data():
    """
    إحصائيات تفصيلية لكل سنة تشمل المجموع العام للثانوية، وحالة القبول الأول أو إعلان النتيجة، واكتشاف الشذوذ.
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("""
        SELECT 
            a.year,
            COUNT(*) as total_count,
            SUM(CASE WHEN a.admission_type = 'عام' THEN 1 ELSE 0 END) as aam_count,
            SUM(CASE WHEN a.admission_type = 'موازي' THEN 1 ELSE 0 END) as muwazi_count,
            SUM(CASE WHEN a.round_type = 'مفاضلة أولى' THEN 1 ELSE 0 END) as first_round_count,
            SUM(CASE WHEN a.round_type = 'إعلان نتيجة' THEN 1 ELSE 0 END) as result_count,
            MIN(a.score) as min_score,
            MAX(a.score) as max_score,
            AVG(a.score) as avg_score,
            COALESCE(s.max_score, 2400) as year_max_score
        FROM admission_data a
        LEFT JOIN year_settings s ON a.year = s.year
        WHERE a.year IS NOT NULL
        GROUP BY a.year
        ORDER BY a.year DESC
    """)
    years_summary = [dict(r) for r in c.fetchall()]
    
    # فحص السجلات المشبوهة
    c.execute("""
        SELECT id, year, university, specialization, admission_type, round_type, is_final_result, score,
            CASE 
                WHEN score > 2500 THEN 'علامة أعلى من الحد الأقصى المعتاد (2400)'
                WHEN score IN (2024, 2025, 2026) THEN 'العلامة مطابقة للعام الدراسي (خطأ استخراج)'
                WHEN LENGTH(specialization) > 80 THEN 'اسم التخصص طويل جداً (احتمال دمج نصوص متعددة)'
                WHEN score < 1000 THEN 'علامة متدنية بشكل غير معتاد'
                ELSE 'تدقيق عام'
            END as anomaly_reason
        FROM admission_data
        WHERE score > 2500 
           OR score IN (2024, 2025, 2026)
           OR LENGTH(specialization) > 80
           OR score < 900
        ORDER BY year DESC, id DESC
    """)
    anomalies = [dict(r) for r in c.fetchall()]
    conn.close()
    
    return years_summary, anomalies

# =============================================================================
# TEMPLATES: LOGIN PAGE (DARK THEME)
# =============================================================================
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تسجيل الدخول - لوحة تنقيح المفاضلات</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    <style>body { font-family: 'Cairo', sans-serif; }</style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4 selection:bg-emerald-500 selection:text-white">

    <div class="max-w-md w-full">
        <!-- Brand Header -->
        <div class="text-center mb-8">
            <div class="inline-flex p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-3xl mb-4 shadow-xl backdrop-blur-md">
                <i class="fa-solid fa-shield-halved text-4xl text-emerald-400"></i>
            </div>
            <h1 class="text-2xl font-black text-white">بوابة الإدارة والتنقيح الآمنة</h1>
            <p class="text-xs text-slate-400 mt-1.5">نظام إدارة وتنقيح بيانات المفاضلات الجامعية السورية (2014 - 2026)</p>
        </div>

        <!-- Login Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-7 shadow-2xl space-y-6">
            {% if error %}
            <div class="p-3.5 bg-rose-950/60 border border-rose-800 text-rose-300 rounded-2xl text-xs font-bold flex items-center gap-2">
                <i class="fa-solid fa-circle-exclamation text-base"></i>
                <span>{{ error }}</span>
            </div>
            {% endif %}

            <form method="POST" action="/login" class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-300 mb-1.5">اسم المستخدم</label>
                    <div class="relative">
                        <i class="fa-solid fa-user absolute right-3.5 top-3.5 text-slate-500 text-sm"></i>
                        <input type="text" name="username" required autofocus placeholder="admin@moazns.sy"
                               class="w-full pr-10 pl-3 py-2.5 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                    </div>
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-300 mb-1.5">كلمة المرور</label>
                    <div class="relative">
                        <i class="fa-solid fa-lock absolute right-3.5 top-3.5 text-slate-500 text-sm"></i>
                        <input type="password" name="password" required placeholder="كلمة المرور"
                               class="w-full pr-10 pl-3 py-2.5 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                    </div>
                </div>

                <div class="pt-2">
                    <button type="submit" 
                            class="w-full py-3 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl shadow-lg shadow-emerald-950/50 transition-all flex items-center justify-center gap-2 text-sm">
                        <i class="fa-solid fa-right-to-bracket"></i>
                        <span>تسجيل الدخول للمنظومة</span>
                    </button>
                </div>
            </form>

            <div class="pt-4 border-t border-slate-800/80 text-center">
                <p class="text-[11px] text-slate-500">
                    <i class="fa-solid fa-lock text-[10px] ml-1"></i>
                    الوصول مقتصر على المشرفين المصرح لهم فقط.
                </p>
            </div>
        </div>
    </div>

</body>
</html>
"""

# =============================================================================
# TEMPLATES: MAIN APP (DARK THEME + YEAR MAX SCORE + PERCENTAGES + ROUND TYPE)
# =============================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تنقيح وإدارة بيانات المفاضلات الجامعية (2014 - 2026)</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        brand: {
                            500: '#10b981',
                            600: '#059669',
                            700: '#047857'
                        }
                    }
                }
            }
        }
    </script>
    <!-- Font Awesome -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- Google Fonts: Cairo -->
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <!-- SweetAlert2 -->
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <style>
        body { font-family: 'Cairo', sans-serif; }
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: #090d16; }
        ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #334155; }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col selection:bg-emerald-500 selection:text-white">

    <!-- Header -->
    <header class="bg-gradient-to-r from-emerald-950 via-slate-900 to-slate-950 text-white shadow-xl border-b border-slate-800/80 sticky top-0 z-40">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex flex-col md:flex-row justify-between items-center gap-4">
            <div class="flex items-center gap-3">
                <div class="bg-emerald-500/10 p-2.5 rounded-2xl backdrop-blur-md border border-emerald-500/30">
                    <i class="fa-solid fa-graduation-cap text-2xl sm:text-3xl text-emerald-400"></i>
                </div>
                <div>
                    <div class="flex items-center gap-2">
                        <h1 class="text-xl sm:text-2xl font-black tracking-wide text-white">لوحة تنقيح وإدارة بيانات المفاضلات</h1>
                        <span class="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[10px] px-2 py-0.5 rounded-full font-bold">حساب النسب المئوية %</span>
                    </div>
                    <p class="text-xs text-emerald-300/80 font-medium">مفاضلة أولى / إعلان نتيجة، والمجموع العام لكل سنة (2014 - 2026)</p>
                </div>
            </div>
            
            <div class="flex items-center gap-2.5">
                <button onclick="openYearSettingsModal()" class="bg-amber-600/90 hover:bg-amber-500 text-white font-bold text-xs px-3 py-2 rounded-xl border border-amber-500/40 shadow-lg shadow-amber-950/40 transition-all flex items-center gap-1.5" title="تحديد وتعديل المجموع العام للشهادة الثانوية لكل سنة">
                    <i class="fa-solid fa-sliders"></i>
                    <span>المجاميع السنوية %</span>
                </button>

                <button onclick="openAddModal()" class="bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs px-3.5 py-2 rounded-xl shadow-lg shadow-emerald-950/50 transition-all flex items-center gap-1.5">
                    <i class="fa-solid fa-plus-circle text-sm"></i>
                    <span>إضافة اختصاص</span>
                </button>

                <button onclick="exportCSV()" class="bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold text-xs px-3 py-2 rounded-xl border border-slate-700 transition-all flex items-center gap-1.5">
                    <i class="fa-solid fa-file-excel text-emerald-400"></i>
                    <span>تصدير Excel</span>
                </button>

                <!-- User & Logout -->
                <div class="flex items-center gap-1.5 bg-slate-950/80 border border-slate-800 px-3 py-1.5 rounded-xl text-xs">
                    <i class="fa-solid fa-user-shield text-emerald-400"></i>
                    <span class="text-slate-300 font-bold ml-2">{{ username }}</span>
                    <a href="/logout" title="تسجيل الخروج" class="text-rose-400 hover:text-rose-300 p-1 hover:bg-rose-950/50 rounded-lg transition-colors">
                        <i class="fa-solid fa-power-off"></i>
                    </a>
                </div>
            </div>
        </div>
    </header>

    <!-- Navigation Tabs -->
    <div class="bg-slate-900/90 backdrop-blur border-b border-slate-800 shadow-sm sticky top-[69px] z-30">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center gap-4 sm:gap-6 text-sm font-bold overflow-x-auto">
            <button onclick="switchTab('data-tab')" id="btn-data-tab" class="py-3.5 border-b-2 border-emerald-500 text-emerald-400 flex items-center gap-2 transition-colors whitespace-nowrap">
                <i class="fa-solid fa-table-list"></i>
                <span>جدول السجلات والبيانات</span>
                <span id="tabTotalBadge" class="bg-emerald-950 text-emerald-300 border border-emerald-800/80 text-xs px-2 py-0.5 rounded-full font-black">{{ stats.total }}</span>
            </button>

            <button onclick="switchTab('audit-tab')" id="btn-audit-tab" class="py-3.5 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2 transition-colors whitespace-nowrap">
                <i class="fa-solid fa-magnifying-glass-chart"></i>
                <span>مركز تدقيق ومصفوفة السنوات</span>
                {% if anomalies|length > 0 %}
                <span class="bg-rose-950 text-rose-300 border border-rose-800/80 text-xs px-2 py-0.5 rounded-full font-black animate-pulse">
                    {{ anomalies|length }} تدقيق مطلوب
                </span>
                {% endif %}
            </button>

            <button onclick="switchTab('manual-tab')" id="btn-manual-tab" class="py-3.5 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2 transition-colors whitespace-nowrap">
                <i class="fa-solid fa-file-circle-question"></i>
                <span>مساعد الملفات الممسوحة ضوئياً</span>
                <span class="bg-amber-950 text-amber-300 border border-amber-800/80 text-xs px-2 py-0.5 rounded-full font-black">4 ملفات</span>
            </button>

            <button onclick="switchTab('chart-tab')" id="btn-chart-tab" class="py-3.5 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2 transition-colors whitespace-nowrap">
                <i class="fa-solid fa-chart-line"></i>
                <span>المخطط البياني والتطور</span>
            </button>
        </div>
    </div>

    <!-- Main Content -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        <!-- TAB 1: DATA TABLE -->
        <div id="data-tab" class="space-y-6">

            <!-- Fast Year Selector Pills (شريط السنوات السريع) -->
            <div class="bg-slate-900/80 border border-slate-800 p-3 rounded-2xl shadow-sm flex items-center gap-2 overflow-x-auto">
                <span class="text-xs font-bold text-slate-400 ml-2 whitespace-nowrap flex items-center gap-1">
                    <i class="fa-solid fa-calendar-days text-emerald-400"></i> السنوات:
                </span>
                <button onclick="quickSelectYear('')" id="pill-all" class="year-pill px-3 py-1 rounded-xl text-xs font-bold bg-emerald-600 text-white transition-all whitespace-nowrap">
                    الكل ({{ stats.total }})
                </button>
                {% for ys in years_summary %}
                <button onclick="quickSelectYear('{{ ys.year }}')" id="pill-{{ ys.year }}" 
                        class="year-pill px-2.5 py-1 rounded-xl text-xs font-bold bg-slate-950 hover:bg-slate-800 text-slate-300 border border-slate-800 transition-all whitespace-nowrap flex items-center gap-1.5"
                        title="المجموع العام لسنة {{ ys.year }}: {{ ys.year_max_score }}">
                    <span>{{ ys.year }}</span>
                    <span class="text-[10px] px-1.5 py-0.2 rounded-md bg-slate-800 text-slate-400">{{ ys.total_count }}</span>
                    <span class="text-[10px] text-amber-400 font-normal">/{{ ys.year_max_score|int }}</span>
                </button>
                {% endfor %}
            </div>

            <!-- Filter Controls -->
            <div class="bg-slate-900 p-5 rounded-2xl shadow-lg border border-slate-800 space-y-4">
                <div class="flex items-center justify-between border-b border-slate-800/80 pb-3">
                    <h2 class="font-bold text-slate-200 text-sm flex items-center gap-2">
                        <i class="fa-solid fa-sliders text-emerald-400"></i>
                        أدوات البحث والفلترة السريعة
                    </h2>
                    <button onclick="resetFilters()" class="text-xs text-rose-400 hover:text-rose-300 font-semibold flex items-center gap-1 hover:underline">
                        <i class="fa-solid fa-rotate-left"></i> تفريغ الفلاتر
                    </button>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
                    <div class="lg:col-span-1">
                        <label class="block text-xs font-bold text-slate-400 mb-1">بحث في التخصص / الجامعة</label>
                        <div class="relative">
                            <i class="fa-solid fa-search absolute right-3 top-3 text-slate-500 text-sm"></i>
                            <input type="text" id="searchInput" placeholder="معلوماتية، تقاني..." oninput="applyFilters()"
                                   class="w-full pr-9 pl-3 py-2 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                        </div>
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 mb-1">السنة الدراسية</label>
                        <select id="yearSelect" onchange="applyFilters()" class="w-full p-2 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                            <option value="">جميع السنوات (2014 - 2026)</option>
                            {% for y in years %}
                            <option value="{{ y }}">{{ y }}</option>
                            {% endfor %}
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 mb-1">الجامعة</label>
                        <select id="uniSelect" onchange="applyFilters()" class="w-full p-2 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                            <option value="">جميع الجامعات</option>
                            {% for u in universities %}
                            <option value="{{ u }}">{{ u }}</option>
                            {% endfor %}
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 mb-1">نوع القبول</label>
                        <select id="typeSelect" onchange="applyFilters()" class="w-full p-2 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                            <option value="">عام وموازي</option>
                            <option value="عام">عام فقط</option>
                            <option value="موازي">موازي فقط</option>
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 mb-1">نوع الإعلان / المرحلة</label>
                        <select id="roundSelect" onchange="applyFilters()" class="w-full p-2 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                            <option value="">الكل (مفاضلة أولى + إعلان نتيجة)</option>
                            <option value="مفاضلة أولى">مفاضلة أولى (شروط التقدم)</option>
                            <option value="إعلان نتيجة">إعلان نتيجة (الحدود الدنيا الفعلية)</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- Data Table -->
            <div class="bg-slate-900 rounded-2xl shadow-lg border border-slate-800 overflow-hidden">
                <div class="px-6 py-4 bg-slate-950/70 border-b border-slate-800 flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <h3 class="font-bold text-slate-200">السجلات المستخرجة والمعدلة</h3>
                        <span id="filteredCountBadge" class="text-xs px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800/80 font-bold"></span>
                    </div>
                    <div class="text-xs text-slate-400">
                        تُحسب النسبة المئوية تلقائياً بناءً على المجموع العام المحدد لكل سنة
                    </div>
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-right text-sm">
                        <thead class="bg-slate-950/80 text-slate-400 text-xs font-black border-b border-slate-800">
                            <tr>
                                <th class="py-3 px-3 text-center">#</th>
                                <th class="py-3 px-3">السنة</th>
                                <th class="py-3 px-3">الجامعة</th>
                                <th class="py-3 px-4">الاختصاص / الكلية</th>
                                <th class="py-3 px-3 text-center">نوع القبول</th>
                                <th class="py-3 px-3 text-center">نوع الإعلان</th>
                                <th class="py-3 px-3 text-center font-black">الحد الأدنى والنسبة %</th>
                                <th class="py-3 px-3 text-center">الإجراءات</th>
                            </tr>
                        </thead>
                        <tbody id="tableBody" class="divide-y divide-slate-800/60">
                            <!-- Dynamic Rows -->
                        </tbody>
                    </table>
                </div>

                <div id="noDataMessage" class="hidden py-12 text-center text-slate-500">
                    <i class="fa-solid fa-folder-open text-4xl mb-3"></i>
                    <p class="font-semibold text-sm">لم يتم العثور على أي بيانات مطابقة للفلاتر المحددة.</p>
                </div>

                <!-- Pagination -->
                <div class="px-6 py-3.5 bg-slate-950/50 border-t border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-400">
                    <span id="pageInfo">عرض صفحة 1 من 1</span>
                    <div class="flex items-center gap-1.5" id="paginationControls"></div>
                </div>
            </div>
        </div>

        <!-- TAB 2: AUDIT & MATRIX (مركز تدقيق ومصفوفة السنوات) -->
        <div id="audit-tab" class="hidden space-y-6">

            <!-- Section 1: Anomaly Detector (كاشف الشذوذ والأخطاء) -->
            {% if anomalies|length > 0 %}
            <div class="bg-gradient-to-r from-rose-950/40 via-slate-900 to-slate-900 border border-rose-800/60 p-5 rounded-2xl space-y-4">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <div class="p-2.5 bg-rose-500/20 text-rose-400 border border-rose-500/30 rounded-xl text-lg">
                            <i class="fa-solid fa-triangle-exclamation"></i>
                        </div>
                        <div>
                            <h3 class="font-bold text-rose-300 text-base">سجلات مشبوهة تحتاج لتدقيق فوري ({{ anomalies|length }} سجل)</h3>
                            <p class="text-xs text-rose-200/80">تم الكشف عن نصوص مدمجة أو درجات غير مطابقة للمألوف (مثل درجات تطابق رقم العام الدراسي 2025/2026 أو علامات فوق المجموع العام).</p>
                        </div>
                    </div>
                </div>

                <div class="overflow-x-auto bg-slate-950/80 rounded-xl border border-slate-800">
                    <table class="w-full text-right text-xs">
                        <thead class="bg-slate-900 text-slate-400 border-b border-slate-800 font-bold">
                            <tr>
                                <th class="py-2.5 px-3">السنة</th>
                                <th class="py-2.5 px-3">الجامعة</th>
                                <th class="py-2.5 px-3">الاختصاص</th>
                                <th class="py-2.5 px-3 text-center">نوع الإعلان</th>
                                <th class="py-2.5 px-3 text-center">الدرجة</th>
                                <th class="py-2.5 px-3">سبب الاشتباه</th>
                                <th class="py-2.5 px-3 text-center">إجراء سريع</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-800/60">
                            {% for a in anomalies %}
                            <tr class="hover:bg-slate-800/40">
                                <td class="py-2.5 px-3 font-bold text-slate-200">{{ a.year }}</td>
                                <td class="py-2.5 px-3 text-slate-300">{{ a.university }}</td>
                                <td class="py-2.5 px-3 text-slate-300 max-w-xs truncate" title="{{ a.specialization }}">{{ a.specialization }}</td>
                                <td class="py-2.5 px-3 text-center">
                                    <span class="text-[10px] px-2 py-0.5 rounded-full font-bold {% if a.round_type == 'مفاضلة أولى' %}bg-amber-950/60 text-amber-300 border border-amber-800/60{% else %}bg-emerald-950/60 text-emerald-300 border border-emerald-800/60{% endif %}">
                                        {{ a.round_type }}
                                    </span>
                                </td>
                                <td class="py-2.5 px-3 text-center font-black text-rose-400">{{ a.score }}</td>
                                <td class="py-2.5 px-3 text-amber-300 font-medium">{{ a.anomaly_reason }}</td>
                                <td class="py-2.5 px-3 text-center">
                                    <div class="flex items-center justify-center gap-1.5">
                                        <button onclick="openEditModal({{ a.id }})" class="p-1 text-slate-400 hover:text-emerald-400">
                                            <i class="fa-solid fa-pen"></i>
                                        </button>
                                        <button onclick="deleteRecord({{ a.id }})" class="p-1 text-slate-400 hover:text-rose-400">
                                            <i class="fa-solid fa-trash-can"></i>
                                        </button>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            {% endif %}

            <!-- Section 2: Year Health Cards (بطاقات فحص وتغطية السنوات والمجموع العام) -->
            <div class="space-y-3">
                <div class="flex items-center justify-between">
                    <h3 class="font-bold text-slate-200 text-sm flex items-center gap-2">
                        <i class="fa-solid fa-calendar-check text-emerald-400"></i>
                        المجاميع العامة وتغطية البيانات لكل سنة دراسية (2014 - 2026)
                    </h3>
                    <button onclick="openYearSettingsModal()" class="text-xs text-amber-400 hover:text-amber-300 font-bold flex items-center gap-1 hover:underline">
                        <i class="fa-solid fa-sliders"></i> تعديل المجاميع العامة لكافة السنوات
                    </button>
                </div>

                <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
                    {% for ys in years_summary %}
                    <div class="bg-slate-900 border border-slate-800 p-3.5 rounded-2xl space-y-2 hover:border-slate-700 transition-all flex flex-col justify-between">
                        <div>
                            <div class="flex items-center justify-between">
                                <span class="text-base font-black text-emerald-400">{{ ys.year }}</span>
                                <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-950 text-slate-400 border border-slate-800">
                                    {{ ys.total_count }} سجل
                                </span>
                            </div>

                            <!-- Max score box -->
                            <div class="mt-2 bg-slate-950 px-2 py-1.5 rounded-xl border border-slate-800/80 flex items-center justify-between text-[11px]">
                                <span class="text-slate-400">المجموع العام:</span>
                                <span onclick="editYearMaxScore({{ ys.year }}, {{ ys.year_max_score }})" 
                                      title="انقر لتعديل المجموع العام لسنة {{ ys.year }}" 
                                      class="cursor-pointer font-black text-amber-400 hover:text-amber-300 underline decoration-dashed">
                                    {{ ys.year_max_score|int }}
                                </span>
                            </div>

                            <div class="flex items-center justify-between text-xs text-slate-300 border-t border-slate-800/80 pt-2 mt-2">
                                <span>عام: <strong class="text-blue-400">{{ ys.aam_count }}</strong></span>
                                <span>موازي: <strong class="text-purple-400">{{ ys.muwazi_count }}</strong></span>
                            </div>

                            <div class="flex items-center justify-between text-[10px] text-slate-400 mt-1">
                                <span>أولى: <strong class="text-amber-400">{{ ys.first_round_count }}</strong></span>
                                <span>نتائج: <strong class="text-emerald-400">{{ ys.result_count }}</strong></span>
                            </div>
                        </div>

                        <button onclick="quickFilterFromCard('{{ ys.year }}')" class="w-full py-1 mt-2 text-[11px] font-bold bg-slate-950 hover:bg-emerald-950 text-slate-400 hover:text-emerald-300 border border-slate-800 rounded-lg transition-colors">
                            تنقيح بيانات {{ ys.year }}
                        </button>
                    </div>
                    {% endfor %}
                </div>
            </div>

            <!-- Section 3: Comparative Matrix (مصفوفة المقارنة المتقاطعة للسنوات) -->
            <div class="bg-slate-900 rounded-2xl shadow-lg border border-slate-800 p-5 space-y-4">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                    <div>
                        <h3 class="font-bold text-slate-200 text-sm flex items-center gap-2">
                            <i class="fa-solid fa-table-cells text-emerald-400"></i>
                            مصفوفة مقارنة التخصصات عبر السنوات (العلامة والنسبة المئوية)
                        </h3>
                        <p class="text-xs text-slate-400 mt-0.5">مقارنة درجات كل كلية جنباً إلى جنب مع النسبة المئوية المحسوبة تلقائياً</p>
                    </div>
                    
                    <div class="flex items-center gap-2">
                        <select id="matrixTypeSelect" onchange="loadMatrix()" class="text-xs font-bold bg-slate-950 text-slate-200 border border-slate-800 rounded-xl p-2 focus:ring-1 focus:ring-emerald-500">
                            <option value="عام">القبول العام فقط</option>
                            <option value="موازي">الموازي فقط</option>
                        </select>
                        <select id="matrixRoundSelect" onchange="loadMatrix()" class="text-xs font-bold bg-slate-950 text-slate-200 border border-slate-800 rounded-xl p-2 focus:ring-1 focus:ring-emerald-500">
                            <option value="">نتائج ومفاضلة أولى</option>
                            <option value="إعلان نتيجة" selected>إعلان نتيجة فقط</option>
                            <option value="مفاضلة أولى">مفاضلة أولى فقط</option>
                        </select>
                        <input type="text" id="matrixSearchInput" placeholder="تصفية اختصاص..." oninput="filterMatrixRows()" 
                               class="text-xs bg-slate-950 text-slate-200 border border-slate-800 rounded-xl px-3 py-2 focus:ring-1 focus:ring-emerald-500 focus:outline-none">
                    </div>
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-right text-xs">
                        <thead id="matrixHead" class="bg-slate-950/90 text-slate-300 font-black border-b border-slate-800">
                            <!-- Dynamic Matrix Header -->
                        </thead>
                        <tbody id="matrixBody" class="divide-y divide-slate-800/60 font-mono">
                            <!-- Dynamic Matrix Body -->
                        </tbody>
                    </table>
                </div>
            </div>

        </div>

        <!-- TAB 3: MANUAL / SCANNED FILES ASSISTANT -->
        <div id="manual-tab" class="hidden space-y-6">
            <div class="bg-gradient-to-r from-amber-950/40 to-slate-900 border border-amber-800/60 p-5 rounded-2xl">
                <div class="flex items-start gap-3">
                    <div class="p-3 bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded-xl text-xl shadow-md">
                        <i class="fa-solid fa-triangle-exclamation"></i>
                    </div>
                    <div>
                        <h3 class="font-bold text-amber-300 text-base">مساعد استكمال الملفات الممسوحة ضوئياً (Scanned Documents)</h3>
                        <p class="text-xs text-amber-200/80 leading-relaxed mt-1">
                            الملفات المدرجة أدناه عبارة عن صور ممسوحة ضوئياً أو منشورات تيليغرام لم تحتوِ على نصوص رقمية قابلة للاستخراج الآلي المباشر.
                            يمكنك النقر على زر <strong>"إضافة بيانات لهذا الملف"</strong> لفتح نافذة الإدخال مع ملء السنة والبيانات الافتراضية تلقائياً لإدخال درجاتها في قاعدة البيانات بكل سرعة.
                        </p>
                    </div>
                </div>
            </div>

            <div class="bg-slate-900 rounded-2xl shadow-lg border border-slate-800 overflow-hidden">
                <div class="px-6 py-4 bg-slate-950/70 border-b border-slate-800 flex items-center justify-between">
                    <h3 class="font-bold text-slate-200">قائمة ملفات المفاضلة التي تحتاج تدقيقاً أو إدخالاً يدوياً</h3>
                    <span class="text-xs text-slate-400">إجمالي الملفات: {{ scanned_files|length }}</span>
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-right text-sm">
                        <thead class="bg-slate-950/80 text-slate-400 text-xs font-black border-b border-slate-800">
                            <tr>
                                <th class="py-3.5 px-4">اسم ملف الـ PDF</th>
                                <th class="py-3.5 px-3 text-center">السنة</th>
                                <th class="py-3.5 px-3 text-center">النوع</th>
                                <th class="py-3.5 px-3 text-center">المرحلة المقترحة</th>
                                <th class="py-3.5 px-3 text-center">الحالة الحالية</th>
                                <th class="py-3.5 px-4 text-center">الإجراء السريع</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-800/60">
                            {% for sf in scanned_files %}
                            <tr class="hover:bg-slate-800/40 transition-colors">
                                <td class="py-3.5 px-4 font-semibold text-slate-200 flex items-center gap-2">
                                    <i class="fa-solid fa-file-pdf text-rose-500 text-base"></i>
                                    <span>{{ sf.filename }}</span>
                                </td>
                                <td class="py-3.5 px-3 text-center font-bold text-slate-300">{{ sf.year or 'غير محدد' }}</td>
                                <td class="py-3.5 px-3 text-center">
                                    <span class="text-xs px-2.5 py-0.5 rounded-full font-bold {% if sf.admission_type == 'عام' %}bg-blue-950/70 text-blue-300 border border-blue-800/60{% else %}bg-purple-950/70 text-purple-300 border border-purple-800/60{% endif %}">
                                        {{ sf.admission_type }}
                                    </span>
                                </td>
                                <td class="py-3.5 px-3 text-center">
                                    <span class="text-xs px-2.5 py-0.5 rounded-full font-bold {% if sf.round_type == 'مفاضلة أولى' %}bg-amber-950/70 text-amber-300 border border-amber-800/60{% else %}bg-emerald-950/70 text-emerald-300 border border-emerald-800/60{% endif %}">
                                        {{ sf.round_type }}
                                    </span>
                                </td>
                                <td class="py-3.5 px-3 text-center">
                                    {% if sf.is_scanned %}
                                    <span class="text-xs px-2.5 py-0.5 rounded-full font-bold bg-amber-950/70 text-amber-300 border border-amber-800/60 flex items-center justify-center gap-1 w-max mx-auto">
                                        <i class="fa-solid fa-image text-[10px]"></i> صورة ممسوحة ضوئياً
                                    </span>
                                    {% else %}
                                    <span class="text-xs px-2.5 py-0.5 rounded-full font-bold bg-slate-800 text-slate-300 border border-slate-700">
                                        مستخرج جزئياً
                                    </span>
                                    {% endif %}
                                </td>
                                <td class="py-3.5 px-4 text-center">
                                    <button onclick="prefillAddModal('{{ sf.year }}', '{{ sf.admission_type }}', '{{ sf.round_type }}')" 
                                            class="bg-emerald-950/60 hover:bg-emerald-900 text-emerald-300 hover:text-emerald-200 text-xs font-bold px-3 py-1.5 rounded-lg border border-emerald-700/60 transition-colors flex items-center gap-1.5 mx-auto">
                                        <i class="fa-solid fa-plus-circle"></i>
                                        <span>إضافة بيانات لهذا الملف</span>
                                    </button>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- TAB 4: CHART -->
        <div id="chart-tab" class="hidden space-y-6">
            <div class="bg-slate-900 p-6 rounded-2xl shadow-lg border border-slate-800">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
                    <div>
                        <h3 class="font-bold text-slate-200 text-base flex items-center gap-2">
                            <i class="fa-solid fa-chart-area text-emerald-400"></i>
                            منحنى تطور معدلات القبول الفعلي عبر السنوات (2014 - 2026)
                        </h3>
                        <p class="text-xs text-slate-400 mt-1">يعكس المخطط متوسط الحدود الدنيا المسجلة لاختصاصات الهندسة والمعاهد التقانية</p>
                    </div>
                    <select id="chartSpecSelect" onchange="updateChart()" class="text-xs font-bold bg-slate-950 text-slate-200 border border-slate-800 rounded-xl p-2.5 focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500">
                        <option value="الهندسة المعلوماتية">الهندسة المعلوماتية</option>
                        <option value="هندسة الحواسيب">هندسة الحواسيب / الأتمتة</option>
                        <option value="الكلية التطبيقية">الكلية التطبيقية (تقنيات حاسوب)</option>
                        <option value="المعهد التقاني للحاسوب">المعهد التقاني للحاسوب</option>
                    </select>
                </div>
                <div class="h-80 sm:h-96 w-full">
                    <canvas id="scoresChart"></canvas>
                </div>
            </div>
        </div>

    </main>

    <!-- Modal 1: Add / Edit Record -->
    <div id="recordModal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
        <div class="bg-slate-900 rounded-3xl max-w-lg w-full shadow-2xl border border-slate-800 overflow-hidden transform transition-all text-slate-100">
            <div class="px-6 py-4 bg-gradient-to-r from-emerald-950 via-slate-900 to-slate-900 border-b border-slate-800 text-white flex items-center justify-between">
                <h3 id="modalTitle" class="font-black text-base flex items-center gap-2 text-emerald-400">
                    <i class="fa-solid fa-pen-nib"></i>
                    <span>إضافة سجل جديد</span>
                </h3>
                <button onclick="closeModal()" class="text-slate-400 hover:text-white text-lg">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>

            <form id="recordForm" onsubmit="saveRecord(event)" class="p-6 space-y-4">
                <input type="hidden" id="recordId" value="">

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-bold text-slate-400 mb-1">السنة الدراسية *</label>
                        <input type="number" id="formYear" min="2010" max="2030" required placeholder="مثال: 2025" oninput="updateModalPercentage()"
                               class="w-full p-2.5 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 mb-1">نوع القبول *</label>
                        <select id="formAdmType" required class="w-full p-2.5 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                            <option value="عام">عام</option>
                            <option value="موازي">موازي</option>
                        </select>
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-bold text-slate-400 mb-1">نوع الإعلان / المرحلة *</label>
                        <select id="formRoundType" required class="w-full p-2.5 text-sm bg-slate-950 border border-slate-800 text-emerald-300 font-bold rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                            <option value="إعلان نتيجة">إعلان نتيجة (الحد الأدنى الفعلي)</option>
                            <option value="مفاضلة أولى">مفاضلة أولى (شروط التقدم)</option>
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 mb-1">العلامة أو الدرجة *</label>
                        <input type="number" step="0.1" id="formScore" min="50" max="3500" required placeholder="مثال: 2310" oninput="updateModalPercentage()"
                               class="w-full p-2.5 text-sm bg-slate-950 border border-slate-800 text-emerald-400 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none font-bold">
                    </div>
                </div>

                <!-- Real-time Percentage Indicator -->
                <div id="modalPercentageBox" class="p-2.5 bg-slate-950 border border-slate-800 rounded-xl flex items-center justify-between text-xs">
                    <span class="text-slate-400 flex items-center gap-1.5">
                        <i class="fa-solid fa-calculator text-amber-400"></i>
                        <span>النسبة المئوية المحسوبة:</span>
                    </span>
                    <span id="modalPercentageValue" class="font-black text-amber-400 text-sm">--%</span>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div class="col-span-2">
                        <label class="block text-xs font-bold text-slate-400 mb-1">الجامعة *</label>
                        <input type="text" id="formUniversity" required list="universitiesList" placeholder="جامعة دمشق، حلب..."
                               class="w-full p-2.5 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                        <datalist id="universitiesList">
                            {% for u in universities %}
                            <option value="{{ u }}"></option>
                            {% endfor %}
                        </datalist>
                    </div>
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-400 mb-1">اسم الاختصاص / الكلية / المعهد *</label>
                    <input type="text" id="formSpec" required list="specializationList" placeholder="مثال: الهندسة المعلوماتية، المعهد التقاني للحاسوب..."
                           class="w-full p-2.5 text-sm bg-slate-950 border border-slate-800 text-slate-100 rounded-xl focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 focus:outline-none">
                    <datalist id="specializationList">
                        <option value="الهندسة المعلوماتية"></option>
                        <option value="هندسة الحواسيب واألتمتة"></option>
                        <option value="هندسة الحواسيب"></option>
                        <option value="هندسة التحكم اآللي والحواسيب"></option>
                        <option value="الكلية التطبيقية (تقنيات حاسوب)"></option>
                        <option value="المعهد التقاني للحاسوب"></option>
                        <option value="هندسة االتصاالت واإللكترونيات"></option>
                        <option value="الهندسة التقنية (أتمتة صناعية)"></option>
                    </datalist>
                </div>

                <div class="pt-4 border-t border-slate-800 flex items-center justify-end gap-2">
                    <button type="button" onclick="closeModal()" class="px-4 py-2 text-xs font-bold text-slate-400 hover:text-slate-200 bg-slate-800 rounded-xl hover:bg-slate-700 transition-colors">
                        إلغاء
                    </button>
                    <button type="submit" class="px-5 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-500 rounded-xl shadow-md transition-colors flex items-center gap-1.5">
                        <i class="fa-solid fa-save"></i>
                        <span>حفظ السجل في قاعدة البيانات</span>
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- Modal 2: Bulk Edit Year Settings (المجاميع السنوية للشهادة الثانوية) -->
    <div id="yearSettingsModal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
        <div class="bg-slate-900 rounded-3xl max-w-lg w-full shadow-2xl border border-slate-800 overflow-hidden transform transition-all text-slate-100">
            <div class="px-6 py-4 bg-gradient-to-r from-amber-950 via-slate-900 to-slate-900 border-b border-slate-800 text-white flex items-center justify-between">
                <h3 class="font-black text-base flex items-center gap-2 text-amber-400">
                    <i class="fa-solid fa-sliders"></i>
                    <span>إعداد المجموع العام للشهادة الثانوية لكل سنة</span>
                </h3>
                <button onclick="closeYearSettingsModal()" class="text-slate-400 hover:text-white text-lg">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>

            <div class="p-6 space-y-4">
                <p class="text-xs text-slate-400 leading-relaxed">
                    حدد المجموع العام الكامل للشهادة الثانوية العامة (الفرع العلمي) لكل سنة دراسية، وسيتم على أساسه حساب وتحديث النسبة المئوية (%) لكافة الاختصاصات آلياً:
                </p>

                <div class="max-h-72 overflow-y-auto space-y-2 pr-1" id="yearSettingsInputsList">
                    <!-- Populated dynamically via JS -->
                </div>

                <div class="pt-4 border-t border-slate-800 flex items-center justify-end gap-2">
                    <button type="button" onclick="closeYearSettingsModal()" class="px-4 py-2 text-xs font-bold text-slate-400 hover:text-slate-200 bg-slate-800 rounded-xl hover:bg-slate-700 transition-colors">
                        إلغاء
                    </button>
                    <button type="button" onclick="saveYearSettingsBulk()" class="px-5 py-2 text-xs font-bold text-white bg-amber-600 hover:bg-amber-500 rounded-xl shadow-md transition-colors flex items-center gap-1.5">
                        <i class="fa-solid fa-save"></i>
                        <span>حفظ وتحديث النسب المئوية</span>
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Client-side Logic -->
    <script>
        let allData = [];
        let filteredData = [];
        let yearSettings = {};
        let currentPage = 1;
        const pageSize = 20;
        let chartInstance = null;
        let matrixCache = null;

        // Custom SweetAlert2 Dark Theme Defaults
        const DarkSwal = Swal.mixin({
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#059669',
            cancelButtonColor: '#475569'
        });

        document.addEventListener('DOMContentLoaded', async () => {
            await loadYearSettings();
            await loadData();
            initChart();
            updateChart();
        });

        async function loadYearSettings() {
            try {
                const res = await fetch('/api/year-settings');
                yearSettings = await res.json();
            } catch (err) {
                console.error("Error loading year settings:", err);
            }
        }

        async function loadData() {
            try {
                const res = await fetch('/api/data');
                allData = await res.json();
                filteredData = [...allData];
                document.getElementById('tabTotalBadge').innerText = allData.length;
                renderTable();
            } catch (err) {
                console.error("Error loading data:", err);
            }
        }

        function switchTab(tabId) {
            ['data-tab', 'audit-tab', 'manual-tab', 'chart-tab'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.classList.add('hidden');
                const btn = document.getElementById(`btn-${id}`);
                if (btn) {
                    btn.classList.remove('border-emerald-500', 'text-emerald-400');
                    btn.classList.add('border-transparent', 'text-slate-400');
                }
            });

            const activeContent = document.getElementById(tabId);
            if (activeContent) activeContent.classList.remove('hidden');
            const activeBtn = document.getElementById(`btn-${tabId}`);
            if (activeBtn) {
                activeBtn.classList.remove('border-transparent', 'text-slate-400');
                activeBtn.classList.add('border-emerald-500', 'text-emerald-400');
            }

            if (tabId === 'chart-tab') {
                setTimeout(updateChart, 50);
            } else if (tabId === 'audit-tab') {
                if (!matrixCache) loadMatrix();
            }
        }

        // Fast Year Quick Pill Filter
        function quickSelectYear(year) {
            document.querySelectorAll('.year-pill').forEach(p => {
                p.classList.remove('bg-emerald-600', 'text-white');
                p.classList.add('bg-slate-950', 'text-slate-300');
            });

            const activePill = document.getElementById(year ? `pill-${year}` : 'pill-all');
            if (activePill) {
                activePill.classList.remove('bg-slate-950', 'text-slate-300');
                activePill.classList.add('bg-emerald-600', 'text-white');
            }

            document.getElementById('yearSelect').value = year;
            applyFilters();
        }

        function quickFilterFromCard(year) {
            switchTab('data-tab');
            quickSelectYear(year);
        }

        function applyFilters() {
            const query = document.getElementById('searchInput').value.trim().toLowerCase();
            const year = document.getElementById('yearSelect').value;
            const uni = document.getElementById('uniSelect').value;
            const type = document.getElementById('typeSelect').value;
            const roundType = document.getElementById('roundSelect').value;

            filteredData = allData.filter(row => {
                if (query && !row.specialization.toLowerCase().includes(query) && !row.university.toLowerCase().includes(query)) return false;
                if (year && row.year != year) return false;
                if (uni && row.university != uni) return false;
                if (type && row.admission_type != type) return false;
                if (roundType && row.round_type != roundType) return false;
                return true;
            });

            currentPage = 1;
            renderTable();
        }

        function resetFilters() {
            document.getElementById('searchInput').value = '';
            document.getElementById('yearSelect').value = '';
            document.getElementById('uniSelect').value = '';
            document.getElementById('typeSelect').value = '';
            document.getElementById('roundSelect').value = '';
            quickSelectYear('');
        }

        function renderTable() {
            const tbody = document.getElementById('tableBody');
            const noData = document.getElementById('noDataMessage');
            const badge = document.getElementById('filteredCountBadge');
            badge.innerText = `${filteredData.length} سطر`;

            if (filteredData.length === 0) {
                tbody.innerHTML = '';
                noData.classList.remove('hidden');
                document.getElementById('pageInfo').innerText = 'لا توجد نتائج';
                document.getElementById('paginationControls').innerHTML = '';
                return;
            }

            noData.classList.add('hidden');
            const start = (currentPage - 1) * pageSize;
            const end = start + pageSize;
            const pageRows = filteredData.slice(start, end);

            tbody.innerHTML = pageRows.map((r, i) => {
                const isAam = r.admission_type === 'عام';
                const typeBadge = isAam
                    ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold bg-blue-950/70 text-blue-300 border border-blue-800/60">عام</span>`
                    : `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold bg-purple-950/70 text-purple-300 border border-purple-800/60">موازي</span>`;

                const isFinal = r.round_type === 'إعلان نتيجة';
                const roundBadge = isFinal
                    ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-950/70 text-emerald-300 border border-emerald-800/60"><i class="fa-solid fa-check-double ml-1 text-[10px]"></i> إعلان نتيجة</span>`
                    : `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold bg-amber-950/70 text-amber-300 border border-amber-800/60"><i class="fa-solid fa-list-check ml-1 text-[10px]"></i> مفاضلة أولى</span>`;

                const maxScore = yearSettings[r.year] || r.max_score || 2400;
                const percentage = ((r.score / maxScore) * 100).toFixed(2);

                return `
                    <tr class="hover:bg-slate-800/40 transition-colors">
                        <td class="py-3 px-3 text-center text-xs font-semibold text-slate-500">${start + i + 1}</td>
                        <td class="py-3 px-3 font-bold text-slate-200">${r.year}</td>
                        <td class="py-3 px-3 font-semibold text-slate-300">${r.university}</td>
                        <td class="py-3 px-4 text-slate-200 font-medium">${r.specialization}</td>
                        <td class="py-3 px-3 text-center">${typeBadge}</td>
                        <td class="py-3 px-3 text-center">${roundBadge}</td>
                        <td class="py-3 px-3 text-center">
                            <div class="inline-flex flex-col items-center">
                                <span onclick="inlineEditScore(${r.id}, ${r.score})" title="انقر لتعديل العلامة فورياً" 
                                      class="cursor-pointer font-black text-emerald-400 hover:text-emerald-300 text-base px-2 py-0.5 rounded-lg hover:bg-slate-800 transition-colors">
                                    ${r.score}
                                </span>
                                <span class="text-[10px] font-bold px-1.5 py-0.2 rounded bg-slate-950 text-amber-300 border border-slate-800" title="المجموع العام لعام ${r.year}: ${maxScore}">
                                    ${percentage}%
                                </span>
                            </div>
                        </td>
                        <td class="py-3 px-3 text-center">
                            <div class="flex items-center justify-center gap-1.5">
                                <button onclick="openEditModal(${r.id})" title="تعديل السطر بالكامل" class="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-emerald-950/60 rounded-lg transition-colors">
                                    <i class="fa-solid fa-pen text-xs"></i>
                                </button>
                                <button onclick="deleteRecord(${r.id})" title="حذف السطر" class="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-950/60 rounded-lg transition-colors">
                                    <i class="fa-solid fa-trash-can text-xs"></i>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');

            renderPagination();
        }

        function renderPagination() {
            const totalPages = Math.ceil(filteredData.length / pageSize);
            document.getElementById('pageInfo').innerText = `عرض صفحة ${currentPage} من ${totalPages}`;
            const controls = document.getElementById('paginationControls');

            let html = '';
            if (currentPage > 1) {
                html += `<button onclick="goToPage(${currentPage - 1})" class="px-2.5 py-1 bg-slate-800 border border-slate-700 text-slate-300 rounded-md hover:bg-slate-700 font-bold">&laquo; السابق</button>`;
            }
            if (currentPage < totalPages) {
                html += `<button onclick="goToPage(${currentPage + 1})" class="px-2.5 py-1 bg-slate-800 border border-slate-700 text-slate-300 rounded-md hover:bg-slate-700 font-bold">التالي &raquo;</button>`;
            }
            controls.innerHTML = html;
        }

        function goToPage(page) {
            currentPage = page;
            renderTable();
        }

        // Quick Inline Score Edit
        async function inlineEditScore(id, oldScore) {
            const { value: newScore } = await DarkSwal.fire({
                title: 'تعديل سريع للعلامة',
                input: 'number',
                inputLabel: 'أدخل العلامة الجديدة:',
                inputValue: oldScore,
                showCancelButton: true,
                inputValidator: (val) => {
                    if (!val || val <= 0) return 'يرجى إدخال علامة صحيحة';
                }
            });

            if (newScore && parseFloat(newScore) !== oldScore) {
                const rec = allData.find(r => r.id === id);
                if (!rec) return;

                const payload = {
                    year: rec.year,
                    admission_type: rec.admission_type,
                    round_type: rec.round_type,
                    university: rec.university,
                    specialization: rec.specialization,
                    score: parseFloat(newScore)
                };

                const res = await fetch(`/api/records/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const resJson = await res.json();
                if (resJson.success) {
                    DarkSwal.fire({ title: 'تم التحديث!', icon: 'success', timer: 1000, showConfirmButton: false });
                    await loadData();
                    updateChart();
                    if (matrixCache) loadMatrix();
                }
            }
        }

        // ==========================================
        // Year Settings (المجاميع السنوية)
        // ==========================================
        async function editYearMaxScore(year, currentMax) {
            const { value: newMax } = await DarkSwal.fire({
                title: `المجموع العام لسنة ${year}`,
                input: 'number',
                inputLabel: `حدد المجموع الكلي للشهادة الثانوية العامة لسنة ${year}:`,
                inputValue: currentMax || 2400,
                showCancelButton: true,
                inputValidator: (val) => {
                    if (!val || val < 1000 || val > 4000) return 'يرجى إدخال مجموع عام صحيح (مثال: 2400 أو 3000)';
                }
            });

            if (newMax) {
                const res = await fetch('/api/year-settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ year: parseInt(year), max_score: parseFloat(newMax) })
                });
                const resJson = await res.json();
                if (resJson.success) {
                    DarkSwal.fire({ title: 'تم تحديث المجموع العام!', icon: 'success', timer: 1200, showConfirmButton: false });
                    await loadYearSettings();
                    await loadData();
                    if (matrixCache) loadMatrix();
                }
            }
        }

        function openYearSettingsModal() {
            const container = document.getElementById('yearSettingsInputsList');
            const years = Object.keys(yearSettings).map(Number).sort((a, b) => b - a);

            let html = '';
            years.forEach(y => {
                const maxVal = yearSettings[y] || 2400;
                html += `
                    <div class="flex items-center justify-between bg-slate-950 p-2.5 rounded-xl border border-slate-800">
                        <span class="font-bold text-slate-200 text-xs">${y}</span>
                        <div class="flex items-center gap-2">
                            <span class="text-[11px] text-slate-400">المجموع:</span>
                            <input type="number" id="setting-year-${y}" value="${maxVal}" 
                                   class="w-24 p-1.5 text-xs bg-slate-900 border border-slate-700 text-amber-300 font-bold rounded-lg text-center focus:ring-1 focus:ring-amber-500 focus:outline-none">
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
            document.getElementById('yearSettingsModal').classList.remove('hidden');
        }

        function closeYearSettingsModal() {
            document.getElementById('yearSettingsModal').classList.add('hidden');
        }

        async function saveYearSettingsBulk() {
            const years = Object.keys(yearSettings).map(Number);
            const settingsList = [];

            years.forEach(y => {
                const input = document.getElementById(`setting-year-${y}`);
                if (input && input.value) {
                    settingsList.push({
                        year: y,
                        max_score: parseFloat(input.value)
                    });
                }
            });

            const res = await fetch('/api/year-settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: settingsList })
            });

            const resJson = await res.json();
            if (resJson.success) {
                closeYearSettingsModal();
                DarkSwal.fire({ title: 'تم الحفظ بنجاح!', text: 'تم تحديث المجاميع والنسب المئوية لكافة السنوات.', icon: 'success', timer: 1500, showConfirmButton: false });
                await loadYearSettings();
                await loadData();
                if (matrixCache) loadMatrix();
            }
        }

        // ==========================================
        // Modal Live Percentage Feedback
        // ==========================================
        function updateModalPercentage() {
            const year = parseInt(document.getElementById('formYear').value);
            const score = parseFloat(document.getElementById('formScore').value);
            const valEl = document.getElementById('modalPercentageValue');

            if (year && score && score > 0) {
                const maxScore = yearSettings[year] || 2400;
                const pct = ((score / maxScore) * 100).toFixed(2);
                valEl.innerText = `${pct}% (المجموع العام: ${maxScore})`;
            } else {
                valEl.innerText = '--%';
            }
        }

        // ==========================================
        // Cross-Year Comparative Matrix Logic
        // ==========================================
        async function loadMatrix() {
            const type = document.getElementById('matrixTypeSelect').value;
            const round = document.getElementById('matrixRoundSelect').value;
            try {
                const res = await fetch(`/api/matrix?type=${encodeURIComponent(type)}&round=${encodeURIComponent(round)}`);
                matrixCache = await res.json();
                renderMatrix();
            } catch (err) {
                console.error("Matrix error:", err);
            }
        }

        function filterMatrixRows() {
            renderMatrix();
        }

        function renderMatrix() {
            if (!matrixCache) return;
            const searchVal = document.getElementById('matrixSearchInput').value.trim().toLowerCase();
            const { years, rows } = matrixCache;

            // Render Header
            let headHtml = `
                <tr>
                    <th class="py-3 px-3 text-right">الجامعة والاختصاص</th>
            `;
            years.forEach(y => {
                const maxS = yearSettings[y] || 2400;
                headHtml += `
                    <th class="py-3 px-2 text-center text-xs font-bold text-slate-300 border-r border-slate-800/80">
                        <div>${y}</div>
                        <div class="text-[9px] text-amber-400 font-normal">/${maxS}</div>
                    </th>
                `;
            });
            headHtml += `</tr>`;
            document.getElementById('matrixHead').innerHTML = headHtml;

            // Render Rows
            const filteredRows = rows.filter(r => {
                if (!searchVal) return true;
                return r.university.toLowerCase().includes(searchVal) || r.specialization.toLowerCase().includes(searchVal);
            });

            let bodyHtml = '';
            filteredRows.forEach(r => {
                bodyHtml += `
                    <tr class="hover:bg-slate-800/30">
                        <td class="py-2.5 px-3">
                            <span class="font-bold text-slate-200 block text-xs">${r.specialization}</span>
                            <span class="text-[10px] text-slate-400 block">${r.university}</span>
                        </td>
                `;

                years.forEach(y => {
                    const cell = r.scores[y];
                    if (cell) {
                        const maxS = yearSettings[y] || 2400;
                        const pct = ((cell.score / maxS) * 100).toFixed(1);
                        bodyHtml += `
                            <td class="py-2 px-1.5 text-center border-r border-slate-800/60">
                                <div onclick="inlineEditScore(${cell.id}, ${cell.score})" title="${cell.round_type} - انقر للتعديل" 
                                     class="cursor-pointer font-bold px-1.5 py-0.5 rounded bg-emerald-950/40 hover:bg-emerald-900 border border-emerald-800/60 block">
                                    <span class="text-emerald-400 text-xs block">${cell.score}</span>
                                    <span class="text-amber-300 text-[10px] font-normal block">${pct}%</span>
                                </div>
                            </td>
                        `;
                    } else {
                        const currentType = document.getElementById('matrixTypeSelect').value;
                        const currentRound = document.getElementById('matrixRoundSelect').value || 'إعلان نتيجة';
                        bodyHtml += `
                            <td class="py-2 px-1.5 text-center border-r border-slate-800/60">
                                <button onclick="quickAddFromMatrix('${y}', '${encodeURIComponent(r.university)}', '${encodeURIComponent(r.specialization)}', '${currentType}', '${currentRound}')" 
                                        title="إضافة علامة لسنة ${y}" 
                                        class="text-[10px] text-slate-600 hover:text-emerald-400 p-1 hover:bg-slate-800 rounded transition-colors">
                                    <i class="fa-solid fa-plus"></i>
                                </button>
                            </td>
                        `;
                    }
                });

                bodyHtml += `</tr>`;
            });

            document.getElementById('matrixBody').innerHTML = bodyHtml || `<tr><td colspan="${years.length + 1}" class="py-8 text-center text-slate-500">لا توجد اختصاصات مطابقة للبحث</td></tr>`;
        }

        function quickAddFromMatrix(year, uniEnc, specEnc, admType, roundType) {
            openAddModal();
            document.getElementById('formYear').value = year;
            document.getElementById('formUniversity').value = decodeURIComponent(uniEnc);
            document.getElementById('formSpec').value = decodeURIComponent(specEnc);
            document.getElementById('formAdmType').value = admType;
            document.getElementById('formRoundType').value = roundType || 'إعلان نتيجة';
            updateModalPercentage();
            document.getElementById('formScore').focus();
        }

        // Modal Operations (Add / Edit)
        function openAddModal() {
            document.getElementById('modalTitle').innerHTML = '<i class="fa-solid fa-plus-circle text-emerald-400"></i> إضافة اختصاص جديد لقاعدة البيانات';
            document.getElementById('recordId').value = '';
            document.getElementById('formYear').value = new Date().getFullYear();
            document.getElementById('formAdmType').value = 'عام';
            document.getElementById('formRoundType').value = 'إعلان نتيجة';
            document.getElementById('formUniversity').value = '';
            document.getElementById('formSpec').value = '';
            document.getElementById('formScore').value = '';
            updateModalPercentage();
            document.getElementById('recordModal').classList.remove('hidden');
        }

        function prefillAddModal(year, admType, roundType) {
            openAddModal();
            if (year && year !== 'None') document.getElementById('formYear').value = year;
            if (admType) document.getElementById('formAdmType').value = admType;
            if (roundType) document.getElementById('formRoundType').value = roundType;
            updateModalPercentage();
        }

        function openEditModal(id) {
            const rec = allData.find(r => r.id === id);
            if (!rec) return;

            document.getElementById('modalTitle').innerHTML = '<i class="fa-solid fa-pen-to-square text-emerald-400"></i> تعديل بيانات السجل';
            document.getElementById('recordId').value = rec.id;
            document.getElementById('formYear').value = rec.year;
            document.getElementById('formAdmType').value = rec.admission_type;
            document.getElementById('formRoundType').value = rec.round_type || 'إعلان نتيجة';
            document.getElementById('formUniversity').value = rec.university;
            document.getElementById('formSpec').value = rec.specialization;
            document.getElementById('formScore').value = rec.score;
            updateModalPercentage();
            document.getElementById('recordModal').classList.remove('hidden');
        }

        function closeModal() {
            document.getElementById('recordModal').classList.add('hidden');
        }

        async function saveRecord(e) {
            e.preventDefault();
            const id = document.getElementById('recordId').value;
            const payload = {
                year: parseInt(document.getElementById('formYear').value),
                admission_type: document.getElementById('formAdmType').value,
                round_type: document.getElementById('formRoundType').value,
                university: document.getElementById('formUniversity').value.trim(),
                specialization: document.getElementById('formSpec').value.trim(),
                score: parseFloat(document.getElementById('formScore').value)
            };

            const url = id ? `/api/records/${id}` : '/api/records';
            const method = id ? 'PUT' : 'POST';

            try {
                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await res.json();
                if (result.success) {
                    closeModal();
                    DarkSwal.fire({
                        title: id ? 'تم التعديل بنجاح!' : 'تمت الإضافة بنجاح!',
                        text: 'تم تحديث قاعدة البيانات وحساب النسبة المئوية فورياً.',
                        icon: 'success',
                        timer: 1500,
                        showConfirmButton: false
                    });
                    await loadData();
                    updateChart();
                    if (matrixCache) loadMatrix();
                } else {
                    DarkSwal.fire('خطأ', result.error || 'تعذر حفظ السجل', 'error');
                }
            } catch (err) {
                DarkSwal.fire('خطأ', 'حدث خطأ في الاتصال بالخادم', 'error');
            }
        }

        async function deleteRecord(id) {
            const confirm = await DarkSwal.fire({
                title: 'هل أنت متأكد من الحذف؟',
                text: 'سيتم حذف هذا السطر نهائياً من قاعدة البيانات!',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#e11d48',
                cancelButtonColor: '#475569',
                confirmButtonText: 'نعم، احذفه',
                cancelButtonText: 'إلغاء'
            });

            if (!confirm.isConfirmed) return;

            try {
                const res = await fetch(`/api/records/${id}`, { method: 'DELETE' });
                const result = await res.json();
                if (result.success) {
                    DarkSwal.fire({
                        title: 'تم الحذف!',
                        icon: 'success',
                        timer: 1200,
                        showConfirmButton: false
                    });
                    await loadData();
                    updateChart();
                    if (matrixCache) loadMatrix();
                }
            } catch (err) {
                DarkSwal.fire('خطأ', 'تعذر حذف السجل', 'error');
            }
        }

        function exportCSV() {
            if (!filteredData.length) return;
            const headers = ["السنة", "الجامعة", "الاختصاص", "نوع القبول", "نوع الإعلان", "الحد الأدنى", "المجموع العام للسنة", "النسبة المئوية %"];
            const rows = filteredData.map(r => {
                const maxS = yearSettings[r.year] || r.max_score || 2400;
                const pct = ((r.score / maxS) * 100).toFixed(2);
                return [
                    r.year,
                    `"${r.university}"`,
                    `"${r.specialization}"`,
                    r.admission_type,
                    r.round_type,
                    r.score,
                    maxS,
                    `${pct}%`
                ];
            });

            const csvContent = "\\uFEFF" + [headers.join(","), ...rows.map(e => e.join(","))].join("\\n");
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = `mofadala_curated_${new Date().toISOString().slice(0,10)}.csv`;
            link.click();
        }

        // Charts Logic
        function initChart() {
            const ctx = document.getElementById('scoresChart').getContext('2d');
            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'إعلان نتيجة - عام',
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.15)',
                            data: [],
                            fill: true,
                            tension: 0.3,
                            borderWidth: 3,
                            pointRadius: 5,
                            pointBackgroundColor: '#10b981'
                        },
                        {
                            label: 'إعلان نتيجة - موازي',
                            borderColor: '#a855f7',
                            backgroundColor: 'rgba(168, 85, 247, 0.1)',
                            data: [],
                            fill: true,
                            tension: 0.3,
                            borderWidth: 2,
                            borderDash: [5, 5],
                            pointRadius: 4,
                            pointBackgroundColor: '#a855f7'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { 
                            position: 'top', 
                            rtl: true, 
                            labels: { 
                                font: { family: 'Cairo', weight: 'bold' },
                                color: '#cbd5e1'
                            } 
                        },
                        tooltip: { 
                            rtl: true, 
                            titleFont: { family: 'Cairo' }, 
                            bodyFont: { family: 'Cairo' },
                            backgroundColor: '#0f172a',
                            borderColor: '#334155',
                            borderWidth: 1,
                            titleColor: '#f8fafc',
                            bodyColor: '#cbd5e1'
                        }
                    },
                    scales: {
                        y: { 
                            min: 1000, 
                            max: 2500, 
                            ticks: { 
                                font: { family: 'Cairo' },
                                color: '#94a3b8'
                            },
                            grid: {
                                color: 'rgba(255, 255, 255, 0.06)'
                            }
                        },
                        x: { 
                            ticks: { 
                                font: { family: 'Cairo' },
                                color: '#94a3b8'
                            },
                            grid: {
                                color: 'rgba(255, 255, 255, 0.06)'
                            }
                        }
                    }
                }
            });
        }

        function updateChart() {
            if (!chartInstance) return;
            const specKey = document.getElementById('chartSpecSelect').value;
            const yearsMap = {};
            for (let y = 2014; y <= 2026; y++) {
                yearsMap[y] = { aam: [], muwazi: [] };
            }

            allData.forEach(r => {
                if (r.specialization.includes(specKey) && r.round_type === 'إعلان نتيجة') {
                    if (r.admission_type === 'عام') {
                        if (yearsMap[r.year]) yearsMap[r.year].aam.push(r.score);
                    } else if (r.admission_type === 'موازي') {
                        if (yearsMap[r.year]) yearsMap[r.year].muwazi.push(r.score);
                    }
                }
            });

            const labels = [];
            const dataAam = [];
            const dataMuwazi = [];

            Object.keys(yearsMap).forEach(y => {
                const item = yearsMap[y];
                if (item.aam.length || item.muwazi.length) {
                    labels.push(y);
                    const avgAam = item.aam.length ? (item.aam.reduce((a, b) => a + b, 0) / item.aam.length).toFixed(0) : null;
                    const avgMuwazi = item.muwazi.length ? (item.muwazi.reduce((a, b) => a + b, 0) / item.muwazi.length).toFixed(0) : null;
                    dataAam.push(avgAam);
                    dataMuwazi.push(avgMuwazi);
                }
            });

            chartInstance.data.labels = labels;
            chartInstance.data.datasets[0].data = dataAam;
            chartInstance.data.datasets[1].data = dataMuwazi;
            chartInstance.update();
        }
    </script>
</body>
</html>
"""

# =============================================================================
# AUTHENTICATION & LOGIN ROUTES
# =============================================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            session["username"] = username
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        else:
            error = "اسم المستخدم أو كلمة المرور غير صحيحة، يرجى المحاولة ثانية."

    return render_template_string(LOGIN_TEMPLATE, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =============================================================================
# REST API Endpoints for Full CRUD, Year Settings & Matrix
# =============================================================================

@app.route("/")
@login_required
def index():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM admission_data")
    total = c.fetchone()[0]
    
    c.execute("SELECT DISTINCT year FROM admission_data WHERE year IS NOT NULL ORDER BY year DESC")
    years = [row[0] for row in c.fetchall()]
    
    c.execute("SELECT DISTINCT university FROM admission_data WHERE university IS NOT NULL AND university != '' ORDER BY university")
    universities = [row[0] for row in c.fetchall()]
    conn.close()
    
    scanned_files = get_scanned_and_empty_files()
    years_summary, anomalies = get_year_audit_data()
    
    stats = {"total": total}
    return render_template_string(
        HTML_TEMPLATE, 
        stats=stats, 
        years=years, 
        universities=universities, 
        scanned_files=scanned_files,
        years_summary=years_summary,
        anomalies=anomalies,
        username=session.get("username", "admin@moazns.sy")
    )

@app.route("/api/year-settings", methods=["GET", "POST"])
@login_required
def api_year_settings():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == "POST":
        data = request.json or {}
        if "settings" in data:
            for item in data["settings"]:
                c.execute("""
                    INSERT INTO year_settings (year, max_score) VALUES (?, ?)
                    ON CONFLICT(year) DO UPDATE SET max_score = excluded.max_score
                """, (item["year"], float(item["max_score"])))
        elif "year" in data and "max_score" in data:
            c.execute("""
                INSERT INTO year_settings (year, max_score) VALUES (?, ?)
                ON CONFLICT(year) DO UPDATE SET max_score = excluded.max_score
            """, (data["year"], float(data["max_score"])))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
        
    c.execute("SELECT year, max_score FROM year_settings ORDER BY year DESC")
    settings = {r["year"]: r["max_score"] for r in c.fetchall()}
    conn.close()
    return jsonify(settings)

@app.route("/api/data")
@login_required
def api_data():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT 
            a.id, a.year, a.university, a.specialization, 
            a.admission_type, a.is_final_result, 
            COALESCE(a.round_type, CASE WHEN a.is_final_result = 1 THEN 'إعلان نتيجة' ELSE 'مفاضلة أولى' END) as round_type, 
            a.score,
            COALESCE(s.max_score, 2400) as max_score
        FROM admission_data a
        LEFT JOIN year_settings s ON a.year = s.year
        ORDER BY a.year DESC, a.score DESC
    """)
    rows = []
    for r in c.fetchall():
        d = dict(r)
        max_s = d["max_score"] if d["max_score"] and d["max_score"] > 0 else 2400
        d["percentage"] = round((d["score"] / max_s) * 100, 2)
        rows.append(d)
    conn.close()
    return jsonify(rows)

@app.route("/api/matrix")
@login_required
def api_matrix():
    adm_type = request.args.get("type", "عام")
    round_type = request.args.get("round", "")
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT DISTINCT year FROM admission_data WHERE year IS NOT NULL ORDER BY year DESC")
    years = [r[0] for r in c.fetchall()]
    
    query = """
        SELECT id, year, university, specialization, score, round_type 
        FROM admission_data 
        WHERE admission_type = ?
    """
    params = [adm_type]
    
    if round_type:
        query += " AND round_type = ?"
        params.append(round_type)
        
    query += " ORDER BY university, specialization, year DESC"
    
    c.execute(query, params)
    records = c.fetchall()
    conn.close()
    
    matrix_map = {}
    for r in records:
        key = (r["university"], r["specialization"])
        if key not in matrix_map:
            matrix_map[key] = {}
        matrix_map[key][r["year"]] = {
            "id": r["id"],
            "score": r["score"],
            "round_type": r["round_type"]
        }
        
    rows = []
    for (uni, spec), scores in matrix_map.items():
        rows.append({
            "university": uni,
            "specialization": spec,
            "scores": scores
        })
        
    rows.sort(key=lambda x: (x["university"], x["specialization"]))
    
    return jsonify({
        "years": years,
        "rows": rows
    })

@app.route("/api/records", methods=["POST"])
@login_required
def api_add_record():
    data = request.json
    if not data or "year" not in data or "score" not in data:
        return jsonify({"success": False, "error": "البيانات ناقصة"}), 400
        
    round_type = data.get("round_type") or ("إعلان نتيجة" if data.get("is_final_result") else "مفاضلة أولى")
    is_final = 1 if round_type == "إعلان نتيجة" else 0
    year = int(data.get("year"))

    conn = get_db_connection()
    c = conn.cursor()
    # تأكد من تسجيل السنة في year_settings
    c.execute("INSERT OR IGNORE INTO year_settings (year, max_score) VALUES (?, 2400)", (year,))
    
    c.execute("""
        INSERT INTO admission_data (year, university, specialization, admission_type, round_type, is_final_result, score)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        year,
        data.get("university"),
        data.get("specialization"),
        data.get("admission_type"),
        round_type,
        is_final,
        data.get("score")
    ))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"success": True, "id": new_id})

@app.route("/api/records/<int:rec_id>", methods=["PUT"])
@login_required
def api_update_record(rec_id):
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "لا توجد بيانات"}), 400
        
    round_type = data.get("round_type") or ("إعلان نتيجة" if data.get("is_final_result") else "مفاضلة أولى")
    is_final = 1 if round_type == "إعلان نتيجة" else 0
    year = int(data.get("year"))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO year_settings (year, max_score) VALUES (?, 2400)", (year,))
    c.execute("""
        UPDATE admission_data
        SET year = ?, university = ?, specialization = ?, admission_type = ?, round_type = ?, is_final_result = ?, score = ?
        WHERE id = ?
    """, (
        year,
        data.get("university"),
        data.get("specialization"),
        data.get("admission_type"),
        round_type,
        is_final,
        data.get("score"),
        rec_id
    ))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/records/<int:rec_id>", methods=["DELETE"])
@login_required
def api_delete_record(rec_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM admission_data WHERE id = ?", (rec_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/healthz")
def healthz():
    """Health check endpoint for Render (Unauthenticated)"""
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Mofadala Curated Dashboard at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
