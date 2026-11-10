"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";

export type SlipLeg = {
  match_id: number;
  market: string;
  selection: string;
  line: number | null;
  price: number;
  book: string;
  label: string;
  matchLabel: string;
  mode: "live" | "replay";
  model_prob?: number;
};

type Me = {
  name: string;
  bankroll: number;
  stake_limit: number;
  daily_loss_limit: number;
  lost_last_24h: number;
  live: any;
  replay: any;
  pnl_curve: { t: string; pnl: number; mode: string }[];
};

type Ctx = {
  slip: SlipLeg[];
  toggleLeg: (leg: SlipLeg) => void;
  removeLeg: (matchId: number) => void;
  clearSlip: () => void;
  inSlip: (matchId: number, market: string, selection: string, line: number | null) => boolean;
  me: Me | null;
  refreshMe: () => Promise<void>;
  setToken: (t: string) => void;
  slipOpen: boolean;
  setSlipOpen: (v: boolean) => void;
  toast: string | null;
  notify: (msg: string) => void;
};

const C = createContext<Ctx | null>(null);

export function useApp() {
  const c = useContext(C);
  if (!c) throw new Error("useApp outside provider");
  return c;
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const [slip, setSlip] = useState<SlipLeg[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [slipOpen, setSlipOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const refreshMe = useCallback(async () => {
    try {
      setMe(await api<Me>("/api/me"));
    } catch {
      setMe(null);
    }
  }, []);

  useEffect(() => {
    refreshMe();
  }, [refreshMe]);

  const setToken = (t: string) => {
    try {
      window.localStorage.setItem("oddsforge_token", t);
    } catch {}
    refreshMe();
  };

  const notify = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const value = useMemo<Ctx>(
    () => ({
      slip,
      toggleLeg: (leg) =>
        setSlip((s) => {
          const same = s.find(
            (l) => l.match_id === leg.match_id && l.market === leg.market && l.selection === leg.selection && l.line === leg.line,
          );
          if (same) return s.filter((l) => l !== same);
          // mixing live and replay legs makes no sense: a new mode starts a fresh slip
          const base = s.length && s[0].mode !== leg.mode ? [] : s;
          // one leg per match (correlated legs are not allowed)
          return [...base.filter((l) => l.match_id !== leg.match_id), leg];
        }),
      removeLeg: (id) => setSlip((s) => s.filter((l) => l.match_id !== id)),
      clearSlip: () => setSlip([]),
      inSlip: (id, market, selection, line) =>
        slip.some((l) => l.match_id === id && l.market === market && l.selection === selection && l.line === line),
      me,
      refreshMe,
      setToken,
      slipOpen,
      setSlipOpen,
      toast,
      notify,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [slip, me, slipOpen, toast],
  );

  return <C.Provider value={value}>{children}</C.Provider>;
}
