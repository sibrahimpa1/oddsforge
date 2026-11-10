"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { money } from "@/lib/api";
import { useApp } from "./Providers";

const LINKS = [
  ["/", "Live MLS"],
  ["/replay", "Replay"],
  ["/bets", "My bets"],
  ["/leaderboard", "Leaderboard"],
  ["/ratings", "Ratings"],
  ["/model", "Model & backtest"],
];

export default function Nav() {
  const path = usePathname();
  const { me, toast } = useApp();
  return (
    <>
      <div className="border-b border-line bg-[#0e1a12] px-4 py-1.5 text-center text-xs text-accent/90">
        Fake credits only · for entertainment and analysis · no real-money betting ·{" "}
        <Link href="/responsible" className="underline">
          play responsibly
        </Link>
      </div>
      <header className="sticky top-0 z-30 border-b border-line bg-bg/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <Link href="/" className="flex items-center gap-2 font-bold tracking-tight">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-sm text-bg">OF</span>
            <span>OddsForge</span>
          </Link>
          <nav className="no-scrollbar flex flex-1 gap-1 overflow-x-auto text-sm">
            {LINKS.map(([href, label]) => {
              const active = href === "/" ? path === "/" : path.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`whitespace-nowrap rounded-md px-3 py-1.5 ${active ? "bg-line text-ink" : "text-muted hover:text-ink"}`}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
          <Link href="/bets" className="hidden whitespace-nowrap rounded-md border border-line px-3 py-1.5 text-sm sm:block">
            {me ? (
              <>
                {me.name} · <span className="font-mono text-accent">{money(me.bankroll)}</span>
              </>
            ) : (
              <span className="text-muted">Get 1,000 credits</span>
            )}
          </Link>
        </div>
      </header>
      {toast && (
        <div className="fixed left-1/2 top-20 z-50 -translate-x-1/2 rounded-lg border border-accent/40 bg-panel px-4 py-2 text-sm shadow-lg">
          {toast}
        </div>
      )}
    </>
  );
}
