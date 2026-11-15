#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
سكربت استخراج بيانات المفاضلات الجامعية السورية (2014 - 2026) إلى SQLite
=============================================================================
المؤلف: مهندس بيانات
الهدف:
قراءة وتحليل كافة ملفات PDF الخاصة بالمفاضلات الجامعية السورية في المجلد الحالي،
واستخراج بيانات الاختصاصات البرمجية وهندسة الحاسوب والمعلوماتية والأتمتة والاتصالات،
وتصحيح تشفير النصوص العربية المعكوسة وأخطاء الخطوط (Font glyph mappings)،
ثم حقن البيانات في قاعدة بيانات SQLite محلية باسم mofadala.db.

مخطط الجدول:
- id (INTEGER PRIMARY KEY)
- year (INTEGER)
- university (TEXT)
- specialization (TEXT)
- admission_type (TEXT) - (عام أو موازي)
- is_final_result (BOOLEAN) - (True للنتائج والحدود الدنيا، False لشروط التقدم)
- score (REAL) - (الحد الأدنى أو شرط التقدم)
=============================================================================
"""

import os
import glob
import re
import sqlite3
import unicodedata
import pdfplumber
from bidi.algorithm import get_display

# =============================================================================
# 1. إعدادات وقواعد الفلترة (Configuration & Rules)
# =============================================================================

DB_NAME = "mofadala.db"
TABLE_NAME = "admission_data"

# جدول استبدال لمحارف الخطوط القديمة أو المشوهة في ملفات الـ PDF السورية
FONT_FIX_TRANS = str.maketrans({
    ")": "ي",
    "(": "ي",
    "#": "و",
    "!": "ه",
    "Ë": "ك",
    "٬": "ج",
    "۲": "ل",
    "ى": "ي",
    "ئ": "ي",
    "ؤ": "و",
})

# الكلمات المفتاحية المطلوب تضمينها (الاختصاصات البرمجية والتقنية المطلوبة)
TARGET_KEYWORDS = [
    "معلوماتية",
    "معلوماتيه",
    "حاسوب",
    "حواسيب",
    "حواسب",
    "بيساوحلا",       # الحواسيب معكوسة
    "بيساولحا",       # الحواسيب بتشفير قديم
    "ةيتامولعم",      # معلوماتية معكوسة
    "ةيتامولعلما",    # المعلوماتية معكوسة
    "أتمتة",
    "اتمتة",
    "ةتتملا",         # أتمتة بتشفير قديم
    "ةيعانصلاةتمتلا",
    "تقانات حاسوب",
    "تقنيات حاسوب",
    "تقانات الحاسوب",
    "تقاني للحاسوب",
    "التقاني للحاسوب",
    "المعهد التقاني للحاسوب",
    "بوساح",          # حاسوب معكوس
    "اتصالات",
    "تلااصتلاا",      # اتصالات معكوسة
    "تكنولوجيا المعلومات",
    "برمجيات",
    "نظم المعلومات",
    "ذكاء اصطناعي",
]

# كلمات الاستبعاد (لتفادي الأفرع غير البرمجية كالأتمتة النسيجية أو التقانات البيئية والكوتات الخاصة)
EXCLUSION_KEYWORDS = [
    "النسيجية",
    "النسيج",
    "جيسنلا",
    "البيئية",
    "البيئيه",
    "الحيوية",
    "الحيويه",
    "الأجهزة الطبية",
    "الطبية",
    "البحرية",
    "البترولية",
    # استبعاد الكوتات الخاصة التزاماً بشرط: "القبول لجميع المحافظات فقط"
    "المحافظات الشرقية",
    "المحافظات الشرقيه",
    "أبناء المحافظات",
    "ابناء المحافظات",
    "أبناء حلب",
    "ابناء حلب",
    "أبناء طرطوس",
    "ابناء طرطوس",
    "أبناء حمص",
    "أبناء اللاذقية",
    "ذوي الشهداء",
    "ابناء الشهداء",
    "أبناء الشهداء",
    "جرحى",
]

# قاموس توحيد أسماء الجامعات من المدن أو الإشارات
CITY_UNIVERSITY_MAP = {
    "دمشق": "جامعة دمشق",
    "قشمد": "جامعة دمشق",
    "حلب": "جامعة حلب",
    "بلح": "جامعة حلب",
    "اللاذقية": "جامعة تشرين",
    "الالذقية": "جامعة تشرين",
    "ةيقذلالا": "جامعة تشرين",
    "تشرين": "جامعة تشرين",
    "نيرشت": "جامعة تشرين",
    "حمص": "جامعة البعث",
    "صمح": "جامعة البعث",
    "البعث": "جامعة البعث",
    "ثعبلا": "جامعة البعث",
    "حماة": "جامعة حماة",
    "ةامح": "جامعة حماة",
    "طرطوس": "جامعة طرطوس",
    "سوطرط": "جامعة طرطوس",
    "الفرات": "جامعة الفرات",
    "تارفلا": "جامعة الفرات",
    "دير الزور": "جامعة الفرات",
    "الحسكة": "جامعة الفرات",
    "ةكسلحا": "جامعة الفرات",
    "الرقة": "جامعة الفرات",
    "ةقرلا": "جامعة الفرات",
    "السويداء": "جامعة دمشق (فرع السويداء)",
    "درعا": "جامعة دمشق (فرع درعا)",
    "اعرد": "جامعة دمشق (فرع درعا)",
    "القنيطرة": "جامعة دمشق (فرع القنيطرة)",
    "ريف دمشق": "جامعة دمشق",
}


# =============================================================================
# 2. وظائف معالجة النصوص واللغة العربية (Arabic Text Normalization)
# =============================================================================

def clean_arabic_text(text: str) -> str:
    """
    تنظيف النص العربي، تصحيح الاتجاه المعكوس (RTL) الناتج عن الـ PDF،
    وإزالة الحركات والأحرف الغريبة التي قد تسبب انهيار مكتبة bidi.
    """
    if not text:
        return ""
    
    text_str = str(text)
    # تنظيف المحارف الغريبة مع الإبقاء على الحروف والأرقام العربية والإنجليزية
    sanitized = re.sub(
        r"[^\u0600-\u06FF\u0750-\u077F0-9a-zA-Z\s\(\)\-\.\,\:\/_\%\[\]]",
        " ",
        text_str
    )
    
    # تصحيح اتجاه النص العربي المعكوس
    try:
        display_text = get_display(sanitized).strip()
    except Exception:
        display_text = sanitized.strip()
        
    # توحيد المسافات
    display_text = re.sub(r"\s+", " ", display_text)
    display_text = display_text.replace("الالذقية", "اللاذقية")
    display_text = display_text.replace("الالذقٌة", "اللاذقية")
    return display_text.strip()


def normalize_for_search(text: str) -> str:
    """
    توحيد الحروف لأغراض البحث والمطابقة (أ، إ، آ -> ا) و (ة -> ه) و (ي -> ى).
    """
    if not text:
        return ""
    t = str(text)
    # تطبيق جدول إصلاح محارف الخط المشوهة
    t = t.translate(FONT_FIX_TRANS)
    t = re.sub(r"[إأآا]", "ا", t)
    t = re.sub(r"ة", "ه", t)
    t = re.sub(r"[يى]", "ي", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_software_specialization(raw_or_cleaned_text: str) -> bool:
    """
    التحقق مما إذا كان النص يشير لاختصاص برمجي/حاسوبي ويستوفي شروط الفلترة.
    يفحص كلاً من النص الخام والنص المعكوس والمصحح لضمان عدم تفويت أي سطر.
    """
    norm = normalize_for_search(raw_or_cleaned_text)
    
    # فحص الاستبعاد أولاً
    for ex in EXCLUSION_KEYWORDS:
        if normalize_for_search(ex) in norm:
            return False
            
    # فحص التضمين
    for inc in TARGET_KEYWORDS:
        if normalize_for_search(inc) in norm:
            return True
            
    return False


# =============================================================================
# 3. استخراج البيانات الوصفية من اسم الملف (Metadata Extraction)
# =============================================================================

def extract_metadata_from_filename(filename: str):
    """
    استخراج (السنة، نوع القبول المبدئي، هل هو إعلان أم نتيجة نهائية) من اسم الملف.
    """
    basename = os.path.basename(filename)
    
    # تحويل الأرقام المكتوبة بالمشرقية (الهندية) إلى أرقام عربية قياسية
    eastern_to_western = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    norm_name = basename.translate(eastern_to_western)
    
    # 1. استخراج السنة (مثال: 2014، 2023...)
    year_match = re.search(r"(20\d\d)", norm_name)
    year = int(year_match.group(1)) if year_match else None
    
    # 2. استخراج نوع القبول الافتراضي من اسم الملف (إن وُجد)
    admission_type = None
    has_aam = "عام" in norm_name or "العام" in norm_name or "العامة" in norm_name
    has_muwazi = "موازي" in norm_name or "الموازي" in norm_name
    
    if has_aam and not has_muwazi:
        admission_type = "عام"
    elif has_muwazi and not has_aam:
        admission_type = "موازي"
    
    # 3. تحديد هل هو نتيجة نهائية/حدود دنيا أم إعلان تقدم مبدئي
    final_indicators = ["نتائج", "حدود", "معدلات", "ثانية", "الثانية", "تانية"]
    is_final_result = any(ind in norm_name for ind in final_indicators)
    
    return year, admission_type, is_final_result


# =============================================================================
# 4. تحليل واستخراج البيانات من الجداول (Table Parsing Engine)
# =============================================================================

def parse_score(val) -> float:
    """
    استخراج العلامة أو النسبة كرقم حقيقي (Float) من الخلية.
    """
    if val is None:
        return None
    val_str = str(val).strip()
    val_str = val_str.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    
    # البحث عن نمط رقمي (مثل 2350 أو 2121.5 أو 78.5%)
    match = re.search(r"(\d+(?:\.\d+)?)", val_str)
    if match:
        num = float(match.group(1))
        # درجات المفاضلة السورية تتراوح عادة بين 1000 و 3200 (أو نسب مئوية بين 50 و 100)
        if 50.0 <= num <= 3200.0:
            return num
    return None


def extract_records_from_pdf(filepath: str):
    """
    قراءة ملف PDF واستخراج الأسطر المطابقة مع التكيف مع أشكال الجداول المختلفة.
    """
    year, default_adm_type, is_final_result = extract_metadata_from_filename(filepath)
    extracted_records = []
    
    try:
        with pdfplumber.open(filepath) as pdf:
            total_pages = len(pdf.pages)
            
            # فحص سريع: التأكد من وجود نص رقمي في الصفحات الأولى
            has_any_text = False
            for p in pdf.pages[:min(3, total_pages)]:
                if p.extract_text() and len(p.extract_text().strip()) > 30:
                    has_any_text = True
                    break
                    
            if not has_any_text:
                print(f"[تحذير] الملف '{os.path.basename(filepath)}' يبدو أنه صورة ممسوحة ضوئياً (Scanned PDF) بدون نص رقمي.")
                return []
                
            for page_idx, page in enumerate(pdf.pages):
                tables = page.extract_tables() or []
                for table in tables:
                    if not table or len(table) < 1:
                        continue
                        
                    # تجاهل جداول الدعاية الخاصة ببوتات التلغرام
                    flat_sample = " ".join([str(c) for r in table[:2] for c in r if c])
                    if "Science_2022bot" in flat_sample or ("مكتبتي" in flat_sample and len(table) <= 2):
                        continue
                        
                    for row in table:
                        if not row or all(c is None or str(c).strip() == "" for c in row):
                            continue
                            
                        # تنظيف نصوص الخلايا في السطر
                        raw_cells = [str(c).strip() if c else "" for c in row]
                        cleaned_cells = [clean_arabic_text(c) for c in row]
                        
                        # -------------------------------------------------------------
                        # النمط الأول: جداول النتائج والحدود الدنيا (Result Cutoff Tables)
                        # تحوي أعمدة: الكلية/المعهد، المدينة، الحد الأدنى
                        # -------------------------------------------------------------
                        target_cell_idx = -1
                        for idx, (raw_c, clean_c) in enumerate(zip(raw_cells, cleaned_cells)):
                            if is_software_specialization(clean_c) or is_software_specialization(raw_c):
                                target_cell_idx = idx
                                break
                                
                        if target_cell_idx != -1:
                            specialization = cleaned_cells[target_cell_idx]
                            raw_spec = raw_cells[target_cell_idx]
                            
                            # استخراج نوع القبول (عام / موازي)
                            adm_type = default_adm_type
                            if "موازي" in specialization or "يزاوم" in raw_spec:
                                adm_type = "موازي"
                            elif "عام" in specialization or "ماع" in raw_spec:
                                adm_type = "عام"
                            elif adm_type is None:
                                adm_type = "عام"
                                
                            # استخراج المدينة والجامعة المقابلة
                            university = None
                            # فحص الخلايا المجاورة
                            for c in cleaned_cells + raw_cells:
                                for city, uni in CITY_UNIVERSITY_MAP.items():
                                    if city in c:
                                        university = uni
                                        break
                                if university:
                                    break
                                    
                            if not university:
                                for city, uni in CITY_UNIVERSITY_MAP.items():
                                    if city in specialization or city in raw_spec:
                                        university = uni
                                        break
                            if not university:
                                university = "جامعة حكومية / غير محددة"
                                
                            # استخراج العلامة (الحد الأدنى)
                            score = None
                            for idx, c in enumerate(cleaned_cells):
                                if idx == target_cell_idx:
                                    continue
                                sc = parse_score(c)
                                if sc and sc >= 1000:
                                    score = sc
                                    break
                                    
                            if score is not None:
                                extracted_records.append({
                                    "year": year,
                                    "university": university,
                                    "specialization": specialization,
                                    "admission_type": adm_type,
                                    "is_final_result": is_final_result,
                                    "score": score
                                })
                                continue
                                
                        # -------------------------------------------------------------
                        # النمط الثاني: جداول إعلانات شروط التقدم (Announcement Tables)
                        # تحوي تخصصات مجمعة مثل: كلية الهندسة المعلوماتية في جامعات (دمشق - حلب - تشرين...)
                        # وبجانبها عمود للعام وعمود للموازي
                        # -------------------------------------------------------------
                        for cell, raw_c in zip(cleaned_cells, raw_cells):
                            if is_software_specialization(cell) or is_software_specialization(raw_c):
                                # استخراج كافة الجامعات المذكورة في نص الخلية
                                unis_found = []
                                combined_text = cell + " " + raw_c
                                for city, uni in CITY_UNIVERSITY_MAP.items():
                                    if city in combined_text and uni not in unis_found:
                                        unis_found.append(uni)
                                        
                                if not unis_found:
                                    unis_found = ["جامعة حكومية / غير محددة"]
                                    
                                # استخراج الدرجات المذكورة في السطر
                                scores_in_row = []
                                for c in cleaned_cells:
                                    sc = parse_score(c)
                                    if sc and sc >= 1000:
                                        scores_in_row.append(sc)
                                        
                                if scores_in_row:
                                    if len(scores_in_row) >= 2:
                                        higher_score = max(scores_in_row)
                                        lower_score = min(scores_in_row)
                                        for u in unis_found:
                                            extracted_records.append({
                                                "year": year,
                                                "university": u,
                                                "specialization": cell if len(cell) > 5 else raw_c,
                                                "admission_type": "عام",
                                                "is_final_result": is_final_result,
                                                "score": higher_score
                                            })
                                            extracted_records.append({
                                                "year": year,
                                                "university": u,
                                                "specialization": cell if len(cell) > 5 else raw_c,
                                                "admission_type": "موازي",
                                                "is_final_result": is_final_result,
                                                "score": lower_score
                                            })
                                    else:
                                        single_score = scores_in_row[0]
                                        adm_type = default_adm_type or "عام"
                                        for u in unis_found:
                                            extracted_records.append({
                                                "year": year,
                                                "university": u,
                                                "specialization": cell if len(cell) > 5 else raw_c,
                                                "admission_type": adm_type,
                                                "is_final_result": is_final_result,
                                                "score": single_score
                                            })
                                break

    except Exception as e:
        print(f"[خطأ] تعذر معالجة الملف '{os.path.basename(filepath)}': {e}")
        
    return extracted_records


# =============================================================================
# 5. إدارة قاعدة البيانات وحقن السجلات (Database Operations)
# =============================================================================

def init_database(db_path: str = DB_NAME):
    """
    إنشاء قاعدة البيانات وجدول admission_data بالمخطط الدقيق المطلوب.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER,
            university TEXT,
            specialization TEXT,
            admission_type TEXT,
            is_final_result BOOLEAN,
            score REAL
        )
    """)
    conn.commit()
    conn.close()
    print(f"[قاعدة البيانات] تم تجهيز الجدول '{TABLE_NAME}' في '{db_path}' بنجاح.")


def insert_records(records, db_path: str = DB_NAME):
    """
    إدخال السجلات المستخرجة مع تفادي التكرار التام.
    """
    if not records:
        return 0
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    inserted_count = 0
    for r in records:
        cursor.execute(f"""
            SELECT COUNT(*) FROM {TABLE_NAME}
            WHERE year = ? AND university = ? AND specialization = ? 
              AND admission_type = ? AND is_final_result = ? AND score = ?
        """, (r["year"], r["university"], r["specialization"], r["admission_type"], r["is_final_result"], r["score"]))
        
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"""
                INSERT INTO {TABLE_NAME} 
                (year, university, specialization, admission_type, is_final_result, score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (r["year"], r["university"], r["specialization"], r["admission_type"], r["is_final_result"], r["score"]))
            inserted_count += 1
            
    conn.commit()
    conn.close()
    return inserted_count


# =============================================================================
# 6. الدالة الرئيسية (Main Execution)
# =============================================================================

def main():
    print("=" * 70)
    print("بدء عملية أتمتة استخراج بيانات المفاضلات الجامعية إلى SQLite")
    print("=" * 70)
    
    # تهيئة قاعدة البيانات
    init_database(DB_NAME)
    
    # جلب جميع ملفات الـ PDF في المجلد الحالي
    current_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_files = sorted(glob.glob(os.path.join(current_dir, "*.pdf")))
    
    if not pdf_files:
        print("[!] لم يتم العثور على أي ملفات PDF في المجلد الحالي.")
        return
        
    print(f"تم العثور على {len(pdf_files)} ملف PDF. جاري المعالجة...\n")
    
    total_extracted = 0
    total_inserted = 0
    
    for idx, pdf_path in enumerate(pdf_files, 1):
        filename = os.path.basename(pdf_path)
        print(f"[{idx}/{len(pdf_files)}] جاري معالجة: {filename} ...")
        
        records = extract_records_from_pdf(pdf_path)
        if records:
            inserted = insert_records(records, DB_NAME)
            total_extracted += len(records)
            total_inserted += inserted
            print(f"   -> تم استخراج {len(records)} سطر، تم إدخال {inserted} سطر جديد.")
        else:
            print("   -> لم يتم العثور على اختصاصات مطابقة أو الملف ممسوح ضوئياً.")
            
    print("\n" + "=" * 70)
    print("اكتملت المعالجة بنجاح!")
    print(f"- إجمالي السجلات المستخرجة: {total_extracted}")
    print(f"- إجمالي السجلات الجديدة المضافة لقاعدة البيانات: {total_inserted}")
    print(f"- مسار قاعدة البيانات: {os.path.abspath(DB_NAME)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
