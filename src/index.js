import { DurableObject } from "cloudflare:workers";

const PORT = 8000;
const INACTIVITY_TIMEOUT_MS = 30 * 60 * 1000;

export class ResQLinkBackend extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.resqlinkEnv = env;

    if (ctx.container.running) {
      void ctx.blockConcurrencyWhile(() =>
        ctx.container.setInactivityTimeout(INACTIVITY_TIMEOUT_MS)
      );
    }
  }

  async fetch(request) {
    this.starting ??= this.startAndWaitForPort().finally(() => {
      this.starting = undefined;
    });
    await this.starting;

    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "container";

    const forwarded = new Request(url, request);
    forwarded.headers.delete("host");

    return this.ctx.container.getTcpPort(PORT).fetch(forwarded);
  }

  async startAndWaitForPort() {
    const container = this.ctx.container;

    if (!container.running) {
      const env = this.resqlinkEnv;
      container.start({
        image: container.images.base,
        instance: "lite",
        enableInternet: true,
        env: {
          PORT: String(PORT),
          AI_ENABLED: env.AI_ENABLED ?? "true",
          GROQ_API_KEY: env.GROQ_API_KEY ?? "",
          GROQ_MODEL: env.GROQ_MODEL ?? "qwen/qwen3.8-27b",
          GROQ_FALLBACK_MODEL: env.GROQ_FALLBACK_MODEL ?? "openai/gpt-oss-20b",
          GROQ_REQUEST_TIMEOUT_SECONDS: env.GROQ_REQUEST_TIMEOUT_SECONDS ?? "14",
          AI_TOTAL_TIMEOUT_SECONDS: env.AI_TOTAL_TIMEOUT_SECONDS ?? "30",
          SACHET_FEED_URL: env.SACHET_FEED_URL ?? "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml",
          SACHET_SYNC_ENABLED: env.SACHET_SYNC_ENABLED ?? "true",
          SACHET_REFRESH_SECONDS: env.SACHET_REFRESH_SECONDS ?? "300",
          IP_GEOLOCATION_ENABLED: env.IP_GEOLOCATION_ENABLED ?? "false",
          IP_GEOLOCATION_URL_TEMPLATE: env.IP_GEOLOCATION_URL_TEMPLATE ?? "https://ipapi.co/{ip}/json/",
          FACILITY_ADMIN_TOKEN: env.FACILITY_ADMIN_TOKEN ?? "",
          WEATHER_CACHE_TTL_SECONDS: env.WEATHER_CACHE_TTL_SECONDS ?? "600",
          OPENROUTESERVICE_API_KEY: env.OPENROUTESERVICE_API_KEY ?? "",
          LOG_LEVEL: env.LOG_LEVEL ?? "INFO"
        }
      });
    }

    await container.setInactivityTimeout(INACTIVITY_TIMEOUT_MS);

    const port = container.getTcpPort(PORT);
    let lastError;
    for (let attempt = 0; attempt < 100; attempt++) {
      try {
        const response = await port.fetch("http://container/health", {
          signal: AbortSignal.timeout(1000)
        });
        await response.body?.cancel();
        if (response.ok) return;
        lastError = new Error(`Backend health check returned HTTP ${response.status}`);
      } catch (error) {
        lastError = error;
      }
      await scheduler.wait(200);
    }

    throw new Error("ResQLink backend did not become ready on port 8000", {
      cause: lastError
    });
  }
}

export default {
  fetch(request, env) {
    return env.RESQLINK_BACKEND.getByName("resqlink-api").fetch(request);
  }
};
