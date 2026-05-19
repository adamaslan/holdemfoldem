import { NextRequest, NextResponse } from "next/server";

const COUNCIL_URL = process.env.COUNCIL_URL ?? "http://localhost:3001";

export async function POST(req: NextRequest) {
  const body = await req.json();
  let res: Response;
  try {
    res = await fetch(`${COUNCIL_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    const msg = String(err).includes("ECONNREFUSED")
      ? `AI Council unreachable at ${COUNCIL_URL} — is ai-text-opt-1024 running on :3001?`
      : `Failed to reach AI Council: ${err}`;
    return NextResponse.json({ detail: msg }, { status: 503 });
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const detail =
      data?.error ??
      data?.detail ??
      data?.message ??
      `Council error ${res.status}: ${res.statusText}`;
    return NextResponse.json({ detail }, { status: res.status });
  }

  return NextResponse.json(data, { status: 200 });
}
