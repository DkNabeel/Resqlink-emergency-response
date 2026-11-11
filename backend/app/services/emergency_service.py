"""Rule-based multilingual emergency intent detection and safety guidance.

This module is a deterministic NLP fallback for development/demo use. It is
not a trained model, does not diagnose injuries, and does not replace official
emergency responders.
"""
import re
import unicodedata


TERMS = {
    "fire": {
        "en": ["fire", "smoke", "burning", "flames", "building is on fire"],
        "hi": ["आग", "धुआँ", "जल रहा", "आग लग"],
        "kn": ["ಬೆಂಕಿ", "ಹೊಗೆ", "ಸುಡುತ್ತ", "ಅಗ್ನಿ"],
    },
    "flood": {
        "en": ["flood", "flooding", "water rising", "water entering house", "submerged"],
        "hi": ["बाढ़", "पानी भर", "पानी चढ़", "जलभराव", "डूब"],
        "kn": ["ಪ್ರವಾಹ", "ನೀರು ತುಂಬ", "ಮನೆಗೆ ನೀರು", "ಮುಳುಗ", "ಜಲಾವೃತ"],
    },
    "earthquake": {
        "en": ["earthquake", "tremor", "ground shaking", "building shaking"],
        "hi": ["भूकंप", "धरती हिल", "जमीन हिल", "झटके"],
        "kn": ["ಭೂಕಂಪ", "ನೆಲ ನಡುಗ", "ಭೂಮಿ ಕಂಪ", "ಕಂಪನ"],
    },
    "cyclone": {
        "en": ["cyclone", "hurricane", "typhoon", "extreme wind", "storm surge"],
        "hi": ["चक्रवात", "तूफान", "तेज आंधी"],
        "kn": ["ಚಂಡಮಾರುತ", "ಸುಂಟರಗಾಳಿ", "ಭಾರಿ ಗಾಳಿ"],
    },
    "landslide": {
        "en": ["landslide", "mudslide", "slope collapse", "hill is collapsing"],
        "hi": ["भूस्खलन", "पहाड़ खिसक", "मिट्टी धंस"],
        "kn": ["ಭೂಕುಸಿತ", "ಬೆಟ್ಟ ಕುಸಿತ", "ಮಣ್ಣು ಕುಸಿತ"],
    },
    "tsunami": {
        "en": ["tsunami", "sea wave warning", "ocean surge"],
        "hi": ["सुनामी", "समुद्री लहर चेतावनी"],
        "kn": ["ಸುನಾಮಿ", "ಸಮುದ್ರ ಅಲೆ ಎಚ್ಚರಿಕೆ"],
    },
    "lightning": {
        "en": ["lightning", "thunder strike", "thunderstorm", "lightning strike"],
        "hi": ["बिजली गिर", "आकाशीय बिजली", "गरज के साथ तूफान"],
        "kn": ["ಮಿಂಚು", "ಸಿಡಿಲು", "ಗುಡುಗು ಮಳೆ"],
    },
    "gas_leak": {
        "en": ["gas leak", "gas leakage", "smell of gas", "gas smell", "lpg leak"],
        "hi": ["गैस रिसाव", "गैस लीक", "गैस की गंध", "एलपीजी लीक"],
        "kn": ["ಅನಿಲ ಸೋರಿಕೆ", "ಗ್ಯಾಸ್ ಲೀಕ್", "ಅನಿಲದ ವಾಸನೆ"],
    },
    "medical": {
        "en": ["bleeding", "unconscious", "not breathing", "cannot breathe", "can't breathe", "difficulty breathing", "shortness of breath", "chest pain", "heart attack", "medical emergency", "laceration", "deep cut", "cut by", "cut my hand", "cut my finger", "hand has been cut", "my hand is cut", "finger cut", "hand injury", "finger injury", "wound", "stab wound"],
        "hi": ["खून बह", "बेहोश", "सांस नहीं", "सांस लेने में", "सीने में दर्द", "दिल का दौरा", "कट गया", "गहरा घाव", "हाथ कट", "उंगली कट"],
        "kn": ["ರಕ್ತಸ್ರಾವ", "ಪ್ರಜ್ಞೆ ಇಲ್ಲ", "ಉಸಿರಾಡುತ್ತಿಲ್ಲ", "ಉಸಿರಾಟದ ತೊಂದರೆ", "ಎದೆನೋವು", "ಹೃದಯಾಘಾತ", "ಕೈ ಕತ್ತರ", "ಕೈಗೆ ಗಾಯ", "ಬೆರಳು ಕತ್ತರ", "ಆಳವಾದ ಗಾಯ"],
    },
    "road_accident": {
        "en": ["road accident", "car crash", "vehicle crash", "collision", "bike accident", "road crash"],
        "hi": ["सड़क हादसा", "दुर्घटना", "गाड़ी टक्कर", "बाइक दुर्घटना"],
        "kn": ["ರಸ್ತೆ ಅಪಘಾತ", "ವಾಹನ ಡಿಕ್ಕಿ", "ಬೈಕ್ ಅಪಘಾತ", "ಅಪಘಾತ"],
    },
    "violence": {
        "en": ["attacker", "being attacked", "assault", "armed person", "physical attack", "gunfire", "gunshots", "shooting", "war", "war zone", "armed conflict", "bombing", "air raid", "shelling", "missile", "civil unrest"],
        "hi": ["हमला", "मारपीट", "धमकी", "हथियार", "युद्ध", "गोलीबारी", "बमबारी", "हवाई हमला"],
        "kn": ["ದಾಳಿ", "ಹಲ್ಲೆ", "ಬೆದರಿಕೆ", "ಆಯುಧ", "ಯುದ್ಧ", "ಗುಂಡಿನ ದಾಳಿ", "ಬಾಂಬ್ ದಾಳಿ"],
    },
}

GUIDANCE = {
    "en": {
        "fire": ["Leave immediately through the nearest safe exit.", "Stay low under smoke; never use elevators.", "Do not re-enter the building. Call emergency services from a safe place."],
        "flood": ["Move to higher ground immediately; do not enter moving floodwater.", "Never walk, swim or drive through floodwater.", "Stay away from electrical equipment and fallen power lines; follow official evacuation instructions."],
        "earthquake": ["Drop, cover and hold on until shaking stops.", "Stay away from windows and heavy objects; do not use elevators.", "After shaking, leave damaged buildings carefully and expect aftershocks."],
        "cyclone": ["Stay inside a sturdy building and away from windows.", "Move to an official cyclone shelter if authorities instruct you to evacuate.", "Avoid coastal areas, floodwater, fallen trees and power lines."],
        "landslide": ["Move away from the path of moving soil or debris if you can do so safely.", "Move to stable ground away from slopes, valleys and drainage channels.", "Follow evacuation orders; do not return until authorities say it is safe."],
        "tsunami": ["After a strong or long coastal earthquake, move immediately to high ground or inland.", "Do not wait to watch the sea or approach the shore.", "Remain in the safe area until authorities issue an all-clear."],
        "lightning": ["Move into a substantial enclosed building or hard-topped vehicle.", "Avoid open fields, isolated trees, hilltops, water and metal objects.", "Wait at least 30 minutes after the last thunder before returning outdoors."],
        "gas_leak": ["Leave the area immediately and move upwind if possible.", "Do not operate switches, appliances, flames or vehicles near the suspected leak.", "From a safe location, call emergency services and do not re-enter until cleared."],
        "medical": ["Apply firm, continuous pressure to external bleeding with clean gauze or cloth.", "If it does not increase pain, raise the injured hand and remove rings before swelling begins.", "Do not pull out glass or another object embedded in the wound; avoid repeatedly lifting the dressing.", "Seek urgent medical care for a deep or gaping wound, numbness, loss of finger movement, or bleeding that will not stop; call 112 for severe bleeding or immediate danger."],
        "road_accident": ["Move yourself away from traffic if you can do so safely.", "Call emergency services and provide the exact location and number of injured people.", "Do not move injured people unless there is immediate danger; do not remove a motorcyclist's helmet."],
        "violence": ["Move away from the threat and reach a secure place if possible.", "Do not confront or approach the attacker.", "Contact emergency services when safe; silence your phone if hiding."],
        "unknown": ["Move away from immediate danger if possible.", "Contact local emergency services and give your exact location.", "Follow official local responder instructions."],
    },
    "hi": {
        "fire": ["निकटतम सुरक्षित निकास से तुरंत बाहर निकलें।", "धुएँ में नीचे झुककर चलें; लिफ्ट का उपयोग न करें।", "इमारत में वापस न जाएँ; सुरक्षित स्थान से आपातकालीन सेवा को कॉल करें।"],
        "flood": ["तुरंत ऊँचे स्थान पर जाएँ; बहते पानी में प्रवेश न करें।", "बाढ़ के पानी में पैदल, तैरकर या वाहन से न जाएँ।", "बिजली के उपकरणों और गिरी तारों से दूर रहें; आधिकारिक निर्देश मानें।"],
        "earthquake": ["झटके रुकने तक नीचे झुकें, ढकें और पकड़े रहें।", "खिड़कियों और भारी वस्तुओं से दूर रहें; लिफ्ट न लें।", "झटके रुकने पर क्षतिग्रस्त इमारत से सावधानी से बाहर निकलें।"],
        "cyclone": ["मजबूत इमारत के अंदर रहें और खिड़कियों से दूर रहें।", "प्रशासन के आदेश पर आधिकारिक चक्रवात आश्रय में जाएँ।", "समुद्र तट, बाढ़ के पानी और गिरी बिजली की तारों से दूर रहें।"],
        "landslide": ["संभव हो तो मिट्टी या मलबे के बहाव के रास्ते से दूर जाएँ।", "ढलानों, घाटियों और जल निकासी मार्गों से दूर स्थिर स्थान पर जाएँ।", "प्रशासन के निर्देश मानें और अनुमति मिलने तक वापस न लौटें।"],
        "tsunami": ["तटीय क्षेत्र में तेज या लंबे भूकंप के बाद तुरंत ऊँचे स्थान या अंदरूनी क्षेत्र में जाएँ।", "समुद्र देखने या किनारे के पास जाने के लिए प्रतीक्षा न करें।", "अधिकारियों की सुरक्षित होने की सूचना तक वहीं रहें।"],
        "lightning": ["किसी मजबूत बंद इमारत या बंद वाहन में जाएँ।", "खुले मैदान, अकेले पेड़, पहाड़ी चोटी और पानी से दूर रहें।", "आखिरी गर्जना के कम से कम 30 मिनट बाद ही बाहर जाएँ।"],
        "gas_leak": ["तुरंत क्षेत्र छोड़ें और संभव हो तो हवा की दिशा के विपरीत सुरक्षित दूरी पर जाएँ।", "स्विच, उपकरण, आग या वाहन चालू न करें।", "सुरक्षित स्थान से आपातकालीन सेवा को कॉल करें; अनुमति मिलने तक वापस न जाएँ।"],
        "medical": ["साफ कपड़े या गॉज से घाव पर लगातार सीधा दबाव दें।", "दर्द न बढ़े तो घायल हाथ को ऊपर रखें और सूजन से पहले अंगूठी निकालें।", "घाव में फँसी वस्तु न निकालें और बार-बार कपड़ा हटाकर न देखें।", "गहरा घाव, सुन्नपन, उँगली न हिल पाना या न रुकता रक्तस्राव हो तो तुरंत चिकित्सा सहायता लें; तेज रक्तस्राव में 112 पर कॉल करें।"],
        "road_accident": ["सुरक्षित हो तो खुद को यातायात से दूर करें।", "आपातकालीन सेवा को कॉल करके सटीक स्थान और घायलों की संख्या बताएँ।", "तत्काल खतरा न हो तो घायल को न हिलाएँ; बाइक सवार का हेलमेट न हटाएँ।"],
        "violence": ["खतरे से दूर होकर सुरक्षित स्थान पर जाएँ।", "हमलावर का सामना न करें।", "सुरक्षित होने पर आपातकालीन सेवा से संपर्क करें।"],
        "unknown": ["संभव हो तो तत्काल खतरे से दूर जाएँ।", "स्थानीय आपातकालीन सेवा से संपर्क कर सटीक स्थान बताएँ।", "स्थानीय अधिकारियों के निर्देश मानें।"],
    },
    "kn": {
        "fire": ["ಹತ್ತಿರದ ಸುರಕ್ಷಿತ ನಿರ್ಗಮನದ ಮೂಲಕ ತಕ್ಷಣ ಹೊರಬನ್ನಿ.", "ಹೊಗೆ ಇದ್ದರೆ ಕೆಳಮಟ್ಟದಲ್ಲಿ ಚಲಿಸಿ; ಲಿಫ್ಟ್ ಬಳಸಬೇಡಿ.", "ಮತ್ತೆ ಒಳಗೆ ಹೋಗಬೇಡಿ; ಸುರಕ್ಷಿತ ಸ್ಥಳದಿಂದ ತುರ್ತು ಸೇವೆಗೆ ಕರೆಮಾಡಿ."],
        "flood": ["ತಕ್ಷಣ ಎತ್ತರದ ಪ್ರದೇಶಕ್ಕೆ ತೆರಳಿ; ಹರಿಯುವ ಪ್ರವಾಹದ ನೀರಿಗೆ ಇಳಿಯಬೇಡಿ.", "ಪ್ರವಾಹದ ನೀರಿನಲ್ಲಿ ನಡೆಯಬೇಡಿ ಅಥವಾ ವಾಹನ ಚಲಾಯಿಸಬೇಡಿ.", "ವಿದ್ಯುತ್ ಉಪಕರಣಗಳು ಮತ್ತು ಬಿದ್ದ ತಂತಿಗಳಿಂದ ದೂರವಿರಿ."],
        "earthquake": ["ಕಂಪನ ನಿಲ್ಲುವವರೆಗೆ ಕೆಳಗೆ ಬಾಗಿ, ಆಶ್ರಯ ಪಡೆದು ಹಿಡಿದುಕೊಳ್ಳಿ.", "ಕಿಟಕಿ ಮತ್ತು ಭಾರವಾದ ವಸ್ತುಗಳಿಂದ ದೂರವಿರಿ; ಲಿಫ್ಟ್ ಬಳಸಬೇಡಿ.", "ಕಂಪನ ನಿಂತ ನಂತರ ಹಾನಿಗೊಂಡ ಕಟ್ಟಡದಿಂದ ಎಚ್ಚರಿಕೆಯಿಂದ ಹೊರಬನ್ನಿ."],
        "cyclone": ["ಗಟ್ಟಿಯಾದ ಕಟ್ಟಡದ ಒಳಗೆ ಇರಿ ಮತ್ತು ಕಿಟಕಿಗಳಿಂದ ದೂರವಿರಿ.", "ಅಧಿಕಾರಿಗಳು ಸೂಚಿಸಿದರೆ ಅಧಿಕೃತ ಚಂಡಮಾರುತ ಆಶ್ರಯಕ್ಕೆ ತೆರಳಿ.", "ಕರಾವಳಿ, ಪ್ರವಾಹದ ನೀರು ಮತ್ತು ಬಿದ್ದ ವಿದ್ಯುತ್ ತಂತಿಗಳಿಂದ ದೂರವಿರಿ."],
        "landslide": ["ಸುರಕ್ಷಿತವಾಗಿ ಸಾಧ್ಯವಾದರೆ ಮಣ್ಣು ಅಥವಾ ಅವಶೇಷಗಳು ಹರಿಯುವ ದಾರಿಯಿಂದ ದೂರ ಸರಿಯಿರಿ.", "ಇಳಿಜಾರು, ಕಣಿವೆ ಮತ್ತು ನೀರು ಹರಿಯುವ ಮಾರ್ಗಗಳಿಂದ ದೂರದ ಸ್ಥಿರ ಸ್ಥಳಕ್ಕೆ ತೆರಳಿ.", "ಅಧಿಕೃತ ಸೂಚನೆ ಪಾಲಿಸಿ; ಅನುಮತಿ ಸಿಗುವವರೆಗೆ ಹಿಂದಿರುಗಬೇಡಿ."],
        "tsunami": ["ಕರಾವಳಿಯಲ್ಲಿ ಬಲವಾದ ಅಥವಾ ದೀರ್ಘ ಭೂಕಂಪವಾದರೆ ತಕ್ಷಣ ಎತ್ತರದ ಅಥವಾ ಒಳನಾಡಿನ ಪ್ರದೇಶಕ್ಕೆ ತೆರಳಿ.", "ಸಮುದ್ರ ನೋಡಲು ಅಥವಾ ಕರಾವಳಿಗೆ ಹತ್ತಿರ ಹೋಗಲು ಕಾಯಬೇಡಿ.", "ಅಧಿಕಾರಿಗಳು ಸುರಕ್ಷಿತವೆಂದು ತಿಳಿಸುವವರೆಗೆ ಅಲ್ಲೇ ಇರಿ."],
        "lightning": ["ಮುಚ್ಚಿದ ಬಲವಾದ ಕಟ್ಟಡ ಅಥವಾ ಗಟ್ಟಿಯಾದ ಮೇಲ್ಛಾವಣಿಯ ವಾಹನದೊಳಗೆ ಹೋಗಿ.", "ತೆರೆದ ಮೈದಾನ, ಒಂಟಿ ಮರ, ಬೆಟ್ಟದ ತುದಿ ಮತ್ತು ನೀರಿನಿಂದ ದೂರವಿರಿ.", "ಕೊನೆಯ ಗುಡುಗಿನ ನಂತರ ಕನಿಷ್ಠ 30 ನಿಮಿಷ ಕಾಯಿರಿ."],
        "gas_leak": ["ತಕ್ಷಣ ಆ ಪ್ರದೇಶದಿಂದ ಹೊರಬನ್ನಿ; ಸಾಧ್ಯವಾದರೆ ಗಾಳಿಯ ವಿರುದ್ಧ ದಿಕ್ಕಿನಲ್ಲಿ ದೂರ ಸರಿಯಿರಿ.", "ಸ್ವಿಚ್, ವಿದ್ಯುತ್ ಉಪಕರಣ, ಬೆಂಕಿ ಅಥವಾ ವಾಹನವನ್ನು ಚಾಲನೆ ಮಾಡಬೇಡಿ.", "ಸುರಕ್ಷಿತ ಸ್ಥಳದಿಂದ ತುರ್ತು ಸೇವೆಗೆ ಕರೆಮಾಡಿ; ಅನುಮತಿ ಸಿಗುವವರೆಗೆ ಹಿಂದಿರುಗಬೇಡಿ."],
        "medical": ["ಸ್ವಚ್ಛ ಬಟ್ಟೆ ಅಥವಾ ಗಾಜ್‌ನಿಂದ ಗಾಯದ ಮೇಲೆ ನಿರಂತರ ನೇರ ಒತ್ತಡ ನೀಡಿ.", "ನೋವು ಹೆಚ್ಚದಿದ್ದರೆ ಗಾಯಗೊಂಡ ಕೈಯನ್ನು ಮೇಲಕ್ಕೆ ಇಡಿ ಮತ್ತು ಊತ ಬರುವ ಮೊದಲು ಉಂಗುರ ತೆಗೆದುಹಾಕಿ.", "ಗಾಯದಲ್ಲಿ ಸಿಲುಕಿರುವ ವಸ್ತುವನ್ನು ಎಳೆಯಬೇಡಿ; ಬಟ್ಟೆಯನ್ನು ಪದೇಪದೇ ತೆಗೆದು ನೋಡಬೇಡಿ.", "ಆಳವಾದ ಗಾಯ, ಮರಗಟ್ಟುವಿಕೆ, ಬೆರಳು ಚಲಿಸಲಾಗದ ಸ್ಥಿತಿ ಅಥವಾ ನಿಲ್ಲದ ರಕ್ತಸ್ರಾವವಿದ್ದರೆ ತಕ್ಷಣ ವೈದ್ಯಕೀಯ ನೆರವು ಪಡೆಯಿರಿ; ತೀವ್ರ ರಕ್ತಸ್ರಾವಕ್ಕೆ 112 ಕರೆಮಾಡಿ."],
        "road_accident": ["ಸುರಕ್ಷಿತವಾಗಿದ್ದರೆ ವಾಹನ ಸಂಚಾರದಿಂದ ದೂರವಿರಿ.", "ತುರ್ತು ಸೇವೆಗೆ ಕರೆಮಾಡಿ ನಿಖರ ಸ್ಥಳ ಮತ್ತು ಗಾಯಾಳುಗಳ ಸಂಖ್ಯೆಯನ್ನು ತಿಳಿಸಿ.", "ತಕ್ಷಣದ ಅಪಾಯವಿಲ್ಲದಿದ್ದರೆ ಗಾಯಾಳುವನ್ನು ಕದಲಿಸಬೇಡಿ; ಹೆಲ್ಮೆಟ್ ತೆಗೆಯಬೇಡಿ."],
        "violence": ["ಅಪಾಯದಿಂದ ದೂರವಾಗಿ ಸುರಕ್ಷಿತ ಸ್ಥಳಕ್ಕೆ ತೆರಳಿ.", "ದಾಳಿ ಮಾಡುವವರನ್ನು ಎದುರಿಸಬೇಡಿ.", "ಸುರಕ್ಷಿತವಾದಾಗ ತುರ್ತು ಸೇವೆಯನ್ನು ಸಂಪರ್ಕಿಸಿ."],
        "unknown": ["ಸಾಧ್ಯವಾದರೆ ತಕ್ಷಣದ ಅಪಾಯದಿಂದ ದೂರವಿರಿ.", "ಸ್ಥಳೀಯ ತುರ್ತು ಸೇವೆಗೆ ಕರೆಮಾಡಿ ನಿಖರ ಸ್ಥಳ ತಿಳಿಸಿ.", "ಸ್ಥಳೀಯ ಅಧಿಕಾರಿಗಳ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸಿ."],
    },
}

FACILITY_SUGGESTIONS = {
    "fire": ["fire_station"],
    "gas_leak": ["fire_station"],
    "medical": ["hospital", "ambulance"],
    "road_accident": ["hospital", "ambulance", "police"],
    "violence": ["police"],
    "earthquake": ["shelter", "hospital", "fire_station"],
    "flood": ["shelter", "hospital", "fire_station"],
    "cyclone": ["shelter", "hospital", "fire_station"],
    "landslide": ["shelter", "hospital", "fire_station"],
    "tsunami": ["shelter", "hospital", "fire_station"],
    "lightning": ["hospital"],
    "unknown": [],
}

EMERGENCY_CONTACT_INDIA = {
    "number": "112",
    "dial_uri": "tel:112",
    "label": "Emergency Response Support System (ERSS)",
    "scope": "Pan-India emergency number for police, fire, health and other emergencies",
    "source": "Ministry of Home Affairs, Government of India",
    "source_url": "https://www.mha.gov.in/emergency-response-support-system-erss",
}


def _normalize(value):
    return unicodedata.normalize("NFKC", value or "").casefold()


def _term_matches(text, term):
    normalized = _normalize(term)
    if not normalized:
        return False
    if normalized.isascii():
        pattern = r"(?<![a-z0-9])" + re.escape(normalized) + r"(?![a-z0-9])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return normalized in text


def detect_emergency(message):
    """Return all keyword-matched intents and a deterministic primary category."""
    text = _normalize(message)
    found_by_type = {}
    for category, translations in TERMS.items():
        found = []
        for words in translations.values():
            found.extend(word for word in words if _term_matches(text, word))
        if found:
            found_by_type[category] = list(dict.fromkeys(found))

    priority = (
        "fire", "gas_leak", "earthquake", "tsunami", "flood",
        "landslide", "cyclone", "lightning", "medical",
        "road_accident", "violence",
    )
    primary = next((name for name in priority if name in found_by_type), "unknown")
    return {
        "emergency_type": primary,
        "matched_keywords": found_by_type.get(primary, []),
        "all_detected_types": list(found_by_type),
        "multiple_emergency_types_detected": len(found_by_type) > 1,
        "method": "multilingual_keyword_intent_detection",
        "confidence_label": "keyword_match" if primary != "unknown" else "not_detected",
    }


def build_emergency_response(message, language="en"):
    """Create a localized response; language is selected by the API caller."""
    lang = (language or "en").lower().split("-")[0]
    if lang not in GUIDANCE:
        lang = "en"

    analysis = detect_emergency(message)
    category = analysis["emergency_type"]
    detected_types = analysis["all_detected_types"] or ["unknown"]

    # Keep the selected primary hazard first, but do not discard other hazards
    # mentioned in the same message (for example, fire after an earthquake).
    ordered_types = [category] + [
        item for item in detected_types if item != category
    ]
    guidance_by_type = {
        item: GUIDANCE[lang][item]
        for item in ordered_types
    }
    combined_guidance = list(dict.fromkeys(
        instruction
        for item in ordered_types
        for instruction in GUIDANCE[lang][item]
    ))
    recommended_facility_types = list(dict.fromkeys(
        facility_type
        for item in ordered_types
        for facility_type in FACILITY_SUGGESTIONS[item]
    ))

    notices = {
        "en": "General guidance only. Call 112 in India and follow official responder instructions.",
        "hi": "यह सामान्य मार्गदर्शन है। भारत में 112 पर कॉल करें और आधिकारिक बचाव निर्देशों का पालन करें।",
        "kn": "ಇದು ಸಾಮಾನ್ಯ ಮಾರ್ಗದರ್ಶನ ಮಾತ್ರ. ಭಾರತದಲ್ಲಿ 112ಕ್ಕೆ ಕರೆಮಾಡಿ ಮತ್ತು ಅಧಿಕೃತ ರಕ್ಷಣಾ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸಿ.",
    }

    return {
        **analysis,
        "language": lang,
        "urgency": "urgent" if category != "unknown" else "undetermined",
        "guidance": combined_guidance,
        "guidance_by_emergency_type": guidance_by_type,
        "recommended_facility_types": recommended_facility_types,
        "emergency_contact": EMERGENCY_CONTACT_INDIA,
        "safety_notice": notices[lang],
    }
