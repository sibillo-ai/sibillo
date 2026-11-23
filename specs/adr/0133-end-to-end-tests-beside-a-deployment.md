# ADR-0133: End-to-end tests run beside a deployment, with images of their own

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0054, ADR-0059, ADR-0114, ADR-0129, OPS-001, OPS-006

## Context

The end-to-end tests install the deployment as the README says, with a
Compose project of their own. But `deploy/compose.yaml` names its images
`sibillo/<service>:local`: the tests build over the images a deployment on
the same host runs, and remove them when they end. The test harness
therefore says they must not run where Sibillo is deployed, so changes that
only they can check, such as hardening the Compose services, cannot be
checked on a maintainer's own server.

## Decision

1. **The image tag is a setting.** `deploy/compose.yaml` tags the images
   it builds `${SIBILLO_IMAGE_TAG:-local}`. An operator never needs to set
   it.
2. **The end-to-end tests use a tag of their own,** `e2e-<random>`, set for
   each deployment they install, and remove only the images of that tag
   when they end, never images another project uses. When CI has built the
   images (`TEST_DEPLOYMENT_IMAGES=built`), they use those, tagged `local`.
3. **They may run beside a deployment.** Their Compose project, published
   port, volumes, networks and images are their own; the host's Docker is
   shared, as for any project.

This amends ADR-0054 on where the end-to-end tests may run.

## Consequences

- A maintainer runs the whole suite on the server where they use Sibillo.
- Each local run builds its images anew under its own tag: slower than
  reusing `local`, as CI's build cache does.

## Alternatives considered

- **Stopping the deployment for the tests:** downtime, and the deployment's
  images still rebuilt from the code under test.
