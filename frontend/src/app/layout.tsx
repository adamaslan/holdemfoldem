import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Hold Em or Fold Em",
  description: "Instant HOLD / FOLD verdict for any US stock, ETF, or options ticker",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
