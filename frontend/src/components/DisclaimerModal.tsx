"use client";
import { useEffect, useState } from "react";
import {
  DISCLAIMER_TEXT,
  DISCLAIMER_VERSION,
  DISCLAIMER_LAST_UPDATED,
  hasAcknowledged,
  markAcknowledged,
} from "@/lib/disclaimer";

export default function DisclaimerModal() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!hasAcknowledged()) setOpen(true);
  }, []);

  function accept() {
    markAcknowledged();
    setOpen(false);
  }

  if (!open) return null;

  // Split text into paragraphs for rendering
  const paragraphs = DISCLAIMER_TEXT.split("\n\n").filter(Boolean);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="disclaimer-title"
    >
      <div className="w-full max-w-2xl rounded-2xl border border-yellow-700/50 bg-gray-950 shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-gray-800 shrink-0">
          <div className="flex items-center gap-3 mb-1">
            <span className="text-yellow-400 text-xl">⚠</span>
            <h2 id="disclaimer-title" className="text-white font-black text-lg tracking-tight">
              Important Disclaimer
            </h2>
          </div>
          <p className="text-gray-500 text-xs">
            Hold Em / Fold Em · version {DISCLAIMER_VERSION} · {DISCLAIMER_LAST_UPDATED}
          </p>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto px-6 py-4 flex-1 space-y-3">
          {paragraphs.map((para, i) => {
            // Bold the first sentence (up to the first period) if it's short
            const dotIdx = para.indexOf(". ");
            const hasLeadLabel = dotIdx > 0 && dotIdx < 60;
            return (
              <p key={i} className="text-gray-400 text-sm leading-relaxed">
                {hasLeadLabel ? (
                  <>
                    <span className="text-white font-semibold">{para.slice(0, dotIdx + 1)}</span>
                    {para.slice(dotIdx + 1)}
                  </>
                ) : (
                  para
                )}
              </p>
            );
          })}
        </div>

        {/* Footer CTA */}
        <div className="px-6 pb-6 pt-4 border-t border-gray-800 shrink-0">
          <button
            onClick={accept}
            className="w-full rounded-xl bg-yellow-600 hover:bg-yellow-500 text-black font-black py-3 text-sm tracking-wide transition-all"
          >
            I understand — this is not investment advice
          </button>
          <p className="text-gray-700 text-[10px] text-center mt-2">
            You must acknowledge to use this tool. This dialog re-appears if the disclaimer is updated.
          </p>
        </div>
      </div>
    </div>
  );
}
