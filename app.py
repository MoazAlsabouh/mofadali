import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error

# 1. إعداد البيانات (هنا وضعنا عينة من البيانات التي جمعناها)
# في مشروعك الحقيقي، ستقوم باستبدال هذا الجزء بـ:
# df = pd.read_excel('mofadala_data.xlsx')
data = {
    'Year': [2023, 2023, 2024, 2024, 2025, 2025, 2026, 2026],
    'University': ['دمشق', 'حلب', 'دمشق', 'حلب', 'دمشق', 'حلب', 'دمشق', 'حلب'],
    'Admission_Type': ['عام', 'عام', 'عام', 'عام', 'عام', 'عام', 'عام', 'عام'],
    'Success_Rate': [66.3, 66.3, 57.9, 57.9, 75.5, 75.5, 65.3, 65.3], # نسبة النجاح للفرع العلمي
    'Initial_Threshold': [2150, 2100, 2200, 2150, 2250, 2200, 2270, 2220], # شرط التقدم (أرقام تقريبية للتوضيح)
    'Final_Cutoff': [2310, 2280, 2350, 2300, 2380, 2330, 2370, 2320] # النتيجة الفعلية للمفاضلة
}

df = pd.DataFrame(data)

# 2. فصل الميزات (Features) عن الهدف (Target)
# X هي المعطيات التي سيتعلم منها المودل، و y هي النتيجة التي يجب أن يتوقعها
X = df[['University', 'Admission_Type', 'Success_Rate', 'Initial_Threshold']]
y = df['Final_Cutoff']

# 3. معالجة البيانات النصية (أسماء الجامعات ونوع القبول)
# الذكاء الاصطناعي لا يفهم النصوص، لذلك نحولها إلى أرقام باستخدام OneHotEncoder
categorical_features = ['University', 'Admission_Type']
categorical_transformer = OneHotEncoder(handle_unknown='ignore')

preprocessor = ColumnTransformer(
    transformers=[
        ('cat', categorical_transformer, categorical_features)
    ],
    remainder='passthrough' # الإبقاء على الأرقام (نسبة النجاح وشرط التقدم) كما هي
)

# 4. بناء هيكل المودل (Pipeline)
# استخدمنا Random Forest لأنه ممتاز جداً مع البيانات الجدولية الصغيرة
model = Pipeline(steps=[
    ('preprocessor', preprocessor),
    ('regressor', RandomForestRegressor(n_estimators=100, random_state=42))
])

# 5. تدريب المودل
# في المشاريع الكبيرة نقسم البيانات لتدريب واختبار (train_test_split)، 
# لكن لأن بياناتنا صغيرة جداً هنا، سندربه على كامل البيانات المتوفرة
model.fit(X, y)
print("تم تدريب المودل بنجاح!\n")

# 6. اختبار دقة المودل على نفس البيانات (لمعرفة مقدار الخطأ)
predictions = model.predict(X)
mae = mean_absolute_error(y, predictions)
print(f"متوسط نسبة الخطأ في التوقع: {mae:.2f} درجة فقط\n")
print("-" * 40)

# ========================================================
# 7. التوقع للسنة القادمة (مثلاً مفاضلة 2027)
# لنفترض أن الوزارة أصدرت شروط التقدم الجديدة، ونسبة النجاح كانت 60%
# ========================================================

new_data_2027 = pd.DataFrame({
    'University': ['دمشق', 'حلب'],
    'Admission_Type': ['عام', 'عام'],
    'Success_Rate': [60.0, 60.0], # نسبة نجاح الدورة الجديدة
    'Initial_Threshold': [2250, 2200] # شروط التقدم الجديدة التي أصدرتها الوزارة
})

# جعل المودل يتوقع الحدود الدنيا الفعلية
future_predictions = model.predict(new_data_2027)

print("التوقعات لمفاضلة العام القادم بناءً على المعطيات الجديدة:")
for i in range(len(new_data_2027)):
    uni = new_data_2027['University'].iloc[i]
    pred_score = future_predictions[i]
    print(f"جامعة {uni}: يتوقع أن يغلق القبول الفعلي عند {pred_score:.0f} درجة تقريباً.")