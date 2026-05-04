/**
 * Backend API client for AI Visibility Grader.
 * All shapes mirror the Pydantic models in backend/models.py.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Product {
  asin: string;
  brand: string;
  title: string;
  category: string;
  bullets: string[];
  image_url: string | null;
}

export interface ModelMentions {
  gpt4: boolean;
  claude: boolean;
  gemini: boolean;
}

export interface Score {
  overall: number;
  gpt4: number;
  claude: number;
  gemini: number;
  top_competitors: Competitor[];
}

export interface QuerySummary {
  query: string;
  mentions: ModelMentions;
  winners: string[];
  your_position: number | null;
}

export interface Competitor {
  brand: string;
  mention_count: number;
}

export interface Recommendation {
  title: string;
  description: string;
  priority: "high" | "medium" | "low";
}

export interface DiagnoseResponse {
  product: Product;
  score: Score;
  queries: QuerySummary[];
  top_competitors: Competitor[];
  recommendations: Recommendation[];
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export class APIError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "APIError";
  }
}

export interface DiagnoseRequest {
  asin?: string;   // optional -- omit when submitting brand+title directly
  brand?: string;
  title?: string;
  category?: string;
}

export async function runDiagnostic(req: DiagnoseRequest): Promise<DiagnoseResponse> {
  const res = await fetch(`${API_URL}/diagnose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch { /* ignore */ }
    throw new APIError(res.status, detail);
  }

  return res.json() as Promise<DiagnoseResponse>;
}

export { API_URL };
