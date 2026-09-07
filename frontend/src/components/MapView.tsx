import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { MapVisualization, MapLayer } from '../types'

interface MapViewProps {
  visualization?: MapVisualization
  geometry?: GeoJSON.Geometry
  center?: [number, number]
  zoom?: number
  className?: string
}

export default function MapView({
  visualization,
  geometry,
  center = [55.0, 32.0], // Default: Iran center
  zoom = 6,
  className = '',
}: MapViewProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [activeLayer, setActiveLayer] = useState<string>('rgb')
  const [opacity, setOpacity] = useState(0.8)

  useEffect(() => {
    if (!mapContainer.current) return

    // Initialize map
    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          'osm': {
            type: 'raster',
            tiles: [
              'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            ],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
          'satellite': {
            type: 'raster',
            tiles: [
              'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            ],
            tileSize: 256,
            attribution: '© Esri',
          },
        },
        layers: [
          {
            id: 'satellite-layer',
            type: 'raster',
            source: 'satellite',
            paint: {
              'raster-opacity': 0.8,
            },
          },
          {
            id: 'osm-layer',
            type: 'raster',
            source: 'osm',
            paint: {
              'raster-opacity': 0.0,
            },
          },
        ],
      },
      center: center,
      zoom: zoom,
    })

    // Add navigation controls
    map.current.addControl(new maplibregl.NavigationControl(), 'top-right')

    // Add scale
    map.current.addControl(
      new maplibregl.ScaleControl({ maxWidth: 200, unit: 'metric' }),
      'bottom-right'
    )

    // Draw geometry if provided
    map.current.on('load', () => {
      if (geometry && map.current) {
        // Add geometry source
        map.current.addSource('geometry', {
          type: 'geojson',
          data: {
            type: 'Feature',
            geometry: geometry,
            properties: {},
          },
        })

        // Add geometry fill
        map.current.addLayer({
          id: 'geometry-fill',
          type: 'fill',
          source: 'geometry',
          paint: {
            'fill-color': '#4CAF50',
            'fill-opacity': 0.2,
          },
        })

        // Add geometry outline
        map.current.addLayer({
          id: 'geometry-outline',
          type: 'line',
          source: 'geometry',
          paint: {
            'line-color': '#4CAF50',
            'line-width': 2,
          },
        })

        // Fit bounds to geometry
        const bounds = new maplibregl.LngLatBounds()
        const coords = extractCoordinates(geometry)
        coords.forEach((coord) => {
          bounds.extend(coord as [number, number])
        })
        map.current.fitBounds(bounds, { padding: 50 })
      }
    })

    return () => {
      map.current?.remove()
    }
  }, [center, zoom, geometry])

  // Handle visualization changes
  useEffect(() => {
    if (!map.current || !visualization) return

    // Update center and zoom
    map.current.flyTo({
      center: visualization.center,
      zoom: visualization.zoom,
    })
  }, [visualization])

  const handleLayerToggle = (layerId: string) => {
    setActiveLayer(layerId)
    if (!map.current) return

    // Toggle layer visibility
    const layers = visualization?.layers || []
    layers.forEach((layer: MapLayer) => {
      if (layer.id === layerId) {
        map.current?.setLayoutProperty(`${layerId}-layer`, 'visibility', 'visible')
      } else {
        map.current?.setLayoutProperty(`${layerId}-layer`, 'visibility', 'none')
      }
    })
  }

  return (
    <div className={`map-container ${className}`}>
      <div ref={mapContainer} className="map" />

      {/* Layer controls */}
      {visualization && (
        <div className="map-controls">
          <div className="control-group">
            <label className="control-label">لایه‌ها (Layers)</label>
            <div className="layer-buttons">
              {visualization.layers.map((layer) => (
                <button
                  key={layer.id}
                  className={`layer-button ${activeLayer === layer.id ? 'active' : ''}`}
                  onClick={() => handleLayerToggle(layer.id)}
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
