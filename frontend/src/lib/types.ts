// Mirrors backend/app/models.py — keep in sync (see docs/API.md).
export interface Quote {
  symbol: string;
  name?: string | null;
  exchange?: string | null;
  currency?: string | null;
  type?: string | null;
  last?: number | null;
  change?: number | null;
  change_pct?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  prev_close?: number | null;
  volume?: number | null;
  bid?: number | null;
  ask?: number | null;
  market_cap?: number | null;
  pe?: number | null;
  eps?: number | null;
  div_yield?: number | null;
  time?: number | null;
  delay_sec?: number | null;
  source: string;
  error?: string | null;
}

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface UniverseItem {
  symbol: string;
  label: string;
  region?: string;
}

export interface Universe {
  lists: Record<string, UniverseItem[]>;
  tape: string[];
  intervals: string[];
  strategies: Record<string, Record<string, number>>;
  alert_conditions: string[];
  factor_sets: Record<string, { benchmark: string; factors: Record<string, string> }>;
  themes: Theme[];
  providers: string[];
}

export interface Theme {
  id: string;
  name: string;
  leader: string;
  market: string | null;
  followers: string[];
  note: string;
}

export interface Health {
  provider: string;
  description: string;
  status: string;
  detail: string;
}

export interface PanelState {
  id: string;
  fn: string;
  symbol?: string; // pinned security; undefined -> follows the global security
  args?: string;
}
