# Query-Builder Fullstack Starter Template 🚀

A complete, runnable, turnkey fullstack application demonstrating end-to-end integration of Query-Builder with a modern **React 18 + Vite + TypeScript** frontend and a **FastAPI + SQLite** backend.

---

## 🌟 What's Included

- **Relational SQLite Database (`database.py`)**: Multi-table e-commerce domain with foreign keys, enums, nullable columns, and realistic seeded data:
  - `categories` (PK `id`, `name`, `slug`, `description`, `is_active`)
  - `products` (PK `id`, FK `category_id`, `name`, `price`, `stock_quantity`, enum `status`)
  - `users` (PK `id`, `email`, `full_name`, enum `role`, `created_at`, `last_login`)
  - `orders` (PK `id`, FK `user_id`, enum `status`, `total_amount`, `shipping_address`)
  - `order_items` (PK `id`, FK `order_id`, FK `product_id`, `quantity`, `unit_price`, `discount`)
- **FastAPI Backend Server (`backend/main.py`)**:
  - Uses `create_query_builder_router(connector=connector, prefix="/api")` for turnkey REST routing.
  - `GET /health`: Engine status, available dialects, active security profile.
  - `GET /api/schema` (and alias `/api/introspect`): Relational schema snapshot for the visual query builder.
  - `POST /api/compile`: Compiles JSON query spec to safe parameterized SQL.
  - `POST /api/validate`: Performs AST safety validation against SQL injection and mutation keywords.
  - `POST /api/execute`: Compiles and executes queries via `SQLiteConnector` with statement timeouts.
  - `POST /api/export`: Exports tabular results into CSV, JSON, Parquet, or Excel files.
- **React 18 + Vite Frontend (`frontend/`)**:
  - **Tab 1: Visual Studio Mode**: Plug-and-play `<VisualQueryBuilder>` with dark container-scoped theming, automatic relational joins, interactive filters, and live results.
  - **Tab 2: Headless Mode**: Unstyled custom UI using `useQueryBuilder` and `useQueryExecution`.
  - **Tab 3: ORM Adapters Demo**: Live conversion of Prisma, Drizzle, and SQLAlchemy schemas into Query-Builder ASTs in the browser.
  - **Custom Extensions**: Custom filter operator (`TAX_EXEMPT`) and custom price currency badge renderer.

---

## 🏃 Quickstart: Running the Application

### 1. Prerequisites
Ensure you have Python 3.9+ and Node.js 18+ (with `pnpm`) installed.

### 2. Start the Backend Server

From the `examples/fullstack_starter` directory:

```bash
# Using the single-command launcher (seeds database and runs server):
python run.py

# Or directly via uvicorn:
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

The server will be available at:
- **API URL**: `http://127.0.0.1:8000`
- **Interactive Swagger Docs**: `http://127.0.0.1:8000/docs`
- **Health Check**: `http://127.0.0.1:8000/health`
- **Schema Snapshot**: `http://127.0.0.1:8000/api/schema`

---

### 3. Start the Frontend Application

In a separate terminal window:

```bash
cd frontend
pnpm install
pnpm dev
```

Open your browser at `http://localhost:5173` to interact with the full-stack visual query studio!

---

## 🔌 API Reference

### `GET /health`
Returns the status of the query engine:
```json
{
  "status": "healthy",
  "service": "query-builder-fullstack-starter",
  "dialects": ["postgres", "snowflake", "sqlite", "mysql", "..."],
  "security_profile": "development",
  "read_only_enforced": true,
  "database": ".../starter.db"
}
```

### `GET /api/schema`
Returns the relational schema snapshot including tables, columns, primary keys, and foreign key relationships.

### `POST /api/compile`
Compiles a declarative JSON query specification:
```json
{
  "spec": {
    "table": "orders",
    "columns": ["orders.id", "orders.total_amount"],
    "joins": [
      {
        "table": "users",
        "type": "LEFT JOIN",
        "on": [{"left": "orders.user_id", "right": "users.id"}]
      }
    ],
    "limit": 10
  },
  "dialect": "sqlite"
}
```

### `POST /api/execute`
Compiles and executes the query with AST safety verification:
```json
{
  "spec": {
    "table": "products",
    "columns": ["products.id", "products.name", "products.price"],
    "filters": [{"column": "products.price", "op": "gt", "value": 100}],
    "limit": 5
  }
}
```

Response:
```json
{
  "columns": ["products.id", "products.name", "products.price"],
  "rows": [
    {"products.id": 1, "products.name": "ProBook 16 Laptop", "products.price": 1299.99},
    {"products.id": 2, "products.name": "Noise-Cancelling Headphones", "products.price": 249.50}
  ],
  "count": 2,
  "latency_ms": 1.45,
  "dialect": "sqlite",
  "limit": 5,
  "offset": 0
}
```

### `POST /api/export`
Exports query dataset into downloadable binary/text formats (`csv`, `json`, `parquet`, `excel`):
```json
{
  "spec": {
    "table": "products",
    "columns": ["products.id", "products.name", "products.price"]
  },
  "format": "csv"
}
```

---

## 📄 License & Ownership

The Fullstack Starter Template is open-source software owned and maintained by **HobbyHabbit LLC** under the **MIT License**. See **[LICENSE](../../LICENSE)** for complete details.
