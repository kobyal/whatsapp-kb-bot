# פוסט לינקדאין (עברית)

**איך לפרסם (מבוסס על נתוני 2026):**
- לפרסם **ג'–ה', 08:00–10:00 או 15:00–17:00**. לא שישי–שבת. להיות זמין לענות לתגובות בשעה הראשונה.
- **בלי קישור בגוף הפוסט** (קישור חיצוני מוריד תפוצה בכ־19%). כותבים "הקישורים בתגובה הראשונה", ומוסיפים את התגובה עם הקישורים **אחרי** שכמה אנשים כבר הגיבו. בנוסף לשים את המאמר ב־Featured בפרופיל.
- לצרף תמונה: `docs/diagrams/architecture.png`. עדיף עוד יותר: קרוסלה (PDF) של 6 שקפים — בעיה, ארכיטקטורה, 3 לקחים, עלות, ריפו.
- 0–3 האשטגים, לא יותר. לסיים בשאלה.
- לא לערבב עברית ואנגלית באותו פוסט. גרסה אנגלית בנפרד, שבוע אחרי.

---

## הפוסט

120 מפתחים בקבוצת וואטסאפ אחת. 20 שאלות שחוזרות. ואני עונה על אותה שאלה בפעם ה־15, בעשר בלילה.

אז בניתי בוט שיושב בקבוצה ועונה על מה שחוזר. הוא רץ כבר כמה חודשים, ולמדתי ממנו 5 דברים שלא היו לי ברשימה:

1. המודל בוחר *איזו* תשובה. הוא לא כותב אותה.
מה שהקבוצה מקבלת זה טקסט שבן אדם כתב ואימת, מילה במילה. אין שלב שבו מודל שפה מחבר הוראות ש־120 אנשים יקראו כאמת.

2. שקט עדיף על תשובה שגויה.
מדדתי על 326 הודעות אמיתיות. ברף ביטחון של 0.80 – 42% מהתשובות היו שגויות. העליתי ל־0.90 והבוט שותק כשהוא לא בטוח. 6%.

3. חצי מה"טעויות" בכלל לא היו שאלות.
מישהו פרסם פתרון, הודעה של הצוות, "גם אצלי". הבוט דיבר מעל האנשים שבאמת עזרו. פסקה אחת בפרומפט – "האם זו בקשה לעזרה בכלל?" – תיקנה את רוב זה.

4. ל־API הרשמי של וואטסאפ אין דרך לקבוצות.
מקסימום 8 משתתפים, והעסק חייב ליצור את הקבוצה. לקבוצה קיימת של 120 אנשים אין מסלול רשמי. יש מסלול לא רשמי, עם סיכון חסימה אמיתי, ואני מפרט אותו בכנות.

5. אף פעם, אבל אף פעם, לא על המספר שלכם.
חסימה על המספר האישי = כל הוואטסאפ שלכם נעלם, בלי ערעור. סים פריפייד ייעודי במחיר של פלאפל, טלפון ישן, ושום דבר חשוב לא מחובר למספר הזה.

הפכתי את זה לתבנית פתוחה: EC2 קטן שמחזיק את החיבור, Lambda שמחליטה, Bedrock עם Claude Haiku, DynamoDB לבסיס הידע. פחות מ־500 שורות. Terraform או CloudFormation. פרסתי מאפס לחשבון נקי כדי לוודא שההוראות עובדות, מצאתי שני באגים בדרך, ואז בדקתי בקבוצה אמיתית: 9 הודעות, 9 החלטות נכונות, כולל צילום מסך של שגיאה.

עולה בערך 18 דולר בחודש.

המאמר המלא (צעד־צעד, עם צילומי מסך) והריפו – בתגובה הראשונה.

ואתם – מה הייתם שמים במקום Baileys? זה החלק שהכי הפריע לי בכל הפרויקט.

#בינהמלאכותית #AWS #הייטקישראלי

---

## התגובה הראשונה (להוסיף אחרי שיש כמה תגובות)

המאמר המלא ב־Medium: <MEDIUM_URL>
הריפו (MIT, Terraform + CloudFormation): https://github.com/kobyal/whatsapp-kb-bot
אם משהו נשבר לכם – פתחו issue, אני עונה.

---

## English version (post a week later, same rules)

120 developers in one WhatsApp group. The same 20 questions. Me, answering number 15 at 10 pm.

So I built a bot that sits in the group and answers what repeats. It has run for months now, and it taught me 5 things I did not have on my list:

1. The model picks *which* answer. It never writes one. The group gets text a human wrote and verified, word for word.

2. Silence beats a wrong answer. On 326 real messages, a 0.80 confidence floor gave 42% wrong answers. At 0.90 with silence below: 6%.

3. Half the "mistakes" were never questions. Someone posting a fix, an announcement, "same here". One paragraph in the prompt asking "is this a request for help at all?" fixed most of it.

4. The official WhatsApp API has no way into groups. 8 participants max, business-created only. For an existing 120-person group there is no compliant route. There is an unofficial one, with real ban risk, and I spell it out.

5. Never on your own number. A ban on your personal number takes your whole WhatsApp with it. Dedicated prepaid SIM, old phone, nothing important attached.

I turned it into an open template: a small EC2 for the WhatsApp session, a Lambda that decides, Bedrock with Claude Haiku, DynamoDB for the knowledge base. Under 500 lines. Terraform or CloudFormation. Deployed from scratch into a clean account while writing (found two bugs), then tested live: 9 messages, 9 correct decisions, screenshot included.

About $18 a month.

Full write-up and repo in the first comment.

What would you have used instead of Baileys? That was the part of this project I liked least.

#AWS #Bedrock #WhatsApp
