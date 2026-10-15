import { useState, useEffect, useRef } from 'react';
import { searchLocations, type GeocodingResult } from './geocoding';

interface MapSearchBarProps {
  onSelectLocation: (result: GeocodingResult) => void;
  className?: string;
  disabled?: boolean;
}

export default function MapSearchBar({
  onSelectLocation,
  className = '',
  disabled = false,
}: MapSearchBarProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GeocodingResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Debounced search
  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResults([]);
      setIsOpen(false);
      setLoading(false);
      setErrorMessage(null);
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    setErrorMessage(null);

    const timer = setTimeout(async () => {
      try {
        const data = await searchLocations(trimmed, controller.signal);
        setResults(data);
        setIsOpen(data.length > 0);
        if (data.length === 0 && trimmed.length >= 3) {
          setErrorMessage('مکانی با این نام پیدا نشد');
        }
      } catch (err: unknown) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          setErrorMessage('خطا در جستجوی مکان');
        }
      } finally {
        setLoading(false);
      }
    }, 350);

    return () => {
      clearTimeout(timer);
    };
  }, [query]);

  const handleSelect = (item: GeocodingResult) => {
    setQuery(item.shortName || item.displayName);
    setIsOpen(false);
    onSelectLocation(item);
  };

  const handleClear = () => {
    setQuery('');
    setResults([]);
    setIsOpen(false);
    setErrorMessage(null);
  };

  return (
    <div
      ref={containerRef}
      className={`map-search-bar ${className}`}
      style={{
        position: 'relative',
        width: '100%',
        maxWidth: 320,
        zIndex: 20,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          background: 'rgba(255, 255, 255, 0.96)',
          borderRadius: 6,
          boxShadow: '0 2px 6px rgba(0,0,0,0.22)',
          padding: '2px 8px',
          border: '1px solid #d0d7de',
        }}
      >
        <span
          style={{
            fontSize: '0.9rem',
            marginRight: 6,
            color: '#555',
          }}
          aria-hidden="true"
        >
          🔍
        </span>
        <input
          type="text"
          data-testid="map-search-input"
          value={query}
          disabled={disabled}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => {
            if (results.length > 0) setIsOpen(true);
          }}
          placeholder="جستجوی شهر، استان، کشور..."
          style={{
            border: 'none',
            outline: 'none',
            background: 'transparent',
            width: '100%',
            fontSize: '0.82rem',
            padding: '5px 0',
            color: '#1f2937',
            fontFamily: 'inherit',
          }}
          aria-label="جستجوی مکان جغرافیایی"
        />
        {loading && (
          <span
            data-testid="map-search-loading"
            style={{
              fontSize: '0.75rem',
              color: '#1976d2',
              marginLeft: 4,
              animation: 'spin 1s linear infinite',
            }}
          >
            ⏳
          </span>
        )}
        {query && !loading && (
          <button
            type="button"
            data-testid="map-search-clear"
            onClick={handleClear}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: '#888',
              fontSize: '0.85rem',
              padding: '2px 4px',
            }}
            title="پاک کردن"
          >
            ✕
          </button>
        )}
      </div>

      {/* Suggestions Dropdown */}
      {isOpen && results.length > 0 && (
        <ul
          data-testid="map-search-results"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: 4,
            background: '#ffffff',
            borderRadius: 6,
            boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
            border: '1px solid #e1e4e8',
            maxHeight: 220,
            overflowY: 'auto',
            padding: 0,
            margin: '4px 0 0 0',
            listStyle: 'none',
            zIndex: 30,
          }}
        >
          {results.map((item) => (
            <li
              key={item.id}
              data-testid={`map-search-item-${item.id}`}
              onClick={() => handleSelect(item)}
              style={{
                padding: '7px 10px',
                borderBottom: '1px solid #f0f0f0',
                cursor: 'pointer',
                textAlign: 'right',
                direction: 'rtl',
                fontSize: '0.8rem',
                lineHeight: 1.3,
                transition: 'background 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#f3f4f6';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = '#ffffff';
              }}
            >
              <div
                style={{
                  fontWeight: 600,
                  color: '#111827',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span>{item.shortName}</span>
                {item.type && (
                  <span
                    style={{
                      fontSize: '0.68rem',
                      color: '#6b7280',
                      background: '#f3f4f6',
                      padding: '1px 5px',
                      borderRadius: 4,
                    }}
                  >
                    {item.type}
                  </span>
                )}
              </div>
              <div
                style={{
                  fontSize: '0.72rem',
                  color: '#6b7280',
                  marginTop: 2,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {item.displayName}
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Error or Empty Message */}
      {errorMessage && query.length >= 3 && !loading && (
        <div
          data-testid="map-search-empty"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: 4,
            background: '#ffffff',
            borderRadius: 6,
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
            border: '1px solid #e1e4e8',
            padding: '8px 10px',
            fontSize: '0.75rem',
            color: '#dc2626',
            textAlign: 'center',
            zIndex: 30,
          }}
        >
          {errorMessage}
        </div>
      )}
    </div>
  );
}
