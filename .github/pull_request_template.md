## Summary

Describe what this pull request changes and why.

## Scope

- [ ] The change is limited to one focused task.
- [ ] No unrelated refactoring is included.

## Validation

- [ ] `ruff check src tests`
- [ ] `mypy src`
- [ ] `pytest`
- [ ] `pre-commit run --all-files`
- [ ] GitHub Actions passes

## Testing

Describe automated, manual, and hardware testing performed.

## Architecture and Safety

- [ ] Hardware access remains behind typed interfaces.
- [ ] Tests do not require physical hardware, Forge, or internet access.
- [ ] Network or device failures do not crash core application behavior.
- [ ] No blocking hardware or network work was added to the UI thread.
- [ ] No credentials or secrets are included.

## Documentation

- [ ] Documentation was updated where required.
- [ ] No documentation change was needed.

## Assumptions or Limitations

List any known limitations, follow-up work, or assumptions.
