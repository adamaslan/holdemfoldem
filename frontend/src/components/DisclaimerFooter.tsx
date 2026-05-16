"use client";
import { DISCLAIMER_VERSION, DISCLAIMER_LAST_UPDATED, DISCLAIMER_STORAGE_KEY } from "@/lib/disclaimer";

export default function DisclaimerFooter() {
  function showDisclaimer() {
    localStorage.removeItem(DISCLAIMER_STORAGE_KEY);
    window.location.reload();
  }

  return (
    <footer className="w-full border-t border-gray-800/60 bg-gray-950 px-4 py-3 text-center">
      <p className="text-gray-700 text-[10px] leading-relaxed max-w-2xl mx-auto">
        <span className="text-yellow-700 font-semibold">Not investment advice.</span>
        {" "}Hold Em or Fold Em is an educational tool. Verdicts are technical signals, not financial recommendations.
        Data may be delayed or inaccurate. Options carry uncapped risk — losses may exceed premium paid.
        You are solely responsible for all trading decisions.{" "}
        <button
          onClick={showDisclaimer}
          className="underline text-gray-600 hover:text-gray-400 transition-colors"
        >
          View full disclaimer
        </button>
        {" "}· v{DISCLAIMER_VERSION} · {DISCLAIMER_LAST_UPDATED}
      </p>
    </footer>
  );
}
