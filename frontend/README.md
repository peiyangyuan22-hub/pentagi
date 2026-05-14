# PentAGI Frontend

React 19 + TypeScript + Vite 7 + Tailwind CSS 4 + Apollo GraphQL + Radix UI.

## Quick Start

```bash
cd frontend
npm ci        # install dependencies
npm run dev   # start dev server (default: http://localhost:8000)
```

## Available Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start dev server with hot reload |
| `npm run build` | TypeScript check + production build |
| `npm run test` | Run vitest unit tests |
| `npm run test:coverage` | Run tests with coverage report |
| `npm run test:watch` | Run tests in watch mode |
| `npm run lint` | ESLint check |
| `npm run lint:fix` | ESLint auto-fix |
| `npm run prettier` | Prettier format check |
| `npm run prettier:fix` | Prettier auto-format |
| `npm run graphql:generate` | Generate TS types from GraphQL schema |

## Tech Stack

| Category | Libraries |
|----------|-----------|
| **Framework** | React 19, TypeScript 5.6 |
| **Bundler** | Vite 7 + SWC |
| **Styling** | Tailwind CSS 4 + class-variance-authority |
| **UI Components** | Radix UI primitives + sonner (toast) + cmdk (command palette) |
| **GraphQL** | Apollo Client 3 + graphql-ws (subscriptions) |
| **Terminal** | xterm.js with WebGL renderer |
| **Editor** | Monaco editor |
| **PDF** | @react-pdf/renderer |
| **Form** | react-hook-form + zod |
| **Charts** | recharts |
| **Markdown** | react-markdown + rehype + remark-gfm |

## Project Structure

```
src/
├── components/     # Shared UI components (Radix-based)
│   ├── ui/         # Primitive UI elements
│   ├── layouts/    # Page layout shells
│   ├── shared/     # App-specific shared components
│   └── icons/      # SVG icon components
├── features/       # Feature modules
│   ├── authentication/  # Login, OAuth, session
│   └── flows/           # Penetration test workflow UI
├── hooks/          # Custom React hooks
├── lib/            # Utilities (api clients, helpers)
├── models/         # Domain model types
├── pages/          # Route-level page components
├── providers/      # React context providers
├── schemas/        # Zod validation schemas
├── styles/         # Global CSS + utility classes
├── types/          # Global TypeScript type definitions
└── graphql/        # GraphQL queries, mutations, subscriptions
```

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8080` | Backend API endpoint |
| `VITE_WS_URL` | `ws://localhost:8080/query` | WebSocket for subscriptions |

## Codegen

GraphQL types are generated from the backend schema:

```bash
npm run graphql:generate
# Output: src/graphql/generated/
```

Requires the backend GraphQL schema at `../backend/pkg/graph/schema.graphqls`.
