# Benchmark tests

The test tree mirrors the benchmark source tree. Run the normal suite from the
repository root:

```bash
pytest -q benchmark/tests
```

Docker integration tests are skipped by default. Enable them with:

```bash
RUN_DOCKER_INTEGRATION=1 pytest -q benchmark/tests
```

The Docker tests use temporary containers, networks, volumes, and copied
fixtures. They do not modify files under `generate_attack_config/output`.
