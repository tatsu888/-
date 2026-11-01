// App-wide context: universe lists, global security, panel actions, toasts.
import { createContext, useContext } from 'react';
import type { Universe } from './lib/types';

export interface TerminalCtx {
  universe: Universe | null;
  security: string; // global "loaded" security (panels that are not pinned follow it)
  setSecurity: (s: string) => void;
  /** Open function in the focused panel (optionally with a security). */
  run: (fn: string, security?: string, args?: string) => void;
  toast: (msg: string) => void;
  provider: string;
}

export const Ctx = createContext<TerminalCtx>(null as unknown as TerminalCtx);
export const useTerminal = () => useContext(Ctx);
