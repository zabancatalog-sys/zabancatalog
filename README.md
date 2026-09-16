# zabanCatalog

דוחות מלאי לפי סניף, מפורסמים כאתר סטטי ב-GitHub Pages.

**האתר:** https://hillb65.github.io/zabanCatalog/

## מבנה

```
branches/666.mht     ← קובץ המקור שנשמר מ-Priority
pics/                ← תמונות מוצרים (אופציונלי, ראה למטה)
build.py             ← ממיר MHT → HTML
666/index.html       ← נוצר אוטומטית, לא לערוך ידנית
index.html           ← תפריט הסניפים, נוצר אוטומטית
```

## הוספת סניף

1. שמור את הדוח מ-Priority כקובץ `.mht`
2. שים אותו ב-`branches/` בשם הסניף, למשל `branches/777.mht`
3. הרץ:

```bash
python build.py
```

```bash
git add -A && git commit -m "Add branch 777" && git push
```

הסניף יהיה זמין ב-`https://hillb65.github.io/zabanCatalog/777/` תוך כדקה.

## תמונות מוצרים

IE11 שומר קובץ MHT **בלי** תמונות שמקורן בנתיב `file:///` — הוא רק משאיר
הפניות ל-`D:\priority\system\mail\pics\` שבשרת Priority. לכן התמונות
לא מגיעות עם הקובץ.

הפתרון: העתק את תיקיית התמונות מהשרת לתוך `pics/` כאן. `build.py` מחפש
כל תמונה חסרה לפי שם הקובץ ומטמיע אותה ב-HTML כ-base64. הרצה של
`build.py` מדפיסה את רשימת התמונות שעדיין חסרות.
