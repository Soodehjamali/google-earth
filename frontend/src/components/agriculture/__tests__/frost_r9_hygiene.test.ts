import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('Item R9 Frontend: Orchard List Search and Pagination', () => {
  const pagePath = resolve('src/pages/agriculture/FrostRiskPage.tsx');
  const content = readFileSync(pagePath, 'utf-8');

  it('declares search and pagination state with pageSize 10', () => {
    assert.ok(content.includes('const [orchardSearchQuery, setOrchardSearchQuery] = useState'));
    assert.ok(content.includes('const [orchardPage, setOrchardPage] = useState'));
    assert.ok(content.includes('const ORCHARD_PAGE_SIZE = 10'));
  });

  it('filters orchards by search query and computes total pages', () => {
    assert.ok(content.includes('const filteredSummaries = useMemo('));
    assert.ok(content.includes('s.name.toLowerCase().includes(q)'));
    assert.ok(content.includes('const totalPages = Math.max(1, Math.ceil(filteredSummaries.length / ORCHARD_PAGE_SIZE))'));
    assert.ok(content.includes('const paginatedSummaries = useMemo('));
  });

  it('renders orchard search input with testid and Persian placeholder', () => {
    assert.ok(content.includes('data-testid="orchard-search-input"'));
    assert.ok(content.includes('placeholder="جستجوی نام باغ..."'));
    assert.ok(content.includes('پاک کردن'));
  });

  it('renders pagination controls with testid and Persian labels', () => {
    assert.ok(content.includes('data-testid="orchard-pagination"'));
    assert.ok(content.includes('صفحه {currentPage} از {totalPages}'));
    assert.ok(content.includes('>قبلی<') || content.includes('قبلی'));
    assert.ok(content.includes('>بعدی<') || content.includes('بعدی'));
  });

  it('renders paginated summaries in the table body', () => {
    assert.ok(content.includes('{paginatedSummaries.map((item) => {'));
  });
});
