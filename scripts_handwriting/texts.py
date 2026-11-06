# ruff: noqa: RUF001 - the pages are written in non-Latin scripts on purpose
"""The synthetic text of the script pages: short invented sentences and form rows per script, each
with a romanised gloss and its English meaning, and invented names built from syllable lists.

Every sentence here was written for this repository. Telephone numbers sit in the 555-0100 to
555-0199 block; e-mail addresses use RFC 2606 domains; account numbers are invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from hidden_layer.rng import mix_seed, scalar_ints

PHONE = "(206) 555-0143"
ACCOUNT = "0000 4471 2290 18"
EMAIL = "office@example.org"


@dataclass(frozen=True)
class TextLine:
    text: str
    gloss: str  # a romanisation (empty for Latin, Greek and Cyrillic where the text is its own)
    meaning: str


# Name syllables per script: (written, romanised). A name is one family part and two given parts.
SYLLABLES: dict[str, tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]] = {
    "zh-Hans": (
        (("林", "Lin"), ("高", "Gao"), ("宋", "Song"), ("周", "Zhou")),
        (
            ("晓", "xiao"),
            ("岚", "lan"),
            ("明", "ming"),
            ("雪", "xue"),
            ("宁", "ning"),
            ("远", "yuan"),
        ),
    ),
    "zh-Hant": (
        (("林", "Lin"), ("高", "Gao"), ("宋", "Song"), ("周", "Zhou")),
        (
            ("曉", "xiao"),
            ("嵐", "lan"),
            ("明", "ming"),
            ("雪", "xue"),
            ("寧", "ning"),
            ("遠", "yuan"),
        ),
    ),
    "ja": (
        (("高森", "Takamori"), ("北川", "Kitagawa"), ("宮原", "Miyahara")),
        (("美", "mi"), ("月", "zuki"), ("春", "haru"), ("奈", "na"), ("花", "ka")),
    ),
    "ko": (
        (("윤", "Yun"), ("한", "Han"), ("서", "Seo")),
        (("서", "seo"), ("진", "jin"), ("하", "ha"), ("은", "eun"), ("민", "min")),
    ),
    "ar": (
        (("الراشد", "ar-Rashid"), ("النجار", "an-Najjar"), ("الحداد", "al-Haddad")),
        (("سليم", "Salim"), ("ليلى", "Layla"), ("كريم", "Karim")),
    ),
    "he": (
        (("ברקן", "Barkan"), ("גלעדי", "Giladi"), ("רוזן", "Rozen")),
        (("נועה", "Noa"), ("עמית", "Amit"), ("טל", "Tal")),
    ),
    "hi": (
        (("वर्मानी", "Varmani"), ("सेठिया", "Sethiya"), ("रावल", "Raval")),
        (("अनिका", "Anika"), ("रोहन", "Rohan"), ("मीरा", "Mira")),
    ),
    "th": (
        (("วงศ์ทอง", "Wongthong"), ("ศรีสุข", "Srisuk"), ("แก้วใส", "Kaewsai")),
        (("ปรียา", "Priya"), ("ธนา", "Thana"), ("มาลี", "Mali")),
    ),
    "el": (
        (("Καραλή", "Karali"), ("Μαυρίδη", "Mavridi"), ("Σταμάτη", "Stamati")),
        (("Ελένη", "Eleni"), ("Δάφνη", "Dafni"), ("Ιουλία", "Ioulia")),
    ),
    "ru": (
        (("Ольховская", "Olkhovskaya"), ("Берестова", "Berestova"), ("Зимина", "Zimina")),
        (("Вера", "Vera"), ("Лада", "Lada"), ("Нина", "Nina")),
    ),
    "vi": (
        (("Trần", "Tran"), ("Lê", "Le"), ("Đoàn", "Doan")),
        (("Ngọc", "Ngoc"), ("Hoà", "Hoa"), ("Thư", "Thu"), ("Quỳnh", "Quynh")),
    ),
    "pl": (
        (("Żelazowska", "Zelazowska"), ("Łęcka", "Lecka"), ("Wróblewska", "Wroblewska")),
        (("Zofia", "Zofia"), ("Józefa", "Jozefa"), ("Ślęża", "Sleza")),
    ),
    "is": (
        (
            ("Ævarsdóttir", "Aevarsdottir"),
            ("Þórisdóttir", "Thorisdottir"),
            ("Ólafsdóttir", "Olafsdottir"),
        ),
        (("Þórdís", "Thordis"), ("Sólrún", "Solrun"), ("Hrönn", "Hronn")),
    ),
}

# Scripts whose names put the family name first and join without a space.
FAMILY_FIRST_JOINED = {"zh-Hans", "zh-Hant"}
FAMILY_FIRST = {"zh-Hans", "zh-Hant", "ja", "ko", "vi"}


def invented_name(script: str) -> tuple[str, str]:
    """(written, romanised): one family part and one or two given parts, chosen by a seeded stream."""
    fam, given = SYLLABLES[script]
    a, b, c = scalar_ints(mix_seed("name", script), 3, 0, 1_000_000)
    f = fam[a % len(fam)]
    g1 = given[b % len(given)]
    g2 = given[c % len(given)] if script in ("zh-Hans", "zh-Hant", "ja", "ko") else None
    if g2 is not None and g2 == g1:
        g2 = given[(c + 1) % len(given)]
    gw = g1[0] + (g2[0] if g2 else "")
    gr = (g1[1] + (g2[1] if g2 else "")).capitalize()
    if script in FAMILY_FIRST_JOINED:
        return f[0] + gw, f"{f[1]} {gr}"
    if script in FAMILY_FIRST:
        return f"{f[0]} {gw}", f"{f[1]} {gr}"
    return f"{gw} {f[0]}", f"{gr} {f[1]}"


def _rows(
    script: str, labels: dict[str, tuple[str, str]], date: str
) -> list[tuple[str, str, str, str]]:
    """Form rows: (label, value, label gloss, label meaning)."""
    name, _ = invented_name(script)
    vals = {"name": name, "phone": PHONE, "account": ACCOUNT, "date": date, "email": EMAIL}
    return [
        (labels[k][0], vals[k], labels[k][1], k)
        for k in ("name", "phone", "account", "date", "email")
    ]


@dataclass(frozen=True)
class Script:
    code: str
    name: str
    direction: str  # ltr | rtl
    lines: tuple[TextLine, ...]
    labels: dict[str, tuple[str, str]]
    date: str


def _s(
    code: str,
    name: str,
    direction: str,
    lines: list[tuple[str, str, str]],
    labels: dict[str, tuple[str, str]],
    date: str,
) -> Script:
    return Script(code, name, direction, tuple(TextLine(*x) for x in lines), labels, date)


def scripts() -> dict[str, Script]:
    n = {k: invented_name(k) for k in SYLLABLES}
    out = [
        _s(
            "zh-Hans",
            "Chinese (simplified)",
            "ltr",
            [
                ("这是一份测试文件。", "Zhè shì yī fèn cèshì wénjiàn.", "This is a test document."),
                (
                    "请于下周一前回复本办公室。",
                    "Qǐng yú xià zhōuyī qián huífù běn bàngōngshì.",
                    "Please reply to this office before next Monday.",
                ),
                (
                    f"联系人：{n['zh-Hans'][0]}",
                    f"Liánxì rén: {n['zh-Hans'][1]}",
                    f"Contact: {n['zh-Hans'][1]}",
                ),
                (f"电话：{PHONE}", f"Diànhuà: {PHONE}", f"Telephone: {PHONE}"),
                (f"账号：{ACCOUNT}", f"Zhànghào: {ACCOUNT}", f"Account number: {ACCOUNT}"),
                ("日期：2026年10月30日", "Rìqī: 2026 nián 10 yuè 30 rì", "Date: 30 October 2026"),
            ],
            {
                "name": ("姓名", "Xìngmíng"),
                "phone": ("电话", "Diànhuà"),
                "account": ("账号", "Zhànghào"),
                "date": ("日期", "Rìqī"),
                "email": ("电子邮件", "Diànzǐ yóujiàn"),
            },
            "2026年10月30日",
        ),
        _s(
            "zh-Hant",
            "Chinese (traditional)",
            "ltr",
            [
                ("這是一份測試文件。", "Zhè shì yī fèn cèshì wénjiàn.", "This is a test document."),
                (
                    "請於下週一前回覆本辦公室。",
                    "Qǐng yú xià zhōuyī qián huífù běn bàngōngshì.",
                    "Please reply to this office before next Monday.",
                ),
                (
                    f"聯絡人：{n['zh-Hant'][0]}",
                    f"Liánluò rén: {n['zh-Hant'][1]}",
                    f"Contact: {n['zh-Hant'][1]}",
                ),
                (f"電話：{PHONE}", f"Diànhuà: {PHONE}", f"Telephone: {PHONE}"),
                (f"帳號：{ACCOUNT}", f"Zhànghào: {ACCOUNT}", f"Account number: {ACCOUNT}"),
                ("日期：2026年10月30日", "Rìqī: 2026 nián 10 yuè 30 rì", "Date: 30 October 2026"),
            ],
            {
                "name": ("姓名", "Xìngmíng"),
                "phone": ("電話", "Diànhuà"),
                "account": ("帳號", "Zhànghào"),
                "date": ("日期", "Rìqī"),
                "email": ("電子郵件", "Diànzǐ yóujiàn"),
            },
            "2026年10月30日",
        ),
        _s(
            "ja",
            "Japanese",
            "ltr",
            [
                (
                    "これはテスト用の書類です。",
                    "Kore wa tesuto-yō no shorui desu.",
                    "This is a document for testing.",
                ),
                (
                    "来週の月曜日までにご返信ください。",
                    "Raishū no getsuyōbi made ni go-henshin kudasai.",
                    "Please reply by next Monday.",
                ),
                (
                    f"担当者：{n['ja'][0]}",
                    f"Tantōsha: {n['ja'][1]}",
                    f"Person in charge: {n['ja'][1]}",
                ),
                (f"電話：{PHONE}", f"Denwa: {PHONE}", f"Telephone: {PHONE}"),
                (f"口座番号：{ACCOUNT}", f"Kōza bangō: {ACCOUNT}", f"Account number: {ACCOUNT}"),
                (
                    "日付：2026年10月30日",
                    "Hizuke: 2026-nen 10-gatsu 30-nichi",
                    "Date: 30 October 2026",
                ),
            ],
            {
                "name": ("氏名", "Shimei"),
                "phone": ("電話", "Denwa"),
                "account": ("口座番号", "Kōza bangō"),
                "date": ("日付", "Hizuke"),
                "email": ("メール", "Mēru"),
            },
            "2026年10月30日",
        ),
        _s(
            "ko",
            "Korean",
            "ltr",
            [
                (
                    "이것은 시험용 문서입니다.",
                    "Igeoseun siheomyong munseoimnida.",
                    "This is a document for testing.",
                ),
                (
                    "다음 주 월요일까지 회신해 주십시오.",
                    "Daeum ju woryoil-kkaji hoesinhae jusipsio.",
                    "Please reply by next Monday.",
                ),
                (
                    f"담당자: {n['ko'][0]}",
                    f"Damdangja: {n['ko'][1]}",
                    f"Person in charge: {n['ko'][1]}",
                ),
                (f"전화: {PHONE}", f"Jeonhwa: {PHONE}", f"Telephone: {PHONE}"),
                (
                    f"계좌 번호: {ACCOUNT}",
                    f"Gyejwa beonho: {ACCOUNT}",
                    f"Account number: {ACCOUNT}",
                ),
                (
                    "날짜: 2026년 10월 30일",
                    "Naljja: 2026-nyeon 10-wol 30-il",
                    "Date: 30 October 2026",
                ),
            ],
            {
                "name": ("성명", "Seongmyeong"),
                "phone": ("전화", "Jeonhwa"),
                "account": ("계좌 번호", "Gyejwa beonho"),
                "date": ("날짜", "Naljja"),
                "email": ("이메일", "Imeil"),
            },
            "2026년 10월 30일",
        ),
        _s(
            "ar",
            "Arabic",
            "rtl",
            [
                (
                    "هذه وثيقة للاختبار.",
                    "Hādhihi wathīqa lil-ikhtibār.",
                    "This is a document for testing.",
                ),
                (
                    "يرجى الرد قبل يوم الاثنين القادم.",
                    "Yurjā ar-radd qabla yawm al-ithnayn al-qādim.",
                    "Please reply before next Monday.",
                ),
                (
                    f"جهة الاتصال: {n['ar'][0]}",
                    f"Jihat al-ittiṣāl: {n['ar'][1]}",
                    f"Contact: {n['ar'][1]}",
                ),
                (f"الهاتف: {PHONE}", f"Al-hātif: {PHONE}", f"Telephone: {PHONE}"),
                (
                    f"رقم الحساب: {ACCOUNT}",
                    f"Raqm al-ḥisāb: {ACCOUNT}",
                    f"Account number: {ACCOUNT}",
                ),
                ("التاريخ: 30/10/2026", "At-tārīkh: 30/10/2026", "Date: 30/10/2026"),
            ],
            {
                "name": ("الاسم", "Al-ism"),
                "phone": ("الهاتف", "Al-hātif"),
                "account": ("رقم الحساب", "Raqm al-ḥisāb"),
                "date": ("التاريخ", "At-tārīkh"),
                "email": ("البريد الإلكتروني", "Al-barīd al-iliktrūnī"),
            },
            "30/10/2026",
        ),
        _s(
            "he",
            "Hebrew",
            "rtl",
            [
                ("זהו מסמך לבדיקה.", "Zehu mismakh li-vdika.", "This is a document for testing."),
                (
                    "נא להשיב עד יום שני הבא.",
                    "Na lehashiv ad yom sheni haba.",
                    "Please reply by next Monday.",
                ),
                (f"איש קשר: {n['he'][0]}", f"Ish kesher: {n['he'][1]}", f"Contact: {n['he'][1]}"),
                (f"טלפון: {PHONE}", f"Telefon: {PHONE}", f"Telephone: {PHONE}"),
                (
                    f"מספר חשבון: {ACCOUNT}",
                    f"Mispar heshbon: {ACCOUNT}",
                    f"Account number: {ACCOUNT}",
                ),
                ("תאריך: 30/10/2026", "Ta'arikh: 30/10/2026", "Date: 30/10/2026"),
            ],
            {
                "name": ("שם", "Shem"),
                "phone": ("טלפון", "Telefon"),
                "account": ("מספר חשבון", "Mispar heshbon"),
                "date": ("תאריך", "Ta'arikh"),
                "email": ("דואר אלקטרוני", "Do'ar elektroni"),
            },
            "30/10/2026",
        ),
        _s(
            "hi",
            "Hindi (Devanagari)",
            "ltr",
            [
                (
                    "यह एक परीक्षण दस्तावेज़ है।",
                    "Yah ek parīkṣaṇ dastāvez hai.",
                    "This is a test document.",
                ),
                (
                    "कृपया अगले सोमवार तक उत्तर दें।",
                    "Kṛpayā agle somvār tak uttar deṁ.",
                    "Please reply by next Monday.",
                ),
                (f"संपर्क: {n['hi'][0]}", f"Sampark: {n['hi'][1]}", f"Contact: {n['hi'][1]}"),
                (f"फ़ोन: {PHONE}", f"Fon: {PHONE}", f"Telephone: {PHONE}"),
                (
                    f"खाता संख्या: {ACCOUNT}",
                    f"Khātā saṅkhyā: {ACCOUNT}",
                    f"Account number: {ACCOUNT}",
                ),
                ("तारीख़: 30/10/2026", "Tārīkh: 30/10/2026", "Date: 30/10/2026"),
            ],
            {
                "name": ("नाम", "Nām"),
                "phone": ("फ़ोन", "Fon"),
                "account": ("खाता संख्या", "Khātā saṅkhyā"),
                "date": ("तारीख़", "Tārīkh"),
                "email": ("ईमेल", "Īmel"),
            },
            "30/10/2026",
        ),
        _s(
            "th",
            "Thai",
            "ltr",
            [
                (
                    "นี่คือเอกสารสำหรับการทดสอบ",
                    "Nî khue èkkasăan sămràp kaan thótsòp",
                    "This is a document for testing.",
                ),
                (
                    "กรุณาตอบกลับภายในวันจันทร์หน้า",
                    "Karunaa tòp klàp phaainai wan chan nâa",
                    "Please reply by next Monday.",
                ),
                (f"ผู้ติดต่อ: {n['th'][0]}", f"Phûu tìt tòo: {n['th'][1]}", f"Contact: {n['th'][1]}"),
                (f"โทรศัพท์: {PHONE}", f"Thoorasàp: {PHONE}", f"Telephone: {PHONE}"),
                (
                    f"เลขที่บัญชี: {ACCOUNT}",
                    f"Lêek thîi banchii: {ACCOUNT}",
                    f"Account number: {ACCOUNT}",
                ),
                ("วันที่: 30/10/2026", "Wan thîi: 30/10/2026", "Date: 30/10/2026"),
            ],
            {
                "name": ("ชื่อ", "Chûe"),
                "phone": ("โทรศัพท์", "Thoorasàp"),
                "account": ("เลขที่บัญชี", "Lêek thîi banchii"),
                "date": ("วันที่", "Wan thîi"),
                "email": ("อีเมล", "Iimeel"),
            },
            "30/10/2026",
        ),
        _s(
            "el",
            "Greek",
            "ltr",
            [
                (
                    "Αυτό είναι ένα έγγραφο δοκιμής.",
                    "Aftó eínai éna éngrafo dokimís.",
                    "This is a test document.",
                ),
                (
                    "Παρακαλούμε απαντήστε έως την επόμενη Δευτέρα.",
                    "Parakaloúme apantíste éos tin epómeni Deftéra.",
                    "Please reply by next Monday.",
                ),
                (
                    f"Επικοινωνία: {n['el'][0]}",
                    f"Epikoinonía: {n['el'][1]}",
                    f"Contact: {n['el'][1]}",
                ),
                (f"Τηλέφωνο: {PHONE}", f"Tiléfono: {PHONE}", f"Telephone: {PHONE}"),
                (f"Λογαριασμός: {ACCOUNT}", f"Logariasmós: {ACCOUNT}", f"Account: {ACCOUNT}"),
                ("Ημερομηνία: 30/10/2026", "Imerominía: 30/10/2026", "Date: 30/10/2026"),
            ],
            {
                "name": ("Όνομα", "Ónoma"),
                "phone": ("Τηλέφωνο", "Tiléfono"),
                "account": ("Λογαριασμός", "Logariasmós"),
                "date": ("Ημερομηνία", "Imerominía"),
                "email": ("Ηλεκτρονικό ταχυδρομείο", "Ilektronikó tachydromeío"),
            },
            "30/10/2026",
        ),
        _s(
            "ru",
            "Russian (Cyrillic)",
            "ltr",
            [
                ("Это тестовый документ.", "Eto testovyy dokument.", "This is a test document."),
                (
                    "Пожалуйста, ответьте до следующего понедельника.",
                    "Pozhaluysta, otvet'te do sleduyushchego ponedel'nika.",
                    "Please reply by next Monday.",
                ),
                (f"Контакт: {n['ru'][0]}", f"Kontakt: {n['ru'][1]}", f"Contact: {n['ru'][1]}"),
                (f"Телефон: {PHONE}", f"Telefon: {PHONE}", f"Telephone: {PHONE}"),
                (
                    f"Номер счёта: {ACCOUNT}",
                    f"Nomer schyota: {ACCOUNT}",
                    f"Account number: {ACCOUNT}",
                ),
                ("Дата: 30.10.2026", "Data: 30.10.2026", "Date: 30.10.2026"),
            ],
            {
                "name": ("Имя", "Imya"),
                "phone": ("Телефон", "Telefon"),
                "account": ("Номер счёта", "Nomer schyota"),
                "date": ("Дата", "Data"),
                "email": ("Эл. почта", "El. pochta"),
            },
            "30.10.2026",
        ),
        _s(
            "vi",
            "Vietnamese",
            "ltr",
            [
                ("Đây là một tài liệu thử nghiệm.", "", "This is a test document."),
                (
                    "Vui lòng trả lời trước thứ Hai tuần sau.",
                    "",
                    "Please reply before Monday next week.",
                ),
                (f"Người liên hệ: {n['vi'][0]}", "", f"Contact: {n['vi'][1]}"),
                (f"Điện thoại: {PHONE}", "", f"Telephone: {PHONE}"),
                (f"Số tài khoản: {ACCOUNT}", "", f"Account number: {ACCOUNT}"),
                ("Ngày: 30/10/2026", "", "Date: 30/10/2026"),
            ],
            {
                "name": ("Họ và tên", ""),
                "phone": ("Điện thoại", ""),
                "account": ("Số tài khoản", ""),
                "date": ("Ngày", ""),
                "email": ("Thư điện tử", ""),
            },
            "30/10/2026",
        ),
        _s(
            "pl",
            "Polish",
            "ltr",
            [
                ("To jest dokument testowy.", "", "This is a test document."),
                (
                    "Proszę odpowiedzieć do przyszłego poniedziałku.",
                    "",
                    "Please reply by next Monday.",
                ),
                (f"Kontakt: {n['pl'][0]}", "", f"Contact: {n['pl'][1]}"),
                (f"Telefon: {PHONE}", "", f"Telephone: {PHONE}"),
                (f"Numer konta: {ACCOUNT}", "", f"Account number: {ACCOUNT}"),
                ("Data: 30.10.2026", "", "Date: 30.10.2026"),
            ],
            {
                "name": ("Imię i nazwisko", ""),
                "phone": ("Telefon", ""),
                "account": ("Numer konta", ""),
                "date": ("Data", ""),
                "email": ("Poczta elektroniczna", ""),
            },
            "30.10.2026",
        ),
        _s(
            "is",
            "Icelandic",
            "ltr",
            [
                ("Þetta er prófunarskjal.", "", "This is a test document."),
                (
                    "Vinsamlegast svarið fyrir næsta mánudag.",
                    "",
                    "Please reply before next Monday.",
                ),
                (f"Tengiliður: {n['is'][0]}", "", f"Contact: {n['is'][1]}"),
                (f"Sími: {PHONE}", "", f"Telephone: {PHONE}"),
                (f"Reikningsnúmer: {ACCOUNT}", "", f"Account number: {ACCOUNT}"),
                ("Dagsetning: 30.10.2026", "", "Date: 30.10.2026"),
            ],
            {
                "name": ("Nafn", ""),
                "phone": ("Sími", ""),
                "account": ("Reikningsnúmer", ""),
                "date": ("Dagsetning", ""),
                "email": ("Netfang", ""),
            },
            "30.10.2026",
        ),
    ]
    by = {s.code: s for s in out}
    zh, ar = n["zh-Hans"], n["ar"]
    by["mixed"] = _s(
        "mixed",
        "Mixed Latin, Chinese and Arabic",
        "ltr",
        [
            (
                f"Contact {zh[0]} or {ar[0]} at {PHONE}.",
                f"Contact {zh[1]} or {ar[1]} at {PHONE}.",
                f"Contact {zh[1]} or {ar[1]} at {PHONE}.",
            ),
            (
                "File 文件 0417 and ملف 0417 are closed.",
                "File wénjiàn 0417 and milaff 0417 are closed.",
                "File (file) 0417 and file 0417 are closed.",
            ),
            (
                f"Account {ACCOUNT} 账号 رقم الحساب",
                f"Account {ACCOUNT} zhànghào raqm al-ḥisāb",
                f"Account {ACCOUNT}, account number, account number",
            ),
            (
                "Reply by Monday 周一 الاثنين please.",
                "Reply by Monday zhōuyī al-ithnayn please.",
                "Reply by Monday, Monday, Monday, please.",
            ),
        ],
        {},
        "",
    )
    return by


def form_rows(s: Script) -> list[tuple[str, str, str, str]]:
    return _rows(s.code, s.labels, s.date)
