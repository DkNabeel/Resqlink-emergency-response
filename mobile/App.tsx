import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import * as Location from "expo-location";
import {
  getOfflineGuidance,
  isApiConfigured,
  sendEmergency,
  downloadOfflinePackage,
  type EmergencyResult,
  type OfflinePackage,
} from "./src/api";
import { getLatestOfflinePackage } from "./src/cache";

type Coordinates = { latitude: number; longitude: number };

const LANGUAGES = ["en", "hi", "kn"] as const;
const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  hi: "हिन्दी",
  kn: "ಕನ್ನಡ",
};

export default function App() {
  const [language, setLanguage] = useState<(typeof LANGUAGES)[number]>("en");
  const [message, setMessage] = useState("");
  const [coordinates, setCoordinates] = useState<Coordinates | null>(null);
  const [offlinePackage, setOfflinePackage] = useState<OfflinePackage | null>(null);
  const [result, setResult] = useState<EmergencyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [locationStatus, setLocationStatus] = useState("Location not requested");

  useEffect(() => {
    let active = true;
    getLatestOfflinePackage()
      .then((cached) => {
        if (active && cached) {
          setOfflinePackage(cached.payload);
          setStatus("Saved emergency package loaded from this device");
        }
      })
      .catch(() => {
        if (active) setStatus("Offline package has not been downloaded yet");
      });
    return () => {
      active = false;
    };
  }, []);

  async function obtainLocation(): Promise<Coordinates> {
    setLocationStatus("Requesting foreground location permission...");
    const permission = await Location.requestForegroundPermissionsAsync();
    if (permission.status !== "granted") {
      setLocationStatus("Location permission denied. Enable it in phone settings or use a manually entered location in the API.");
      throw new Error("Location permission was not granted.");
    }
    const position = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    const point = {
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
    };
    setCoordinates(point);
    setLocationStatus(
      "Location received (accuracy about " +
        Math.round(position.coords.accuracy ?? 0) +
        " m).",
    );
    return point;
  }

  async function handleLocation() {
    setBusy(true);
    try {
      await obtainLocation();
      setStatus("GPS location available");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to read location");
    } finally {
      setBusy(false);
    }
  }

  async function handlePackageDownload() {
    setBusy(true);
    try {
      const point = coordinates ?? (await obtainLocation());
      const response = await downloadOfflinePackage(point, language);
      setOfflinePackage(response.payload);
      setStatus(
        response.cacheStatus === "not_modified"
          ? "Offline package unchanged. Existing SQLite copy retained."
          : "Emergency package downloaded and saved to device SQLite.",
      );
    } catch (error) {
      const cached = await getLatestOfflinePackage().catch(() => null);
      if (cached) {
        setOfflinePackage(cached.payload);
        setStatus(
          "Network unavailable. Using saved package from " +
            cached.storedAt +
            ". It may be out of date.",
        );
      } else {
        setStatus(error instanceof Error ? error.message : "Package download failed");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleEmergency() {
    if (!message.trim()) {
      setStatus("Describe the emergency first.");
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const point = coordinates ?? (await obtainLocation());
      const response = await sendEmergency({
        message: message.trim(),
        language,
        latitude: point.latitude,
        longitude: point.longitude,
        radius_km: 10,
        include_weather: false,
        use_gemini: true,
      });
      setResult(response);
      setStatus("Emergency analysis received from backend.");
    } catch (error) {
      const cached = offlinePackage ?? (await getLatestOfflinePackage().then((x) => x?.payload ?? null).catch(() => null));
      setResult(getOfflineGuidance(message, language, cached));
      setStatus(
        "Backend unavailable. Showing saved local guidance only. Call 112 for emergency response.",
      );
    } finally {
      setBusy(false);
    }
  }

  function cycleLanguage() {
    const index = LANGUAGES.indexOf(language);
    setLanguage(LANGUAGES[(index + 1) % LANGUAGES.length]);
    setResult(null);
  }

  const instructions = result?.guidance ?? [];
  const contact = offlinePackage?.emergency_contact?.number ?? "112";

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.header}>
          <Text style={styles.brand}>ResQLink</Text>
          <Text style={styles.subtitle}>Multilingual emergency assistance</Text>
        </View>

        <View style={styles.emergencyCard}>
          <Text style={styles.emergencyTitle}>Emergency number</Text>
          <Text style={styles.emergencyNumber}>{contact}</Text>
          <Text style={styles.small}>
            India Emergency Response Support System. Use 112 for urgent help.
          </Text>
        </View>

        <View style={styles.row}>
          <View style={styles.flex}>
            <Text style={styles.sectionTitle}>Language</Text>
            <Text style={styles.body}>{LANGUAGE_NAMES[language]}</Text>
          </View>
          <ActionButton title="Change" onPress={cycleLanguage} disabled={busy} />
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Your location</Text>
          <Text style={styles.body}>{locationStatus}</Text>
          {coordinates ? (
            <Text style={styles.small}>
              {coordinates.latitude.toFixed(5)}, {coordinates.longitude.toFixed(5)}
            </Text>
          ) : null}
          <ActionButton
            title="Get GPS location"
            onPress={handleLocation}
            disabled={busy}
          />
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Describe the emergency</Text>
          <TextInput
            value={message}
            onChangeText={setMessage}
            placeholder="Example: There is smoke and fire in my building"
            placeholderTextColor="#8A97A8"
            multiline
            maxLength={4000}
            style={styles.input}
            textAlignVertical="top"
          />
          <ActionButton
            title="Get emergency guidance"
            onPress={handleEmergency}
            disabled={busy}
            primary
          />
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Offline emergency package</Text>
          <Text style={styles.body}>
            Save emergency guides, 112 and the verified facility/alert snapshot on this phone.
          </Text>
          <ActionButton
            title="Download / refresh offline package"
            onPress={handlePackageDownload}
            disabled={busy}
          />
          <Text style={styles.small}>
            {offlinePackage
              ? "Saved package: " + offlinePackage.generated_at
              : "No package saved yet."}
          </Text>
          <Text style={styles.warning}>
            Map tiles and live alert updates are not included. Refresh when internet is available.
          </Text>
        </View>

        {busy ? (
          <View style={styles.loading}>
            <ActivityIndicator size="small" color="#175CD3" />
            <Text style={styles.body}>Working...</Text>
          </View>
        ) : null}

        {result ? (
          <View style={styles.resultCard}>
            <Text style={styles.sectionTitle}>Emergency response</Text>
            <Text style={styles.resultType}>
              {String(result.emergency_type ?? "unknown").replaceAll("_", " ").toUpperCase()}
            </Text>
            <Text style={styles.body}>
              Source: {result.status === "offline_guidance_only" ? "Saved offline guidance" : "Backend"}
            </Text>
            {instructions.map((instruction, index) => (
              <Text style={styles.instruction} key={String(index)}>
                {index + 1}. {instruction}
              </Text>
            ))}
            <Text style={styles.warning}>
              {result.safety_notice ??
                "General guidance only. Follow official emergency responders."}
            </Text>
            {result.gemini_status ? (
              <Text style={styles.small}>Gemini: {String(result.gemini_status)}</Text>
            ) : null}
          </View>
        ) : null}

        <View style={styles.footer}>
          <Text style={styles.small}>{status}</Text>
          <Text style={styles.small}>
            {isApiConfigured()
              ? "Backend URL configured"
              : "Set EXPO_PUBLIC_API_BASE_URL in mobile/.env"}
          </Text>
          <Text style={styles.small}>
            ResQLink is a prototype. Do not treat it as a substitute for government alerts or emergency responders.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function ActionButton({
  title,
  onPress,
  disabled,
  primary = false,
}: {
  title: string;
  onPress: () => void;
  disabled: boolean;
  primary?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={[
        styles.button,
        primary ? styles.primaryButton : styles.secondaryButton,
        disabled ? styles.disabledButton : null,
      ]}
    >
      <Text style={primary ? styles.primaryButtonText : styles.secondaryButtonText}>
        {title}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F3F6FB" },
  container: { padding: 18, gap: 14, paddingBottom: 40 },
  header: { paddingVertical: 8 },
  brand: { fontSize: 30, fontWeight: "800", color: "#102A43" },
  subtitle: { fontSize: 14, color: "#526477", marginTop: 3 },
  emergencyCard: {
    backgroundColor: "#FFF0F0",
    borderColor: "#F3B4B4",
    borderWidth: 1,
    padding: 16,
    borderRadius: 14,
  },
  emergencyTitle: { fontSize: 14, fontWeight: "700", color: "#8D1B1B" },
  emergencyNumber: { fontSize: 34, fontWeight: "900", color: "#B42318", marginVertical: 3 },
  small: { color: "#64748B", fontSize: 12, lineHeight: 18, marginTop: 5 },
  card: {
    backgroundColor: "#FFFFFF",
    borderColor: "#E0E7EF",
    borderWidth: 1,
    borderRadius: 14,
    padding: 15,
    gap: 9,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  flex: { flex: 1 },
  sectionTitle: { color: "#16324F", fontSize: 16, fontWeight: "800" },
  body: { color: "#40566D", fontSize: 13, lineHeight: 19 },
  input: {
    minHeight: 100,
    borderColor: "#CBD5E1",
    borderWidth: 1,
    borderRadius: 10,
    padding: 11,
    fontSize: 14,
    color: "#172B4D",
    backgroundColor: "#FBFDFF",
  },
  button: {
    paddingVertical: 12,
    paddingHorizontal: 15,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 4,
  },
  primaryButton: { backgroundColor: "#175CD3" },
  secondaryButton: { backgroundColor: "#EAF1FB", borderWidth: 1, borderColor: "#C9D9F0" },
  primaryButtonText: { color: "#FFFFFF", fontWeight: "700", fontSize: 14 },
  secondaryButtonText: { color: "#174A8B", fontWeight: "700", fontSize: 14 },
  disabledButton: { opacity: 0.5 },
  warning: { color: "#805B10", fontSize: 12, lineHeight: 18, marginTop: 5 },
  resultCard: {
    backgroundColor: "#FFFFFF",
    borderColor: "#A8C7FA",
    borderWidth: 1,
    padding: 15,
    borderRadius: 14,
    gap: 9,
  },
  resultType: { fontSize: 20, color: "#174A8B", fontWeight: "900" },
  instruction: { color: "#243B53", fontSize: 14, lineHeight: 21 },
  loading: { flexDirection: "row", gap: 10, alignItems: "center", justifyContent: "center" },
  footer: { gap: 3, paddingTop: 8 },
});
