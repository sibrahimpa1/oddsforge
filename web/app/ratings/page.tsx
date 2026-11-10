"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Ratings() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    api<any[]>("/api/ratings").then(setRows);
  }, []);
  const max = Math.max(...rows.map((r) => Math.abs(r.net)), 0.01);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">MLS power ratings</h1>
      <p className="max-w-3xl text-sm text-muted">
        Opponent-adjusted attack and defence from a time-decayed Poisson model of a 60/40 blend of xG and goals (half-life 240
        days, shrunk towards league average). Expected goals are per game against a league-average opponent at a neutral venue.
        These are the ratings the live model uses before context and lineup adjustments.
      </p>
      <div className="card overflow-x-auto">
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>Team</th>
              <th>Conf.</th>
              <th>xG for</th>
              <th>xG against</th>
              <th>Net rating</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.id}>
                <td className="text-muted">{i + 1}</td>
                <td className="font-medium">{r.name}</td>
                <td className="text-muted">{r.conference}</td>
                <td className="font-mono">{r.xg_for.toFixed(2)}</td>
                <td className="font-mono">{r.xg_against.toFixed(2)}</td>
                <td className="w-1/3">
                  <div className="flex items-center gap-2">
                    <div className="relative h-2 flex-1 rounded bg-bg">
                      <div
                        className={`absolute top-0 h-2 rounded ${r.net >= 0 ? "bg-accent" : "bg-bad"}`}
                        style={{
                          left: r.net >= 0 ? "50%" : `${50 - (Math.abs(r.net) / max) * 50}%`,
                          width: `${(Math.abs(r.net) / max) * 50}%`,
                        }}
                      />
                    </div>
                    <span className="w-12 text-right font-mono text-xs">{r.net.toFixed(2)}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
