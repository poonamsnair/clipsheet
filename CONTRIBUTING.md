# Contributing

Thanks for your interest in clipsheet!

## Bug reports

Open an issue with:
- What you ran (command + video format)
- What you expected
- What happened (paste the error or attach the output)
- `clipsheet --status` output

## Pull requests

1. Fork the repo and create a branch
2. `pip install -e ".[dev]"` to install dev dependencies
3. Make your changes
4. Run `ruff check src tests` and `pytest` before submitting
5. Open a PR with a short description of what changed and why

Keep PRs focused — one fix or feature per PR.

## Development

```bash
git clone https://github.com/poonamsnair/clipsheet.git
cd clipsheet
pip install -e ".[dev]"
pytest
```
