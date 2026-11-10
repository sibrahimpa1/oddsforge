import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import BetSlip from "@/components/BetSlip";
import Nav from "@/components/Nav";
import Providers from "@/components/Providers";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "OddsForge · MLS predictions & fake-money betting",
  description:
    "Pregame MLS model: xG team ratings, Dixon-Coles score distributions, honest walk-forward backtests and paper betting with fake credits.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers>
          <Nav />
          <main className="mx-auto max-w-6xl px-4 pb-24 pt-6">{children}</main>
          <footer className="mx-auto max-w-6xl px-4 pb-10 text-xs text-muted">
            OddsForge is a portfolio project. Fake credits only, no deposits, no payouts. Data: football-data.co.uk, American
            Soccer Analysis, ESPN. If gambling is causing you harm, contact a local support service (US: 1-800-GAMBLER, UK:
            GamCare 0808 8020 133).
          </footer>
          <BetSlip />
        </Providers>
      </body>
    </html>
  );
}
