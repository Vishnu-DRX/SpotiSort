import pytest

from src.enrichment.languages import CANONICAL
from src.enrichment.script_detect import detect_script_language, dominant_script

POSITIVE = [
    # Hindi / Devanagari
    ("Kesariya (केसरिया)", "hindi"),
    ("तुम ही हो", "hindi"),
    ("Tum Hi Ho - तुम ही हो", "hindi"),
    ("कल हो ना हो", "hindi"),
    ("अरिजीत सिंह", "hindi"),
    # Malayalam
    ("മഞ്ഞ് പെയ്യുന്നു", "malayalam"),
    ("Jimikki Kammal (ജിമിക്കി കമ്മൽ)", "malayalam"),
    ("എന്നും എപ്പോഴും", "malayalam"),
    # Tamil
    ("என்ன சொல்ல போகிறாய்", "tamil"),
    ("Vaathi Coming (வாத்தி கமிங்)", "tamil"),
    ("அனிருத் ரவிச்சந்தர்", "tamil"),
    # Telugu
    ("బుట్ట బొమ్మ", "telugu"),
    ("Naatu Naatu (నాటు నాటు)", "telugu"),
    # Kannada
    ("ಹೃದಯ ಗೀತೆ", "kannada"),
    ("Belageddu (ಬೆಳಗೆದ್ದು)", "kannada"),
    # Bengali
    ("আমি তোমার", "bengali"),
    ("Ekla Cholo (একলা চলো)", "bengali"),
    # Punjabi / Gurmukhi
    ("ਮੇਰੇ ਵਾਂਗ", "punjabi"),
    ("Lover (ਲਵਰ)", "punjabi"),
    # Gujarati
    ("કેમ છો", "gujarati"),
    # Odia
    ("ମୋ ଗାଁ", "odia"),
    # Sinhala
    ("සුදු මලේ", "sinhala"),
    # Japanese
    ("夜に駆ける", "japanese"),
    ("Lemon (レモン)", "japanese"),
    ("さくら", "japanese"),
    ("ありがとう", "japanese"),
    ("カラオケ", "japanese"),
    ("米津玄師 - 打ち上げ花火", "japanese"),
    ("ｶﾀｶﾅ", "japanese"),  # halfwidth katakana
    # Korean
    ("봄날", "korean"),
    ("Dynamite (다이너마이트)", "korean"),
    ("사랑해 愛", "korean"),
    # Chinese
    ("月亮代表我的心", "chinese"),
    ("小幸运", "chinese"),
    ("Jay Chou 周杰伦", "chinese"),
    # Russian
    ("Группа крови", "russian"),
    ("Мурашки (Murashki)", "russian"),
    # Arabic
    ("يا حبيبي", "arabic"),
    ("Habibi (حبيبي)", "arabic"),
    # Hebrew
    ("שיר לשלום", "hebrew"),
    # Thai
    ("สวัสดีปีใหม่", "thai"),
    # Greek
    ("Σ' αγαπώ", "greek"),
    ("Ελληνικά τραγούδια", "greek"),
]

NEGATIVE = [
    "Blinding Lights",
    "Shape of You",
    "Beyoncé",
    "Mañana",
    "Café del Mar",
    "Über Alles",
    "Björk",
    "Sigur Rós",
    "1999",
    "!!! (Chk Chk Chk)",
    "😀🎶",
    "",
    "   ",
    None,
]


@pytest.mark.parametrize("text, expected", POSITIVE)
def test_positive(text, expected):
    got = detect_script_language(text)
    assert got == expected
    assert got in CANONICAL


def test_at_least_40_positive_cases():
    assert len(POSITIVE) >= 40


@pytest.mark.parametrize("text", NEGATIVE)
def test_negative(text):
    assert detect_script_language(text) is None
    assert dominant_script(text) is None


def test_no_args():
    assert detect_script_language() is None


def test_multi_arg_combined_counts():
    # Latin track + Devanagari album -> hindi
    assert detect_script_language("Kesariya", "Brahmastra", "अरिजीत सिंह") == "hindi"
    # None args are skipped
    assert detect_script_language(None, "봄날", None) == "korean"
    # Combined letter counts: more Tamil letters than Telugu letters overall
    assert detect_script_language("తె", "தமிழ் பாடல்") == "tamil"
    # Pure Latin across all args -> None
    assert detect_script_language("Track", "Album", "Artist") is None


def test_kana_wins_over_han_even_if_outnumbered():
    assert detect_script_language("東京事変 私の記憶 の") == "japanese"


def test_hangul_with_hanja_is_korean():
    assert detect_script_language("愛 사랑") == "korean"


def test_devanagari_default_override():
    assert detect_script_language("मराठी गाणे") == "hindi"
    assert detect_script_language("मराठी गाणे", devanagari_default="marathi") == "marathi"
    assert detect_script_language("तुम ही हो", devanagari_default="marathi") == "marathi"
    # override does not affect other scripts
    assert detect_script_language("தமிழ்", devanagari_default="marathi") == "tamil"


def test_dominant_script_ids():
    assert dominant_script("Kesariya (केसरिया)") == "devanagari"
    assert dominant_script("Lemon (レモン)") == "kana"
    assert dominant_script("月亮代表我的心") == "han"
    assert dominant_script("봄날") == "hangul"
    assert dominant_script("ਮੇਰੇ ਵਾਂਗ") == "gurmukhi"


def test_all_outputs_canonical():
    for text, _ in POSITIVE:
        assert detect_script_language(text) in CANONICAL
    assert detect_script_language("मराठी", devanagari_default="marathi") in CANONICAL
