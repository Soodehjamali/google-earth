import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { agricultureApi } from '../../api/agriculture';
import type {
  AgriculturalAnalysisResponse,
  AgricultureAnalysisRequest,
} from '../../types';
import { normalizeResponse } from './parse';

interface AgricultureContextValue {
  result: AgriculturalAnalysisResponse | null;
  loading: boolean;
  error: string | null;
  lastRequest: AgricultureAnalysisRequest | null;
  runAnalysis: (request: AgricultureAnalysisRequest) => Promise<void>;
  clearResult: () => void;
}

const AgricultureContext = createContext<AgricultureContextValue | null>(null);

/** Access the parent-owned Comprehensive analysis context (F1 §4). */
export function useAgricultureContext(): AgricultureContextValue {
  const context = useContext(AgricultureContext);
  if (!context) {
    throw new Error('useAgricultureContext must be used inside AgricultureLayout');
  }
  return context;
}

/**
 * Comprehensive parent route (F1 §4). Owns the hub analysis context so
 * the /agriculture overview keeps one shared request flow.
 * Calls only the Comprehensive API — never Legacy.
 *
 * NOTE (Prompt 2, done): DomainPage children no longer depend on this
 * shared result — each runs its own per-domain analysis
 * (fixedDomains = config.apiDomains). This context is retained for the
 * hub overview and stage 3 comprehensive work. No contract changed here.
 */
export default function AgricultureLayout() {
  const [result, setResult] = useState<AgriculturalAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRequest, setLastRequest] = useState<AgricultureAnalysisRequest | null>(
    null,
  );

  const runAnalysis = useCallback(async (request: AgricultureAnalysisRequest) => {
    setLoading(true);
    setError(null);
    try {
      const raw: unknown = await agricultureApi.analyze(request);
      const normalized = normalizeResponse(raw);
      if (!normalized) {
        setResult(null);
        setLastRequest(null);
        setError('پاسخ تحلیل نامعتبر — Invalid analysis response');
        return;
      }
      setResult(normalized);
      setLastRequest(request);
    } catch (err) {
      setResult(null);
      setLastRequest(null);
      setError(err instanceof Error ? err.message : 'خطا در تحلیل کشاورزی');
    } finally {
      setLoading(false);
    }
  }, []);

  const clearResult = useCallback(() => {
    setResult(null);
    setError(null);
    setLastRequest(null);
  }, []);

  const value = useMemo<AgricultureContextValue>(
    () => ({ result, loading, error, lastRequest, runAnalysis, clearResult }),
    [result, loading, error, lastRequest, runAnalysis, clearResult],
  );

  return (
    <AgricultureContext.Provider value={value}>
      <Outlet />
    </AgricultureContext.Provider>
  );
}
