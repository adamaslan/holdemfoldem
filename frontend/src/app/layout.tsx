import type { Metadata } from "next";
import "./globals.css";
import DisclaimerModal from "@/components/DisclaimerModal";
import DisclaimerFooter from "@/components/DisclaimerFooter";

export const metadata: Metadata = {
  title: "Hold Em or Fold Em",
  description: "Instant HOLD / FOLD verdict for any US stock, ETF, or options ticker",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex flex-col min-h-screen bg-gray-950">
        <DisclaimerModal />
        <div className="flex-1">{children}</div>
        <DisclaimerFooter />
      </body>
    </html>
  );
}
