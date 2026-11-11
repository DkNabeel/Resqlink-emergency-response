"""Local multilingual emergency intent detection and basic safety guidance."""
import unicodedata

TERMS = {
    "fire": {
        "en": ["fire", "smoke", "burning", "flames"],
        "hi": ["आग", "धुआँ", "जल रहा"],
        "kn": ["ಬೆಂಕಿ", "ಹೊಗೆ", "ಸುಡುತ್ತ"],
    },
    "flood": {
        "en": ["flood", "flooding", "water rising", "drowning"],
        "hi": ["बाढ़", "पानी भर", "डूब"],
        "kn": ["ಪ್ರವಾಹ", "ನೀರು ತುಂಬ", "ಮುಳುಗ"],
    },
    "earthquake": {
        "en": ["earthquake", "tremor", "ground shaking"],
        "hi": ["भूकंप", "धरती हिल", "झटके"],
        "kn": ["ಭೂಕಂಪ", "ನೆಲ ನಡುಗ", "ಕಂಪನ"],
    },
    "medical": {
        "en": ["bleeding", "unconscious", "not breathing", "chest pain", "heart attack", "medical emergency"],
        "hi": ["खून बह", "बेहोश", "सांस नहीं", "सीने में दर्द"],
        "kn": ["ರಕ್ತಸ್ರಾವ", "ಪ್ರಜ್ಞೆ ಇಲ್ಲ", "ಉಸಿರಾಡುತ್ತಿಲ್ಲ", "ಎದೆನೋವು"],
    },
    "road_accident": {
        "en": ["road accident", "car crash", "vehicle crash", "collision", "bike accident"],
        "hi": ["सड़क हादसा", "दुर्घटना", "गाड़ी टक्कर"],
        "kn": ["ರಸ್ತೆ ಅಪಘಾತ", "ವಾಹನ ಡಿಕ್ಕಿ", "ಅಪಘಾತ"],
    },
    "violence": {
        "en": ["attacker", "being attacked", "assault", "armed person"],
        "hi": ["हमला", "मारपीट", "धमकी"],
        "kn": ["ದಾಳಿ", "ಹಲ್ಲೆ", "ಬೆದರಿಕೆ"],
    },
}

GUIDANCE = {
    "en": {
        "fire": ["Leave immediately through the nearest safe exit.", "Stay low under smoke; never use elevators.", "Do not re-enter; call local emergency services from a safe place."],
        "flood": ["Move to higher ground immediately.", "Never walk or drive through floodwater.", "Stay away from electrical lines and follow official evacuation instructions."],
        "earthquake": ["Drop, cover and hold on until shaking stops.", "Stay away from windows and heavy objects; do not use elevators.", "After shaking, leave damaged buildings carefully and expect aftershocks."],
        "medical": ["Contact local emergency medical services immediately.", "Apply firm direct pressure to severe external bleeding.", "Do not move a seriously injured person unless there is immediate danger; follow dispatcher instructions."],
        "road_accident": ["Move away from traffic if safe.", "Call local emergency services and give the exact location.", "Do not move injured people unless there is immediate danger; do not remove a motorcyclist's helmet."],
        "violence": ["Move away from the threat and reach a secure place.", "Do not confront the attacker.", "Contact emergency services when safe; silence your phone if hiding."],
        "unknown": ["Move away from immediate danger if possible.", "Contact local emergency services and give your exact location.", "Follow official local responder instructions."],
    },
    "hi": {
        "fire": ["निकटतम सुरक्षित निकास से तुरंत बाहर निकलें।", "धुएँ में नीचे झुककर चलें; लिफ्ट का उपयोग न करें।", "वापस अंदर न जाएँ; सुरक्षित स्थान से स्थानीय आपातकालीन सेवा को कॉल करें।"],
        "flood": ["तुरंत ऊँचे स्थान पर जाएँ।", "बाढ़ के पानी में पैदल या वाहन से न जाएँ।", "बिजली की तारों से दूर रहें और आधिकारिक निकासी निर्देश मानें।"],
        "earthquake": ["झटके रुकने तक नीचे झुकें, ढकें और पकड़े रहें।", "खिड़कियों और भारी वस्तुओं से दूर रहें; लिफ्ट न लें।", "झटके रुकने पर क्षतिग्रस्त इमारत से सावधानी से बाहर निकलें।"],
        "medical": ["तुरंत स्थानीय चिकित्सा आपातकालीन सेवा से संपर्क करें।", "अधिक बाहरी रक्तस्राव पर साफ कपड़े से सीधा दबाव दें।", "तत्काल खतरा न हो तो गंभीर घायल को न हिलाएँ; डिस्पैचर के निर्देश मानें।"],
        "road_accident": ["सुरक्षित हो तो यातायात से दूर जाएँ।", "आपातकालीन सेवा को कॉल करके सटीक स्थान बताएँ।", "तत्काल खतरा न हो तो घायल को न हिलाएँ; बाइक सवार का हेलमेट न हटाएँ।"],
        "violence": ["खतरे से दूर होकर सुरक्षित स्थान पर जाएँ।", "हमलावर का सामना न करें।", "सुरक्षित होने पर आपातकालीन सेवा से संपर्क करें।"],
        "unknown": ["संभव हो तो तत्काल खतरे से दूर जाएँ।", "स्थानीय आपातकालीन सेवा से संपर्क कर सटीक स्थान बताएँ।", "स्थानीय अधिकारियों के निर्देश मानें।"],
    },
    "kn": {
        "fire": ["ಹತ್ತಿರದ ಸುರಕ್ಷಿತ ನಿರ್ಗಮನದ ಮೂಲಕ ತಕ್ಷಣ ಹೊರಬನ್ನಿ.", "ಹೊಗೆ ಇದ್ದರೆ ಕೆಳಮಟ್ಟದಲ್ಲಿ ಚಲಿಸಿ; ಲಿಫ್ಟ್ ಬಳಸಬೇಡಿ.", "ಮತ್ತೆ ಒಳಗೆ ಹೋಗಬೇಡಿ; ಸುರಕ್ಷಿತ ಸ್ಥಳದಿಂದ ತುರ್ತು ಸೇವೆಗೆ ಕರೆಮಾಡಿ."],
        "flood": ["ತಕ್ಷಣ ಎತ್ತರದ ಪ್ರದೇಶಕ್ಕೆ ತೆರಳಿ.", "ಪ್ರವಾಹದ ನೀರಿನಲ್ಲಿ ನಡೆಯಬೇಡಿ ಅಥವಾ ವಾಹನ ಚಲಾಯಿಸಬೇಡಿ.", "ವಿದ್ಯುತ್ ತಂತಿಗಳಿಂದ ದೂರವಿದ್ದು ಅಧಿಕೃತ ಸೂಚನೆ ಪಾಲಿಸಿ."],
        "earthquake": ["ಕಂಪನ ನಿಲ್ಲುವವರೆಗೆ ಕೆಳಗೆ ಬಾಗಿ, ಆಶ್ರಯ ಪಡೆದು ಹಿಡಿದುಕೊಳ್ಳಿ.", "ಕಿಟಕಿ ಮತ್ತು ಭಾರವಾದ ವಸ್ತುಗಳಿಂದ ದೂರವಿರಿ; ಲಿಫ್ಟ್ ಬಳಸಬೇಡಿ.", "ಕಂಪನ ನಿಂತ ನಂತರ ಹಾನಿಗೊಂಡ ಕಟ್ಟಡದಿಂದ ಎಚ್ಚರಿಕೆಯಿಂದ ಹೊರಬನ್ನಿ."],
        "medical": ["ತಕ್ಷಣ ಸ್ಥಳೀಯ ವೈದ್ಯಕೀಯ ತುರ್ತು ಸೇವೆಯನ್ನು ಸಂಪರ್ಕಿಸಿ.", "ತೀವ್ರ ರಕ್ತಸ್ರಾವಕ್ಕೆ ಸ್ವಚ್ಛ ಬಟ್ಟೆಯಿಂದ ನೇರ ಒತ್ತಡ ನೀಡಿ.", "ತಕ್ಷಣದ ಅಪಾಯವಿಲ್ಲದಿದ್ದರೆ ಗಂಭೀರ ಗಾಯಾಳುವನ್ನು ಕದಲಿಸಬೇಡಿ."],
        "road_accident": ["ಸುರಕ್ಷಿತವಾಗಿದ್ದರೆ ವಾಹನ ಸಂಚಾರದಿಂದ ದೂರವಿರಿ.", "ತುರ್ತು ಸೇವೆಗೆ ಕರೆಮಾಡಿ ನಿಖರ ಸ್ಥಳ ತಿಳಿಸಿ.", "ತಕ್ಷಣದ ಅಪಾಯವಿಲ್ಲದಿದ್ದರೆ ಗಾಯಾಳುವನ್ನು ಕದಲಿಸಬೇಡಿ; ಹೆಲ್ಮೆಟ್ ತೆಗೆಯಬೇಡಿ."],
        "violence": ["ಅಪಾಯದಿಂದ ದೂರವಾಗಿ ಸುರಕ್ಷಿತ ಸ್ಥಳಕ್ಕೆ ತೆರಳಿ.", "ದಾಳಿ ಮಾಡುವವರನ್ನು ಎದುರಿಸಬೇಡಿ.", "ಸುರಕ್ಷಿತವಾದಾಗ ತುರ್ತು ಸೇವೆಯನ್ನು ಸಂಪರ್ಕಿಸಿ."],
        "unknown": ["ಸಾಧ್ಯವಾದರೆ ತಕ್ಷಣದ ಅಪಾಯದಿಂದ ದೂರವಿರಿ.", "ಸ್ಥಳೀಯ ತುರ್ತು ಸೇವೆಗೆ ಕರೆಮಾಡಿ ನಿಖರ ಸ್ಥಳ ತಿಳಿಸಿ.", "ಸ್ಥಳೀಯ ಅಧಿಕಾರಿಗಳ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸಿ."],
    },
}


def _norm(value):
    return unicodedata.normalize("NFKC", value or "").casefold()


def detect_emergency(message):
    text = _norm(message)
    found_by_type = {}
    for category, translations in TERMS.items():
        found = []
        for words in translations.values():
            found.extend(word for word in words if _norm(word) in text)
        if found:
            found_by_type[category] = list(dict.fromkeys(found))
    priority = ("fire", "earthquake", "flood", "medical", "road_accident", "violence")
    category = next((name for name in priority if name in found_by_type), "unknown")
    return {
        "emergency_type": category,
        "matched_keywords": found_by_type.get(category, []),
        "all_detected_types": list(found_by_type),
        "method": "multilingual_keyword_intent_detection",
        "confidence_label": "keyword_match" if category != "unknown" else "not_detected",
    }


def build_emergency_response(message, language="en"):
    lang = (language or "en").lower().split("-")[0]
    if lang not in GUIDANCE:
        lang = "en"
    result = detect_emergency(message)
    category = result["emergency_type"]
    notices = {
        "en": "General guidance only. Contact local emergency services and follow official instructions.",
        "hi": "यह सामान्य मार्गदर्शन है। स्थानीय आपातकालीन सेवा और आधिकारिक निर्देशों का पालन करें।",
        "kn": "ಇದು ಸಾಮಾನ್ಯ ಮಾರ್ಗದರ್ಶನ ಮಾತ್ರ. ಸ್ಥಳೀಯ ತುರ್ತು ಸೇವೆ ಮತ್ತು ಅಧಿಕೃತ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸಿ.",
    }
    return {
        **result,
        "language": lang,
        "urgency": "urgent" if category != "unknown" else "undetermined",
        "guidance": GUIDANCE[lang][category],
        "safety_notice": notices[lang],
    }
