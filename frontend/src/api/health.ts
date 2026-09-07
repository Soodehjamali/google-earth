import { apiGet } from './client';
import type { EarthEngineHealth } from '../types';

export const healthApi = {
  // Live Earth Engine connection status. Response contains no credentials.
  earthEngine: () => apiGet<EarthEngineHealth>('/health/earth-engine'),
};
