# TeamFlow Roadmap

## Milestone 1: Backend foundation

- establish the Flask backend
- configure environment-driven app settings
- set up SQLAlchemy, Flask-Migrate, and health endpoints
- add test and CI infrastructure
- document usage and development setup

## Milestone 2: User registration

- add user models and registration flows
- normalize email and enforce uniqueness
- store secure password hashes

## Milestone 3: Authentication and session management

- cookie-based login, current-user, and logout endpoints
- CSRF validation, session expiration, and logout revocation
- authorization foundation for protected API routes

## Milestone 4: React authentication UI and API integration (complete)

- [x] initialize the React + TypeScript + Vite frontend
- [x] build registration, login, authenticated shell, and logout flows
- [x] integrate the typed API client with CSRF and credentialed requests
- [x] add frontend integration tests and development setup documentation

## Milestone 5: Workspaces and memberships

- model workspaces and membership roles
- add authorization checks for team actions
- test cross-workspace access isolation

## Milestone 6: Projects and tasks

- implement project creation and lifecycle management
- add task models, statuses, and assignee workflows
- build CRUD APIs for core project operations

## Milestone 7: Collaboration

- add comment and discussion flows
- track activity log events
- support notifications, pagination, and filtering

## Milestone 8: Analytics and product polish

- add reporting and dashboard metrics
- improve accessibility, responsive design, testing, and performance

## Milestone 9: Deployment readiness

- prepare production configuration, migrations, and CI/CD
- improve logging, observability, and security review
- document backup, recovery, and deployment operations
