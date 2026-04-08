/**
 * Pagination Component
 *
 * Reusable pagination controls for paginated lists.
 * Supports page navigation, items per page selection, and page info display.
 */
import './Pagination.css';

interface PaginationProps {
  /** Current page number (1-indexed) */
  currentPage: number;
  /** Total number of items */
  totalItems: number;
  /** Items per page */
  pageSize: number;
  /** Callback when page changes */
  onPageChange: (page: number) => void;
  /** Callback when page size changes */
  onPageSizeChange?: (size: number) => void;
  /** Available page size options */
  pageSizeOptions?: number[];
  /** Whether pagination is disabled (e.g., during loading) */
  disabled?: boolean;
}

/**
 * Pagination Controls
 *
 * Displays: [< Prev] [1] [2] [3] [4] [5] [Next >]
 * With page info: "Showing 1-10 of 99"
 */
export function Pagination({
  currentPage,
  totalItems,
  pageSize,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50],
  disabled = false,
}: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const canGoPrev = currentPage > 1;
  const canGoNext = currentPage < totalPages;

  // Calculate item range for display
  const startItem = totalItems === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const endItem = Math.min(currentPage * pageSize, totalItems);

  // Generate page numbers to display (show max 5 pages around current)
  const getPageNumbers = (): (number | 'ellipsis')[] => {
    const pages: (number | 'ellipsis')[] = [];
    const maxVisible = 5;

    if (totalPages <= maxVisible) {
      // Show all pages if total is small
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i);
      }
    } else {
      // Always show first page
      pages.push(1);

      // Calculate range around current page
      let start = Math.max(2, currentPage - 1);
      let end = Math.min(totalPages - 1, currentPage + 1);

      // Adjust if at boundaries
      if (currentPage <= 3) {
        end = Math.min(4, totalPages - 1);
      }
      if (currentPage >= totalPages - 2) {
        start = Math.max(2, totalPages - 3);
      }

      // Add ellipsis before middle pages if needed
      if (start > 2) {
        pages.push('ellipsis');
      }

      // Add middle pages
      for (let i = start; i <= end; i++) {
        pages.push(i);
      }

      // Add ellipsis after middle pages if needed
      if (end < totalPages - 1) {
        pages.push('ellipsis');
      }

      // Always show last page
      if (totalPages > 1) {
        pages.push(totalPages);
      }
    }

    return pages;
  };

  const handlePrev = () => {
    if (canGoPrev && !disabled) {
      onPageChange(currentPage - 1);
    }
  };

  const handleNext = () => {
    if (canGoNext && !disabled) {
      onPageChange(currentPage + 1);
    }
  };

  const handlePageClick = (page: number) => {
    if (!disabled && page !== currentPage) {
      onPageChange(page);
    }
  };

  const handlePageSizeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newSize = parseInt(e.target.value, 10);
    onPageSizeChange?.(newSize);
    // Reset to page 1 when page size changes
    onPageChange(1);
  };

  // Don't render if there's nothing to paginate
  if (totalItems === 0) {
    return null;
  }

  const pageNumbers = getPageNumbers();

  return (
    <nav className="pagination" aria-label="Pagination">
      <div className="pagination__info">
        <span className="pagination__showing">
          Showing {startItem}-{endItem} of {totalItems}
        </span>
        {onPageSizeChange && (
          <label className="pagination__page-size">
            <span className="pagination__page-size-label">per page:</span>
            <select
              value={pageSize}
              onChange={handlePageSizeChange}
              disabled={disabled}
              className="pagination__page-size-select"
            >
              {pageSizeOptions.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="pagination__controls">
        <button
          type="button"
          className="pagination__button pagination__button--prev"
          onClick={handlePrev}
          disabled={!canGoPrev || disabled}
          aria-label="Previous page"
        >
          <span aria-hidden="true">&lt;</span>
          <span className="pagination__button-text">Prev</span>
        </button>

        <div className="pagination__pages">
          {pageNumbers.map((page, index) =>
            page === 'ellipsis' ? (
              <span key={`ellipsis-${index}`} className="pagination__ellipsis">
                ...
              </span>
            ) : (
              <button
                key={page}
                type="button"
                className={`pagination__page ${
                  page === currentPage ? 'pagination__page--active' : ''
                }`}
                onClick={() => handlePageClick(page)}
                disabled={disabled || page === currentPage}
                aria-label={`Page ${page}`}
                aria-current={page === currentPage ? 'page' : undefined}
              >
                {page}
              </button>
            )
          )}
        </div>

        <button
          type="button"
          className="pagination__button pagination__button--next"
          onClick={handleNext}
          disabled={!canGoNext || disabled}
          aria-label="Next page"
        >
          <span className="pagination__button-text">Next</span>
          <span aria-hidden="true">&gt;</span>
        </button>
      </div>
    </nav>
  );
}
