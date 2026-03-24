import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();
  let res: Response;
  try {
    res = await fetch(`${BACKEND}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    const msg = String(err).includes("ECONNREFUSED")
      ? `Backend unreachable at ${BACKEND} — is the backend server running?`
      : `Failed to reach backend: ${err}`;
    return NextResponse.json({ detail: msg }, { status: 503 });
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    // Surface the backend's error message (detail, error, or message field)
    const detail =
      data?.detail ??
      data?.error ??
      data?.message ??
      `Backend error ${res.status}: ${res.statusText}`;
    return NextResponse.json({ detail }, { status: res.status });
  }

  return NextResponse.json(data, { status: res.status });
}
