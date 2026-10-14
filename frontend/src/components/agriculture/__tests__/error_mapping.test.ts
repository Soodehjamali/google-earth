import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../../../api/client.ts';
import { mapErrorToPersian, ERROR_CODE_MAP } from '../errorMapping.ts';

describe('Step 3: Stable Error Codes & Persian Error Mapping', () => {
  it('1. maps ApiError with ERR_GEE_UNAVAILABLE to respectful Persian guidance', () => {
    const apiErr = new ApiError({
      code: 'ERR_GEE_UNAVAILABLE',
      reason: 'Earth Engine service is unavailable',
      detail: { technical_message: 'ee.EEException: Socket closed' },
      status: 503,
    });

    const mapping = mapErrorToPersian(apiErr);
    assert.strictEqual(mapping.code, 'ERR_GEE_UNAVAILABLE');
    assert.strictEqual(mapping.titleFa, ERROR_CODE_MAP.ERR_GEE_UNAVAILABLE.titleFa);
    assert.strictEqual(mapping.messageFa, ERROR_CODE_MAP.ERR_GEE_UNAVAILABLE.messageFa);
    assert.ok(mapping.suggestedActionFa.length > 0);
    // Raw socket text is NOT leaked into user-facing title or message
    assert.doesNotMatch(mapping.titleFa, /Socket closed/i);
    assert.doesNotMatch(mapping.messageFa, /Socket closed/i);
    // Technical details are preserved for Developer Mode
    assert.match(mapping.technicalDetails || '', /Socket closed/);
  });

  it('2. maps ERR_INVALID_GEOMETRY and ERR_INVALID_DATE_RANGE correctly', () => {
    const geomErr = new ApiError({
      code: 'ERR_INVALID_GEOMETRY',
      reason: 'Self-intersection found',
      status: 400,
    });
    const geomMap = mapErrorToPersian(geomErr);
    assert.strictEqual(geomMap.code, 'ERR_INVALID_GEOMETRY');
    assert.strictEqual(geomMap.titleFa, ERROR_CODE_MAP.ERR_INVALID_GEOMETRY.titleFa);

    const dateErr = new ApiError({
      code: 'ERR_INVALID_DATE_RANGE',
      reason: 'Start date after end date',
      status: 400,
    });
    const dateMap = mapErrorToPersian(dateErr);
    assert.strictEqual(dateMap.code, 'ERR_INVALID_DATE_RANGE');
    assert.strictEqual(dateMap.titleFa, ERROR_CODE_MAP.ERR_INVALID_DATE_RANGE.titleFa);
  });

  it('3. maps expected unavailability ERR_INSUFFICIENT_DATA to educational guidance, not crash', () => {
    const noDataErr = new ApiError({
      code: 'ERR_INSUFFICIENT_DATA',
      reason: 'No cloud-free imagery',
      status: 200,
    });
    const noDataMap = mapErrorToPersian(noDataErr);
    assert.strictEqual(noDataMap.code, 'ERR_INSUFFICIENT_DATA');
    assert.strictEqual(noDataMap.titleFa, ERROR_CODE_MAP.ERR_INSUFFICIENT_DATA.titleFa);
    assert.ok(noDataMap.suggestedActionFa.includes('بازه زمانی'));
  });

  it('4. maps generic raw Error string heuristically to safe codes', () => {
    const netErr = mapErrorToPersian(new Error('Failed to fetch'));
    assert.strictEqual(netErr.code, 'ERR_NETWORK');

    const timeoutErr = mapErrorToPersian('Socket timeout after 120s on Earth Engine');
    assert.strictEqual(timeoutErr.code, 'ERR_GEE_UNAVAILABLE');

    const unknownErr = mapErrorToPersian('Some unknown internal issue');
    assert.strictEqual(unknownErr.code, 'ERR_INTERNAL_SERVER_ERROR');
    assert.strictEqual(unknownErr.titleFa, ERROR_CODE_MAP.ERR_INTERNAL_SERVER_ERROR.titleFa);
  });
});
