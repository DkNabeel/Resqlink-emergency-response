import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Modal,
  Pressable,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import MapView, { Marker, Polyline } from "react-native-maps";
import * as Location from "expo-location";
import "./src/background";
import { startBackgroundMonitoring, setBackgroundLanguage, getLastBackgroundLocation } from "./src/background";
import {
  getOfflineGuidance,
  getSystemStatus,
  isApiConfigured,
  sendEmergencyChat,
  getNearbyWeather,
  getNearbyFacilities,
  cacheNearbyFacilities,
  getCachedNearbyFacilities,
  getDrivingRoute,
  downloadOfflinePackage,
  type EmergencyResult,
  type NearbyFacility,
  type OfflinePackage,
  type WeatherSnapshot,
  type DrivingRouteEstimate,
} from "./src/api";
import { getLatestOfflinePackage } from "./src/cache";

type Coordinates = { latitude: number; longitude: number };
type Language = "en" | "hi" | "kn";
type FacilityLookupStatus = "idle" | "loading" | "available" | "empty" | "error";
type FacilityFilter = "all" | "medical" | "police" | "fire" | "shelter" | "community";
const FACILITY_FILTERS: { value: FacilityFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "medical", label: "Medical" },
  { value: "police", label: "Police" },
  { value: "fire", label: "Fire" },
  { value: "shelter", label: "Shelter / assembly" },
  { value: "community", label: "Community" },
];
const FACILITY_RADIUS_OPTIONS = [5, 10, 20] as const;

function matchesFacilityFilter(facility: NearbyFacility, filter: FacilityFilter) {
  const type = String(facility.facility_type ?? "").toLowerCase();
  if (filter === "all") return true;
  if (filter === "medical") return ["hospital", "clinic", "pharmacy", "ambulance"].includes(type);
  if (filter === "police") return type === "police";
  if (filter === "fire") return type === "fire_station";
  if (filter === "shelter") return ["shelter", "assembly_point"].includes(type);
  return ["community_center", "education"].includes(type);
}

type RouteSummary = {
  facilityKey: string;
  facilityName: string;
  distanceKm: number;
  etaMinutes: number;
  note: string;
};

const LANGUAGES: { code: Language; label: string }[] = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "kn", label: "ಕನ್ನಡ" },
];

const QUICK_REPORTS: { emoji: string; label: string; messages: Record<Language, string> }[] = [
  { emoji: "🔥", label: "Fire", messages: { en: "There is a fire and smoke nearby. I need emergency assistance.", hi: "पास में आग और धुआँ है। मुझे आपातकालीन सहायता चाहिए।", kn: "ಹತ್ತಿರದಲ್ಲಿ ಬೆಂಕಿ ಮತ್ತು ಹೊಗೆ ಇದೆ. ನನಗೆ ತುರ್ತು ಸಹಾಯ ಬೇಕು." } },
  { emoji: "🌊", label: "Flood", messages: { en: "Floodwater is rising in my area. I need emergency assistance.", hi: "मेरे इलाके में बाढ़ का पानी बढ़ रहा है। मुझे आपातकालीन सहायता चाहिए।", kn: "ನನ್ನ ಪ್ರದೇಶದಲ್ಲಿ ಪ್ರವಾಹದ ನೀರು ಏರುತ್ತಿದೆ. ನನಗೆ ತುರ್ತು ಸಹಾಯ ಬೇಕು." } },
  { emoji: "🚑", label: "Medical", messages: { en: "Someone is seriously injured and needs medical assistance.", hi: "कोई गंभीर रूप से घायल है और उसे चिकित्सा सहायता चाहिए।", kn: "ಯಾರೋ ಗಂಭೀರವಾಗಿ ಗಾಯಗೊಂಡಿದ್ದಾರೆ. ಅವರಿಗೆ ವೈದ್ಯಕೀಯ ಸಹಾಯ ಬೇಕು." } },
  { emoji: "🚗", label: "Accident", messages: { en: "There has been a road accident and people may be injured.", hi: "सड़क दुर्घटना हुई है और लोग घायल हो सकते हैं।", kn: "ರಸ್ತೆ ಅಪಘಾತ ಸಂಭವಿಸಿದೆ ಮತ್ತು ಕೆಲವರು ಗಾಯಗೊಂಡಿರಬಹುದು." } },
  { emoji: "🏚️", label: "Earthquake", messages: { en: "An earthquake is happening and buildings may be damaged.", hi: "भूकंप आ रहा है और इमारतों को नुकसान हो सकता है।", kn: "ಭೂಕಂಪ ಸಂಭವಿಸುತ್ತಿದೆ ಮತ್ತು ಕಟ್ಟಡಗಳಿಗೆ ಹಾನಿಯಾಗಿರಬಹುದು." } },
  { emoji: "⚠️", label: "Gas leak", messages: { en: "I can smell gas in the building. There may be a gas leak.", hi: "इमारत में गैस की गंध आ रही है। गैस रिसाव हो सकता है।", kn: "ಕಟ್ಟಡದಲ್ಲಿ ಅನಿಲದ ವಾಸನೆ ಬರುತ್ತಿದೆ. ಅನಿಲ ಸೋರಿಕೆ ಇರಬಹುದು." } },
];

const COPY: Record<Language, { eyebrow: string; title: string; subtitle: string; report: string; placeholder: string; analyze: string; location: string; getLocation: string; offline: string; saveOffline: string }> = {
  en: {
    eyebrow: "EMERGENCY ASSISTANCE",
    title: "What is happening?",
    subtitle: "Describe the situation. ResQLink will help identify the emergency and show immediate safety guidance.",
    report: "Describe the emergency",
    placeholder: "Tell us what happened, where it happened, and whether anyone is in danger...",
    analyze: "Get emergency guidance",
    location: "Your location",
    getLocation: "Get GPS location",
    offline: "Offline safety pack",
    saveOffline: "Download / refresh pack",
  },
  hi: {
    eyebrow: "आपातकालीन सहायता",
    title: "क्या हुआ है?",
    subtitle: "स्थिति का वर्णन करें। ResQLink आपातस्थिति पहचानकर सुरक्षा निर्देश दिखाएगा।",
    report: "आपातस्थिति का वर्णन करें",
    placeholder: "बताएँ क्या हुआ, कहाँ हुआ और क्या कोई खतरे में है...",
    analyze: "आपातकालीन सहायता प्राप्त करें",
    location: "आपकी लोकेशन",
    getLocation: "GPS लोकेशन प्राप्त करें",
    offline: "ऑफलाइन सुरक्षा पैक",
    saveOffline: "पैक डाउनलोड / रीफ्रेश करें",
  },
  kn: {
    eyebrow: "ತುರ್ತು ಸಹಾಯ",
    title: "ಏನಾಗಿದೆ?",
    subtitle: "ಪರಿಸ್ಥಿತಿಯನ್ನು ವಿವರಿಸಿ. ResQLink ತುರ್ತು ಪರಿಸ್ಥಿತಿಯನ್ನು ಗುರುತಿಸಿ ಸುರಕ್ಷತಾ ಮಾರ್ಗದರ್ಶನ ನೀಡುತ್ತದೆ.",
    report: "ತುರ್ತು ಪರಿಸ್ಥಿತಿಯನ್ನು ವಿವರಿಸಿ",
    placeholder: "ಏನಾಯಿತು, ಎಲ್ಲಿ ಸಂಭವಿಸಿತು ಮತ್ತು ಯಾರಿಗಾದರೂ ಅಪಾಯವಿದೆಯೇ ಎಂದು ತಿಳಿಸಿ...",
    analyze: "ತುರ್ತು ಮಾರ್ಗದರ್ಶನ ಪಡೆಯಿರಿ",
    location: "ನಿಮ್ಮ ಸ್ಥಳ",
    getLocation: "GPS ಸ್ಥಳ ಪಡೆಯಿರಿ",
    offline: "ಆಫ್‌ಲೈನ್ ಸುರಕ್ಷತಾ ಪ್ಯಾಕ್",
    saveOffline: "ಪ್ಯಾಕ್ ಡೌನ್‌ಲೋಡ್ / ರಿಫ್ರೆಶ್",
  },
};

export default function App() {
  const [language, setLanguage] = useState<Language>("en");
  const [message, setMessage] = useState("");
  const [selectedPrompt, setSelectedPrompt] = useState("");
  const [coordinates, setCoordinates] = useState<Coordinates | null>(null);
  const [geoDetails, setGeoDetails] = useState<{ city?: string; district?: string; state?: string }>({});
  const [offlinePackage, setOfflinePackage] = useState<OfflinePackage | null>(null);
  const [result, setResult] = useState<EmergencyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [permissionsReady, setPermissionsReady] = useState(false);
  const [permissionBusy, setPermissionBusy] = useState(false);
  const [permissionMessage, setPermissionMessage] = useState("ResQLink needs location and notification permissions to provide emergency assistance.");
  const [backgroundMonitoringReady, setBackgroundMonitoringReady] = useState(false);
  const [status, setStatus] = useState("Ready to help");
  const [locationStatus, setLocationStatus] = useState("Location has not been requested");
  const [backendConnection, setBackendConnection] = useState<"checking" | "connected" | "unreachable">("checking");
  const [backendAiConfigured, setBackendAiConfigured] = useState<boolean | null>(null);
  const [chatHistory, setChatHistory] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [weatherVisible, setWeatherVisible] = useState(false);
  const [weatherBusy, setWeatherBusy] = useState(false);
  const [weatherData, setWeatherData] = useState<WeatherSnapshot | null>(null);
  const [nearbyFacilities, setNearbyFacilities] = useState<NearbyFacility[]>([]);
  const [cachedNearbyFacilities, setCachedNearbyFacilities] = useState<NearbyFacility[]>([]);
  const [cachedNearbyFacilitiesAt, setCachedNearbyFacilitiesAt] = useState<string | null>(null);
  const [facilityLookupStatus, setFacilityLookupStatus] = useState<FacilityLookupStatus>("idle");
  const [facilityLookupError, setFacilityLookupError] = useState("");
  const [routeEstimate, setRouteEstimate] = useState<RouteSummary | null>(null);
  const [routeEstimateError, setRouteEstimateError] = useState("");
  const [routeBusyFacility, setRouteBusyFacility] = useState<string | null>(null);
  const [routePath, setRoutePath] = useState<Coordinates[]>([]);
  const [routeDestination, setRouteDestination] = useState<{ coordinates: Coordinates; name: string } | null>(null);
  const [facilityFilter, setFacilityFilter] = useState<FacilityFilter>("all");
  const [facilityRadiusKm, setFacilityRadiusKm] = useState(20);
  const [mapExpanded, setMapExpanded] = useState(false);
  const [offlineExpanded, setOfflineExpanded] = useState(false);
  const facilityRequestSequence = useRef(0);
  const currentGpsAvailable = useRef(false);
  const mapRef = useRef<MapView | null>(null);

  const copy = COPY[language];

  useEffect(() => {
    if (!mapExpanded || routePath.length < 2) return;
    mapRef.current?.fitToCoordinates(routePath, {
      edgePadding: { top: 52, right: 42, bottom: 52, left: 42 },
      animated: true,
    });
  }, [mapExpanded, routePath]);

  async function refreshNearbyFacilities(point: Coordinates, radiusKm = facilityRadiusKm) {
    if (!isApiConfigured()) return;
    const requestSequence = ++facilityRequestSequence.current;
    setFacilityLookupStatus("loading");
    setFacilityLookupError("");
    try {
      const found = await getNearbyFacilities(point, radiusKm);
      if (requestSequence !== facilityRequestSequence.current) return;
      const items = Array.isArray(found.items) ? found.items : [];
      setNearbyFacilities(items);
      setFacilityLookupStatus(items.length > 0 ? "available" : "empty");
      const saved = await cacheNearbyFacilities(items, point, radiusKm).catch(() => null);
      if (saved && saved.items.length > 0) {
        setCachedNearbyFacilities(saved.items);
        setCachedNearbyFacilitiesAt(saved.storedAt);
      }
      if (items.length > 0) {
        setOfflinePackage((current) => current
          ? { ...current, nearby_discovered_facilities: items, facility_discovery_status: "available" }
          : current);
      }
      setStatus(items.length > 0
        ? `Found ${items.length} nearby facility candidate(s) within ${radiusKm} km`
        : saved?.items.length
          ? "No new live results · showing previously saved nearby facilities"
          : `No mapped public-service or community facilities returned within ${radiusKm} km`);
    } catch (error) {
      if (requestSequence !== facilityRequestSequence.current) return;
      const detail = error instanceof Error ? error.message : "Nearby facility lookup failed.";
      setFacilityLookupError(detail);
      setFacilityLookupStatus("error");
      setStatus("Nearby facility search is temporarily unavailable");
    }
  }

  async function enableRequiredPermissions() {
    setPermissionBusy(true);
    try {
      const permissions = await startBackgroundMonitoring();
      setPermissionMessage(permissions.message);
      setBackgroundMonitoringReady(permissions.backgroundEnabled);
      const ready = permissions.locationEnabled && permissions.notificationsEnabled;
      setPermissionsReady(ready);
      if (ready) {
        setStatus(permissions.message);
        // Capture GPS and seed the first offline package as soon as onboarding succeeds.
        void (async () => {
          try {
            const point = await obtainLocation();
            if (isApiConfigured()) {
              const downloaded = await downloadOfflinePackage(point, language);
              setOfflinePackage(downloaded.payload);
              void refreshNearbyFacilities(point);
              setStatus("GPS ready · nearby emergency information saved for offline use");
            }
          } catch (error) {
            setLocationStatus(error instanceof Error ? error.message : "GPS or offline package is not ready yet.");
          }
        })();
      }
    } catch (error) {
      setPermissionsReady(false);
      setPermissionMessage(error instanceof Error ? error.message : "Please enable location and notification permissions in Settings.");
    } finally {
      setPermissionBusy(false);
    }
  }

  async function checkBackendConnection() {
    setBackendConnection("checking");
    try {
      const health = await getSystemStatus();
      setBackendConnection(health.api?.status === "ok" ? "connected" : "unreachable");
      setBackendAiConfigured(Boolean(health.providers?.ai?.api_key_configured));
    } catch {
      setBackendConnection("unreachable");
      setBackendAiConfigured(null);
    }
  }

  useEffect(() => {
    setBackgroundLanguage(language).catch(() => {});
  }, [language]);

  useEffect(() => {
    let active = true;
    enableRequiredPermissions().catch(() => {});
    getLastBackgroundLocation()
      .then((saved) => {
        if (active && saved && !currentGpsAvailable.current) {
          const savedPoint = { latitude: saved.latitude, longitude: saved.longitude };
          setCoordinates(savedPoint);
          setLocationStatus("Using last saved GPS position · " + new Date(saved.recorded_at ?? Date.now()).toLocaleString());
          void refreshNearbyFacilities(savedPoint);
        }
      })
      .catch(() => {});
    getLatestOfflinePackage()
      .then((cached) => {
        if (active && cached) setOfflinePackage(cached.payload);
      })
      .catch(() => {});
    getCachedNearbyFacilities()
      .then((cached) => {
        if (active && cached) {
          setCachedNearbyFacilities(cached.items);
          setCachedNearbyFacilitiesAt(cached.storedAt);
        }
      })
      .catch(() => {});
    getSystemStatus()
      .then((health) => {
        if (!active) return;
        setBackendConnection(health.api?.status === "ok" ? "connected" : "unreachable");
        setBackendAiConfigured(Boolean(health.providers?.ai?.api_key_configured));
      })
      .catch(() => {
        if (active) {
          setBackendConnection("unreachable");
          setBackendAiConfigured(null);
        }
      });
    return () => { active = false; };
  }, []);

  async function obtainLocation(): Promise<Coordinates> {
    setLocationStatus("Requesting location permission...");
    const permission = await Location.requestForegroundPermissionsAsync();
    if (permission.status !== "granted") {
      setLocationStatus("Permission denied. You can still send a report without GPS.");
      throw new Error("Location permission was not granted.");
    }
    const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    const point = { latitude: position.coords.latitude, longitude: position.coords.longitude };
    currentGpsAvailable.current = true;
    setCoordinates(point);
    void refreshNearbyFacilities(point);
    try {
      const addresses = await Location.reverseGeocodeAsync(point);
      const address = addresses[0];
      if (address) {
        setGeoDetails({
          city: address.city ?? address.subregion ?? undefined,
          district: address.district ?? address.subregion ?? address.city ?? undefined,
          state: address.region ?? undefined,
        });
      }
    } catch {
      // GPS coordinates remain usable when reverse geocoding is unavailable.
    }
    setLocationStatus("GPS location received · accuracy about " + Math.round(position.coords.accuracy ?? 0) + " m");
    return point;
  }

  async function handleLocation() {
    setBusy(true);
    try {
      await obtainLocation();
      setStatus("Your GPS location is ready");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to read location");
    } finally {
      setBusy(false);
    }
  }

  async function handlePackageDownload() {
    setBusy(true);
    try {
      const point = coordinates ?? await obtainLocation();
      const response = await downloadOfflinePackage(point, language);
      setOfflinePackage(response.payload);
      void refreshNearbyFacilities(point);
      setStatus(response.cacheStatus === "not_modified"
        ? "Offline pack is already up to date"
        : "Emergency safety pack saved to this device");
    } catch (error) {
      const cached = await getLatestOfflinePackage().catch(() => null);
      if (cached) {
        setOfflinePackage(cached.payload);
        setStatus("Network unavailable · showing saved pack from " + cached.storedAt);
      } else {
        setStatus(error instanceof Error ? error.message : "Offline pack download failed");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleEmergency() {
    const submittedMessage = message.trim();
    if (!submittedMessage) {
      setStatus("Please describe the emergency first");
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      let point = coordinates;
      if (!point) {
        try { point = await obtainLocation(); }
        catch {
          const saved = await getLastBackgroundLocation();
          if (saved) {
            point = { latitude: saved.latitude, longitude: saved.longitude };
            setCoordinates(point);
            setLocationStatus("Using the last saved GPS position; it may be out of date.");
          } else {
            setLocationStatus("Sending report without current GPS coordinates");
          }
        }
      }
      const response = await sendEmergencyChat({
        message: submittedMessage,
        language,
        conversation_history: chatHistory.slice(-10),
        ...(point ? { latitude: point.latitude, longitude: point.longitude } : {}),
        radius_km: 10,
        ...geoDetails,
      });
      setResult(response);
      if (response.in_scope) {
        if (point) {
          // Facility discovery stays independent from the urgent Groq reply.
          void refreshNearbyFacilities(point);
        }
        const assistantConnected = response.ai_status === "connected" || response.gemini_status === "connected";
        if (assistantConnected) {
          setChatHistory((current) => [
            ...current,
            { role: "user" as const, content: submittedMessage },
            ...(response.reply ? [{
              role: "assistant" as const,
              content: response.reply + (response.follow_up_question ? "\nFollow-up: " + response.follow_up_question : ""),
            }] : []),
          ].slice(-10));
          setStatus("Emergency response received");
        } else {
          // Local fallback guidance is shown in the response card, but it
          // must not be sent back as though Groq generated it on the next turn.
          setStatus("Local emergency guidance shown · AI conversation context preserved");
        }
      } else {
        setStatus("ResQLink only handles emergency-related assistance");
      }
      setMessage("");
      setSelectedPrompt("");
    } catch (error) {
      const cached = offlinePackage ?? await getLatestOfflinePackage().then((x) => x?.payload ?? null).catch(() => null);
      const fallback = getOfflineGuidance(submittedMessage, language, cached);
      const reason = error instanceof Error ? error.message : "Unable to reach the backend.";
      setBackendConnection("unreachable");
      const offlineReply = fallback.reply ?? (fallback.guidance ?? []).join("\n");
      setResult({ ...fallback, reply: offlineReply, diagnostic_message: reason });
      if (fallback.in_scope) {
        // Keep this result visible in the response card without contaminating
        // the live multi-turn Groq history with an offline keyword fallback.
        setStatus("Offline keyword guidance · AI and live data unavailable");
      } else {
        setStatus("ResQLink only handles emergency-related assistance");
      }
      setMessage("");
      setSelectedPrompt("");
    } finally {
      setBusy(false);
    }
  }

  async function openWeather() {
    setWeatherVisible(true);
    setWeatherBusy(true);
    try {
      const point = coordinates ?? await obtainLocation();
      const snapshot = await getNearbyWeather(point);
      setWeatherData(snapshot);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Weather is unavailable");
    } finally {
      setWeatherBusy(false);
    }
  }

  function facilityKey(facility: NearbyFacility) {
    return [
      facility.name ?? "facility",
      facility.latitude ?? "no-lat",
      facility.longitude ?? "no-lon",
    ].join("|");
  }

  async function openFacilityRoute(facility: NearbyFacility) {
    if (typeof facility.latitude !== "number" || typeof facility.longitude !== "number") {
      setStatus("This facility has no usable map coordinates");
      return;
    }
    const key = facilityKey(facility);
    const destinationPoint = {
      latitude: facility.latitude,
      longitude: facility.longitude,
    };
    const destinationName = facility.name ?? "Nearby facility";
    setRouteBusyFacility(key);
    setRouteEstimateError("");
    setRouteEstimate(null);
    setRoutePath([]);
    setRouteDestination({ coordinates: destinationPoint, name: destinationName });
    setMapExpanded(true);
    try {
      const originPoint = coordinates ?? await obtainLocation();
      const route: DrivingRouteEstimate = await getDrivingRoute(originPoint, destinationPoint);
      const rawCoordinates = route.route_geometry?.coordinates;
      const path = Array.isArray(rawCoordinates)
        ? rawCoordinates
            .filter((point) => Array.isArray(point) && point.length >= 2
              && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])))
            .map((point) => ({ latitude: Number(point[1]), longitude: Number(point[0]) }))
        : [];
      setRoutePath(path);
      setRouteEstimate({
        facilityKey: key,
        facilityName: destinationName,
        distanceKm: route.distance_km,
        etaMinutes: route.estimated_travel_time_minutes,
        note: route.note,
      });
      setStatus(path.length > 1 ? "Driving route preview ready" : "Road route estimate calculated");
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Road route estimate unavailable.";
      setRouteEstimateError(detail);
      setStatus("Route estimate unavailable · you can still open map directions");
    } finally {
      setRouteBusyFacility(null);
    }
  }

  async function openTurnByTurnDirections() {
    if (!coordinates || !routeDestination) return;
    const mapsUrl = "https://www.google.com/maps/dir/?api=1"
      + "&origin=" + coordinates.latitude + "," + coordinates.longitude
      + "&destination=" + routeDestination.coordinates.latitude + "," + routeDestination.coordinates.longitude
      + "&travelmode=driving";
    try {
      await Linking.openURL(mapsUrl);
    } catch {
      setStatus("Unable to open Google Maps directions. Check your internet connection.");
    }
  }

  async function callFacility(facility: NearbyFacility) {
    const phone = String(facility.phone ?? "").replace(/[^0-9+]/g, "");
    if (!phone || phone.replace(/\D/g, "").length < 5) {
      setStatus("No usable phone number is listed for this facility.");
      return;
    }
    try {
      await Linking.openURL("tel:" + phone);
    } catch {
      setStatus("Unable to open the phone dialer.");
    }
  }

  async function callEmergencyNumber() {
    try { await Linking.openURL("tel:112"); }
    catch { setStatus("Please dial 112 from your phone for emergency assistance"); }
  }

  function chooseLanguage(code: Language) {
    setLanguage(code);
    setResult(null);
  }

  function startNewIncident() {
    setChatHistory([]);
    setResult(null);
    setMessage("");
    setSelectedPrompt("");
    setRouteEstimate(null);
    setRouteEstimateError("");
    setRoutePath([]);
    setRouteDestination(null);
    setStatus("New incident started · previous chat context cleared");
  }

  const instructions = result?.guidance ?? [];
  const contact = offlinePackage?.emergency_contact?.number ?? "112";
  const ai = result?.ai_analysis;
  const aiConnected = result?.ai_status === "connected" || result?.gemini_status === "connected";
  const aiLabel = aiConnected
    ? (ai?.provider ?? "Groq AI") + (ai?.model ? " · " + ai.model : "")
    : result?.status === "offline_guidance_only" ? "On-device offline guidance" : "Server-side local NLP fallback";
  const aiError = typeof ai?.message === "string" ? ai.message : "";
  const networkError = typeof result?.diagnostic_message === "string" ? result.diagnostic_message : "";
  const emergencyType = String(result?.emergency_type ?? "unknown").replaceAll("_", " ");
  const packageFacilities = [
    ...(offlinePackage?.nearby_verified_facilities ?? []),
    ...(offlinePackage?.nearby_discovered_facilities ?? []),
  ];
  const facilities: NearbyFacility[] =
    nearbyFacilities.length > 0
      ? nearbyFacilities
      : cachedNearbyFacilities.length > 0
        ? cachedNearbyFacilities
        : (result?.nearby_facilities?.length ? result.nearby_facilities : packageFacilities);
  const visibleFacilities = facilities
    .filter((facility) => matchesFacilityFilter(facility, facilityFilter))
    .sort((a, b) => (a.distance_km ?? Number.POSITIVE_INFINITY) - (b.distance_km ?? Number.POSITIVE_INFINITY))
    .slice(0, 12);

  if (!permissionsReady) {
    return (
      <SafeAreaView style={styles.safe}>
        <StatusBar barStyle="light-content" />
        <View style={styles.permissionGate}>
          <View style={styles.logo}><Text style={styles.logoText}>R</Text></View>
          <Text style={styles.permissionTitle}>Enable ResQLink protection</Text>
          <Text style={styles.permissionBody}>
            ResQLink needs location to identify nearby government alerts and emergency facilities, and notifications to warn you about relevant disasters.
          </Text>
          <Text style={styles.permissionMessage}>{permissionMessage}</Text>
          <Pressable onPress={enableRequiredPermissions} disabled={permissionBusy} style={styles.permissionButton}>
            {permissionBusy ? <ActivityIndicator color="#F7F7F7" /> : <Text style={styles.permissionButtonText}>Allow required permissions</Text>}
          </Pressable>
          <Pressable onPress={() => Linking.openSettings()} style={styles.permissionSettings}>
            <Text style={styles.permissionSettingsText}>Open phone Settings</Text>
          </Pressable>
          <Text style={styles.permissionFootnote}>Background location refresh is best-effort and requires a compatible native app build. Foreground emergency assistance requires location and notifications.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="light-content" />
      <ScrollView contentContainerStyle={styles.container} showsVerticalScrollIndicator={false}>
        <View style={styles.topBar}>
          <View style={styles.brandRow}>
            <View style={styles.logo}><Text style={styles.logoText}>R</Text></View>
            <View>
              <Text style={styles.brand}>ResQLink</Text>
              <Text style={styles.brandSub}>EMERGENCY RESPONSE</Text>
            </View>
          </View>
          <Pressable onPress={checkBackendConnection} style={styles.readyPill}>
            <View style={[styles.readyDot, backendConnection === "unreachable" ? styles.connectionBad : backendConnection === "checking" ? styles.connectionChecking : null]} />
            <Text style={styles.readyText}>{backendConnection === "connected" ? "API ONLINE" : backendConnection === "checking" ? "CHECKING" : "API OFFLINE"}</Text>
          </Pressable>
        </View>

        <View style={styles.hero}>
          <Text style={styles.eyebrow}>{copy.eyebrow}</Text>
          <Text style={styles.heroTitle}>{copy.title}</Text>
          <Text style={styles.heroSub}>{copy.subtitle}</Text>
        </View>

        <Pressable onPress={callEmergencyNumber} style={({ pressed }) => [styles.sosCard, pressed && styles.pressed]}>
          <View style={styles.sosIcon}><Text style={styles.sosIconText}>112</Text></View>
          <View style={styles.sosCopy}>
            <Text style={styles.sosTitle}>Need immediate help?</Text>
            <Text style={styles.sosSub}>Call India's emergency number now</Text>
          </View>
          <Text style={styles.sosArrow}>↗</Text>
        </Pressable>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Choose your language</Text>
          <Text style={styles.sectionHint}>ಭಾಷೆ / भाषा</Text>
        </View>
        <View style={styles.languageRow}>
          {LANGUAGES.map((item) => (
            <Pressable
              key={item.code}
              onPress={() => chooseLanguage(item.code)}
              style={[styles.languageButton, language === item.code && styles.languageSelected]}
            >
              <Text style={[styles.languageText, language === item.code && styles.languageTextSelected]}>{item.label}</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Quick incident</Text>
          <Text style={styles.sectionHint}>Tap to fill</Text>
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.quickScroller} keyboardShouldPersistTaps="handled">
          {QUICK_REPORTS.map((item) => (
            <Pressable
              key={item.label}
              onPress={() => { setMessage(item.messages[language]); setSelectedPrompt(item.label); setResult(null); }}
              style={[styles.quickChip, selectedPrompt === item.label && styles.quickSelected]}
            >
              <Text style={styles.quickChipEmoji}>{item.emoji}</Text>
              <Text style={[styles.quickChipLabel, selectedPrompt === item.label && styles.quickLabelSelected]}>{item.label}</Text>
            </Pressable>
          ))}
        </ScrollView>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>{copy.report}</Text>
          <Text style={styles.sectionHint}>{message.length}/4000</Text>
        </View>
        <View style={styles.inputCard}>
          <TextInput
            value={message}
            onChangeText={(value) => { setMessage(value); setSelectedPrompt(""); }}
            placeholder={copy.placeholder}
            placeholderTextColor="#AEABA8"
            multiline
            scrollEnabled
            maxLength={4000}
            style={styles.input}
            textAlignVertical="top"
          />
          <View style={styles.inputFoot}><Text style={styles.inputHint}>Be clear. Mention injuries, hazards and nearby landmarks.</Text></View>
        </View>

        <Pressable onPress={handleEmergency} disabled={busy} style={({ pressed }) => [styles.analyzeButton, pressed && styles.pressed, busy && styles.disabled]}>
          {busy ? <ActivityIndicator color="#F7F7F7" /> : <Text style={styles.analyzeIcon}>✦</Text>}
          <Text style={styles.analyzeText}>{busy ? "Analyzing..." : copy.analyze}</Text>
          {!busy && <Text style={styles.analyzeArrow}>→</Text>}
        </Pressable>
        <Text style={styles.secureNote}>Emergency-only AI chat · GPS context · Government alerts and nearby services</Text>

        {chatHistory.length > 0 ? (
          <View style={styles.chatThread}>
            <View style={styles.chatHeader}>
              <Text style={styles.sectionTitle}>Latest emergency update</Text>
              <Pressable onPress={startNewIncident} style={styles.newIncidentButton}>
                <Text style={styles.newIncidentText}>New incident</Text>
              </Pressable>
            </View>
            {chatHistory.slice(-4).map((item, index) => (
              <View key={String(index)} style={[styles.chatBubble, item.role === "user" ? styles.chatUser : styles.chatAssistant]}>
                <Text style={[styles.chatBubbleText, item.role === "user" ? styles.chatUserText : styles.chatAssistantText]}>{item.content}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {result ? (
          <View style={styles.resultCard}>
            <View style={styles.resultTop}>
              <View>
                <Text style={styles.resultEyebrow}>RESPONSE SUMMARY</Text>
                <Text style={styles.resultTitle}>{emergencyType.toUpperCase()}</Text>
              </View>
              <View style={[styles.aiPill, aiConnected ? styles.aiOnline : styles.aiLocal]}>
                <View style={[styles.aiDot, aiConnected ? styles.aiDotOnline : styles.aiDotLocal]} />
                <Text style={[styles.aiPillText, aiConnected ? styles.aiTextOnline : styles.aiTextLocal]}>{aiConnected ? "AI CONNECTED" : "LOCAL MODE"}</Text>
              </View>
            </View>
            <Text style={styles.sourceText}>{aiLabel}</Text>
            {result.in_scope === false || !aiConnected
              ? <Text style={styles.summary}>{result.reply ?? "ResQLink only handles emergency-related assistance."}</Text>
              : null}
            {result.follow_up_question ? <Text style={styles.followUp}>Follow-up: {result.follow_up_question}</Text> : null}
            {networkError ? <Text style={styles.diagnosticWarning}>Backend connection failed: {networkError}</Text> : null}
            {aiError && !aiConnected ? <Text style={styles.diagnosticWarning}>Groq AI unavailable: {aiError}</Text> : null}
            {!aiConnected && !aiError && !networkError && backendConnection === "connected" && backendAiConfigured === false
              ? <Text style={styles.diagnosticWarning}>The backend is reachable, but GROQ_API_KEY is not configured on the server.</Text>
              : null}
            <View style={styles.resultDivider} />
            {instructions.length > 0 ? <Text style={styles.guidanceTitle}>Immediate safety guidance</Text> : null}
            {instructions.map((instruction, index) => (
              <View style={styles.instructionRow} key={String(index)}>
                <View style={styles.stepNumber}><Text style={styles.stepNumberText}>{index + 1}</Text></View>
                <Text style={styles.instruction}>{instruction}</Text>
              </View>
            ))}
            <Text style={styles.safetyNotice}>{result.safety_notice ?? "Follow official emergency responder instructions."}</Text>
            {result.nearby_alerts && result.nearby_alerts.length > 0 ? <Text style={styles.sourceText}>Location-matched government alerts (check match precision): {result.nearby_alerts.length}</Text> : null}
            {result.unverified_alerts && result.unverified_alerts.length > 0 ? <Text style={styles.diagnosticWarning}>{result.unverified_alerts.length} government alert(s) could not be confirmed for your exact location. Review their official source before acting.</Text> : null}
            {result.weather_context && typeof result.weather_context === "object" ? <Text style={styles.sourceText}>Weather context: {String((result.weather_context as { status?: string }).status ?? "available")}</Text> : null}
          </View>
        ) : null}

        <View style={styles.locationCard}>
          <View style={styles.locationIcon}><Text style={styles.locationIconText}>⌖</Text></View>
          <View style={styles.locationCopy}>
            <Text style={styles.locationTitle}>{copy.location}</Text>
            <Text style={styles.locationSub}>{coordinates ? coordinates.latitude.toFixed(4) + ", " + coordinates.longitude.toFixed(4) : locationStatus}</Text>
          </View>
          <Pressable onPress={handleLocation} disabled={busy} style={styles.locationAction}>
            <Text style={styles.locationActionText}>GPS ↗</Text>
          </Pressable>
        </View>

        <View style={styles.toolsRow}>
          <Pressable
            onPress={() => {
              if (!coordinates) { void handleLocation(); return; }
              setMapExpanded((value) => !value);
            }}
            style={[styles.toolButton, mapExpanded && styles.toolButtonSelected]}
          >
            <Text style={styles.toolEmoji}>🗺️</Text>
            <Text style={[styles.toolLabel, mapExpanded && styles.toolLabelSelected]}>{mapExpanded ? "Hide map" : "Map"}</Text>
          </Pressable>
          <Pressable onPress={openWeather} style={styles.toolButton}>
            <Text style={styles.toolEmoji}>☀️</Text>
            <Text style={styles.toolLabel}>Weather</Text>
          </Pressable>
          <Pressable
            onPress={() => setOfflineExpanded((value) => !value)}
            style={[styles.toolButton, offlineExpanded && styles.toolButtonSelected]}
          >
            <Text style={styles.toolEmoji}>◈</Text>
            <Text style={[styles.toolLabel, offlineExpanded && styles.toolLabelSelected]}>Offline pack</Text>
          </Pressable>
        </View>

        {mapExpanded && coordinates ? (
          <View style={styles.mapCard}>
            <Text style={styles.sectionTitle}>Your current area</Text>
            <MapView
              ref={mapRef}
              style={styles.map}
              userInterfaceStyle="dark"
              tintColor="#C38F6C"
              initialRegion={{
                latitude: coordinates.latitude,
                longitude: coordinates.longitude,
                latitudeDelta: 0.025,
                longitudeDelta: 0.025,
              }}
              onMapReady={() => {
                if (routePath.length > 1) {
                  mapRef.current?.fitToCoordinates(routePath, {
                    edgePadding: { top: 52, right: 42, bottom: 52, left: 42 },
                    animated: true,
                  });
                }
              }}
              showsUserLocation
              showsMyLocationButton
            >
              <Marker coordinate={coordinates} title="Your current location" pinColor="#D13B2F" />
              {visibleFacilities.filter((item) => typeof item.latitude === "number" && typeof item.longitude === "number").map((item, index) => (
                <Marker
                  key={String(item.name ?? "facility") + "-" + index}
                  coordinate={{ latitude: item.latitude as number, longitude: item.longitude as number }}
                  title={item.name ?? "Emergency facility"}
                  description={(item.facility_type ?? "Facility").replaceAll("_", " ") + " · " + (item.verification_status ?? "unverified")}
                  pinColor={routeDestination?.coordinates.latitude === item.latitude && routeDestination?.coordinates.longitude === item.longitude ? "#D13B2F" : "#C38F6C"}
                />
              ))}
              {routePath.length > 1 ? (
                <Polyline coordinates={routePath} strokeWidth={5} strokeColor="#D13B2F" />
              ) : null}
            </MapView>
            <Text style={styles.mapNote}>
              {routeDestination
                ? "Route preview to " + routeDestination.name + ". This is a road-network estimate, not a hazard-cleared or officially safe route."
                : "Map points are community-mapped candidates unless marked as verified. They are not automatically designated safe zones."}
            </Text>
          </View>
        ) : null}

        {coordinates ? (
          <View style={styles.facilityCard}>
            <Text style={styles.sectionTitle}>Nearby emergency facilities</Text>
            <Text style={styles.facilityHint}>
              Search public-service candidates around your GPS location. Community-mapped places are unverified and must not be treated as confirmed safe zones.
            </Text>
            <View style={styles.facilityRadiusSection}>
              <Text style={styles.facilityMeta}>Search radius</Text>
              <View style={styles.facilityFilterRow}>
                {FACILITY_RADIUS_OPTIONS.map((radius) => (
                  <Pressable
                    key={String(radius)}
                    onPress={() => {
                      setFacilityRadiusKm(radius);
                      if (coordinates) void refreshNearbyFacilities(coordinates, radius);
                    }}
                    style={[styles.facilityFilter, facilityRadiusKm === radius && styles.facilityFilterSelected]}
                  >
                    <Text style={[styles.facilityFilterText, facilityRadiusKm === radius && styles.facilityFilterTextSelected]}>{radius} km</Text>
                  </Pressable>
                ))}
              </View>
            </View>
            <View style={styles.facilityFilterRow}>
              {FACILITY_FILTERS.map((filter) => (
                <Pressable
                  key={filter.value}
                  onPress={() => setFacilityFilter(filter.value)}
                  style={[styles.facilityFilter, facilityFilter === filter.value && styles.facilityFilterSelected]}
                >
                  <Text style={[styles.facilityFilterText, facilityFilter === filter.value && styles.facilityFilterTextSelected]}>{filter.label}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.facilityMeta}>
              Showing {visibleFacilities.length} of {facilities.length} saved/live candidates within {facilityRadiusKm} km
            </Text>
            {facilityLookupStatus === "loading" ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 9, paddingVertical: 8 }}>
                <ActivityIndicator color="#D13B2F" />
                <Text style={styles.facilityMeta}>Finding nearby hospitals, shelters, fire and police services...</Text>
              </View>
            ) : null}
            {facilityLookupStatus === "error" ? (
              <Text style={styles.diagnosticWarning}>
                Live facility search failed: {facilityLookupError}
                {facilities.length > 0 ? " Showing saved candidates where available." : " Please retry when the network is available."}
              </Text>
            ) : null}
            {facilityLookupStatus === "empty" && facilities.length === 0 ? (
              <Text style={styles.facilityHint}>No mapped public-service or community facilities were returned within {facilityRadiusKm} km. This does not mean no services exist nearby; use 112 for urgent help.</Text>
            ) : null}
            {facilities.length > 0 && visibleFacilities.length === 0 ? (
              <Text style={styles.facilityHint}>No saved candidates match this category. Choose All or another category to see nearby places.</Text>
            ) : null}
            {nearbyFacilities.length === 0 && cachedNearbyFacilities.length > 0 ? (
              <Text style={styles.facilityHint}>
                Showing {cachedNearbyFacilities.length} previously saved nearby candidates
                {cachedNearbyFacilitiesAt ? " · saved " + new Date(cachedNearbyFacilitiesAt).toLocaleString() : ""}.
                These are cached map records and may have changed.
              </Text>
            ) : null}
            {facilityLookupStatus === "idle" && facilities.length === 0 ? (
              <Text style={styles.facilityHint}>Nearby facility lookup will start when GPS is ready.</Text>
            ) : null}
            {visibleFacilities.map((facility, index) => {
              const key = facilityKey(facility);
              return (
                <View key={key + "-" + index} style={styles.facilityRow}>
                  <View style={styles.facilityCopy}>
                    <Text style={styles.facilityName}>{facility.name ?? "Emergency facility"}</Text>
                    <Text style={styles.facilityMeta}>
                      {(facility.facility_type ?? "facility").replaceAll("_", " ")}
                      {typeof facility.distance_km === "number" ? " · " + facility.distance_km.toFixed(1) + " km" : ""}
                    </Text>
                    <Text style={facility.verification_status === "verified" ? styles.verifiedText : styles.unverifiedText}>
                      {facility.verification_status === "verified"
                        ? "Verified project record"
                        : facility.has_map_name === false
                          ? "Inferred map label · unverified"
                          : "Unverified map candidate"}
                    </Text>
                  </View>
                  {facility.phone ? (
                    <Pressable onPress={() => callFacility(facility)} style={styles.callFacilityButton}>
                      <Text style={styles.callFacilityText}>Call</Text>
                    </Pressable>
                  ) : null}
                  <Pressable onPress={() => openFacilityRoute(facility)} disabled={routeBusyFacility === key} style={styles.routeButton}>
                    <Text style={styles.routeButtonText}>{routeBusyFacility === key ? "Calculating..." : "Route ↗"}</Text>
                  </Pressable>
                </View>
              );
            })}
            {routeEstimate ? (
              <View style={styles.routePreviewCard}>
                <Text style={styles.facilityName}>Driving route · {routeEstimate.facilityName}</Text>
                <Text style={styles.routePreviewMetric}>{routeEstimate.distanceKm.toFixed(2)} km · about {routeEstimate.etaMinutes.toFixed(0)} min</Text>
                <Text style={styles.facilityHint}>{routeEstimate.note} Not checked against live disaster hazards.</Text>
                <Pressable onPress={openTurnByTurnDirections} style={styles.routeDirectionsButton}>
                  <Text style={styles.routeDirectionsText}>Open turn-by-turn directions ↗</Text>
                </Pressable>
              </View>
            ) : routeDestination ? (
              <View style={styles.routePreviewCard}>
                <Text style={styles.facilityName}>Route destination · {routeDestination.name}</Text>
                <Text style={styles.facilityHint}>The in-app road estimate is unavailable. You can still request directions from Google Maps.</Text>
                <Pressable onPress={openTurnByTurnDirections} style={styles.routeDirectionsButton}>
                  <Text style={styles.routeDirectionsText}>Open directions in Google Maps ↗</Text>
                </Pressable>
              </View>
            ) : null}
            {routeEstimateError ? <Text style={styles.diagnosticWarning}>{routeEstimateError}</Text> : null}
            <Pressable onPress={() => refreshNearbyFacilities(coordinates)} style={styles.recheckButton}>
              <Text style={styles.recheckText}>Refresh nearby facilities</Text>
            </Pressable>
          </View>
        ) : null}

        {offlineExpanded ? (
        <View style={styles.offlineCard}>
          <View style={styles.offlineHeader}>
            <View style={styles.offlineIcon}><Text style={styles.offlineIconText}>◈</Text></View>
            <View style={styles.offlineCopy}>
              <Text style={styles.offlineTitle}>{copy.offline}</Text>
              <Text style={styles.offlineSub}>Save essential guidance and 112 on this device</Text>
            </View>
          </View>
          <Pressable onPress={handlePackageDownload} disabled={busy} style={styles.offlineButton}>
            <Text style={styles.offlineButtonText}>{copy.saveOffline}</Text>
            <Text style={styles.offlineButtonArrow}>↓</Text>
          </Pressable>
          <Text style={styles.offlineStatus}>{offlinePackage ? "Saved · " + new Date(offlinePackage.generated_at).toLocaleString() : "No saved package yet"}</Text>
          <Text style={styles.offlineStatus}>
            Nearby facilities saved: {Math.max(
              cachedNearbyFacilities.length,
              (offlinePackage?.nearby_verified_facilities?.length ?? 0) + (offlinePackage?.nearby_discovered_facilities?.length ?? 0)
            )} · separate on-device facility cache
          </Text>
          <Text style={styles.offlineWarning}>Offline mode uses cached emergency facilities and guidance. Full offline map tiles and road-by-road routing are not included yet.</Text>
        </View>
        ) : null}

        <View style={styles.footer}>
          <Text style={styles.footerStatus}>{status}</Text>
          {permissionsReady && !backgroundMonitoringReady ? <Text style={styles.offlineWarning}>Background alerts and automatic cache refresh are not active on this device build.</Text> : null}
          <Text style={styles.footerApi}>
            {backendConnection === "connected"
              ? "● Backend reachable" + (backendAiConfigured ? " · Groq key configured" : " · Groq key missing")
              : backendConnection === "checking"
                ? "◌ Checking backend connection..."
                : isApiConfigured()
                  ? "○ Backend unreachable · check laptop IP, Wi-Fi and firewall"
                  : "○ Configure mobile/.env API address"}
          </Text>
          <Pressable onPress={checkBackendConnection} style={styles.recheckButton}>
            <Text style={styles.recheckText}>Test backend connection again</Text>
          </Pressable>
          <Text style={styles.disclaimer}>ResQLink is a prototype. It does not replace 112, government alerts or professional emergency responders.</Text>
        </View>
      </ScrollView>
      <Modal visible={weatherVisible} transparent animationType="fade" onRequestClose={() => setWeatherVisible(false)}>
        <View style={styles.modalShade}>
          <View style={styles.weatherModal}>
            <View style={styles.weatherModalHeader}>
              <View>
                <Text style={styles.weatherTitle}>Local weather</Text>
                <Text style={styles.weatherSub}>Supporting information · Open-Meteo</Text>
              </View>
              <Pressable onPress={() => setWeatherVisible(false)} style={styles.weatherClose}>
                <Text style={styles.weatherCloseText}>✕</Text>
              </Pressable>
            </View>
            {weatherBusy ? <ActivityIndicator color="#D13B2F" size="large" /> : weatherData?.current ? (
              <>
                <Text style={styles.weatherCondition}>{weatherData.current.condition ?? "Current conditions"}</Text>
                <Text style={styles.weatherTemperature}>{weatherData.current.temperature_c ?? "—"}°C</Text>
                <View style={styles.weatherMetrics}>
                  <View style={styles.weatherMetric}><Text style={styles.weatherMetricValue}>{weatherData.current.relative_humidity_pct ?? "—"}%</Text><Text style={styles.weatherMetricLabel}>Humidity</Text></View>
                  <View style={styles.weatherMetric}><Text style={styles.weatherMetricValue}>{weatherData.current.wind_speed_kmh ?? "—"} km/h</Text><Text style={styles.weatherMetricLabel}>Wind</Text></View>
                  <View style={styles.weatherMetric}><Text style={styles.weatherMetricValue}>{weatherData.forecast_indicators?.max_precipitation_probability_pct ?? "—"}%</Text><Text style={styles.weatherMetricLabel}>Rain chance</Text></View>
                </View>
                <Text style={styles.weatherDisclaimer}>{weatherData.disclaimer ?? "Weather is supporting context, not an official disaster warning."}</Text>
              </>
            ) : <Text style={styles.weatherSub}>Weather is unavailable. Check your connection and GPS.</Text>}
            <Pressable onPress={() => setWeatherVisible(false)} style={styles.weatherDone}><Text style={styles.weatherDoneText}>Close</Text></Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#030303" },
  permissionGate: { flex: 1, justifyContent: "center", alignItems: "center", padding: 28, gap: 16 },
  permissionTitle: { color: "#F7F7F7", fontSize: 24, fontWeight: "900", textAlign: "center" },
  permissionBody: { color: "#AEABA8", fontSize: 13, lineHeight: 20, textAlign: "center" },
  permissionMessage: { color: "#C38F6C", backgroundColor: "#1B1716", borderWidth: 1, borderColor: "#5B3733", borderRadius: 10, padding: 12, fontSize: 11, lineHeight: 17, textAlign: "center" },
  permissionButton: { backgroundColor: "#D13B2F", borderRadius: 12, paddingVertical: 14, paddingHorizontal: 20, minWidth: "100%", alignItems: "center" },
  permissionButtonText: { color: "#F7F7F7", fontSize: 13, fontWeight: "900" },
  permissionSettings: { padding: 10 },
  permissionSettingsText: { color: "#C38F6C", fontSize: 12, fontWeight: "800" },
  permissionFootnote: { color: "#AEABA8", fontSize: 10, lineHeight: 15, textAlign: "center" },
  container: { paddingHorizontal: 18, paddingTop: 12, paddingBottom: 44, gap: 14 },
  topBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 5 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  logo: { width: 42, height: 42, borderRadius: 13, backgroundColor: "#D13B2F", alignItems: "center", justifyContent: "center" },
  logoText: { color: "#F7F7F7", fontWeight: "900", fontSize: 23 },
  brand: { color: "#F7F7F7", fontSize: 21, fontWeight: "900", letterSpacing: -0.5 },
  brandSub: { color: "#AEABA8", fontSize: 9, fontWeight: "800", letterSpacing: 1.5, marginTop: 1 },
  weatherPill: { backgroundColor: "#141414", borderWidth: 1, borderColor: "#2A2A2A", borderRadius: 12, paddingHorizontal: 13, paddingVertical: 11, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  weatherPillText: { color: "#C38F6C", fontSize: 11, fontWeight: "800" },
  weatherPillArrow: { color: "#C38F6C", fontSize: 15, fontWeight: "900" },
  readyPill: { backgroundColor: "#171717", borderRadius: 30, borderWidth: 1, borderColor: "#292929", paddingHorizontal: 11, paddingVertical: 7, flexDirection: "row", alignItems: "center", gap: 6 },
  readyDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: "#C38F6C" },
  readyText: { color: "#AEABA8", fontSize: 10, fontWeight: "900", letterSpacing: 0.8 },
  hero: { gap: 6, paddingVertical: 4 },
  eyebrow: { color: "#C38F6C", fontSize: 10, fontWeight: "900", letterSpacing: 1.8 },
  heroTitle: { color: "#F7F7F7", fontSize: 31, fontWeight: "900", letterSpacing: -1.1 },
  heroSub: { color: "#AEABA8", fontSize: 13, lineHeight: 20, maxWidth: 500 },
  sosCard: { backgroundColor: "#171313", borderRadius: 17, borderWidth: 1, borderColor: "#5B3733", padding: 13, flexDirection: "row", alignItems: "center", gap: 12 },
  sosIcon: { width: 46, height: 46, backgroundColor: "#D13B2F", borderRadius: 13, alignItems: "center", justifyContent: "center" },
  sosIconText: { color: "#F7F7F7", fontWeight: "900", fontSize: 17 },
  sosCopy: { flex: 1, gap: 3 },
  sosTitle: { color: "#F7F7F7", fontSize: 14, fontWeight: "900" },
  sosSub: { color: "#AEABA8", fontSize: 11 },
  sosArrow: { color: "#D13B2F", fontSize: 22, fontWeight: "700" },
  sectionHeader: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", marginBottom: -9 },
  sectionTitle: { color: "#F7F7F7", fontSize: 14, fontWeight: "900" },
  sectionHint: { color: "#AEABA8", fontSize: 10, fontWeight: "600" },
  languageRow: { flexDirection: "row", gap: 8 },
  languageButton: { flex: 1, paddingVertical: 12, borderRadius: 11, backgroundColor: "#121212", borderWidth: 1, borderColor: "#2C2C2C", alignItems: "center" },
  languageSelected: { backgroundColor: "#D13B2F", borderColor: "#D13B2F" },
  languageText: { color: "#AEABA8", fontSize: 12, fontWeight: "800" },
  languageTextSelected: { color: "#F7F7F7" },
  quickScroller: { flexDirection: "row", gap: 8, paddingRight: 4, paddingVertical: 2 },
  quickChip: { flexDirection: "row", alignItems: "center", gap: 7, backgroundColor: "#131313", borderRadius: 13, borderWidth: 1, borderColor: "#2B2B2B", paddingHorizontal: 13, paddingVertical: 11 },
  quickSelected: { borderColor: "#D13B2F", backgroundColor: "#211412" },
  quickChipEmoji: { fontSize: 16 },
  quickChipLabel: { color: "#AEABA8", fontSize: 11, fontWeight: "800" },
  quickLabelSelected: { color: "#F7F7F7" },
  inputCard: { borderWidth: 1, borderColor: "#303030", backgroundColor: "#111111", borderRadius: 19, padding: 13, gap: 8 },
  input: { height: 116, fontSize: 14, color: "#F7F7F7", lineHeight: 21, padding: 3 },
  inputFoot: { borderTopWidth: 1, borderColor: "#292929", paddingTop: 8 },
  inputHint: { color: "#AEABA8", fontSize: 10 },
  locationCard: { backgroundColor: "#111111", borderRadius: 16, borderWidth: 1, borderColor: "#2B2B2B", padding: 11, flexDirection: "row", alignItems: "center", gap: 10 },
  locationIcon: { width: 36, height: 36, borderRadius: 11, backgroundColor: "#1A1A1A", alignItems: "center", justifyContent: "center" },
  locationIconText: { color: "#C38F6C", fontSize: 23 },
  locationCopy: { flex: 1, gap: 3 },
  locationTitle: { color: "#F7F7F7", fontSize: 12, fontWeight: "900" },
  locationSub: { color: "#AEABA8", fontSize: 10 },
  locationAction: { backgroundColor: "#211412", borderRadius: 9, paddingHorizontal: 12, paddingVertical: 9 },
  locationActionText: { color: "#C38F6C", fontSize: 10, fontWeight: "900" },
  analyzeButton: { backgroundColor: "#D13B2F", borderRadius: 16, paddingVertical: 16, paddingHorizontal: 17, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, shadowColor: "#D13B2F", shadowOpacity: 0.14, shadowRadius: 9, shadowOffset: { width: 0, height: 3 }, elevation: 3 },
  pressed: { opacity: 0.82 },
  disabled: { opacity: 0.55 },
  analyzeIcon: { color: "#F7F7F7", fontSize: 17, fontWeight: "900" },
  analyzeText: { color: "#F7F7F7", fontSize: 14, fontWeight: "900", flex: 1, textAlign: "center" },
  analyzeArrow: { color: "#F7F7F7", fontSize: 20, fontWeight: "800" },
  secureNote: { textAlign: "center", color: "#AEABA8", fontSize: 9, marginTop: -10 },
  resultCard: { backgroundColor: "#111111", borderWidth: 1, borderColor: "#2C2C2C", borderRadius: 19, padding: 16, gap: 11, shadowColor: "#000000", shadowOpacity: 0.20, shadowRadius: 9, shadowOffset: { width: 0, height: 3 }, elevation: 2 },
  resultTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  resultEyebrow: { color: "#C38F6C", fontSize: 9, fontWeight: "900", letterSpacing: 1.7 },
  resultTitle: { color: "#F7F7F7", fontSize: 25, fontWeight: "900", textTransform: "capitalize", marginTop: 3, letterSpacing: -0.6 },
  aiPill: { flexDirection: "row", alignItems: "center", gap: 5, borderRadius: 20, paddingHorizontal: 8, paddingVertical: 6 },
  aiOnline: { backgroundColor: "#1B1715" },
  aiLocal: { backgroundColor: "#1A1A1A" },
  aiDot: { width: 6, height: 6, borderRadius: 4 },
  aiDotOnline: { backgroundColor: "#C38F6C" },
  aiDotLocal: { backgroundColor: "#AEABA8" },
  aiPillText: { fontSize: 8, fontWeight: "900", letterSpacing: 0.5 },
  aiTextOnline: { color: "#C38F6C" },
  aiTextLocal: { color: "#AEABA8" },
  sourceText: { color: "#AEABA8", fontSize: 10 },
  summary: { color: "#F7F7F7", fontSize: 13, lineHeight: 19 },
  resultDivider: { height: 1, backgroundColor: "#2A2A2A" },
  guidanceTitle: { color: "#F7F7F7", fontSize: 14, fontWeight: "900", letterSpacing: -0.2 },
  instructionRow: { flexDirection: "row", alignItems: "flex-start", gap: 9 },
  stepNumber: { width: 27, height: 27, borderRadius: 9, backgroundColor: "#211412", alignItems: "center", justifyContent: "center" },
  stepNumberText: { color: "#C38F6C", fontSize: 11, fontWeight: "900" },
  instruction: { flex: 1, color: "#F7F7F7", fontSize: 13, lineHeight: 20, paddingTop: 2 },
  safetyNotice: { color: "#C38F6C", backgroundColor: "#1B1715", borderWidth: 1, borderColor: "#5B3733", borderRadius: 9, padding: 10, fontSize: 10, lineHeight: 16 },
  toolsRow: { flexDirection: "row", gap: 9 },
  toolButton: { flex: 1, minHeight: 58, backgroundColor: "#121212", borderRadius: 15, borderWidth: 1, borderColor: "#2C2C2C", paddingVertical: 9, alignItems: "center", justifyContent: "center", gap: 3 },
  toolButtonSelected: { backgroundColor: "#211412", borderColor: "#D13B2F" },
  toolEmoji: { fontSize: 17 },
  toolLabel: { color: "#AEABA8", fontSize: 10, fontWeight: "900" },
  toolLabelSelected: { color: "#F7F7F7" },
  mapCard: { backgroundColor: "#111111", borderWidth: 1, borderColor: "#2C2C2C", borderRadius: 19, padding: 12, gap: 9 },
  map: { width: "100%", height: 230, borderRadius: 11 },
  mapNote: { color: "#C38F6C", fontSize: 9, lineHeight: 14 },
  chatThread: { backgroundColor: "#111111", borderRadius: 19, borderWidth: 1, borderColor: "#2C2C2C", padding: 14, gap: 9 },
  chatHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  newIncidentButton: { borderWidth: 1, borderColor: "#3A302D", backgroundColor: "#1A1A1A", borderRadius: 9, paddingHorizontal: 10, paddingVertical: 7 },
  newIncidentText: { color: "#D13B2F", fontSize: 10, fontWeight: "900" },
  chatBubble: { maxWidth: "92%", padding: 11, borderRadius: 12 },
  chatUser: { alignSelf: "flex-end", backgroundColor: "#5B3733" },
  chatAssistant: { alignSelf: "flex-start", backgroundColor: "#1A1A1A" },
  chatBubbleText: { fontSize: 13, lineHeight: 20 },
  chatUserText: { color: "#F7F7F7" },
  chatAssistantText: { color: "#F7F7F7" },
  followUp: { color: "#F7F7F7", backgroundColor: "#1B1716", borderWidth: 1, borderColor: "#5B3733", padding: 12, borderRadius: 12, fontSize: 12, lineHeight: 18, overflow: "hidden" },
  facilityCard: { backgroundColor: "#111111", borderRadius: 15, borderWidth: 1, borderColor: "#2C2C2C", padding: 13, gap: 10 },
  facilityHint: { color: "#AEABA8", fontSize: 10, lineHeight: 15 },
  facilityRadiusSection: { gap: 6 },
  facilityFilterRow: { flexDirection: "row", flexWrap: "wrap", gap: 7 },
  facilityFilter: { backgroundColor: "#171717", borderWidth: 1, borderColor: "#303030", borderRadius: 18, paddingHorizontal: 11, paddingVertical: 7 },
  facilityFilterSelected: { backgroundColor: "#211412", borderColor: "#D13B2F" },
  facilityFilterText: { color: "#AEABA8", fontSize: 10, fontWeight: "800" },
  facilityFilterTextSelected: { color: "#F7F7F7" },
  facilityRow: { flexDirection: "row", alignItems: "center", borderTopWidth: 1, borderColor: "#2A2A2A", paddingTop: 10, gap: 9 },
  facilityCopy: { flex: 1, gap: 3 },
  facilityName: { color: "#F7F7F7", fontSize: 12, fontWeight: "900" },
  facilityMeta: { color: "#AEABA8", fontSize: 10, textTransform: "capitalize" },
  verifiedText: { color: "#C38F6C", fontSize: 9, fontWeight: "800" },
  unverifiedText: { color: "#AEABA8", fontSize: 9, fontWeight: "800" },
  callFacilityButton: { backgroundColor: "#211412", borderRadius: 9, paddingHorizontal: 11, paddingVertical: 9 },
  callFacilityText: { color: "#C38F6C", fontSize: 10, fontWeight: "900" },
  routeButton: { backgroundColor: "#1A1A1A", borderWidth: 1, borderColor: "#5B3733", borderRadius: 9, paddingHorizontal: 12, paddingVertical: 9 },
  routeButtonText: { color: "#C38F6C", fontSize: 10, fontWeight: "900" },
  routePreviewCard: { paddingTop: 11, borderTopWidth: 1, borderTopColor: "#2A2A2A", marginTop: 6, gap: 7 },
  routePreviewMetric: { color: "#F7F7F7", fontSize: 15, fontWeight: "900" },
  routeDirectionsButton: { backgroundColor: "#211412", borderWidth: 1, borderColor: "#5B3733", borderRadius: 10, padding: 12, alignItems: "center" },
  routeDirectionsText: { color: "#D13B2F", fontSize: 11, fontWeight: "900" },
  modalShade: { flex: 1, backgroundColor: "rgba(0,0,0,0.78)", justifyContent: "center", padding: 22 },
  weatherModal: { backgroundColor: "#111111", borderWidth: 1, borderColor: "#2C2C2C", borderRadius: 18, padding: 18, gap: 14 },
  weatherModalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  weatherTitle: { color: "#F7F7F7", fontSize: 18, fontWeight: "900" },
  weatherSub: { color: "#AEABA8", fontSize: 10, lineHeight: 15 },
  weatherClose: { width: 32, height: 32, borderRadius: 10, backgroundColor: "#222222", alignItems: "center", justifyContent: "center" },
  weatherCloseText: { color: "#F7F7F7", fontSize: 16 },
  weatherCondition: { color: "#AEABA8", fontSize: 13, fontWeight: "800", textAlign: "center" },
  weatherTemperature: { color: "#F7F7F7", fontSize: 42, fontWeight: "900", textAlign: "center" },
  weatherMetrics: { flexDirection: "row", gap: 8, justifyContent: "space-between" },
  weatherMetric: { flex: 1, backgroundColor: "#1A1A1A", borderRadius: 10, padding: 10, alignItems: "center", gap: 4 },
  weatherMetricValue: { color: "#C38F6C", fontSize: 13, fontWeight: "900" },
  weatherMetricLabel: { color: "#AEABA8", fontSize: 9 },
  weatherDisclaimer: { color: "#AEABA8", fontSize: 9, lineHeight: 14 },
  weatherDone: { backgroundColor: "#D13B2F", borderRadius: 10, padding: 12, alignItems: "center" },
  weatherDoneText: { color: "#F7F7F7", fontSize: 12, fontWeight: "900" },
  offlineCard: { backgroundColor: "#111111", borderRadius: 19, padding: 14, gap: 10, borderWidth: 1, borderColor: "#2C2C2C" },
  offlineHeader: { flexDirection: "row", alignItems: "center", gap: 10 },
  offlineIcon: { width: 38, height: 38, borderRadius: 11, backgroundColor: "#211412", alignItems: "center", justifyContent: "center" },
  offlineIconText: { color: "#C38F6C", fontSize: 22 },
  offlineCopy: { flex: 1, gap: 3 },
  offlineTitle: { color: "#F7F7F7", fontWeight: "900", fontSize: 13 },
  offlineSub: { color: "#AEABA8", fontSize: 10 },
  offlineButton: { backgroundColor: "#1A1A1A", borderWidth: 1, borderColor: "#3A302D", borderRadius: 10, padding: 12, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 8 },
  offlineButtonText: { color: "#F7F7F7", fontSize: 11, fontWeight: "900" },
  offlineButtonArrow: { color: "#D13B2F", fontSize: 16, fontWeight: "900" },
  offlineStatus: { color: "#AEABA8", fontSize: 10 },
  offlineWarning: { color: "#C38F6C", fontSize: 9, lineHeight: 14 },
  footer: { paddingTop: 3, gap: 5, alignItems: "center" },
  footerStatus: { color: "#F7F7F7", fontSize: 11, fontWeight: "800" },
  footerApi: { color: "#C38F6C", fontSize: 9, fontWeight: "800", textAlign: "center" },
  recheckButton: { paddingVertical: 7, paddingHorizontal: 12, backgroundColor: "#1A1A1A", borderRadius: 8 },
  recheckText: { color: "#C38F6C", fontSize: 10, fontWeight: "800" },
  diagnosticWarning: { color: "#F1B2A7", backgroundColor: "#241311", borderWidth: 1, borderColor: "#5B211B", borderRadius: 9, padding: 10, fontSize: 10, lineHeight: 16 },
  connectionBad: { backgroundColor: "#D13B2F" },
  connectionChecking: { backgroundColor: "#C38F6C" },
  disclaimer: { color: "#AEABA8", fontSize: 9, textAlign: "center", lineHeight: 14 },
});
