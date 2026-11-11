import { saveOfflinePackage, getCachedPackage, type CachedPackage } from "./cache";

export type Coordinates = {
  latitude: number;
  longitude: number;
};

export type OfflinePackage = {
  package_type: string;
  schema_version: number;
  generated_at: string;
  language: string;
  location: Coordinates & {
    city?: string | null;
    district?: string | null;
    state?: string | null;
    radius_km?: number;
  };
  emergency_contact?: { number?: string; dial_uri?: string; label?: string };
  guidance_catalog?: Record<string, { instructions?: string[]; recommended_facility_types?: string[] }>;
  nearby_verified_facilities?: unknown[];
  location_matched_official_alerts?: unknown[];
  unverified_location_alerts?: unknown[];
  offline_capabilities?: Record<string, boolean>;
  important?: string[];
};

export type EmergencyResult = {
  status?: string;
  emergency_type?: string;
  guidance?: string[];
  safety_notice?: string;
  ai_provider?: string;
  ai_status?: string;
  ai_analysis?: {
    status?: string;
    provider?: string;
    model?: string;
    short_summary?: string;
    confidence?: string;
    key_details?: string[];
    message?: string;
  };
  // Legacy aliases returned by the backend for older installed app builds.
  gemini_status?: string;
  [key: string]: unknown;
};

const API_BASE_URL = (process.env.EXPO_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

export function isApiConfigured() {
  return API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
}

function requireApiUrl() {
  if (!isApiConfigured()) {
    throw new Error("Backend address missing. Set EXPO_PUBLIC_API_BASE_URL in mobile/.env.");
  }
  return API_BASE_URL;
}

function packageKey(point: Coordinates, language: string) {
  return (
    point.latitude.toFixed(3) +
    "|" +
    point.longitude.toFixed(3) +
    "|" +
    language +
    "|10"
  );
}

export async function downloadOfflinePackage(
  point: Coordinates,
  language: string,
): Promise<{ payload: OfflinePackage; cacheStatus: "live" | "not_modified"; cached: CachedPackage }> {
  const key = packageKey(point, language);
  const cached = await getCachedPackage(key);
  const query = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
    language,
    radius_km: "10",
  });
  const headers: Record<string, string> = { Accept: "application/json" };
  if (cached?.etag) headers["If-None-Match"] = cached.etag;

  const response = await fetch(
    requireApiUrl() + "/offline/package?" + query.toString(),
    { method: "GET", headers },
  );

  if (response.status === 304 && cached) {
    return { payload: cached.payload, cacheStatus: "not_modified", cached };
  }
  if (!response.ok) {
    throw new Error("Offline package request failed with HTTP " + response.status + ".");
  }

  const payload = (await response.json()) as OfflinePackage;
  const etag = response.headers.get("ETag");
  const stored = await saveOfflinePackage(key, etag, payload);
  return { payload, cacheStatus: "live", cached: stored };
}

export async function sendEmergency(input: {
  message: string;
  language: string;
  latitude?: number;
  longitude?: number;
  radius_km: number;
  include_weather: boolean;
  use_ai: boolean;
}): Promise<EmergencyResult> {
  const response = await fetch(requireApiUrl() + "/emergency", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new Error("Emergency API request failed with HTTP " + response.status + ".");
  }
  return (await response.json()) as EmergencyResult;
}

const BUILT_IN_OFFLINE_GUIDANCE: Record<string, Record<string, string[]>> = {
  en: {
    fire: ["Leave immediately through the nearest safe exit.", "Stay low under smoke and do not use elevators.", "Do not re-enter; call 112 from a safe place."],
    flood: ["Move to higher ground immediately.", "Never walk or drive through floodwater.", "Stay away from electrical lines and follow official evacuation instructions."],
    earthquake: ["Drop, cover and hold on until shaking stops.", "Stay away from windows and heavy objects; do not use elevators.", "After shaking, leave damaged buildings carefully and expect aftershocks."],
    medical: ["Call 112 and request medical help.", "Apply firm direct pressure to severe external bleeding.", "Do not move a seriously injured person unless there is immediate danger."],
    gas_leak: ["Leave the area immediately.", "Do not operate switches, appliances, flames or vehicles near the suspected leak.", "From a safe location call 112; do not re-enter until cleared."],
    unknown: ["Move away from immediate danger if possible.", "Call 112 in India and give your exact location.", "Follow official local responder instructions."],
  },
  hi: {
    fire: ["निकटतम सुरक्षित निकास से तुरंत बाहर निकलें।", "धुएँ में नीचे झुककर चलें; लिफ्ट का उपयोग न करें।", "वापस अंदर न जाएँ; सुरक्षित स्थान से 112 पर कॉल करें।"],
    flood: ["तुरंत ऊँचे स्थान पर जाएँ।", "बाढ़ के पानी में पैदल या वाहन से न जाएँ।", "बिजली की तारों से दूर रहें और आधिकारिक निकासी निर्देश मानें।"],
    earthquake: ["झटके रुकने तक नीचे झुकें, ढकें और पकड़े रहें।", "खिड़कियों और भारी वस्तुओं से दूर रहें; लिफ्ट न लें।", "झटके रुकने पर क्षतिग्रस्त इमारत से सावधानी से बाहर निकलें।"],
    medical: ["112 पर कॉल करके चिकित्सा सहायता माँगें।", "अधिक बाहरी रक्तस्राव पर साफ कपड़े से सीधा दबाव दें।", "तत्काल खतरा न हो तो गंभीर घायल को न हिलाएँ।"],
    gas_leak: ["तुरंत उस स्थान से बाहर निकलें।", "स्विच, बिजली के उपकरण या आग का उपयोग न करें।", "सुरक्षित स्थान से 112 पर कॉल करें; अनुमति मिलने तक वापस न जाएँ।"],
    unknown: ["संभव हो तो तत्काल खतरे से दूर जाएँ।", "भारत में 112 पर कॉल करके सटीक स्थान बताएँ।", "स्थानीय अधिकारियों के निर्देश मानें।"],
  },
  kn: {
    fire: ["ಹತ್ತಿರದ ಸುರಕ್ಷಿತ ನಿರ್ಗಮನದ ಮೂಲಕ ತಕ್ಷಣ ಹೊರಬನ್ನಿ.", "ಹೊಗೆ ಇದ್ದರೆ ಕೆಳಮಟ್ಟದಲ್ಲಿ ಚಲಿಸಿ; ಲಿಫ್ಟ್ ಬಳಸಬೇಡಿ.", "ಮತ್ತೆ ಒಳಗೆ ಹೋಗಬೇಡಿ; ಸುರಕ್ಷಿತ ಸ್ಥಳದಿಂದ 112ಕ್ಕೆ ಕರೆಮಾಡಿ."],
    flood: ["ತಕ್ಷಣ ಎತ್ತರದ ಪ್ರದೇಶಕ್ಕೆ ತೆರಳಿ.", "ಪ್ರವಾಹದ ನೀರಿನಲ್ಲಿ ನಡೆಯಬೇಡಿ ಅಥವಾ ವಾಹನ ಚಲಾಯಿಸಬೇಡಿ.", "ವಿದ್ಯುತ್ ತಂತಿಗಳಿಂದ ದೂರವಿದ್ದು ಅಧಿಕೃತ ಸೂಚನೆ ಪಾಲಿಸಿ."],
    earthquake: ["ಕಂಪನ ನಿಲ್ಲುವವರೆಗೆ ಕೆಳಗೆ ಬಾಗಿ, ಆಶ್ರಯ ಪಡೆದು ಹಿಡಿದುಕೊಳ್ಳಿ.", "ಕಿಟಕಿ ಮತ್ತು ಭಾರವಾದ ವಸ್ತುಗಳಿಂದ ದೂರವಿರಿ; ಲಿಫ್ಟ್ ಬಳಸಬೇಡಿ.", "ಕಂಪನ ನಿಂತ ನಂತರ ಹಾನಿಗೊಂಡ ಕಟ್ಟಡದಿಂದ ಎಚ್ಚರಿಕೆಯಿಂದ ಹೊರಬನ್ನಿ."],
    medical: ["ವೈದ್ಯಕೀಯ ಸಹಾಯಕ್ಕಾಗಿ 112ಕ್ಕೆ ಕರೆಮಾಡಿ.", "ತೀವ್ರ ರಕ್ತಸ್ರಾವಕ್ಕೆ ಸ್ವಚ್ಛ ಬಟ್ಟೆಯಿಂದ ನೇರ ಒತ್ತಡ ನೀಡಿ.", "ತಕ್ಷಣದ ಅಪಾಯವಿಲ್ಲದಿದ್ದರೆ ಗಂಭೀರ ಗಾಯಾಳುವನ್ನು ಕದಲಿಸಬೇಡಿ."],
    gas_leak: ["ತಕ್ಷಣ ಆ ಪ್ರದೇಶದಿಂದ ಹೊರಬನ್ನಿ.", "ಸ್ವಿಚ್, ವಿದ್ಯುತ್ ಉಪಕರಣ ಅಥವಾ ಬೆಂಕಿ ಬಳಸಬೇಡಿ.", "ಸುರಕ್ಷಿತ ಸ್ಥಳದಿಂದ 112ಕ್ಕೆ ಕರೆಮಾಡಿ; ಅನುಮತಿ ಸಿಗುವವರೆಗೆ ಹಿಂದಿರುಗಬೇಡಿ."],
    unknown: ["ಸಾಧ್ಯವಾದರೆ ತಕ್ಷಣದ ಅಪಾಯದಿಂದ ದೂರವಿರಿ.", "ಭಾರತದಲ್ಲಿ 112ಕ್ಕೆ ಕರೆಮಾಡಿ ನಿಖರ ಸ್ಥಳ ತಿಳಿಸಿ.", "ಸ್ಥಳೀಯ ಅಧಿಕಾರಿಗಳ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸಿ."],
  },
};

const OFFLINE_TERMS: Record<string, string[]> = {
  fire: ["fire", "smoke", "आग", "धुआँ", "ಬೆಂಕಿ", "ಹೊಗೆ"],
  flood: ["flood", "flooding", "बाढ़", "ಪ್ರವಾಹ", "ನೀರು ತುಂಬ"],
  earthquake: ["earthquake", "tremor", "भूकंप", "ಭೂಕಂಪ", "ನೆಲ ನಡುಗ"],
  cyclone: ["cyclone", "चक्रवात", "ಚಂಡಮಾರುತ"],
  landslide: ["landslide", "भूस्खलन", "ಭೂಕುಸಿತ", "ಬೆಟ್ಟ ಕುಸಿತ"],
  tsunami: ["tsunami", "सुनामी", "ಸುನಾಮಿ"],
  lightning: ["lightning", "thunderstorm", "बिजली गिर", "ಮಿಂಚು", "ಸಿಡಿಲು"],
  gas_leak: ["gas leak", "gas smell", "गैस रिसाव", "ಅನಿಲ ಸೋರಿಕೆ"],
  medical: ["unconscious", "bleeding", "बेहोश", "रक्तस्राव", "ಪ್ರಜ್ಞೆ ಇಲ್ಲ", "ರಕ್ತಸ್ರಾವ"],
  road_accident: ["road accident", "car crash", "दुर्घटना", "ರಸ್ತೆ ಅಪಘಾತ"],
  violence: ["assault", "attack", "हमला", "ದಾಳಿ", "ಹಲ್ಲೆ"],
};

export function getOfflineGuidance(
  message: string,
  language: string,
  cachedPackage: OfflinePackage | null,
): EmergencyResult {
  const normalized = message.toLocaleLowerCase();
  const category =
    Object.entries(OFFLINE_TERMS).find(([, terms]) =>
      terms.some((term) => normalized.includes(term.toLocaleLowerCase())),
    )?.[0] ?? "unknown";
  const normalizedLanguage = language in BUILT_IN_OFFLINE_GUIDANCE ? language : "en";
  const instructions =
    cachedPackage?.guidance_catalog?.[category]?.instructions ??
    BUILT_IN_OFFLINE_GUIDANCE[normalizedLanguage]?.[category] ??
    cachedPackage?.guidance_catalog?.unknown?.instructions ??
    BUILT_IN_OFFLINE_GUIDANCE[normalizedLanguage]?.unknown ??
    BUILT_IN_OFFLINE_GUIDANCE.en.unknown;
  const fallbackNotice = {
    en: "Offline keyword guidance only. Call 112 in India and follow official responders.",
    hi: "यह केवल ऑफलाइन सामान्य मार्गदर्शन है। भारत में 112 पर कॉल करें और आधिकारिक निर्देश मानें।",
    kn: "ಇದು ಆಫ್‌ಲೈನ್ ಸಾಮಾನ್ಯ ಮಾರ್ಗದರ್ಶನ ಮಾತ್ರ. ಭಾರತದಲ್ಲಿ 112ಕ್ಕೆ ಕರೆಮಾಡಿ ಮತ್ತು ಅಧಿಕೃತ ಸೂಚನೆ ಪಾಲಿಸಿ.",
  } as Record<string, string>;
  return {
    status: "offline_guidance_only",
    emergency_type: category,
    language,
    urgency: category === "unknown" ? "undetermined" : "urgent",
    guidance: instructions,
    emergency_contact: cachedPackage?.emergency_contact ?? { number: "112", dial_uri: "tel:112" },
    safety_notice: fallbackNotice[language] ?? fallbackNotice.en,
    note: "The server, Gemini, live weather and new alerts are unavailable offline. This local keyword match may be incomplete.",
  };
}
