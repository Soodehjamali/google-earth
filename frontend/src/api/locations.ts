import { apiGet, apiPost, apiDelete } from './client';
import type { Location, LocationCreate } from '../types';

export const locationsApi = {
  list: (skip = 0, limit = 50) =>
    apiGet<Location[]>(`/locations?skip=${skip}&limit=${limit}`),

  get: (id: string) =>
    apiGet<Location>(`/locations/${id}`),

  create: (data: LocationCreate) =>
    apiPost<Location>('/locations', data),

  delete: (id: string) =>
    apiDelete(`/locations/${id}`),
};
