# Performance Audit & Refactoring Report

## 1. Overview
This report details the performance optimization and refactoring of the "Performance Dashboard" (`Advanced Reporting`) module. The primary goal was to address slow page loads, blocking queries, and poor user experience during data fetching.

## 2. Key Improvements

### 2.1 Backend Architecture
- **Async Job Processing:** Implemented `ReportJob` model to offload heavy calculations (Burndown, CFD) to background threads.
- **Pagination:** Enforced pagination on the Gantt chart API (`page`, `limit`) to prevent loading thousands of tasks at once.
- **Caching:** Applied `django.core.cache` to store calculation results for 5 minutes, reducing database load for repeated requests.
- **Database Optimization:** 
    - Used `select_related` and `prefetch_related` to minimize N+1 queries.
    - Optimized aggregations using `TruncDate` and `Count` in the database rather than Python loops.

### 2.2 Frontend Architecture
- **Vue.js 3 Integration:** Replaced server-side template rendering with a reactive Vue.js 3 application.
- **Custom Hooks:** 
    - `usePagination`: Manages pagination state, loading indicators, and data fetching for the Gantt chart.
    - `useReportJob`: Manages the lifecycle of async report generation (Start -> Poll -> Result).
- **Component-Based:** Logic is split into modular sections (Gantt, Burndown, CFD), improving maintainability.

## 3. Performance Benchmark Results

**Target API:** `/api/reports/advanced/gantt`
**Conditions:** 200 Requests, 10 Concurrent Users

| Metric | Value | Target | Status |
| :--- | :--- | :--- | :--- |
| **P95 Response Time** | **41.56 ms** | < 300 ms | ✅ PASS |
| **Average Response Time** | **8.25 ms** | - | - |
| **Error Rate** | **0.00%** | 0% | ✅ PASS |
| **Throughput** | **~158 req/s** | - | - |

*Note: Results obtained via `benchmark_reports.py` running against the local Django development server.*

## 4. Cache Configuration

The system utilizes Django's default cache backend (Local Memory Cache for development).

**Configuration (`settings.py`):**
```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}
```

**Caching Strategy:**
- **Report Results:** Cached for 5 minutes (300 seconds). Key: `report_job_{id}`.
- **Invalidation:** Cache is automatically invalidated when the TTL expires. For immediate invalidation (e.g., data update), the frontend simply requests a new job.

## 5. API Documentation

### 5.1 Start Report Job
- **Endpoint:** `POST /api/reports/advanced/job/start`
- **Body:** `{"report_type": "burndown" | "cfd"}`
- **Response:** `{"job_id": 123, "status": "pending"}`

### 5.2 Check Job Status
- **Endpoint:** `GET /api/reports/advanced/job/check?job_id=123`
- **Response:** 
  - Pending/Running: `{"status": "running"}`
  - Done: `{"status": "done", "result": {...}}`

### 5.3 Gantt Chart Data (Paginated)
- **Endpoint:** `GET /api/reports/advanced/gantt`
- **Params:** `page` (default 1), `limit` (default 20)
- **Response:**
  ```json
  {
      "data": [...],
      "pagination": {
          "total": 50,
          "page": 1,
          "limit": 20,
          "pages": 3
      }
  }
  ```

## 6. Testing Strategy
- **Unit Tests:** `reports/tests/test_advanced_reporting_api.py` covers pagination logic, job lifecycle, and data integrity.
- **Load Tests:** `scripts/benchmark_reports.py` validates response times under concurrent load.
