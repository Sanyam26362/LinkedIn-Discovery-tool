import type {
  ApiConfigResponse,
  DiscoveryRequestPayload,
  PipelineRunResult,
  ProgressEvent,
  RankedInfluencer,
  SimilarProfile,
} from "@/types/discovery";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

export async function fetchConfig(): Promise<ApiConfigResponse> {
  const res = await fetch(`${API_BASE_URL}/api/config`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Config request failed (${res.status})`);
  }
  return res.json();
}

export async function fetchLatestResult(): Promise<PipelineRunResult | null> {
  const res = await fetch(`${API_BASE_URL}/api/latest`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Latest result request failed (${res.status})`);
  }
  const data = (await res.json()) as { result: PipelineRunResult | null };
  return data.result;
}

export async function runDiscoveryStream(
  payload: DiscoveryRequestPayload,
  onProgress: (ev: ProgressEvent) => void
): Promise<PipelineRunResult> {
  const res = await fetch(`${API_BASE_URL}/api/discover/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok || !res.body) {
    const errText = await res.text().catch(() => "");
    throw new Error(errText || `Discovery failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: PipelineRunResult | null = null;

  const processBlock = (block: string) => {
    const lines = block.split(/\r?\n/);
    let eventName = "message";
    const dataParts: string[] = [];

    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataParts.push(line.slice(5).trimStart());
      }
    }

    if (dataParts.length === 0) return;
    const rawJson = dataParts.join("\n");
    const parsed = JSON.parse(rawJson);

    if (eventName === "progress") {
      onProgress(parsed as ProgressEvent);
    } else if (eventName === "complete") {
      finalResult = parsed as PipelineRunResult;
    } else if (eventName === "error") {
      throw new Error(parsed.detail || "Pipeline execution failed.");
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split(/\r?\n\r?\n/);
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      if (chunk.trim()) {
        processBlock(chunk);
      }
    }
  }

  if (buffer.trim()) {
    processBlock(buffer);
  }

  if (!finalResult) {
    throw new Error("Discovery stream closed without returning results.");
  }

  return finalResult;
}

export async function fetchSimilarProfiles(params: {
  phrase: string;
  seed_influencers: RankedInfluencer[];
  exclude_urls: string[];
  limit?: number;
  use_cache: boolean;
  serper_api_key?: string;
  gemini_api_key?: string;
}): Promise<{ similar_profiles: SimilarProfile[]; warnings: string[] }> {
  const res = await fetch(`${API_BASE_URL}/api/similar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Similar profiles search failed (${res.status})`);
  }
  return {
    similar_profiles: (data.similar_profiles ?? []) as SimilarProfile[],
    warnings: (data.warnings ?? []) as string[],
  };
}

export async function downloadExport(
  format: "csv" | "json",
  result: PipelineRunResult
): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/export/${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(result),
  });
  if (!res.ok) {
    throw new Error(`Export failed (${res.status})`);
  }
  const blob = await res.blob();
  const slug =
    result.search_phrase
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "results";

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${slug}_results.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
