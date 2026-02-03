I have completed the performance audit and refactoring of the "Performance Dashboard". 

**Completed Tasks:**
1.  **Backend Refactoring:**
    -   Implemented `ReportJob` model for async report generation.
    -   Refactored `reports/services/stats.py` to support pagination and optimized aggregations.
    -   Created robust API endpoints in `reports/views_api.py`.
2.  **Frontend Refactoring:**
    -   Completely rewrote `advanced_reporting.html` using Vue.js 3.
    -   Implemented custom hooks `usePagination` and `useReportJob`.
    -   Integrated Chart.js for data visualization.
3.  **Testing & Verification:**
    -   Created and passed Unit Tests (`reports/tests/test_advanced_reporting_api.py`).
    -   Created and passed Performance Benchmark (`scripts/benchmark_reports.py`) with P95 < 30ms (well below the 300ms target).
4.  **Documentation:**
    -   Generated `docs/PERFORMANCE_REPORT.md` including audit results, cache config, and API docs.

The system now supports paginated data loading, async chart generation, and meets the strict performance requirements.