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
  latitude: number;
  longitude: number;
  radius_km: number;
  include_weather: boolean;
  use_gemini: boolean;
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
  const instructions =
    cachedPackage?.guidance_catalog?.[category]?.instructions ??
    cachedPackage?.guidance_catalog?.unknown?.instructions ??
    [];
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
