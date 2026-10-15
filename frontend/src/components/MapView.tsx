import { useEffect, useRef, useState, useCallback } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { MapVisualization, MapLayer } from '../types'
import {
  calculatePolygonAreaSqMeters,
  calculatePolygonCenter,
  validatePolygonCoordinates,
} from './agriculture/polygon'
import MapSearchBar from './agriculture/MapSearchBar'
import { type GeocodingResult, formatCoordinates } from './agriculture/geocoding'

export type DrawState = 'idle' | 'drawing' | 'editing' | 'confirmed';
export type BaseMapMode = 'hybrid' | 'streets' | 'satellite';

interface MapViewProps {
  visualization?: MapVisualization
  geometry?: GeoJSON.Geometry
  /** Optional verbatim backend polygons (e.g. analysis grid cells). */
  overlays?: GeoJSON.Feature[]
  /** Optional Earth Engine raster tile URL template (e.g. https://.../tiles/{z}/{x}/{y}) */
  rasterTileUrl?: string | null
  /** Optional opacity for the raster tile layer (0.0 to 1.0, default 0.85) */
  rasterOpacity?: number
  /** Optional bounding box to fit [west, south, east, north] */
  bounds?: [number, number, number, number] | null
  center?: [number, number]
  zoom?: number
  className?: string
  // Interactive Polygon Drawing Props (Phase P-AGRI Field Boundary)
  enableDrawing?: boolean
  showDrawControls?: boolean
  initialPolygon?: GeoJSON.Polygon | null
  onPolygonChange?: (polygon: GeoJSON.Polygon | null, isConfirmed: boolean) => void
  onPolygonConfirm?: (polygon: GeoJSON.Polygon) => void
  onPolygonClear?: () => void
  /** Candidate inspection zones to overlay as priority markers on the field */
  inspectionZones?: MapInspectionZoneItem[]
}

export interface MapInspectionZoneItem {
  id: string
  nameFa: string
  centerCoordinates?: [number, number] | null
  priority: 'high' | 'medium' | 'low' | 'unknown'
  statusFa: string
  reasonFa: string
}

export default function MapView({
  visualization,
  geometry,
  overlays,
  rasterTileUrl,
  rasterOpacity = 0.85,
  bounds,
  center = [53.688, 32.428], // Default: Iran F-A12 central agricultural region
  zoom = 6,
  className = '',
  enableDrawing = false,
  showDrawControls = false,
  initialPolygon = null,
  onPolygonChange,
  onPolygonConfirm,
  onPolygonClear,
  inspectionZones = [],
}: MapViewProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [activeLayer, setActiveLayer] = useState<string>('rgb')
  const [opacity, setOpacity] = useState(0.8)

  // Geographic Context & Base Map Layer mode
  const [baseMapMode, setBaseMapMode] = useState<BaseMapMode>('hybrid')

  // Navigation & Coordinates tracking
  const [currentCenter, setCurrentCenter] = useState<[number, number]>(center)
  const [currentZoom, setCurrentZoom] = useState<number>(zoom)
  const [isLocating, setIsLocating] = useState<boolean>(false)
  const [locationError, setLocationError] = useState<string | null>(null)
  const [searchLocation, setSearchLocation] = useState<GeocodingResult | null>(null)
  const [rasterTileStatus, setRasterTileStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle')
  const [rasterRetryCount, setRasterRetryCount] = useState<number>(0)
  const [mapProviderError, setMapProviderError] = useState<string | null>(null)

  // Drawing state
  const [drawState, setDrawState] = useState<DrawState>(() =>
    initialPolygon ? 'confirmed' : 'idle'
  )
  const [vertices, setVertices] = useState<[number, number][]>(() => {
    if (initialPolygon && initialPolygon.coordinates && initialPolygon.coordinates[0]) {
      const ring = initialPolygon.coordinates[0]
      return (ring.length > 3 ? ring.slice(0, -1) : ring) as [number, number][]
    }
    return []
  })
  const [isFullscreen, setIsFullscreen] = useState(false)

  // Refs for event listeners to avoid stale closures
  const drawStateRef = useRef<DrawState>(drawState)
  drawStateRef.current = drawState
  const verticesRef = useRef<[number, number][]>(vertices)
  verticesRef.current = vertices
  const dragVertexIndexRef = useRef<number | null>(null)
  const consecutiveSatelliteErrorsRef = useRef<number>(0)

  // Helper to construct GeoJSON FeatureCollection for drawn polygon
  const buildDrawnFeatureCollection = useCallback(
    (pts: [number, number][], state: DrawState, hoverPt: [number, number] | null) => {
      const features: GeoJSON.Feature[] = []

      // If at least 3 vertices and in editing/confirmed state, add closed Polygon
      if (pts.length >= 3 && (state === 'editing' || state === 'confirmed')) {
        const closedRing = [...pts, pts[0]]
        features.push({
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [closedRing],
          },
          properties: {
            kind: 'polygon',
            isConfirmed: state === 'confirmed',
          },
        })
      }

      // If drawing or editing, add LineString
      if (pts.length >= 2) {
        const lineCoords: [number, number][] = [...pts]
        if (state === 'drawing' && hoverPt) {
          lineCoords.push(hoverPt)
        } else if (state === 'editing' || state === 'confirmed') {
          lineCoords.push(pts[0]) // close outline
        }
        features.push({
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: lineCoords,
          },
          properties: {
            kind: 'line',
            isConfirmed: state === 'confirmed',
          },
        })
      } else if (pts.length === 1 && state === 'drawing' && hoverPt) {
        features.push({
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: [pts[0], hoverPt],
          },
          properties: {
            kind: 'line',
            isConfirmed: false,
          },
        })
      }

      // Add vertex points
      pts.forEach((pt, index) => {
        features.push({
          type: 'Feature',
          geometry: {
            type: 'Point',
            coordinates: pt,
          },
          properties: {
            kind: 'vertex',
            index: index,
            isFirst: index === 0,
            isConfirmed: state === 'confirmed',
          },
        })
      })

      return {
        type: 'FeatureCollection',
        features,
      } as GeoJSON.FeatureCollection
    },
    []
  )

  // Sync drawn source on map
  const updateDrawnSource = useCallback(
    (pts: [number, number][], state: DrawState, hoverPt: [number, number] | null) => {
      if (!map.current) return
      const src = map.current.getSource('drawn-polygon-source') as maplibregl.GeoJSONSource
      if (src) {
        src.setData(buildDrawnFeatureCollection(pts, state, hoverPt))
      }
    },
    [buildDrawnFeatureCollection]
  )

  useEffect(() => {
    if (!mapContainer.current) return

    // Basemap Provider Configuration:
    // Default = OpenStreetMap standard tiles + Sentinel-2 true-color proxy overlay.
    // Direct Google tiles only behind ALLOW_GOOGLE_DIRECT_TILES (default false).
    const allowGoogleDirect = typeof window !== 'undefined' && Boolean(
      (window as any).__ALLOW_GOOGLE_DIRECT_TILES__ ||
      (import.meta.env && import.meta.env.VITE_ALLOW_GOOGLE_DIRECT_TILES === 'true')
    )

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          satellite: {
            type: 'raster',
            tiles: allowGoogleDirect
              ? [
                  'https://mt0.google.com/vt/lyrs=s&hl=fa&x={x}&y={y}&z={z}',
                  'https://mt1.google.com/vt/lyrs=s&hl=fa&x={x}&y={y}&z={z}',
                ]
              : ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            maxzoom: allowGoogleDirect ? 19 : 18,
            attribution: allowGoogleDirect
              ? '© Google Satellite'
              : '© OpenStreetMap contributors | Sentinel-2 True-Color (Proxy)',
          },
          labels: {
            type: 'raster',
            tiles: allowGoogleDirect
              ? [
                  'https://mt0.google.com/vt/lyrs=h&hl=fa&x={x}&y={y}&z={z}',
                  'https://mt1.google.com/vt/lyrs=h&hl=fa&x={x}&y={y}&z={z}',
                ]
              : ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            maxzoom: allowGoogleDirect ? 19 : 18,
            attribution: allowGoogleDirect ? '© Google Reference' : '© OpenStreetMap contributors',
          },
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [
          {
            id: 'osm-layer',
            type: 'raster',
            source: 'osm',
            paint: {
              'raster-opacity': (baseMapMode === 'streets' || baseMapMode === 'hybrid') ? 1.0 : 0.0,
            },
          },
          {
            id: 'satellite-layer',
            type: 'raster',
            source: 'satellite',
            paint: {
              'raster-opacity': baseMapMode === 'streets' ? 0.0 : 1.0,
            },
          },
          {
            id: 'labels-layer',
            type: 'raster',
            source: 'labels',
            paint: {
              'raster-opacity': baseMapMode === 'hybrid' ? 1.0 : 0.0,
            },
          },
        ],
      },
      center: center,
      zoom: zoom,
    })

    const currentMap = map.current

    // Add navigation controls (Zoom +, Zoom -, Compass)
    currentMap.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')

    // Add metric scale
    currentMap.addControl(
      new maplibregl.ScaleControl({ maxWidth: 200, unit: 'metric' }),
      'bottom-right'
    )

    // Setup sources and layers when map is ready
    currentMap.on('load', () => {
      // 1. Setup Drawn Polygon source and layers
      currentMap.addSource('drawn-polygon-source', {
        type: 'geojson',
        data: buildDrawnFeatureCollection(verticesRef.current, drawStateRef.current, null),
      })

      // Fill layer
      currentMap.addLayer({
        id: 'drawn-polygon-fill',
        type: 'fill',
        source: 'drawn-polygon-source',
        filter: ['==', ['get', 'kind'], 'polygon'],
        paint: {
          'fill-color': [
            'case',
            ['get', 'isConfirmed'],
            '#2e7d32', // confirmed emerald green
            '#1976d2', // editing blue
          ],
          'fill-opacity': [
            'case',
            ['get', 'isConfirmed'],
            0.35,
            0.2,
          ],
        },
      })

      // Outline / Line layer
      currentMap.addLayer({
        id: 'drawn-polygon-outline',
        type: 'line',
        source: 'drawn-polygon-source',
        filter: ['in', ['get', 'kind'], ['literal', ['polygon', 'line']]],
        paint: {
          'line-color': [
            'case',
            ['get', 'isConfirmed'],
            '#1b5e20',
            '#1565c0',
          ],
          'line-width': 2.5,
        },
      })

      // Vertices circle layer
      currentMap.addLayer({
        id: 'drawn-polygon-vertices',
        type: 'circle',
        source: 'drawn-polygon-source',
        filter: ['==', ['get', 'kind'], 'vertex'],
        paint: {
          'circle-radius': ['case', ['get', 'isFirst'], 7, 5.5],
          'circle-color': [
            'case',
            ['get', 'isFirst'],
            '#ffeb3b', // Yellow start point
            '#ffffff',
          ],
          'circle-stroke-color': [
            'case',
            ['get', 'isConfirmed'],
            '#1b5e20',
            '#1565c0',
          ],
          'circle-stroke-width': 2.5,
        },
      })

      // 2. Setup Search Location Marker Source & Layers
      currentMap.addSource('search-marker-source', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [],
        },
      })
      currentMap.addLayer({
        id: 'search-marker-halo',
        type: 'circle',
        source: 'search-marker-source',
        paint: {
          'circle-radius': 16,
          'circle-color': '#ff9800',
          'circle-opacity': 0.3,
        },
      })
      currentMap.addLayer({
        id: 'search-marker-point',
        type: 'circle',
        source: 'search-marker-source',
        paint: {
          'circle-radius': 7,
          'circle-color': '#e65100',
          'circle-stroke-width': 2.5,
          'circle-stroke-color': '#ffffff',
        },
      })

      // 3. Setup User GPS Location Marker Source & Layers
      currentMap.addSource('user-location-source', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [],
        },
      })
      currentMap.addLayer({
        id: 'user-location-halo',
        type: 'circle',
        source: 'user-location-source',
        paint: {
          'circle-radius': 18,
          'circle-color': '#2196f3',
          'circle-opacity': 0.28,
        },
      })
      currentMap.addLayer({
        id: 'user-location-point',
        type: 'circle',
        source: 'user-location-source',
        paint: {
          'circle-radius': 7,
          'circle-color': '#1565c0',
          'circle-stroke-width': 2.5,
          'circle-stroke-color': '#ffffff',
        },
      })

      // 4. Setup standard geometry source and layers
      currentMap.addSource('geometry', {
        type: 'geojson',
        data: geometry
          ? {
              type: 'FeatureCollection',
              features: [
                {
                  type: 'Feature',
                  geometry: geometry,
                  properties: {},
                },
              ],
            }
          : {
              type: 'FeatureCollection',
              features: [],
            },
      })

      currentMap.addLayer({
        id: 'geometry-fill',
        type: 'fill',
        source: 'geometry',
        filter: ['==', '$type', 'Polygon'],
        paint: {
          'fill-color': '#4CAF50',
          'fill-opacity': 0.25,
        },
      })

      currentMap.addLayer({
        id: 'geometry-outline',
        type: 'line',
        source: 'geometry',
        paint: {
          'line-color': '#2e7d32',
          'line-width': 2.5,
        },
      })

      currentMap.addLayer({
        id: 'geometry-point',
        type: 'circle',
        source: 'geometry',
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 7,
          'circle-color': '#e53935',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
        },
      })

      if (geometry) {
        if (geometry.type === 'Point') {
          const [lon, lat] = geometry.coordinates as [number, number]
          if (lon !== 0 || lat !== 0) {
            currentMap.flyTo({ center: [lon, lat], zoom: 14 })
          }
        } else {
          const polyBounds = new maplibregl.LngLatBounds()
          const coords = extractCoordinates(geometry)
          if (coords.length > 0) {
            coords.forEach((coord) => {
              polyBounds.extend(coord as [number, number])
            })
            currentMap.fitBounds(polyBounds, { padding: 50, maxZoom: 16 })
          }
        }
      }
    })

    // Track coordinates & zoom unobtrusively for geographic orientation
    const onMapMove = () => {
      const c = currentMap.getCenter()
      setCurrentCenter([c.lng, c.lat])
      setCurrentZoom(currentMap.getZoom())
    }
    currentMap.on('move', onMapMove)

    // Handle map provider errors: require 5 consecutive failures before disabling satellite provider
    const onMapError = (e: any) => {
      const srcId = e?.sourceId || e?.tile?.source || ''
      const errMsg = typeof e?.error?.message === 'string' ? e.error.message : ''
      const is403 = e?.error?.status === 403 || e?.status === 403 || /403/i.test(errMsg)

      // Operational Invariant (Phase 2 Closeout):
      // A 403 from an expired token or analysis raster layer must NOT count toward
      // the "5 consecutive failures -> switch basemap" counter.
      if (srcId === 'ee-raster-source' || is403 || errMsg.includes('/tiles/')) {
        return
      }

      const isSatellite =
        srcId === 'satellite' ||
        srcId === 'labels' ||
        errMsg.includes('google.com/vt') ||
        errMsg.includes('arcgisonline') ||
        errMsg.includes('World_Imagery')
      if (isSatellite) {
        consecutiveSatelliteErrorsRef.current += 1
        if (consecutiveSatelliteErrorsRef.current >= 5) {
          setMapProviderError('ارتباط با سرور تصاویر ماهواره‌ای برقرار نشد. نقشه پایه OpenStreetMap فعال است.')
          try {
            if (currentMap.getLayer('osm-layer')) {
              currentMap.setPaintProperty('osm-layer', 'raster-opacity', 1.0)
            }
          } catch {
            // ignore
          }
        }
      }
    }
    currentMap.on('error', onMapError)

    const onSourceData = (e: any) => {
      if (e?.sourceId === 'satellite' && e?.isSourceLoaded && e?.tile) {
        consecutiveSatelliteErrorsRef.current = 0
        setMapProviderError(null)
      }
    }
    currentMap.on('sourcedata', onSourceData)

    // Handle dynamic resize of container
    const resizeObserver = new ResizeObserver(() => {
      if (map.current) {
        map.current.resize()
      }
    })
    if (mapContainer.current) {
      resizeObserver.observe(mapContainer.current)
    }

    // Interactive map event listeners for drawing and editing
    const onMapClick = (e: maplibregl.MapMouseEvent) => {
      const state = drawStateRef.current
      if (state !== 'drawing') return

      const clickCoord: [number, number] = [e.lngLat.lng, e.lngLat.lat]
      const curPts = verticesRef.current

      // If vertices >= 3, check if clicked near first point to close polygon
      if (curPts.length >= 3) {
        const p0 = currentMap.project(curPts[0])
        const pClick = currentMap.project(clickCoord)
        const dist = Math.hypot(p0.x - pClick.x, p0.y - pClick.y)
        if (dist < 22) {
          // Close polygon!
          setDrawState('editing')
          updateDrawnSource(curPts, 'editing', null)
          return
        }
      }

      // Otherwise add vertex
      const nextPts: [number, number][] = [...curPts, clickCoord]
      setVertices(nextPts)
      updateDrawnSource(nextPts, 'drawing', null)
    }

    const onMapDblClick = (e: maplibregl.MapMouseEvent) => {
      const state = drawStateRef.current
      if (state !== 'drawing') return

      e.preventDefault()
      const curPts = verticesRef.current
      if (curPts.length >= 3) {
        // Close polygon on double click
        setDrawState('editing')
        updateDrawnSource(curPts, 'editing', null)
      }
    }

    const onMapMouseMove = (e: maplibregl.MapMouseEvent) => {
      const state = drawStateRef.current
      const curPts = verticesRef.current

      if (state === 'drawing' && curPts.length > 0) {
        const hoverPt: [number, number] = [e.lngLat.lng, e.lngLat.lat]
        updateDrawnSource(curPts, 'drawing', hoverPt)
      } else if (dragVertexIndexRef.current !== null) {
        // Dragging active vertex
        const idx = dragVertexIndexRef.current
        const nextPts = [...curPts]
        nextPts[idx] = [e.lngLat.lng, e.lngLat.lat]
        setVertices(nextPts)
        updateDrawnSource(nextPts, state, null)
      }
    }

    const onVertexMouseDown = (e: maplibregl.MapLayerMouseEvent) => {
      const state = drawStateRef.current
      if (state !== 'editing') return
      if (!e.features || e.features.length === 0) return

      const index = e.features[0].properties?.index
      if (typeof index === 'number') {
        dragVertexIndexRef.current = index
        currentMap.getCanvas().style.cursor = 'grabbing'
        currentMap.dragPan.disable()
      }
    }

    const onMouseUp = () => {
      if (dragVertexIndexRef.current !== null) {
        dragVertexIndexRef.current = null
        currentMap.getCanvas().style.cursor = ''
        currentMap.dragPan.enable()
        // If in editing mode, update parent with current polygon
        if (drawStateRef.current === 'editing' && verticesRef.current.length >= 3) {
          const closedRing = [...verticesRef.current, verticesRef.current[0]]
          onPolygonChange?.(
            { type: 'Polygon', coordinates: [closedRing] },
            false
          )
        }
      }
    }

    const onVertexMouseEnter = () => {
      if (drawStateRef.current === 'editing') {
        currentMap.getCanvas().style.cursor = 'grab'
      }
    }

    const onVertexMouseLeave = () => {
      if (drawStateRef.current === 'editing' && dragVertexIndexRef.current === null) {
        currentMap.getCanvas().style.cursor = ''
      }
    }

    currentMap.on('click', onMapClick)
    currentMap.on('dblclick', onMapDblClick)
    currentMap.on('mousemove', onMapMouseMove)
    currentMap.on('mouseup', onMouseUp)
    currentMap.on('mousedown', 'drawn-polygon-vertices', onVertexMouseDown)
    currentMap.on('mouseenter', 'drawn-polygon-vertices', onVertexMouseEnter)
    currentMap.on('mouseleave', 'drawn-polygon-vertices', onVertexMouseLeave)

    return () => {
      resizeObserver.disconnect()
      currentMap.remove()
    }
  }, [])

  // Sync Base Map layer opacities on mode switch or provider error
  useEffect(() => {
    const current = map.current
    if (!current) return

    const updateLayers = () => {
      try {
        if (current.getLayer('satellite-layer')) {
          current.setPaintProperty(
            'satellite-layer',
            'raster-opacity',
            baseMapMode === 'streets' ? 0.0 : (mapProviderError ? 0.0 : 1.0)
          )
        }
        if (current.getLayer('osm-layer')) {
          current.setPaintProperty(
            'osm-layer',
            'raster-opacity',
            (baseMapMode === 'streets' || mapProviderError || baseMapMode === 'hybrid') ? 1.0 : 0.0
          )
        }
        if (current.getLayer('labels-layer')) {
          current.setPaintProperty(
            'labels-layer',
            'raster-opacity',
            (baseMapMode === 'hybrid' && !mapProviderError) ? 1.0 : 0.0
          )
        }
        current.triggerRepaint()
      } catch (err) {
        console.warn('Error switching base map layer:', err)
      }
    }

    if (current.getLayer('satellite-layer') || current.getLayer('osm-layer')) {
      updateLayers()
    } else {
      current.once('load', updateLayers)
    }
  }, [baseMapMode, mapProviderError])

  // Sync polygon when initialPolygon prop changes (e.g. loaded saved analysis)
  useEffect(() => {
    if (initialPolygon && initialPolygon.coordinates && initialPolygon.coordinates[0]) {
      const ring = initialPolygon.coordinates[0]
      const pts = (ring.length > 3 ? ring.slice(0, -1) : ring) as [number, number][]
      setVertices(pts)
      setDrawState('confirmed')
      updateDrawnSource(pts, 'confirmed', null)

      if (map.current && pts.length >= 3) {
        const polyBounds = new maplibregl.LngLatBounds()
        ring.forEach((pt) => polyBounds.extend(pt as [number, number]))
        map.current.fitBounds(polyBounds, { padding: 50, maxZoom: 15 })
      }
    } else if (initialPolygon === null && drawStateRef.current === 'confirmed') {
      setVertices([])
      setDrawState('idle')
      updateDrawnSource([], 'idle', null)
    }
  }, [initialPolygon, updateDrawnSource])

  // Sync center / zoom when changed externally (only if not drawing/editing)
  useEffect(() => {
    if (!map.current || drawStateRef.current === 'drawing' || drawStateRef.current === 'editing') return
    try {
      map.current.flyTo({ center, zoom })
    } catch {
      // Map not ready
    }
  }, [center[0], center[1], zoom])

  // Sync cursor when drawState changes
  useEffect(() => {
    if (!map.current) return
    const canvas = map.current.getCanvas()
    if (drawState === 'drawing') {
      canvas.style.cursor = 'crosshair'
      map.current.doubleClickZoom.disable()
    } else {
      canvas.style.cursor = ''
      map.current.doubleClickZoom.enable()
    }
  }, [drawState])

  // Handle Earth Engine raster layer changes (Phase P-AGRI-3 / P-AGRI-4)
  useEffect(() => {
    const current = map.current
    if (!current) return

    if (!rasterTileUrl) {
      setRasterTileStatus('idle')
      try {
        if (current.getLayer('ee-raster-layer')) {
          current.removeLayer('ee-raster-layer')
        }
        if (current.getSource('ee-raster-source')) {
          current.removeSource('ee-raster-source')
        }
      } catch {
        // Source/layer absent
      }
      return
    }

    setRasterTileStatus('loading')

    const onSourceData = (e: maplibregl.MapSourceDataEvent) => {
      if (e.sourceId === 'ee-raster-source') {
        if (e.isSourceLoaded) {
          setRasterTileStatus('loaded')
        }
      }
    }

    const onError = (e: any) => {
      if (e?.sourceId === 'ee-raster-source' || e?.error?.message?.includes('raster') || e?.error?.status >= 400) {
        // Operational Invariant (Phase 2 Closeout):
        // 403 from an expired token triggers token refresh / auto-retry
        const is403 = e?.error?.status === 403 || e?.status === 403 || /403/i.test(e?.error?.message || '')
        if (is403) {
          setRasterRetryCount((prev) => (prev < 3 ? prev + 1 : prev))
        }
        setRasterTileStatus('error')
      }
    }

    current.on('sourcedata', onSourceData)
    current.on('error', onError)

    const applyRasterLayer = () => {
      try {
        if (current.getLayer('ee-raster-layer')) {
          current.removeLayer('ee-raster-layer')
        }
        if (current.getSource('ee-raster-source')) {
          current.removeSource('ee-raster-source')
        }
      } catch {
        // Source/layer absent
      }

      if (!rasterTileUrl) return

      try {
        current.addSource('ee-raster-source', {
          type: 'raster',
          tiles: [rasterTileUrl],
          tileSize: 256,
          attribution: 'Contains modified Copernicus Sentinel data',
        })

        const beforeId = current.getLayer('drawn-polygon-fill')
          ? 'drawn-polygon-fill'
          : current.getLayer('geometry-point')
            ? 'geometry-point'
            : current.getLayer('geometry-outline')
              ? 'geometry-outline'
              : undefined

        current.addLayer(
          {
            id: 'ee-raster-layer',
            type: 'raster',
            source: 'ee-raster-source',
            paint: {
              'raster-opacity': rasterOpacity !== undefined ? rasterOpacity : 0.85,
            },
          },
          beforeId
        )
      } catch (err) {
        console.warn('Failed to add EE raster layer:', err)
        setRasterTileStatus('error')
      }
    }

    if (!current.loaded()) {
      current.once('load', applyRasterLayer)
    } else {
      applyRasterLayer()
    }

    return () => {
      current.off('sourcedata', onSourceData)
      current.off('error', onError)
    }
  }, [rasterTileUrl, rasterRetryCount])

  // Update raster layer opacity without reloading tile source
  useEffect(() => {
    const current = map.current
    if (!current) return
    try {
      if (current.getLayer('ee-raster-layer')) {
        current.setPaintProperty('ee-raster-layer', 'raster-opacity', rasterOpacity !== undefined ? rasterOpacity : 0.85)
      }
    } catch {
      // Layer not ready yet
    }
  }, [rasterOpacity])

  // Candidate Inspection Zones Markers (Step 1 & 8)
  const zoneMarkersRef = useRef<maplibregl.Marker[]>([])

  useEffect(() => {
    const current = map.current
    if (!current) return

    // Clear previous markers
    zoneMarkersRef.current.forEach((m) => m.remove())
    zoneMarkersRef.current = []

    if (!inspectionZones || inspectionZones.length === 0) return

    const addMarkers = () => {
      zoneMarkersRef.current.forEach((m) => m.remove())
      zoneMarkersRef.current = []

      inspectionZones.forEach((z) => {
        if (!z.centerCoordinates || z.centerCoordinates.length < 2) return
        const [lon, lat] = z.centerCoordinates
        if (typeof lon !== 'number' || typeof lat !== 'number' || isNaN(lon) || isNaN(lat)) return

        const el = document.createElement('div')
        el.className = 'inspection-zone-marker'
        const color = z.priority === 'high' ? '#e53e3e' : z.priority === 'medium' ? '#dd6b20' : '#38a169'
        el.style.cssText = `
          background-color: ${color};
          color: white;
          border: 2px solid white;
          border-radius: 50%;
          width: 26px;
          height: 26px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 13px;
          font-weight: bold;
          box-shadow: 0 2px 5px rgba(0,0,0,0.4);
          cursor: pointer;
        `
        el.innerText = z.priority === 'high' ? '!' : '✓'

        const popup = new maplibregl.Popup({ offset: 25, closeButton: true }).setHTML(`
          <div style="direction: rtl; text-align: right; font-family: sans-serif; font-size: 0.82rem; padding: 4px; min-width: 160px;">
            <div style="font-weight: 700; color: ${color}; margin-bottom: 4px;">${z.nameFa}</div>
            <div style="margin-bottom: 2px;">اولویت: <strong>${z.priority === 'high' ? 'بالا (فوری)' : z.priority === 'medium' ? 'متوسط' : 'عادی'}</strong></div>
            <div style="margin-bottom: 4px; color: #4a5568;">وضعیت: ${z.statusFa}</div>
            <div style="font-size: 0.75rem; color: #718096; border-top: 1px solid #edf2f7; padding-top: 4px;">${z.reasonFa}</div>
          </div>
        `)

        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([lon, lat])
          .setPopup(popup)
          .addTo(current)

        zoneMarkersRef.current.push(marker)
      })
    }

    if (!current.loaded()) {
      current.once('load', addMarkers)
    } else {
      addMarkers()
    }

    return () => {
      zoneMarkersRef.current.forEach((m) => m.remove())
      zoneMarkersRef.current = []
    }
  }, [inspectionZones])

  // Handle dynamic geometry updates from parent components or saved analyses
  useEffect(() => {
    const current = map.current
    if (!current) return

    const updateGeometry = () => {
      try {
        const source = current.getSource('geometry') as maplibregl.GeoJSONSource | undefined
        if (!source) return

        if (!geometry) {
          source.setData({
            type: 'FeatureCollection',
            features: [],
          })
          return
        }

        source.setData({
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              geometry: geometry,
              properties: {},
            },
          ],
        })

        if (geometry.type === 'Point') {
          const [lon, lat] = geometry.coordinates as [number, number]
          if (lon !== 0 || lat !== 0) {
            current.flyTo({ center: [lon, lat], zoom: 14 })
          }
        } else {
          const polyBounds = new maplibregl.LngLatBounds()
          const coords = extractCoordinates(geometry)
          if (coords.length > 0) {
            coords.forEach((coord) => {
              polyBounds.extend(coord as [number, number])
            })
            current.fitBounds(polyBounds, { padding: 50, maxZoom: 16 })
          }
        }
      } catch (err) {
        console.warn('Error updating geometry on MapView:', err)
      }
    }

    if (!current.loaded()) {
      current.once('load', updateGeometry)
      return
    }
    updateGeometry()
  }, [geometry])

  // Handle explicit bbox bounds fitting
  useEffect(() => {
    if (!map.current || !bounds) return
    try {
      const [west, south, east, north] = bounds
      map.current.fitBounds(
        [
          [west, south],
          [east, north],
        ],
        { padding: 40, maxZoom: 15 }
      )
    } catch {
      // Map not ready
    }
  }, [bounds])

  // Handle visualization changes
  useEffect(() => {
    if (!map.current || !visualization) return

    map.current.flyTo({
      center: visualization.center,
      zoom: visualization.zoom,
    })
  }, [visualization])

  // Draw optional overlay features (verbatim backend polygons)
  useEffect(() => {
    const current = map.current
    if (!current) return

    const applyOverlays = () => {
      try {
        if (current.getLayer('spatial-cells-outline')) {
          current.removeLayer('spatial-cells-outline')
        }
        if (current.getLayer('spatial-cells-fill')) {
          current.removeLayer('spatial-cells-fill')
        }
        if (current.getSource('spatial-cells')) {
          current.removeSource('spatial-cells')
        }
      } catch {
        // Layers or source already absent
      }
      if (!overlays || overlays.length === 0) return
      current.addSource('spatial-cells', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: overlays,
        },
      })
      current.addLayer({
        id: 'spatial-cells-fill',
        type: 'fill',
        source: 'spatial-cells',
        paint: {
          'fill-color': '#607d8b',
          'fill-opacity': 0.25,
        },
      })
      current.addLayer({
        id: 'spatial-cells-outline',
        type: 'line',
        source: 'spatial-cells',
        paint: {
          'line-color': '#37474f',
          'line-width': 1,
        },
      })
    }

    if (!current.loaded()) {
      current.once('load', applyOverlays)
      return
    }
    applyOverlays()
  }, [overlays])

  // Resize map when entering/exiting fullscreen
  useEffect(() => {
    if (map.current) {
      setTimeout(() => {
        map.current?.resize()
      }, 100)
    }
  }, [isFullscreen])

  // Geocoding location selection handler
  const handleSelectLocation = (loc: GeocodingResult) => {
    if (!map.current) return
    setSearchLocation(loc)

    // Update search marker source on map
    const src = map.current.getSource('search-marker-source') as maplibregl.GeoJSONSource
    if (src) {
      src.setData({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [loc.lon, loc.lat] },
        properties: { name: loc.shortName },
      })
    }

    if (loc.boundingBox) {
      const [minLat, maxLat, minLon, maxLon] = loc.boundingBox
      map.current.fitBounds(
        [
          [minLon, minLat],
          [maxLon, maxLat],
        ],
        { padding: 50, maxZoom: 13 }
      )
    } else {
      map.current.flyTo({
        center: [loc.lon, loc.lat],
        zoom: 12,
      })
    }
  }

  // Current Location ("My Location") handler
  const handleMyLocation = () => {
    if (!navigator.geolocation) {
      setLocationError('مرورگر شما از قابلیت تعیین موقعیت مکانی پشتیبانی نمی‌کند.')
      return
    }

    setIsLocating(true)
    setLocationError(null)

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setIsLocating(false)
        const lat = position.coords.latitude
        const lon = position.coords.longitude
        setLocationError(null)

        if (map.current) {
          map.current.flyTo({
            center: [lon, lat],
            zoom: 14,
          })
          const src = map.current.getSource('user-location-source') as maplibregl.GeoJSONSource
          if (src) {
            src.setData({
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [lon, lat] },
              properties: {},
            })
          }
        }
      },
      (err) => {
        setIsLocating(false)
        let msg = 'دسترسی به موقعیت مکانی ممکن نشد.'
        if (err.code === err.PERMISSION_DENIED) {
          msg = 'دسترسی به موقعیت مکانی توسط مرورگر یا کاربر تایید نشد.'
        } else if (err.code === err.POSITION_UNAVAILABLE) {
          msg = 'اطلاعات موقعیت مکانی در دسترس نیست.'
        } else if (err.code === err.TIMEOUT) {
          msg = 'زمان درخواست موقعیت مکانی به پایان رسید.'
        }
        setLocationError(msg)
        setTimeout(() => setLocationError(null), 5000)
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    )
  }

  // Reset / Initial View handler
  const handleResetView = () => {
    if (!map.current) return
    if (initialPolygon && initialPolygon.coordinates && initialPolygon.coordinates[0]?.length >= 4) {
      const polyBounds = new maplibregl.LngLatBounds()
      initialPolygon.coordinates[0].forEach((pt) => polyBounds.extend(pt as [number, number]))
      map.current.fitBounds(polyBounds, { padding: 50, maxZoom: 14 })
    } else if (geometry) {
      const coords = extractCoordinates(geometry)
      if (coords.length > 1) {
        const polyBounds = new maplibregl.LngLatBounds()
        coords.forEach((pt) => polyBounds.extend(pt))
        map.current.fitBounds(polyBounds, { padding: 50, maxZoom: 14 })
      } else if (coords.length === 1) {
        map.current.flyTo({ center: coords[0], zoom: 12 })
      }
    } else {
      map.current.flyTo({ center, zoom })
    }
  }

  // Zoom handlers
  const handleZoomIn = () => {
    map.current?.zoomIn()
  }

  const handleZoomOut = () => {
    map.current?.zoomOut()
  }

  // Toolbar actions
  const handleStartDraw = () => {
    setDrawState('drawing')
    setVertices([])
    updateDrawnSource([], 'drawing', null)
    onPolygonChange?.(null, false)
  }

  const handleStartEdit = () => {
    if (vertices.length >= 3) {
      setDrawState('editing')
      updateDrawnSource(vertices, 'editing', null)
      const closedRing = [...vertices, vertices[0]]
      onPolygonChange?.({ type: 'Polygon', coordinates: [closedRing] }, false)
    }
  }

  const handleClear = () => {
    setVertices([])
    setDrawState('idle')
    updateDrawnSource([], 'idle', null)
    onPolygonClear?.()
    onPolygonChange?.(null, false)
  }

  const handleConfirm = () => {
    if (vertices.length < 3) return

    const closedRing = [...vertices, vertices[0]]
    const validation = validatePolygonCoordinates(closedRing)
    if (!validation.valid) {
      alert(validation.error || 'چندضلعی نامعتبر است')
      return
    }

    const polygon: GeoJSON.Polygon = {
      type: 'Polygon',
      coordinates: [closedRing],
    }

    setDrawState('confirmed')
    updateDrawnSource(vertices, 'confirmed', null)

    onPolygonConfirm?.(polygon)
    onPolygonChange?.(polygon, true)

    // Center view on confirmed polygon
    if (map.current) {
      const center = calculatePolygonCenter(vertices)
      map.current.flyTo({ center, zoom: Math.max(map.current.getZoom(), 13) })
    }
  }

  // Calculate live area in hectares
  const areaSqM = vertices.length >= 3 ? calculatePolygonAreaSqMeters(vertices) : 0
  const areaHectares = areaSqM / 10000

  return (
    <div
      className={`map-container ${className}`}
      style={
        isFullscreen
          ? {
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100vw',
              height: '100vh',
              zIndex: 9999,
              background: '#000',
            }
          : { position: 'relative', width: '100%', height: 520, background: '#eaedf1' }
      }
    >
      <div ref={mapContainer} className="map" style={{ width: '100%', height: isFullscreen ? '100vh' : 520, background: '#eaedf1' }} />

      {/* Dedicated Floating Zoom & Navigation Controls */}
      <div
        data-testid="map-zoom-controls"
        style={{
          position: 'absolute',
          top: 10,
          left: 10,
          zIndex: 25,
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
          background: 'rgba(255, 255, 255, 0.96)',
          borderRadius: 6,
          boxShadow: '0 2px 8px rgba(0,0,0,0.22)',
          padding: 2,
          border: '1px solid #d0d7de',
        }}
      >
        <button
          type="button"
          data-testid="map-zoom-in-btn"
          onClick={handleZoomIn}
          style={{
            width: 32,
            height: 32,
            fontSize: '1rem',
            border: 'none',
            background: 'transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#1f2937',
            fontWeight: 'bold',
            borderRadius: 4,
          }}
          title="بزرگ‌نمایی (+)"
          aria-label="بزرگ‌نمایی"
        >
          ➕
        </button>
        <div style={{ height: 1, backgroundColor: '#e5e7eb', margin: '0 4px' }} />
        <button
          type="button"
          data-testid="map-zoom-out-btn"
          onClick={handleZoomOut}
          style={{
            width: 32,
            height: 32,
            fontSize: '1rem',
            border: 'none',
            background: 'transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#1f2937',
            fontWeight: 'bold',
            borderRadius: 4,
          }}
          title="کوچک‌نمایی (-)"
          aria-label="کوچک‌نمایی"
        >
          ➖
        </button>
        <div style={{ height: 1, backgroundColor: '#e5e7eb', margin: '0 4px' }} />
        <button
          type="button"
          data-testid="map-reset-view-btn"
          onClick={handleResetView}
          style={{
            width: 32,
            height: 32,
            fontSize: '0.9rem',
            border: 'none',
            background: 'transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#1f2937',
            borderRadius: 4,
          }}
          title="بازگشت به نمای اولیه نقشه (Reset View)"
          aria-label="نمای اولیه"
        >
          🏠
        </button>
        <div style={{ height: 1, backgroundColor: '#e5e7eb', margin: '0 4px' }} />
        <button
          type="button"
          data-testid="map-my-location-btn"
          onClick={handleMyLocation}
          disabled={isLocating}
          style={{
            width: 32,
            height: 32,
            fontSize: '0.9rem',
            border: 'none',
            background: 'transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#1565c0',
            borderRadius: 4,
          }}
          title="پیدا کردن موقعیت جغرافیایی من (My Location)"
          aria-label="موقعیت من"
        >
          {isLocating ? '⏳' : '🎯'}
        </button>
      </div>

      {/* Top Navigation & Context Bar */}
      <div
        data-testid="map-top-bar"
        style={{
          position: 'absolute',
          top: 10,
          left: 54, // Leave room for zoom controls cluster on top-left
          right: 50, // Leave room for MapLibre navigation control on top-right
          zIndex: 15,
          display: 'flex',
          gap: 6,
          flexWrap: 'wrap',
          alignItems: 'center',
          pointerEvents: 'none',
        }}
      >
        {/* Real Geocoding Search Bar */}
        <div style={{ pointerEvents: 'auto', flex: '1 1 200px', maxWidth: 280 }}>
          <MapSearchBar onSelectLocation={handleSelectLocation} />
        </div>

        {/* Base Map Switcher */}
        <div
          data-testid="map-base-switcher"
          style={{
            pointerEvents: 'auto',
            display: 'flex',
            background: 'rgba(255, 255, 255, 0.96)',
            borderRadius: 6,
            boxShadow: '0 2px 6px rgba(0,0,0,0.22)',
            padding: 2,
            border: '1px solid #d0d7de',
          }}
        >
          <button
            type="button"
            data-testid="map-style-hybrid"
            onClick={() => setBaseMapMode('hybrid')}
            style={{
              padding: '3px 7px',
              fontSize: '0.74rem',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
              fontWeight: baseMapMode === 'hybrid' ? 600 : 400,
              background: baseMapMode === 'hybrid' ? '#1976d2' : 'transparent',
              color: baseMapMode === 'hybrid' ? '#ffffff' : '#333333',
            }}
            title="ماهواره همراه با مرز کشورها، استان‌ها و اسامی شهرها"
          >
            🛰️+🏷️ ترکیبی
          </button>
          <button
            type="button"
            data-testid="map-style-streets"
            onClick={() => setBaseMapMode('streets')}
            style={{
              padding: '3px 7px',
              fontSize: '0.74rem',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
              fontWeight: baseMapMode === 'streets' ? 600 : 400,
              background: baseMapMode === 'streets' ? '#1976d2' : 'transparent',
              color: baseMapMode === 'streets' ? '#ffffff' : '#333333',
            }}
            title="نقشه خیابان‌ها، مرزها و اسامی جغرافیایی (OpenStreetMap)"
          >
            🗺️ خیابان (OSM)
          </button>
          <button
            type="button"
            data-testid="map-style-satellite"
            onClick={() => setBaseMapMode('satellite')}
            style={{
              padding: '3px 7px',
              fontSize: '0.74rem',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
              fontWeight: baseMapMode === 'satellite' ? 600 : 400,
              background: baseMapMode === 'satellite' ? '#1976d2' : 'transparent',
              color: baseMapMode === 'satellite' ? '#ffffff' : '#333333',
            }}
            title="تصویر خالص ماهواره‌ای بدون لایه برچسب"
          >
            🛰️ ماهواره
          </button>
        </div>
      </div>

      {/* Map Provider Failure Error State Banner */}
      {mapProviderError && (
        <div
          data-testid="map-provider-error"
          style={{
            position: 'absolute',
            top: 52,
            left: 54,
            right: 50,
            zIndex: 22,
            background: 'rgba(254, 242, 242, 0.96)',
            color: '#991b1b',
            border: '1px solid #f87171',
            borderRadius: 6,
            padding: '5px 10px',
            fontSize: '0.78rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
            boxShadow: '0 2px 6px rgba(0,0,0,0.18)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>⚠️</span>
            <span>{mapProviderError}</span>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <button
              type="button"
              data-testid="map-provider-retry-btn"
              className="btn btn-sm"
              style={{
                padding: '2px 8px',
                fontSize: '0.72rem',
                background: '#ef4444',
                color: '#fff',
                border: 'none',
                borderRadius: 4,
                cursor: 'pointer',
              }}
              onClick={() => {
                consecutiveSatelliteErrorsRef.current = 0
                setMapProviderError(null)
                if (map.current) {
                  try {
                    map.current.triggerRepaint()
                  } catch {
                    // ignore
                  }
                }
              }}
            >
              تلاش مجدد
            </button>
            <button
              type="button"
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: '#991b1b',
                fontWeight: 'bold',
                fontSize: '0.9rem',
                padding: '0 4px',
              }}
              onClick={() => setMapProviderError(null)}
              title="بستن پیام"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Geolocation Notice Banner */}
      {locationError && (
        <div
          data-testid="map-location-error"
          style={{
            position: 'absolute',
            top: 50,
            left: 54,
            right: 50,
            zIndex: 20,
            background: 'rgba(254, 226, 226, 0.95)',
            color: '#b91c1c',
            border: '1px solid #f87171',
            borderRadius: 6,
            padding: '5px 10px',
            fontSize: '0.75rem',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            boxShadow: '0 2px 6px rgba(0,0,0,0.15)',
          }}
        >
          <span>⚠️</span>
          <span>{locationError}</span>
          <button
            type="button"
            onClick={() => setLocationError(null)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: '#b91c1c',
              marginLeft: 4,
              fontWeight: 'bold',
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Polygon Drawing Toolbar (Phase P-AGRI Field Boundary) */}
      {(enableDrawing || showDrawControls) && (
        <div
          data-testid="map-drawing-toolbar"
          style={{
            position: 'absolute',
            top: 155,
            left: 10,
            zIndex: 20,
            background: 'rgba(255, 255, 255, 0.96)',
            padding: '6px 10px',
            borderRadius: 8,
            boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            maxWidth: 380,
            border: '1px solid #d0d7de',
          }}
        >
          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              type="button"
              data-testid="map-draw-btn"
              className={`btn btn-sm ${drawState === 'drawing' ? 'btn-primary' : 'btn-outline'}`}
              style={{ padding: '4px 8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 4 }}
              onClick={handleStartDraw}
              title="رسم محدوده زمین با کلیک روی نقشه"
            >
              <span>✏️</span>
              <span>{drawState === 'drawing' ? 'در حال رسم...' : 'رسم محدوده'}</span>
            </button>

            {vertices.length >= 3 && drawState !== 'drawing' && (
              <button
                type="button"
                data-testid="map-edit-btn"
                className={`btn btn-sm ${drawState === 'editing' ? 'btn-primary' : 'btn-outline'}`}
                style={{ padding: '4px 8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 4 }}
                onClick={handleStartEdit}
                title="ویرایش رئوس چندضلعی"
              >
                <span>🔄</span>
                <span>ویرایش</span>
              </button>
            )}

            {vertices.length > 0 && (
              <button
                type="button"
                data-testid="map-clear-btn"
                className="btn btn-sm btn-outline"
                style={{ padding: '4px 8px', fontSize: '0.8rem', color: '#c62828' }}
                onClick={handleClear}
                title="پاک کردن چندضلعی"
              >
                <span>🗑️</span>
                <span>پاک کردن</span>
              </button>
            )}

            {vertices.length >= 3 && drawState !== 'confirmed' && (
              <button
                type="button"
                data-testid="map-confirm-btn"
                className="btn btn-sm btn-primary"
                style={{
                  padding: '4px 10px',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  backgroundColor: '#2e7d32',
                  borderColor: '#1b5e20',
                }}
                onClick={handleConfirm}
                title="تأیید نهایی محدوده برای تحلیل"
              >
                <span>✅</span>
                <span>تأیید محدوده</span>
              </button>
            )}

            {/* Fullscreen Toggle */}
            <button
              type="button"
              data-testid="map-fullscreen-btn"
              className="btn btn-sm btn-outline"
              style={{ padding: '4px 8px', fontSize: '0.8rem', marginLeft: 'auto' }}
              onClick={() => setIsFullscreen(!isFullscreen)}
              title={isFullscreen ? 'خروج از تمام‌صفحه' : 'بزرگ‌نمایی نقشه'}
            >
              {isFullscreen ? '✕ خروج' : '⛶ بزرگ‌نمایی'}
            </button>
          </div>

          {/* Status & Guidance Indicator */}
          <div
            data-testid="map-draw-status"
            style={{
              fontSize: '0.78rem',
              color: '#333',
              borderTop: '1px solid #eee',
              paddingTop: 4,
              lineHeight: 1.4,
            }}
          >
            {drawState === 'drawing' && (
              <span style={{ color: '#e65100', fontWeight: 600 }}>
                📍 حالت رسم مرز مزرعه فعال است (Draw Field Boundary) — {vertices.length} نقطه ثبت شد. برای بستن، روی نقطه اول کلیک کنید یا دوبار کلیک کنید.
              </span>
            )}
            {drawState === 'editing' && (
              <span style={{ color: '#1565c0' }}>
                🔄 چندضلعی بسته شد ({vertices.length} رأس، {areaHectares.toFixed(2)} هکتار). رئوس را بکشید تا تغییر کنند، سپس «تأیید محدوده» را بزنید.
              </span>
            )}
            {drawState === 'confirmed' && (
              <span style={{ color: '#2e7d32', fontWeight: 600 }}>
                ✓ محدوده زمین تأیید شد (Field boundary confirmed): {areaHectares.toFixed(2)} هکتار ({vertices.length} نقطه) — آماده برای تحلیل کشاورزی
              </span>
            )}
            {drawState === 'idle' && vertices.length === 0 && (
              <span className="text-muted">
                برای تعیین مرز مزرعه، دکمه «رسم محدوده» را بزنید و دور زمین خط بکشید.
              </span>
            )}
          </div>
        </div>
      )}

      {/* Unobtrusive Coordinates & Zoom Pill (Geographic Context Indicator) */}
      <div
        data-testid="map-coordinates-pill"
        style={{
          position: 'absolute',
          bottom: 10,
          left: 10,
          zIndex: 10,
          background: 'rgba(27, 38, 59, 0.78)',
          color: '#ffffff',
          padding: '3px 8px',
          borderRadius: 4,
          fontSize: '0.74rem',
          fontFamily: 'monospace',
          direction: 'ltr',
          boxShadow: '0 1px 4px rgba(0,0,0,0.25)',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
        title="مختصات مرکز نقشه و میزان بزرگ‌نمایی"
      >
        <span>📍 {formatCoordinates(currentCenter[1], currentCenter[0], { labeled: true, compact: true })}</span>
        {searchLocation && (
          <>
            <span style={{ opacity: 0.5 }}>|</span>
            <span style={{ color: '#ffb74d' }}>{searchLocation.shortName}</span>
          </>
        )}
        <span style={{ opacity: 0.5 }}>|</span>
        <span>بزرگ‌نمایی: {currentZoom.toFixed(1)}</span>
      </div>

      {/* Raster Tile Status Overlay Badge */}
      {rasterTileUrl && rasterTileStatus !== 'idle' && (
        <div
          data-testid="raster-tile-status-badge"
          style={{
            position: 'absolute',
            bottom: 42,
            left: 10,
            zIndex: 10,
            backgroundColor: 'rgba(255, 255, 255, 0.94)',
            padding: '4px 10px',
            borderRadius: 6,
            fontSize: '0.78rem',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
            border: rasterTileStatus === 'error' ? '1px solid #ef4444' : rasterTileStatus === 'loaded' ? '1px solid #10b981' : '1px solid #3b82f6',
            color: rasterTileStatus === 'error' ? '#b91c1c' : rasterTileStatus === 'loaded' ? '#047857' : '#1d4ed8',
            direction: 'rtl',
          }}
        >
          {rasterTileStatus === 'loading' && (
            <>
              <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />
              <span>در حال بارگذاری تایل‌های رستری GEE...</span>
            </>
          )}
          {rasterTileStatus === 'loaded' && (
            <>
              <span style={{ color: '#10b981', fontSize: '1rem', lineHeight: 1 }}>●</span>
              <span>لایه رستری فعال است</span>
            </>
          )}
          {rasterTileStatus === 'error' && (
            <>
              <span style={{ color: '#ef4444', fontSize: '1rem', lineHeight: 1 }}>⚠</span>
              <span>خطا در دریافت تایل رستری</span>
              <button
                type="button"
                data-testid="raster-tile-retry-btn"
                style={{
                  background: '#ef4444',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 4,
                  padding: '2px 6px',
                  fontSize: '0.75rem',
                  cursor: 'pointer',
                  marginRight: 4,
                }}
                onClick={() => setRasterRetryCount((c) => c + 1)}
              >
                تلاش مجدد
              </button>
            </>
          )}
        </div>
      )}

      {/* Opacity and Layer controls for visualization */}
      {visualization && (
        <div className="map-controls">
          <div className="control-group">
            <label className="control-label">لایه‌ها (Layers)</label>
            <div className="layer-buttons">
              {visualization.layers.map((layer) => (
                <button
                  key={layer.id}
                  className={`layer-button ${activeLayer === layer.id ? 'active' : ''}`}
                  onClick={() => {
                    setActiveLayer(layer.id)
                    if (!map.current) return
                    const layers = visualization?.layers || []
                    layers.forEach((l: MapLayer) => {
                      if (l.id === layer.id) {
                        map.current?.setLayoutProperty(`${layer.id}-layer`, 'visibility', 'visible')
                      } else {
                        map.current?.setLayoutProperty(`${l.id}-layer`, 'visibility', 'none')
                      }
                    })
                  }}
                >
                  {layer.name_fa || layer.name}
                </button>
              ))}
            </div>
          </div>

          <div className="control-group">
            <label className="control-label">شفافیت (Opacity)</label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={opacity}
              onChange={(e) => setOpacity(parseFloat(e.target.value))}
              className="opacity-slider"
            />
            <span className="opacity-value">{Math.round(opacity * 100)}%</span>
          </div>
        </div>
      )}

      {/* Legend */}
      {visualization && (
        <div className="map-legend">
          <div className="legend-title">راهنما (Legend)</div>
          <div className="legend-items">
            <div className="legend-item">
              <span className="legend-color" style={{ backgroundColor: '#4CAF50' }} />
              <span>پوشش گیاهی</span>
            </div>
            <div className="legend-item">
              <span className="legend-color" style={{ backgroundColor: '#2196F3' }} />
              <span>آب</span>
            </div>
            <div className="legend-item">
              <span className="legend-color" style={{ backgroundColor: '#8B4513' }} />
              <span>خاک</span>
            </div>
          </div>
        </div>
      )}

      {/* Map Layer Attributions */}
      <div
        data-testid="map-attribution-bar"
        style={{
          position: 'absolute',
          bottom: 4,
          left: 4,
          zIndex: 10,
          background: 'rgba(255, 255, 255, 0.85)',
          padding: '2px 8px',
          borderRadius: 4,
          fontSize: '0.68rem',
          color: '#475569',
          direction: 'ltr',
          pointerEvents: 'none',
          boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
        }}
      >
        <span>© Google Satellite / Hybrid</span>
        <span style={{ margin: '0 4px' }}>|</span>
        <span>© OpenStreetMap contributors</span>
        {rasterTileUrl && (
          <>
            <span style={{ margin: '0 4px' }}>|</span>
            <span>Contains modified Copernicus Sentinel data</span>
          </>
        )}
      </div>
    </div>
  )
}

// Helper to extract coordinates from any geometry type
function extractCoordinates(geometry: GeoJSON.Geometry): [number, number][] {
  const coords: [number, number][] = []

  if (geometry.type === 'Point') {
    coords.push(geometry.coordinates as [number, number])
  } else if (geometry.type === 'Polygon') {
    geometry.coordinates[0].forEach((coord) => {
      coords.push(coord as [number, number])
    })
  } else if (geometry.type === 'MultiPolygon') {
    geometry.coordinates.forEach((polygon) => {
      polygon[0].forEach((coord) => {
        coords.push(coord as [number, number])
      })
    })
  } else if (geometry.type === 'LineString') {
    geometry.coordinates.forEach((coord) => {
      coords.push(coord as [number, number])
    })
  } else if (geometry.type === 'MultiLineString') {
    geometry.coordinates.forEach((line) => {
      line.forEach((coord) => {
        coords.push(coord as [number, number])
      })
    })
  } else if (geometry.type === 'MultiPoint') {
    geometry.coordinates.forEach((coord) => {
      coords.push(coord as [number, number])
    })
  }

  return coords
}
