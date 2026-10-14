import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Outlet, useSearchParams } from 'react-router-dom';
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
  savedAnalysisId: string | null;
  runAnalysis: (request: AgricultureAnalysisRequest) => Promise<void>;
  loadSavedAnalysis: (analysisId: string) => Promise<void>;
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
 * (Phase P0-HISTORY): Supports loading saved analysis results from PostgreSQL
 * with zero GEE re-execution, surviving page refreshes via URL analysis_id param.
 */
export default function AgricultureLayout() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [result, setResult] = useState<AgriculturalAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAnalysisId, setSavedAnalysisId] = useState<string | null>(null);
  const [lastRequest, setLastRequest] = useState<AgricultureAnalysisRequest | null>(
    null,
  );

  const loadSavedAnalysis = useCallback(async (analysisId: string) => {
    setLoading(true);
    setError(null);
    setResult(null); // CRITICAL: Clear prior result immediately so it never flashes as the new result
    try {
      const raw = await agricultureApi.getHistoryItem(analysisId);
      const normalized = normalizeResponse(raw);
      if (!normalized) {
        setError('پاسخ تحلیل ذخیره‌شده نامعتبر است');
        return;
      }
      setResult(normalized);
      setSavedAnalysisId(analysisId);
      try {
        localStorage.setItem('active_agriculture_analysis_id', analysisId);
      } catch {
        // LocalStorage unavailable
      }
      if (normalized.time_start && normalized.time_end) {
        setLastRequest({
          geometry: normalized.geometry || { type: 'Point', coordinates: [0, 0] },
          start_date: normalized.time_start,
          end_date: normalized.time_end,
          request_id: analysisId,
          name: normalized.location_name || undefined,
        });
      }
    } catch (err) {
      setResult(null);
      setSavedAnalysisId(null);
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری تحلیل ذخیره‌شده');
    } finally {
      setLoading(false);
    }
  }, []);

  // Automatically load saved analysis if analysis_id URL search param is present (survives refresh)
  // or restore from localStorage if switching menus without search param
  useEffect(() => {
    const paramId = searchParams.get('analysis_id');
    if (paramId) {
      try {
        localStorage.setItem('active_agriculture_analysis_id', paramId);
      } catch {
        // LocalStorage unavailable
      }
      if (paramId !== savedAnalysisId) {
        loadSavedAnalysis(paramId);
      }
    } else {
      let storedId: string | null = null;
      try {
        storedId = localStorage.getItem('active_agriculture_analysis_id');
      } catch {
        storedId = null;
      }
      if (storedId) {
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.set('analysis_id', storedId!);
            return next;
          },
          { replace: true }
        );
        if (storedId !== savedAnalysisId) {
          loadSavedAnalysis(storedId);
        }
      }
    }
  }, [searchParams, savedAnalysisId, loadSavedAnalysis, setSearchParams]);

  const runAnalysis = useCallback(async (request: AgricultureAnalysisRequest) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setSavedAnalysisId(null);
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
      if (normalized.request_id) {
        setSavedAnalysisId(normalized.request_id);
        try {
          localStorage.setItem('active_agriculture_analysis_id', normalized.request_id);
        } catch {
          // LocalStorage unavailable
        }
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          next.set('analysis_id', normalized.request_id!);
          return next;
        }, { replace: true });
      }
    } catch (err) {
      setResult(null);
      setLastRequest(null);
      setError(err instanceof Error ? err.message : 'خطا در تحلیل کشاورزی');
    } finally {
      setLoading(false);
    }
  }, [setSearchParams]);

  const clearResult = useCallback(() => {
    setResult(null);
    setError(null);
    setLastRequest(null);
    setSavedAnalysisId(null);
    try {
      localStorage.removeItem('active_agriculture_analysis_id');
    } catch {
      // LocalStorage unavailable
    }
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('analysis_id');
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const value = useMemo<AgricultureContextValue>(
    () => ({
      result,
      loading,
      error,
      lastRequest,
      savedAnalysisId,
      runAnalysis,
      loadSavedAnalysis,
      clearResult,
    }),
    [result, loading, error, lastRequest, savedAnalysisId, runAnalysis, loadSavedAnalysis, clearResult],
  );

  return (
    <AgricultureContext.Provider value={value}>
      <Outlet />
    </AgricultureContext.Provider>
  );
}

