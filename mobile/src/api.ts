import { saveOfflinePackage, getCachedPackage, getLatestOfflinePackage, type CachedPackage } from "./cache";

export type Coordinates = {
  latitude: number;
  longitude: number;
};

export type NearbyFacility = {
  name?: string;
  facility_type?: string;
  latitude?: number;
  longitude?: number;
  distance_km?: number;
  address?: string | null;
  phone?: string | null;
  source_name?: string | null;
  source_url?: string | null;
  verification_status?: "verified" | "unverified" | string;
  verification_warning?: string;
};

export type WeatherSnapshot = {
  current?: {
    temperature_c?: number | null;
    apparent_temperature_c?: number | null;
    relative_humidity_pct?: number | null;
    wind_speed_kmh?: number | null;
    condition?: string;
    time?: string;
  };
  forecast_indicators?: {
    max_precipitation_probability_pct?: number | null;
  };
  attribution?: string;
  disclaimer?: string;
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
  nearby_verified_facilities?: NearbyFacility[];
  nearby_discovered_facilities?: NearbyFacility[];
  facility_discovery_status?: string;
  location_matched_official_alerts?: unknown[];
  unverified_location_alerts?: unknown[];
  offline_capabilities?: Record<string, boolean>;
  important?: string[];
};

export type EmergencyResult = {
  status?: string;
  in_scope?: boolean;
  reply?: string;
  follow_up_question?: string | null;
  urgency?: string;
  emergency_type?: string;
  guidance?: string[];
  safety_notice?: string;
  nearby_facilities?: NearbyFacility[];
  nearby_alerts?: unknown[];
  unverified_alerts?: unknown[];
  emergency_contact?: { number?: string; dial_uri?: string; label?: string };
  weather_context?: { status?: string; [key: string]: unknown };
  ai_provider?: string;
  ai_status?: string;
  ai_analysis?: {
    status?: string;
    provider?: string;
    in_scope?: boolean;
    urgency?: string;
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

export async function sendEmergencyChat(input: {
  message: string;
  language: string;
  conversation_history: { role: "user" | "assistant"; content: string }[];
  latitude?: number;
  longitude?: number;
  radius_km?: number;
  city?: string;
  district?: string;
  state?: string;
}): Promise<EmergencyResult> {
  const response = await fetch(requireApiUrl() + "/emergency/chat", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      ...input,
      conversation_history: input.conversation_history.slice(-10).map((item) => ({
        role: item.role,
        content: item.content.slice(0, 1600),
      })),
    }),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error("Emergency chat failed with HTTP " + response.status + (detail ? ": " + detail.slice(0, 220) : "."));
  }
  return (await response.json()) as EmergencyResult;
}

export async function getNearbyFacilities(
  point: Coordinates,
  radiusKm = 10,
): Promise<{ count: number; items: NearbyFacility[]; source?: string; note?: string }> {
  const query = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
    radius_km: String(radiusKm),
  });
  const response = await fetch(requireApiUrl() + "/facilities/discover?" + query.toString(), {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error("Facility discovery failed with HTTP " + response.status + (detail ? ": " + detail.slice(0, 160) : "."));
  }
  return (await response.json()) as { count: number; items: NearbyFacility[]; source?: string; note?: string };
}

export async function cacheNearbyFacilities(facilities: NearbyFacility[]) {
  const cached = await getLatestOfflinePackage();
  if (!cached) return;
  const payload = {
    ...cached.payload,
    nearby_discovered_facilities: facilities,
  };
  await saveOfflinePackage(cached.cacheKey, cached.etag, payload);
}

export async function getNearbyWeather(point: Coordinates): Promise<WeatherSnapshot> {
  const query = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
    forecast_hours: "6",
  });
  const response = await fetch(requireApiUrl() + "/weather/nearby?" + query.toString(), {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error("Weather request failed with HTTP " + response.status + (detail ? ": " + detail.slice(0, 180) : "."));
  }
  return (await response.json()) as WeatherSnapshot;
}

export type SystemStatus = {
  api?: { status?: string; version?: string };
  providers?: {
    ai?: {
      provider?: string;
      enabled?: boolean;
      api_key_configured?: boolean;
      primary_model?: string;
      fallback_model?: string;
    };
  };
};

export async function getSystemStatus(): Promise<SystemStatus> {
  const response = await fetch(requireApiUrl() + "/system/status", {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error("Backend health check failed with HTTP " + response.status + (detail ? ": " + detail.slice(0, 180) : ""));
  }
  return (await response.json()) as SystemStatus;
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
    const detail = await response.text().catch(() => "");
    throw new Error(
      "Emergency API request failed with HTTP " +
        response.status +
        (detail ? ": " + detail.slice(0, 220) : "."),
    );
  }
  return (await response.json()) as EmergencyResult;
}

const BUILT_IN_OFFLINE_GUIDANCE: Record<string, Record<string, string[]>> = {
  en: {
    fire: ["Leave immediately through the nearest safe exit.", "Stay low under smoke and do not use elevators.", "Do not re-enter; call 112 from a safe place."],
    flood: ["Move to higher ground immediately.", "Never walk or drive through floodwater.", "Stay away from electrical lines and follow official evacuation instructions."],
    earthquake: ["Drop, cover and hold on until shaking stops.", "Stay away from windows and heavy objects; do not use elevators.", "After shaking, leave damaged buildings carefully and expect aftershocks."],
    cyclone: ["Stay inside a sturdy building and away from windows.", "Move to an official cyclone shelter if authorities order evacuation.", "Avoid coastal areas, floodwater, fallen trees and power lines."],
    landslide: ["Move away from moving soil or debris and leave the path of the slide if you can do so safely.", "Move to stable ground away from slopes, valleys and drainage channels.", "Do not return until local authorities say it is safe."],
    tsunami: ["After a strong or long coastal earthquake, move immediately to high ground or inland.", "Do not wait to watch the sea or approach the shore.", "Remain in the safe area until authorities issue an all-clear."],
    lightning: ["Move into a substantial enclosed building or hard-topped vehicle.", "Avoid open fields, isolated trees, hilltops, water and metal objects.", "Wait at least 30 minutes after the last thunder before returning outdoors."],
    road_accident: ["Move away from traffic if you can do so safely.", "Call 112 and give the exact location and number of injured people.", "Do not move seriously injured people unless there is immediate danger; do not remove a motorcyclist's helmet."],
    medical: ["Call 112 and request medical help.", "Apply firm direct pressure to severe external bleeding.", "Do not move a seriously injured person unless there is immediate danger."],
    violence: ["Move away from gunfire or the threat and seek substantial cover if possible.", "Do not approach, confront or investigate armed people or suspicious objects.", "When safe, call 112 and follow police or district authority instructions."],
    gas_leak: ["Leave the area immediately.", "Do not operate switches, appliances, flames or vehicles near the suspected leak.", "From a safe location call 112; do not re-enter until cleared."],
    unknown: ["Move away from immediate danger if possible.", "Call 112 in India and give your exact location.", "Follow official local responder instructions."],
  },
  hi: {
    fire: ["निकटतम सुरक्षित निकास से तुरंत बाहर निकलें।", "धुएँ में नीचे झुककर चलें; लिफ्ट का उपयोग न करें।", "वापस अंदर न जाएँ; सुरक्षित स्थान से 112 पर कॉल करें।"],
    flood: ["तुरंत ऊँचे स्थान पर जाएँ।", "बाढ़ के पानी में पैदल या वाहन से न जाएँ।", "बिजली की तारों से दूर रहें और आधिकारिक निकासी निर्देश मानें।"],
    earthquake: ["झटके रुकने तक नीचे झुकें, ढकें और पकड़े रहें।", "खिड़कियों और भारी वस्तुओं से दूर रहें; लिफ्ट न लें।", "झटके रुकने पर क्षतिग्रस्त इमारत से सावधानी से बाहर निकलें।"],
    cyclone: ["मजबूत इमारत के अंदर रहें और खिड़कियों से दूर रहें।", "अधिकारियों के आदेश पर आधिकारिक चक्रवात आश्रय में जाएँ।", "समुद्र तट, बाढ़ के पानी और गिरी बिजली की तारों से दूर रहें।"],
    landslide: ["संभव हो तो खिसकती मिट्टी या मलबे के रास्ते से तुरंत दूर जाएँ।", "ढलानों, घाटियों और नालों से दूर स्थिर स्थान पर जाएँ।", "अधिकारियों की अनुमति मिलने तक वापस न लौटें।"],
    tsunami: ["तटीय क्षेत्र में तेज या लंबे भूकंप के बाद तुरंत ऊँचे स्थान या अंदरूनी क्षेत्र में जाएँ।", "समुद्र देखने या किनारे के पास जाने के लिए प्रतीक्षा न करें।", "अधिकारियों की सुरक्षित होने की सूचना तक वहीं रहें।"],
    lightning: ["मजबूत बंद इमारत या बंद वाहन में जाएँ।", "खुले मैदान, अकेले पेड़, पहाड़ी चोटी और पानी से दूर रहें।", "आखिरी गर्जना के कम से कम 30 मिनट बाद ही बाहर जाएँ।"],
    road_accident: ["सुरक्षित हो तो खुद को यातायात से दूर करें।", "112 पर कॉल करके सटीक स्थान और घायलों की संख्या बताएँ।", "तत्काल खतरा न हो तो गंभीर घायल को न हिलाएँ; बाइक सवार का हेलमेट न हटाएँ।"],
    medical: ["112 पर कॉल करके चिकित्सा सहायता माँगें।", "अधिक बाहरी रक्तस्राव पर साफ कपड़े से सीधा दबाव दें।", "तत्काल खतरा न हो तो गंभीर घायल को न हिलाएँ।"],
    violence: ["गोलीबारी या खतरे से दूर जाएँ और संभव हो तो मजबूत आड़ लें।", "सशस्त्र लोगों या संदिग्ध वस्तुओं के पास न जाएँ और सामना न करें।", "सुरक्षित होने पर 112 पर कॉल करें और पुलिस के निर्देश मानें।"],
    gas_leak: ["तुरंत उस स्थान से बाहर निकलें।", "स्विच, बिजली के उपकरण या आग का उपयोग न करें।", "सुरक्षित स्थान से 112 पर कॉल करें; अनुमति मिलने तक वापस न जाएँ।"],
    unknown: ["संभव हो तो तत्काल खतरे से दूर जाएँ।", "भारत में 112 पर कॉल करके सटीक स्थान बताएँ।", "स्थानीय अधिकारियों के निर्देश मानें।"],
  },
  kn: {
    fire: ["ಹತ್ತಿರದ ಸುರಕ್ಷಿತ ನಿರ್ಗಮನದ ಮೂಲಕ ತಕ್ಷಣ ಹೊರಬನ್ನಿ.", "ಹೊಗೆ ಇದ್ದರೆ ಕೆಳಮಟ್ಟದಲ್ಲಿ ಚಲಿಸಿ; ಲಿಫ್ಟ್ ಬಳಸಬೇಡಿ.", "ಮತ್ತೆ ಒಳಗೆ ಹೋಗಬೇಡಿ; ಸುರಕ್ಷಿತ ಸ್ಥಳದಿಂದ 112ಕ್ಕೆ ಕರೆಮಾಡಿ."],
    flood: ["ತಕ್ಷಣ ಎತ್ತರದ ಪ್ರದೇಶಕ್ಕೆ ತೆರಳಿ.", "ಪ್ರವಾಹದ ನೀರಿನಲ್ಲಿ ನಡೆಯಬೇಡಿ ಅಥವಾ ವಾಹನ ಚಲಾಯಿಸಬೇಡಿ.", "ವಿದ್ಯುತ್ ತಂತಿಗಳಿಂದ ದೂರವಿದ್ದು ಅಧಿಕೃತ ಸೂಚನೆ ಪಾಲಿಸಿ."],
    earthquake: ["ಕಂಪನ ನಿಲ್ಲುವವರೆಗೆ ಕೆಳಗೆ ಬಾಗಿ, ಆಶ್ರಯ ಪಡೆದು ಹಿಡಿದುಕೊಳ್ಳಿ.", "ಕಿಟಕಿ ಮತ್ತು ಭಾರವಾದ ವಸ್ತುಗಳಿಂದ ದೂರವಿರಿ; ಲಿಫ್ಟ್ ಬಳಸಬೇಡಿ.", "ಕಂಪನ ನಿಂತ ನಂತರ ಹಾನಿಗೊಂಡ ಕಟ್ಟಡದಿಂದ ಎಚ್ಚರಿಕೆಯಿಂದ ಹೊರಬನ್ನಿ."],
    cyclone: ["ಗಟ್ಟಿಯಾದ ಕಟ್ಟಡದ ಒಳಗೆ ಇರಿ ಮತ್ತು ಕಿಟಕಿಗಳಿಂದ ದೂರವಿರಿ.", "ಅಧಿಕಾರಿಗಳು ಸೂಚಿಸಿದರೆ ಅಧಿಕೃತ ಚಂಡಮಾರುತ ಆಶ್ರಯಕ್ಕೆ ತೆರಳಿ.", "ಕರಾವಳಿ, ಪ್ರವಾಹದ ನೀರು ಮತ್ತು ಬಿದ್ದ ವಿದ್ಯುತ್ ತಂತಿಗಳಿಂದ ದೂರವಿರಿ."],
    landslide: ["ಸಾಧ್ಯವಾದರೆ ಜಾರುವ ಮಣ್ಣು ಅಥವಾ ಅವಶೇಷಗಳ ದಾರಿಯಿಂದ ತಕ್ಷಣ ದೂರ ಸರಿಯಿರಿ.", "ಬೆಟ್ಟದ ಇಳಿಜಾರು, ಕಣಿವೆ ಮತ್ತು ನೀರು ಹರಿಯುವ ಮಾರ್ಗಗಳಿಂದ ದೂರವಿರುವ ಸ್ಥಿರ ಸ್ಥಳಕ್ಕೆ ಹೋಗಿ.", "ಅಧಿಕಾರಿಗಳು ಸುರಕ್ಷಿತವೆಂದು ಹೇಳುವವರೆಗೆ ಹಿಂದಿರುಗಬೇಡಿ."],
    tsunami: ["ಕರಾವಳಿಯಲ್ಲಿ ಬಲವಾದ ಅಥವಾ ದೀರ್ಘ ಭೂಕಂಪದ ನಂತರ ತಕ್ಷಣ ಎತ್ತರದ ಅಥವಾ ಒಳನಾಡಿನ ಪ್ರದೇಶಕ್ಕೆ ತೆರಳಿ.", "ಸಮುದ್ರವನ್ನು ನೋಡಲು ಕಾಯಬೇಡಿ ಅಥವಾ ತೀರದ ಹತ್ತಿರ ಹೋಗಬೇಡಿ.", "ಅಧಿಕಾರಿಗಳು ಸುರಕ್ಷಿತವೆಂದು ಘೋಷಿಸುವವರೆಗೆ ಸುರಕ್ಷಿತ ಸ್ಥಳದಲ್ಲೇ ಇರಿ."],
    lightning: ["ಬಲವಾದ ಮುಚ್ಚಿದ ಕಟ್ಟಡ ಅಥವಾ ಮೇಲ್ಛಾವಣಿ ಇರುವ ವಾಹನದೊಳಗೆ ಹೋಗಿ.", "ತೆರೆದ ಮೈದಾನ, ಒಂಟಿ ಮರ, ಬೆಟ್ಟದ ತುದಿ ಮತ್ತು ನೀರಿನಿಂದ ದೂರವಿರಿ.", "ಕೊನೆಯ ಗುಡುಗಿನ ನಂತರ ಕನಿಷ್ಠ 30 ನಿಮಿಷ ಹೊರಗೆ ಹೋಗಬೇಡಿ."],
    road_accident: ["ಸಾಧ್ಯವಾದರೆ ಸಂಚಾರದಿಂದ ದೂರ ಸರಿಯಿರಿ.", "112ಕ್ಕೆ ಕರೆಮಾಡಿ ನಿಖರ ಸ್ಥಳ ಮತ್ತು ಗಾಯಾಳುಗಳ ಸಂಖ್ಯೆಯನ್ನು ತಿಳಿಸಿ.", "ತಕ್ಷಣದ ಅಪಾಯವಿಲ್ಲದಿದ್ದರೆ ಗಂಭೀರ ಗಾಯಾಳುವನ್ನು ಕದಲಿಸಬೇಡಿ; ಬೈಕ್ ಸವಾರನ ಹೆಲ್ಮೆಟ್ ತೆಗೆಯಬೇಡಿ."],
    medical: ["ವೈದ್ಯಕೀಯ ಸಹಾಯಕ್ಕಾಗಿ 112ಕ್ಕೆ ಕರೆಮಾಡಿ.", "ತೀವ್ರ ರಕ್ತಸ್ರಾವಕ್ಕೆ ಸ್ವಚ್ಛ ಬಟ್ಟೆಯಿಂದ ನೇರ ಒತ್ತಡ ನೀಡಿ.", "ತಕ್ಷಣದ ಅಪಾಯವಿಲ್ಲದಿದ್ದರೆ ಗಂಭೀರ ಗಾಯಾಳುವನ್ನು ಕದಲಿಸಬೇಡಿ."],
    violence: ["ಗುಂಡಿನ ದಾಳಿ ಅಥವಾ ಅಪಾಯದಿಂದ ದೂರ ಸರಿದು ಸಾಧ್ಯವಾದರೆ ಗಟ್ಟಿಯಾದ ಆವರಣ ಪಡೆಯಿರಿ.", "ಸಶಸ್ತ್ರ ವ್ಯಕ್ತಿಗಳು ಅಥವಾ ಅನುಮಾನಾಸ್ಪದ ವಸ್ತುಗಳ ಹತ್ತಿರ ಹೋಗಬೇಡಿ.", "ಸುರಕ್ಷಿತವಾದಾಗ 112ಕ್ಕೆ ಕರೆಮಾಡಿ ಮತ್ತು ಪೊಲೀಸರ ಸೂಚನೆ ಪಾಲಿಸಿ."],
    gas_leak: ["ತಕ್ಷಣ ಆ ಪ್ರದೇಶದಿಂದ ಹೊರಬನ್ನಿ.", "ಸ್ವಿಚ್, ವಿದ್ಯುತ್ ಉಪಕರಣ ಅಥವಾ ಬೆಂಕಿ ಬಳಸಬೇಡಿ.", "ಸುರಕ್ಷಿತ ಸ್ಥಳದಿಂದ 112ಕ್ಕೆ ಕರೆಮಾಡಿ; ಅನುಮತಿ ಸಿಗುವವರೆಗೆ ಹಿಂದಿರುಗಬೇಡಿ."],
    unknown: ["ಸಾಧ್ಯವಾದರೆ ತಕ್ಷಣದ ಅಪಾಯದಿಂದ ದೂರವಿರಿ.", "ಭಾರತದಲ್ಲಿ 112ಕ್ಕೆ ಕರೆಮಾಡಿ ನಿಖರ ಸ್ಥಳ ತಿಳಿಸಿ.", "ಸ್ಥಳೀಯ ಅಧಿಕಾರಿಗಳ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸಿ."],
  },
};

const OFFLINE_TERMS: Record<string, string[]> = {
  fire: ["fire", "smoke", "burning", "flames", "आग", "धुआँ", "जल रहा", "ಬೆಂಕಿ", "ಹೊಗೆ"],
  flood: ["flood", "flooding", "water rising", "बाढ़", "जलभराव", "ಪ್ರವಾಹ", "ನೀರು ತುಂಬ"],
  earthquake: ["earthquake", "tremor", "ground shaking", "भूकंप", "धरती हिल", "ಭೂಕಂಪ", "ನೆಲ ನಡುಗ"],
  cyclone: ["cyclone", "hurricane", "typhoon", "storm surge", "चक्रवात", "तूफान", "ಚಂಡಮಾರುತ", "ಸುಂಟರಗಾಳಿ"],
  landslide: ["landslide", "mudslide", "slope collapse", "falling rocks", "भूस्खलन", "पहाड़ खिसक", "ಭೂಕುಸಿತ", "ಬೆಟ್ಟ ಕುಸಿತ"],
  tsunami: ["tsunami", "sea wave warning", "ocean surge", "सुनामी", "समुद्री लहर", "ಸುನಾಮಿ"],
  lightning: ["lightning", "thunderstorm", "thunder strike", "बिजली गिर", "आकाशीय बिजली", "ಮಿಂಚು", "ಸಿಡಿಲು"],
  gas_leak: ["gas leak", "gas smell", "गैस रिसाव", "गैस की गंध", "ಅನಿಲ ಸೋರಿಕೆ", "ಅನಿಲದ ವಾಸನೆ"],
  medical: ["unconscious", "bleeding", "injured", "heart attack", "not breathing", "बेहोश", "रक्तस्राव", "घायल", "ಪ್ರಜ್ಞೆ ಇಲ್ಲ", "ರಕ್ತಸ್ರಾವ", "ಗಾಯ"],
  road_accident: ["road accident", "car crash", "vehicle crash", "collision", "bike accident", "सड़क हादसा", "दुर्घटना", "ರಸ್ತೆ ಅಪಘಾತ", "ವಾಹನ ಡಿಕ್ಕಿ"],
  violence: ["assault", "attack", "attacker", "gunfire", "gunshots", "shooting", "war", "war zone", "armed conflict", "bombing", "air raid", "shelling", "missile", "explosion", "bomb", "civil unrest", "हमला", "युद्ध", "गोलीबारी", "बमबारी", "हवाई हमला", "ದಾಳಿ", "ಹಲ್ಲೆ", "ಯುದ್ಧ", "ಗುಂಡಿನ ದಾಳಿ", "ಬಾಂಬ್ ದಾಳಿ"],
  general: ["emergency", "help me", "sos", "trapped", "stranded", "i am stuck", "i'm stuck", "people are injured", "building collapsed", "collapse", "explosion", "debris", "danger", "मदद", "फँसा", "आपातकाल", "सहायता", "ಸಹಾಯ", "ಸಿಲುಕಿಕೊಂಡಿದ್ದೇನೆ", "ತುರ್ತು ಪರಿಸ್ಥಿತಿ"],
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
  const generalEmergencyDetected = (OFFLINE_TERMS.general ?? []).some((term) =>
    normalized.includes(term.toLocaleLowerCase()),
  );
  if (category === "unknown" && !generalEmergencyDetected) {
    const outOfScope = {
      en: "ResQLink works only for emergency situations. Describe the danger you are facing, such as fire, flooding, injury or violence.",
      hi: "ResQLink केवल आपातकालीन स्थितियों के लिए है। कृपया आग, बाढ़, चोट या हिंसा जैसे खतरे का वर्णन करें।",
      kn: "ResQLink ತುರ್ತು ಪರಿಸ್ಥಿತಿಗಳಿಗಾಗಿ ಮಾತ್ರ. ಬೆಂಕಿ, ಪ್ರವಾಹ, ಗಾಯ ಅಥವಾ ಹಿಂಸೆಯಂತಹ ಅಪಾಯವನ್ನು ವಿವರಿಸಿ.",
    } as Record<string, string>;
    return {
      status: "offline_guidance_only",
      in_scope: false,
      emergency_type: "unknown",
      language,
      urgency: "unknown",
      reply: outOfScope[normalizedLanguage] ?? outOfScope.en,
      guidance: [],
      emergency_contact: cachedPackage?.emergency_contact ?? { number: "112", dial_uri: "tel:112" },
      safety_notice: "Call 112 in India if anyone is in immediate danger.",
    };
  }
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
    in_scope: true,
    reply: instructions.join("\n"),
    emergency_type: category,
    language,
    urgency: category === "unknown" ? "undetermined" : "urgent",
    guidance: instructions,
    emergency_contact: cachedPackage?.emergency_contact ?? { number: "112", dial_uri: "tel:112" },
    safety_notice: fallbackNotice[language] ?? fallbackNotice.en,
    note: "The server, Groq AI, live weather and new alerts are unavailable offline. This local keyword match may be incomplete.",
  };
}
