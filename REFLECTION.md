# Reflection

## Development Experience

Building this project helped me understand how FastAPI, SQLAlchemy, PostgreSQL, authentication, Docker, and automated testing work together in a complete application. I learned how to organize application code into routes, models, schemas, database configuration, and authentication modules.

Writing unit, integration, and end-to-end tests showed the importance of testing more than just individual functions. Unit tests helped check small pieces of behavior, integration tests checked database and application interactions, and end-to-end tests checked the application from the user's perspective.

## Challenges

One challenge was configuring the database consistently across the local environment, Docker, pytest, and GitHub Actions. The environment variable `DATABASE_URL` had to point to the correct database in each environment.

Docker also required careful configuration. The application, database, health check, and startup command had to use consistent paths and ports. Debugging container startup was easier once PostgreSQL and the API were clearly separated and the logs could be inspected.

End-to-end tests were another challenge because they require a running server and a working browser environment. Installing Playwright and Chromium in local and CI environments was necessary for these tests to run reliably.

## What I Learned

I learned to use environment variables instead of hard-coded infrastructure settings. I also learned the value of health checks, database initialization, and container volumes for predictable deployment.

Automated tests and CI/CD reduced manual work by checking changes after each push or pull request. The Docker deployment workflow also showed how to build and publish the same image to Docker Hub and use tags for version identification.

## Future Improvements

Future work could include stronger secret management, database migrations, broader test coverage, and more complete monitoring. The application could also use different Docker configurations for development and production.
