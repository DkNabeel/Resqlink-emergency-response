import React, { useEffect, useState } from "react";
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
import MapView, { Marker } from "react-native-maps";
import * as Location from "expo-location";
import "./src/background";
import { startBackgroundMonitoring, setBackgroundLanguage } from "./src/background";
import {
  getOfflineGuidance,
  getSystemStatus,
  isApiConfigured,
  sendEmergencyChat,
  getNearbyWeather,
  getNearbyFacilities,
  cacheNearbyFacilities,
  downloadOfflinePackage,
  type EmergencyResult,
  type NearbyFacility,
  type OfflinePackage,
  type WeatherSnapshot,
} from "./src/api";
import { getLatestOfflinePackage } from "./src/cache";

type Coordinates = { latitude: number; longitude: number };
type Language = "en" | "hi" | "kn";

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
  const [status, setStatus] = useState("Ready to help");
  const [locationStatus, setLocationStatus] = useState("Location has not been requested");
  const [backendConnection, setBackendConnection] = useState<"checking" | "connected" | "unreachable">("checking");
  const [backendAiConfigured, setBackendAiConfigured] = useState<boolean | null>(null);
  const [chatHistory, setChatHistory] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [weatherVisible, setWeatherVisible] = useState(false);
  const [weatherBusy, setWeatherBusy] = useState(false);
  const [weatherData, setWeatherData] = useState<WeatherSnapshot | null>(null);

  const copy = COPY[language];

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
    startBackgroundMonitoring()
      .then((result) => {
        if (active) setStatus(result.message);
      })
      .catch(() => {
        if (active) setStatus("Background monitoring could not be enabled. Foreground emergency assistance remains available.");
      });
    getLatestOfflinePackage()
      .then((cached) => {
        if (active && cached) setOfflinePackage(cached.payload);
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
    setCoordinates(point);
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
        catch { setLocationStatus("Sending report without current GPS coordinates"); }
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
          // Keep the urgent Groq reply fast; load OSM places separately.
          void getNearbyFacilities(point, 10).then(async (found) => {
            const candidates = found.items ?? [];
            setResult((current) => {
              if (!current || !current.in_scope) return current;
              const existing = current.nearby_facilities ?? [];
              const keys = new Set(existing.map((item) => [item.name, item.latitude, item.longitude].join("|")));
              const additional = candidates.filter((item) => !keys.has([item.name, item.latitude, item.longitude].join("|")));
              return { ...current, nearby_facilities: [...existing, ...additional] };
            });
            await cacheNearbyFacilities(candidates).catch(() => {});
          }).catch(() => {});
        }
        setChatHistory((current) => [
          ...current,
          { role: "user", content: submittedMessage },
          ...(response.reply ? [{ role: "assistant" as const, content: response.reply }] : []),
        ].slice(-10));
        setStatus("Emergency response received");
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
      const offlineReply = (fallback.guidance ?? []).join("\n");
      setResult({ ...fallback, reply: offlineReply, diagnostic_message: reason });
      setChatHistory((current) => [
        ...current,
        { role: "user", content: submittedMessage },
        { role: "assistant", content: offlineReply },
      ].slice(-10));
      setMessage("");
      setSelectedPrompt("");
      setStatus("Offline keyword guidance · AI and live data unavailable");
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

  async function openFacilityRoute(facility: NearbyFacility) {
    if (typeof facility.latitude !== "number" || typeof facility.longitude !== "number") {
      setStatus("This facility has no usable map coordinates");
      return;
    }
    const destination = facility.latitude + "," + facility.longitude;
    const origin = coordinates ? "&origin=" + coordinates.latitude + "," + coordinates.longitude : "";
    const url = "https://www.google.com/maps/dir/?api=1" + origin
      + "&destination=" + destination + "&travelmode=driving";
    try {
      await Linking.openURL(url);
    } catch {
      setStatus("Unable to open the map app. Check your internet connection.");
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
  const facilities: NearbyFacility[] = result?.nearby_facilities?.length
    ? result.nearby_facilities
    : packageFacilities;

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="dark-content" />
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

        <Pressable onPress={openWeather} style={styles.weatherPill}>
          <Text style={styles.weatherPillText}>☀  Local weather · temperature & humidity</Text>
          <Text style={styles.weatherPillArrow}>↗</Text>
        </Pressable>

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
        <View style={styles.quickGrid}>
          {QUICK_REPORTS.map((item) => (
            <Pressable
              key={item.label}
              onPress={() => { setMessage(item.messages[language]); setSelectedPrompt(item.label); setResult(null); }}
              style={[styles.quickCard, selectedPrompt === item.label && styles.quickSelected]}
            >
              <Text style={styles.quickEmoji}>{item.emoji}</Text>
              <Text style={[styles.quickLabel, selectedPrompt === item.label && styles.quickLabelSelected]}>{item.label}</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>{copy.report}</Text>
          <Text style={styles.sectionHint}>{message.length}/4000</Text>
        </View>
        <View style={styles.inputCard}>
          <TextInput
            value={message}
            onChangeText={(value) => { setMessage(value); setSelectedPrompt(""); }}
            placeholder={copy.placeholder}
            placeholderTextColor="#8793A2"
            multiline
            maxLength={4000}
            style={styles.input}
            textAlignVertical="top"
          />
          <View style={styles.inputFoot}><Text style={styles.inputHint}>Be clear. Mention injuries, hazards and nearby landmarks.</Text></View>
        </View>

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

        {coordinates ? (
          <View style={styles.mapCard}>
            <Text style={styles.sectionTitle}>Your current area</Text>
            <MapView
              style={styles.map}
              initialRegion={{
                latitude: coordinates.latitude,
                longitude: coordinates.longitude,
                latitudeDelta: 0.025,
                longitudeDelta: 0.025,
              }}
              region={{
                latitude: coordinates.latitude,
                longitude: coordinates.longitude,
                latitudeDelta: 0.025,
                longitudeDelta: 0.025,
              }}
              showsUserLocation
              showsMyLocationButton
            >
              <Marker coordinate={coordinates} title="Your location" pinColor="#147A6A" />
              {facilities.filter((item) => typeof item.latitude === "number" && typeof item.longitude === "number").map((item, index) => (
                <Marker
                  key={String(item.name ?? "facility") + "-" + index}
                  coordinate={{ latitude: item.latitude as number, longitude: item.longitude as number }}
                  title={item.name ?? "Emergency facility"}
                  description={(item.facility_type ?? "Facility").replaceAll("_", " ") + " · " + (item.verification_status ?? "unverified")}
                />
              ))}
            </MapView>
            <Text style={styles.mapNote}>Map routes are not verified against live disaster hazards. Follow official evacuation instructions.</Text>
          </View>
        ) : null}

        <Pressable onPress={handleEmergency} disabled={busy} style={({ pressed }) => [styles.analyzeButton, pressed && styles.pressed, busy && styles.disabled]}>
          {busy ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.analyzeIcon}>✦</Text>}
          <Text style={styles.analyzeText}>{busy ? "Analyzing..." : copy.analyze}</Text>
          {!busy && <Text style={styles.analyzeArrow}>→</Text>}
        </Pressable>
        <Text style={styles.secureNote}>Emergency-only AI chat · GPS context · Government alerts and nearby services</Text>

        {chatHistory.length > 0 ? (
          <View style={styles.chatThread}>
            <Text style={styles.sectionTitle}>Emergency conversation</Text>
            {chatHistory.map((item, index) => (
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
            {result.in_scope === false
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
            {result.nearby_alerts && result.nearby_alerts.length > 0 ? <Text style={styles.sourceText}>Confirmed location-matched government alerts: {result.nearby_alerts.length}</Text> : null}
            {result.unverified_alerts && result.unverified_alerts.length > 0 ? <Text style={styles.diagnosticWarning}>{result.unverified_alerts.length} government alert(s) could not be confirmed for your exact location. Review their official source before acting.</Text> : null}
            {result.weather_context && typeof result.weather_context === "object" ? <Text style={styles.sourceText}>Weather context: {String((result.weather_context as { status?: string }).status ?? "available")}</Text> : null}
          </View>
        ) : null}

        {facilities.length > 0 ? (
          <View style={styles.facilityCard}>
            <Text style={styles.sectionTitle}>Nearby emergency facilities</Text>
            <Text style={styles.facilityHint}>Verified records and community-mapped candidates are labelled separately.</Text>
            {facilities.slice(0, 12).map((facility, index) => (
              <View key={String(facility.name ?? "facility") + "-" + index} style={styles.facilityRow}>
                <View style={styles.facilityCopy}>
                  <Text style={styles.facilityName}>{facility.name ?? "Emergency facility"}</Text>
                  <Text style={styles.facilityMeta}>
                    {(facility.facility_type ?? "facility").replaceAll("_", " ")}
                    {typeof facility.distance_km === "number" ? " · " + facility.distance_km.toFixed(1) + " km" : ""}
                  </Text>
                  <Text style={facility.verification_status === "verified" ? styles.verifiedText : styles.unverifiedText}>
                    {facility.verification_status === "verified" ? "Verified project record" : "Unverified map candidate"}
                  </Text>
                </View>
                <Pressable onPress={() => openFacilityRoute(facility)} style={styles.routeButton}>
                  <Text style={styles.routeButtonText}>Route ↗</Text>
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}

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
          {offlinePackage ? <Text style={styles.offlineStatus}>Nearby facilities saved: {(offlinePackage.nearby_verified_facilities?.length ?? 0) + (offlinePackage.nearby_discovered_facilities?.length ?? 0)} · {offlinePackage.facility_discovery_status ?? "facility discovery not refreshed"}</Text> : null}
          <Text style={styles.offlineWarning}>Offline mode uses cached emergency facilities and guidance. Full offline map tiles and road-by-road routing are not included yet.</Text>
        </View>

        <View style={styles.footer}>
          <Text style={styles.footerStatus}>{status}</Text>
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
            {weatherBusy ? <ActivityIndicator color="#147A6A" size="large" /> : weatherData?.current ? (
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
  safe: { flex: 1, backgroundColor: "#F5F7FA" },
  container: { paddingHorizontal: 18, paddingTop: 12, paddingBottom: 44, gap: 17 },
  topBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 5 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  logo: { width: 42, height: 42, borderRadius: 13, backgroundColor: "#123B50", alignItems: "center", justifyContent: "center" },
  logoText: { color: "#FFFFFF", fontWeight: "900", fontSize: 23 },
  brand: { color: "#123344", fontSize: 21, fontWeight: "900", letterSpacing: -0.5 },
  brandSub: { color: "#758494", fontSize: 9, fontWeight: "800", letterSpacing: 1.5, marginTop: 1 },
  weatherPill: { backgroundColor: "#EAF4F5", borderWidth: 1, borderColor: "#D5E7E9", borderRadius: 12, paddingHorizontal: 13, paddingVertical: 11, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  weatherPillText: { color: "#1C6870", fontSize: 11, fontWeight: "800" },
  weatherPillArrow: { color: "#1C6870", fontSize: 15, fontWeight: "900" },
  readyPill: { backgroundColor: "#E7F5EF", borderRadius: 30, paddingHorizontal: 11, paddingVertical: 7, flexDirection: "row", alignItems: "center", gap: 6 },
  readyDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: "#1C9A65" },
  readyText: { color: "#16734E", fontSize: 10, fontWeight: "900", letterSpacing: 0.8 },
  hero: { gap: 6, paddingVertical: 4 },
  eyebrow: { color: "#16816D", fontSize: 10, fontWeight: "900", letterSpacing: 1.8 },
  heroTitle: { color: "#132F40", fontSize: 31, fontWeight: "900", letterSpacing: -1.1 },
  heroSub: { color: "#68798A", fontSize: 13, lineHeight: 20, maxWidth: 500 },
  sosCard: { backgroundColor: "#FFF1ED", borderRadius: 16, borderWidth: 1, borderColor: "#FFD7CA", padding: 14, flexDirection: "row", alignItems: "center", gap: 12 },
  sosIcon: { width: 46, height: 46, backgroundColor: "#D9432F", borderRadius: 13, alignItems: "center", justifyContent: "center" },
  sosIconText: { color: "#FFFFFF", fontWeight: "900", fontSize: 17 },
  sosCopy: { flex: 1, gap: 3 },
  sosTitle: { color: "#862B20", fontSize: 14, fontWeight: "900" },
  sosSub: { color: "#A15B4F", fontSize: 11 },
  sosArrow: { color: "#C94A38", fontSize: 22, fontWeight: "700" },
  sectionHeader: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", marginBottom: -9 },
  sectionTitle: { color: "#1B3547", fontSize: 14, fontWeight: "900" },
  sectionHint: { color: "#8A98A6", fontSize: 10, fontWeight: "600" },
  languageRow: { flexDirection: "row", gap: 8 },
  languageButton: { flex: 1, paddingVertical: 12, borderRadius: 11, backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#E1E7ED", alignItems: "center" },
  languageSelected: { backgroundColor: "#123B50", borderColor: "#123B50" },
  languageText: { color: "#647687", fontSize: 12, fontWeight: "800" },
  languageTextSelected: { color: "#FFFFFF" },
  quickGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  quickCard: { width: "31.5%", minHeight: 78, backgroundColor: "#FFFFFF", borderRadius: 13, borderWidth: 1, borderColor: "#E2E8EE", alignItems: "center", justifyContent: "center", gap: 5, padding: 8 },
  quickSelected: { borderColor: "#16816D", backgroundColor: "#EAF6F3" },
  quickEmoji: { fontSize: 22 },
  quickLabel: { color: "#526779", fontSize: 11, fontWeight: "800" },
  quickLabelSelected: { color: "#14715F" },
  inputCard: { borderWidth: 1, borderColor: "#DFE6EC", backgroundColor: "#FFFFFF", borderRadius: 15, padding: 12, gap: 8 },
  input: { minHeight: 112, fontSize: 14, color: "#173446", lineHeight: 21, padding: 3 },
  inputFoot: { borderTopWidth: 1, borderColor: "#F0F2F4", paddingTop: 8 },
  inputHint: { color: "#92A0AD", fontSize: 10 },
  locationCard: { backgroundColor: "#FFFFFF", borderRadius: 14, borderWidth: 1, borderColor: "#E2E8EE", padding: 12, flexDirection: "row", alignItems: "center", gap: 10 },
  locationIcon: { width: 36, height: 36, borderRadius: 11, backgroundColor: "#EAF4F5", alignItems: "center", justifyContent: "center" },
  locationIconText: { color: "#157B70", fontSize: 23 },
  locationCopy: { flex: 1, gap: 3 },
  locationTitle: { color: "#243E50", fontSize: 12, fontWeight: "900" },
  locationSub: { color: "#83919E", fontSize: 10 },
  locationAction: { backgroundColor: "#E8F4F1", borderRadius: 9, paddingHorizontal: 12, paddingVertical: 9 },
  locationActionText: { color: "#14715F", fontSize: 10, fontWeight: "900" },
  analyzeButton: { backgroundColor: "#147A6A", borderRadius: 14, paddingVertical: 16, paddingHorizontal: 16, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, shadowColor: "#0D6255", shadowOpacity: 0.14, shadowRadius: 9, shadowOffset: { width: 0, height: 4 }, elevation: 3 },
  pressed: { opacity: 0.82 },
  disabled: { opacity: 0.55 },
  analyzeIcon: { color: "#B8F2D9", fontSize: 17, fontWeight: "900" },
  analyzeText: { color: "#FFFFFF", fontSize: 14, fontWeight: "900", flex: 1, textAlign: "center" },
  analyzeArrow: { color: "#FFFFFF", fontSize: 20, fontWeight: "800" },
  secureNote: { textAlign: "center", color: "#91A0AD", fontSize: 9, marginTop: -10 },
  resultCard: { backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#B9DCD5", borderRadius: 16, padding: 15, gap: 11 },
  resultTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  resultEyebrow: { color: "#16816D", fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  resultTitle: { color: "#173849", fontSize: 23, fontWeight: "900", textTransform: "capitalize", marginTop: 3 },
  aiPill: { flexDirection: "row", alignItems: "center", gap: 5, borderRadius: 20, paddingHorizontal: 8, paddingVertical: 6 },
  aiOnline: { backgroundColor: "#E5F5EE" },
  aiLocal: { backgroundColor: "#EDF1F5" },
  aiDot: { width: 6, height: 6, borderRadius: 4 },
  aiDotOnline: { backgroundColor: "#168653" },
  aiDotLocal: { backgroundColor: "#768493" },
  aiPillText: { fontSize: 8, fontWeight: "900", letterSpacing: 0.5 },
  aiTextOnline: { color: "#16734E" },
  aiTextLocal: { color: "#647687" },
  sourceText: { color: "#8996A3", fontSize: 10 },
  summary: { color: "#40596A", fontSize: 13, lineHeight: 19 },
  resultDivider: { height: 1, backgroundColor: "#EAF0F0" },
  guidanceTitle: { color: "#1B3547", fontSize: 13, fontWeight: "900" },
  instructionRow: { flexDirection: "row", alignItems: "flex-start", gap: 9 },
  stepNumber: { width: 22, height: 22, borderRadius: 7, backgroundColor: "#E7F4F1", alignItems: "center", justifyContent: "center" },
  stepNumberText: { color: "#14715F", fontSize: 10, fontWeight: "900" },
  instruction: { flex: 1, color: "#435A69", fontSize: 12, lineHeight: 19, paddingTop: 1 },
  safetyNotice: { color: "#986A20", backgroundColor: "#FFF8E8", borderRadius: 9, padding: 10, fontSize: 10, lineHeight: 16 },
  mapCard: { backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#E2E8EE", borderRadius: 15, padding: 12, gap: 9 },
  map: { width: "100%", height: 230, borderRadius: 11 },
  mapNote: { color: "#8C734F", fontSize: 9, lineHeight: 14 },
  chatThread: { backgroundColor: "#FFFFFF", borderRadius: 15, borderWidth: 1, borderColor: "#E2E8EE", padding: 12, gap: 8 },
  chatBubble: { maxWidth: "92%", padding: 11, borderRadius: 12 },
  chatUser: { alignSelf: "flex-end", backgroundColor: "#147A6A" },
  chatAssistant: { alignSelf: "flex-start", backgroundColor: "#EEF3F6" },
  chatBubbleText: { fontSize: 12, lineHeight: 18 },
  chatUserText: { color: "#FFFFFF" },
  chatAssistantText: { color: "#2D4656" },
  followUp: { color: "#14715F", backgroundColor: "#EAF6F3", padding: 10, borderRadius: 9, fontSize: 11, lineHeight: 16 },
  facilityCard: { backgroundColor: "#FFFFFF", borderRadius: 15, borderWidth: 1, borderColor: "#E2E8EE", padding: 13, gap: 10 },
  facilityHint: { color: "#8996A3", fontSize: 10, lineHeight: 15 },
  facilityRow: { flexDirection: "row", alignItems: "center", borderTopWidth: 1, borderColor: "#EDF1F3", paddingTop: 10, gap: 9 },
  facilityCopy: { flex: 1, gap: 3 },
  facilityName: { color: "#243E50", fontSize: 12, fontWeight: "900" },
  facilityMeta: { color: "#758696", fontSize: 10, textTransform: "capitalize" },
  verifiedText: { color: "#168653", fontSize: 9, fontWeight: "800" },
  unverifiedText: { color: "#A16B1C", fontSize: 9, fontWeight: "800" },
  routeButton: { backgroundColor: "#EAF4F1", borderRadius: 9, paddingHorizontal: 12, paddingVertical: 9 },
  routeButtonText: { color: "#14715F", fontSize: 10, fontWeight: "900" },
  modalShade: { flex: 1, backgroundColor: "rgba(10,25,35,0.45)", justifyContent: "center", padding: 22 },
  weatherModal: { backgroundColor: "#FFFFFF", borderRadius: 18, padding: 18, gap: 14 },
  weatherModalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  weatherTitle: { color: "#173849", fontSize: 18, fontWeight: "900" },
  weatherSub: { color: "#82919E", fontSize: 10, lineHeight: 15 },
  weatherClose: { width: 32, height: 32, borderRadius: 10, backgroundColor: "#F0F3F5", alignItems: "center", justifyContent: "center" },
  weatherCloseText: { color: "#536777", fontSize: 16 },
  weatherCondition: { color: "#556B7B", fontSize: 13, fontWeight: "800", textAlign: "center" },
  weatherTemperature: { color: "#173849", fontSize: 42, fontWeight: "900", textAlign: "center" },
  weatherMetrics: { flexDirection: "row", gap: 8, justifyContent: "space-between" },
  weatherMetric: { flex: 1, backgroundColor: "#F2F6F7", borderRadius: 10, padding: 10, alignItems: "center", gap: 4 },
  weatherMetricValue: { color: "#1C6870", fontSize: 13, fontWeight: "900" },
  weatherMetricLabel: { color: "#80909C", fontSize: 9 },
  weatherDisclaimer: { color: "#8C734F", fontSize: 9, lineHeight: 14 },
  weatherDone: { backgroundColor: "#147A6A", borderRadius: 10, padding: 12, alignItems: "center" },
  weatherDoneText: { color: "#FFFFFF", fontSize: 12, fontWeight: "900" },
  offlineCard: { backgroundColor: "#EDF3F7", borderRadius: 15, padding: 14, gap: 10, borderWidth: 1, borderColor: "#DDE6EC" },
  offlineHeader: { flexDirection: "row", alignItems: "center", gap: 10 },
  offlineIcon: { width: 38, height: 38, borderRadius: 11, backgroundColor: "#DCE9ED", alignItems: "center", justifyContent: "center" },
  offlineIconText: { color: "#285B68", fontSize: 22 },
  offlineCopy: { flex: 1, gap: 3 },
  offlineTitle: { color: "#234455", fontWeight: "900", fontSize: 13 },
  offlineSub: { color: "#7A8D99", fontSize: 10 },
  offlineButton: { backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#CCD9E0", borderRadius: 10, padding: 12, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 8 },
  offlineButtonText: { color: "#31596A", fontSize: 11, fontWeight: "900" },
  offlineButtonArrow: { color: "#147A6A", fontSize: 16, fontWeight: "900" },
  offlineStatus: { color: "#667B89", fontSize: 10 },
  offlineWarning: { color: "#8A7450", fontSize: 9, lineHeight: 14 },
  footer: { paddingTop: 3, gap: 5, alignItems: "center" },
  footerStatus: { color: "#496273", fontSize: 11, fontWeight: "800" },
  footerApi: { color: "#16816D", fontSize: 9, fontWeight: "800", textAlign: "center" },
  recheckButton: { paddingVertical: 7, paddingHorizontal: 12, backgroundColor: "#E8F4F1", borderRadius: 8 },
  recheckText: { color: "#14715F", fontSize: 10, fontWeight: "800" },
  diagnosticWarning: { color: "#9B3E2D", backgroundColor: "#FFF0EB", borderRadius: 9, padding: 10, fontSize: 10, lineHeight: 16 },
  connectionBad: { backgroundColor: "#C24135" },
  connectionChecking: { backgroundColor: "#D69E2E" },
  disclaimer: { color: "#9AA5AE", fontSize: 9, textAlign: "center", lineHeight: 14 },
});
